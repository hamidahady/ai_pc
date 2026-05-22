"""
pcd_probes.py — read-only monitoring probes + startup-only probes.
"""

import os
import re
import subprocess

from pcd_config import (
    BATTERY_STATUS_NAMES, GENERIC_CLASS_PATTERN, OEM_CLASS_PATTERN,
    OEM_NAMESPACE_TOKENS,
)
from pcd_log import logger
from pcd_shell import ps, safe_float

import pcd_state


def probe_system_info() -> dict:
    info = {"hostname": ps("[System.Environment]::MachineName").strip()}

    def collect(prefix, cmd):
        for line in ps(cmd).splitlines():
            if ":" not in line:
                continue
            k, v = [s.strip() for s in line.split(":", 1)]
            if v:
                info[prefix + k] = v

    collect("", "Get-CimInstance Win32_ComputerSystem | "
                "Format-List Manufacturer, Model, SystemFamily, "
                "TotalPhysicalMemory, NumberOfLogicalProcessors")
    collect("os_", "Get-CimInstance Win32_OperatingSystem | "
                   "Format-List Caption, Version, OSArchitecture, BuildNumber")
    collect("cpu_", "Get-CimInstance Win32_Processor | Select-Object -First 1 | "
                    "Format-List Name, NumberOfCores, MaxClockSpeed")
    collect("bios_", "Get-CimInstance Win32_BIOS | "
                     "Format-List Manufacturer, SMBIOSBIOSVersion")

    ram_raw = safe_float(info.get("TotalPhysicalMemory"))
    if ram_raw:
        info["ram_gb"] = round(ram_raw / (1024 ** 3), 1)
    return info


def oem_discover() -> list[tuple[str, str]]:
    logger.info("  scanning WMI for OEM / sensor classes ...")
    walker = (
        "function Walk($p) { $p; "
        "Get-CimInstance -Namespace $p -ClassName __Namespace -ErrorAction SilentlyContinue | "
        "ForEach-Object { Walk \"$p\\$($_.Name)\" } "
        "}; Walk 'root'"
    )
    all_ns = [n.strip() for n in ps(walker, timeout=30).splitlines() if n.strip()]
    candidates = {n for n in all_ns
                  if any(tok.lower() in n.lower() for tok in OEM_NAMESPACE_TOKENS)}
    candidates.update(["root\\WMI", "root\\CIMV2"])
    found = []
    for ns in sorted(candidates):
        out = ps(
            f"Get-CimClass -Namespace '{ns}' -ErrorAction SilentlyContinue | "
            "Where-Object { $_.CimClassName -match "
            f"'{OEM_CLASS_PATTERN}' -or "
            f"$_.CimClassName -match '{GENERIC_CLASS_PATTERN}' }} | "
            "Select-Object -ExpandProperty CimClassName",
            timeout=15,
        )
        for cls in out.splitlines():
            cls = cls.strip()
            if not cls or cls == "MSAcpi_ThermalZoneTemperature":
                continue
            found.append((ns, cls))
            logger.info("    + %s :: %s", ns, cls)
    if not found:
        logger.info("    (no OEM-specific fan/thermal classes exposed on this model)")
    return found


def probe_thermal_zones():
    out = ps(
        r"Get-Counter -Counter '\Thermal Zone Information(*)\Temperature' "
        r"-ErrorAction SilentlyContinue | "
        r"ForEach-Object { $_.CounterSamples } | "
        r"ForEach-Object { '{0}|{1:N2}' -f $_.Path, ($_.CookedValue - 273.15) }"
    )
    sensors = []
    for line in out.splitlines():
        if "|" not in line:
            continue
        name, temp = line.split("|", 1)
        v = safe_float(temp)
        if v is not None and v > 5:
            sensors.append({"name": name.strip(), "value": v})
    return sensors


def probe_nvidia():
    """Cross-vendor GPU telemetry. Name kept for backward-compat with
    pcd_state and pcd_page_js, which read _state["sources"]["nvidia"].

    Implementation delegates to the provider chain in pcd_providers_gpu:
    NVIDIA via nvidia-smi → AMD WMI → Intel WMI → Windows Perf Counters.

    On any non-NVIDIA machine you still get util% and VRAM via the
    perf-counter fallback. On a machine where no provider yields data,
    returns [] and the UI tile renders 'not available on this hardware'."""
    from pcd_providers_gpu import get_gpu_metrics
    return get_gpu_metrics()


def probe_storage():
    out = ps(
        "Get-PhysicalDisk | ForEach-Object { "
        "  $rc = $_ | Get-StorageReliabilityCounter -ErrorAction SilentlyContinue; "
        "  if ($rc -and $rc.Temperature) { "
        "    '{0}|{1}|{2}|{3}' -f $_.FriendlyName, $_.MediaType, $rc.Temperature, $rc.TemperatureMax "
        "  } "
        "}"
    )
    drives = []
    for line in out.splitlines():
        parts = line.split("|")
        if len(parts) < 3:
            continue
        name, media = parts[0], parts[1]
        temp = safe_float(parts[2])
        if temp is None or temp <= 0:
            continue
        drives.append({
            "name": name.strip(),
            "media": media.strip(),
            "temp_c": temp,
            "temp_max_c": safe_float(parts[3]) if len(parts) > 3 else None,
        })
    return drives


def probe_battery():
    info = {}
    state = ps(
        "Get-CimInstance Win32_Battery -ErrorAction SilentlyContinue | "
        "Select-Object EstimatedChargeRemaining,BatteryStatus,EstimatedRunTime | "
        "Format-List"
    )
    for line in state.splitlines():
        if ":" not in line:
            continue
        k, v = [s.strip() for s in line.split(":", 1)]
        if k == "EstimatedChargeRemaining":
            info["charge_pct"] = safe_float(v)
        elif k == "BatteryStatus":
            code = safe_float(v)
            if code is not None:
                info["status_code"] = int(code)
                info["status"] = BATTERY_STATUS_NAMES.get(int(code), f"Code {int(code)}")
        elif k == "EstimatedRunTime":
            rt = safe_float(v)
            if rt is not None and rt < 1440:
                info["runtime_min"] = rt
    raw = ps(
        "Get-CimInstance -Namespace root/WMI -ClassName BatteryTemperature "
        "-ErrorAction SilentlyContinue | "
        "Select-Object -First 1 -ExpandProperty Temperature"
    )
    t = safe_float(raw)
    if t and t > 100:
        info["temp_c"] = round((t / 10.0) - 273.15, 1)
    return info


def probe_cpu_proxy():
    out = ps(
        r"Get-Counter -Counter "
        r"'\Processor Information(_Total)\% Processor Time',"
        r"'\Processor Information(_Total)\% Processor Performance',"
        r"'\Processor Information(_Total)\Processor Frequency' "
        r"-ErrorAction SilentlyContinue | "
        r"ForEach-Object { $_.CounterSamples } | "
        r"ForEach-Object { '{0}|{1:N2}' -f $_.Path, $_.CookedValue }"
    )
    info = {}
    for line in out.splitlines():
        if "|" not in line:
            continue
        path, v = line.split("|", 1)
        fv = safe_float(v)
        if fv is None:
            continue
        p = path.lower()
        if "% processor time" in p:
            info["util_pct"] = fv
        elif "% processor performance" in p:
            info["perf_pct"] = fv
        elif "processor frequency" in p:
            info["freq_mhz"] = fv
    if "freq_mhz" not in info:
        raw = ps(
            "(Get-CimInstance Win32_Processor | "
            "Select-Object -First 1 -ExpandProperty CurrentClockSpeed)"
        )
        fv = safe_float(raw)
        if fv is not None:
            info["freq_mhz"] = fv
    return info


def probe_system_load():
    """One-shot Get-Counter that pulls memory %, disk I/O, network rates,
    process count, and per-core CPU load — all in a single PowerShell call
    to keep latency low. Returns a dict shaped like:

        {
          "memory_pct":        68.2,
          "memory_avail_mb":   4923.0,
          "disk_io_pct":       12.0,
          "disk_read_kbps":    2048.0,
          "disk_write_kbps":   5120.0,
          "net_in_kbps":       120.0,
          "net_out_kbps":      45.0,
          "process_count":     412,
          "cpu_cores_pct":     [3.2, 1.0, 8.5, ...],   # one per logical core
          "cpu_core_max_pct":  23.8,
          "cpu_core_avg_pct":  7.4,
        }
    """
    out = ps(
        r"Get-Counter -Counter "
        r"'\Memory\% Committed Bytes In Use',"
        r"'\Memory\Available MBytes',"
        r"'\PhysicalDisk(_Total)\% Disk Time',"
        r"'\PhysicalDisk(_Total)\Disk Read Bytes/sec',"
        r"'\PhysicalDisk(_Total)\Disk Write Bytes/sec',"
        r"'\Network Interface(*)\Bytes Received/sec',"
        r"'\Network Interface(*)\Bytes Sent/sec',"
        r"'\System\Processes',"
        r"'\Processor Information(*)\% Processor Time' "
        r"-ErrorAction SilentlyContinue | "
        r"ForEach-Object { $_.CounterSamples } | "
        r"ForEach-Object { '{0}|{1:N4}' -f $_.Path, $_.CookedValue }"
    )
    info = {}
    cores = []
    net_in_total = 0.0
    net_out_total = 0.0
    for line in out.splitlines():
        if "|" not in line:
            continue
        path, v = line.split("|", 1)
        fv = safe_float(v)
        if fv is None:
            continue
        p = path.lower()
        if "% committed bytes in use" in p:
            info["memory_pct"] = round(fv, 1)
        elif "available mbytes" in p:
            info["memory_avail_mb"] = round(fv, 0)
        elif "% disk time" in p:
            info["disk_io_pct"] = round(fv, 1)
        elif "disk read bytes/sec" in p:
            info["disk_read_kbps"] = round(fv / 1024.0, 1)
        elif "disk write bytes/sec" in p:
            info["disk_write_kbps"] = round(fv / 1024.0, 1)
        elif "bytes received/sec" in p:
            # Sum across all network interfaces — skip loopback / virtual which
            # are usually zero anyway.
            if "loopback" not in p and "isatap" not in p:
                net_in_total += fv
        elif "bytes sent/sec" in p:
            if "loopback" not in p and "isatap" not in p:
                net_out_total += fv
        elif "system\\processes" in p:
            info["process_count"] = int(fv)
        elif "% processor time" in p and "_total" not in p:
            # Per-core load — keep them all so the recorder can report
            # min/avg/max plus the worst single core (catches a busy-loop
            # on one core that hides inside the _Total average).
            cores.append(round(fv, 1))
    info["net_in_kbps"] = round(net_in_total / 1024.0, 1)
    info["net_out_kbps"] = round(net_out_total / 1024.0, 1)
    if cores:
        info["cpu_cores_pct"] = cores
        info["cpu_core_max_pct"] = max(cores)
        info["cpu_core_avg_pct"] = round(sum(cores) / len(cores), 1)
    return info


def probe_top_processes(n: int = 8) -> list[dict]:
    """Top N CPU-consuming processes, with Windows service-name resolution.

    Returns a list of dicts shaped like:
        {
          "name":                 "sspservice",            # exe basename
          "cpu_pct":              49.3,                    # % across all cores
          "pid":                  4521,                    # primary PID (or None)
          "service_name":         "SophosEPDS",            # EXACT Set-Service name
          "service_display_name": "Sophos Endpoint Defense Service",
        }

    `service_name` / `service_display_name` are populated when at least one
    of the process's PIDs corresponds to a row in Win32_Service. They will
    be None when the process is a standalone user app (browsers, Office) or
    when the WMI query fails.

    This is the field optimizer prompts MUST use for disable_service /
    set_service_manual — the `name` field is the executable basename and
    often differs from the Windows service Name (e.g. process name
    'sspservice' but service name 'SophosEPDS').

    Slow (~700-1000 ms — one Get-Counter call + one Win32_Service query).
    Called only at optimizer cycle time, not from the 2-second poll loop.
    """
    # 1. CPU% + PID per process instance, via two synchronized PerfMon counters.
    counter_cmd = (
        "$cpu = (Get-Counter -Counter '\\Process(*)\\% Processor Time' "
        "  -ErrorAction SilentlyContinue).CounterSamples; "
        "$pids = (Get-Counter -Counter '\\Process(*)\\ID Process' "
        "  -ErrorAction SilentlyContinue).CounterSamples; "
        "$pidMap = @{}; "
        "foreach ($s in $pids) { "
        "  if ($s.InstanceName -notmatch '^(_total|idle)$') { "
        "    $pidMap[$s.InstanceName] = [int]$s.CookedValue "
        "  } "
        "} "
        "foreach ($s in $cpu) { "
        "  if ($s.InstanceName -notmatch '^(_total|idle)$' "
        "      -and $s.CookedValue -gt 0.5) { "
        "    $p = if ($pidMap.ContainsKey($s.InstanceName)) "
        "         { $pidMap[$s.InstanceName] } else { 0 }; "
        "    '{0}|{1}|{2:N2}' -f $s.InstanceName, $p, $s.CookedValue "
        "  } "
        "}"
    )
    out = ps(counter_cmd, timeout=20)

    # Merge per-instance samples by cleaned process name (strip #N suffix).
    merged: dict[str, dict] = {}
    for line in out.splitlines():
        parts = line.split("|", 2)
        if len(parts) != 3:
            continue
        iname, pid_s, cpu_s = parts
        cpu = safe_float(cpu_s)
        if cpu is None or cpu < 0.5:
            continue
        clean = re.sub(r"#\d+$", "", iname.strip())
        entry = merged.setdefault(
            clean, {"name": clean, "cpu_pct": 0.0, "pids": []}
        )
        entry["cpu_pct"] += cpu
        pid_v = safe_float(pid_s)
        if pid_v is not None and pid_v > 0:
            entry["pids"].append(int(pid_v))

    procs = sorted(merged.values(), key=lambda p: p["cpu_pct"], reverse=True)[:n]

    # 2. PID → Windows service name mapping, from Win32_Service.
    svc_cmd = (
        "Get-CimInstance Win32_Service -ErrorAction SilentlyContinue "
        "| Where-Object { $_.ProcessId -gt 0 } "
        "| ForEach-Object { '{0}|{1}|{2}' -f $_.ProcessId, $_.Name, $_.DisplayName }"
    )
    pid_to_service: dict[int, dict] = {}
    try:
        svc_out = ps(svc_cmd, timeout=20)
    except Exception as e:
        logger.warning("probe_top_processes: service map query failed: %s", e)
        svc_out = ""

    for line in svc_out.splitlines():
        parts = line.split("|", 2)
        if len(parts) != 3:
            continue
        pid_s, sname, sdisplay = parts
        try:
            pid_i = int(pid_s.strip())
        except (ValueError, TypeError):
            continue
        # If multiple services share a PID (svchost), keep the first encountered.
        if pid_i > 0 and pid_i not in pid_to_service:
            pid_to_service[pid_i] = {
                "service_name": sname.strip(),
                "service_display_name": sdisplay.strip(),
            }

    # 3. Attach service info to each top process via the first PID that matches.
    for p in procs:
        matched = None
        for pid in p.get("pids") or []:
            if pid in pid_to_service:
                matched = pid_to_service[pid]
                break
        p["pid"] = (p["pids"][0] if p.get("pids") else None)
        p["service_name"] = matched["service_name"] if matched else None
        p["service_display_name"] = matched["service_display_name"] if matched else None
        # Don't leak internal accumulator
        if "pids" in p:
            del p["pids"]

    return procs


def probe_user_session():
    """User-presence and session-state signals — what we can reliably tell
    from a running Python process about whether the human is here, the
    screen is on, and whether explorer.exe is running for them.

    Returns:
        {
          "idle_s":            seconds since last keyboard/mouse input,
          "idle_human":        "4h 12m 30s" formatted,
          "screen_saver_on":   True if the screen saver is currently running,
          "monitor_on":        True/False if we can tell, None if unsure,
          "user_logged_in":    True iff explorer.exe is running (user shell up),
          "username":          current console user,
        }

    All fields are best-effort — None when the underlying API isn't available.
    """
    import ctypes
    import sys
    from ctypes import wintypes

    info = {}
    if sys.platform != "win32":
        return info

    # ── idle time via GetLastInputInfo ──
    class _LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    try:
        lii = _LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(lii)
        if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
            tick = ctypes.windll.kernel32.GetTickCount()
            idle_ms = max(0, tick - lii.dwTime)
            info["idle_s"] = idle_ms // 1000
            s = idle_ms // 1000
            h, rem = divmod(s, 3600)
            m, sec = divmod(rem, 60)
            info["idle_human"] = (
                f"{h}h{m:02d}m{sec:02d}s" if h else
                f"{m}m{sec:02d}s" if m else f"{sec}s"
            )
    except Exception as e:
        logger.debug("probe_user_session: GetLastInputInfo failed: %s", e)

    # ── screen saver active? via SystemParametersInfoW ──
    try:
        SPI_GETSCREENSAVERRUNNING = 0x0072
        running = wintypes.BOOL(False)
        if ctypes.windll.user32.SystemParametersInfoW(
            SPI_GETSCREENSAVERRUNNING, 0, ctypes.byref(running), 0
        ):
            info["screen_saver_on"] = bool(running.value)
    except Exception as e:
        logger.debug("probe_user_session: SPI_GETSCREENSAVERRUNNING failed: %s", e)

    # ── monitor power state via Win32 ──
    # We can't directly query "is the panel lit" from user-mode, but we CAN
    # ask EnumDisplayMonitors how many monitors Windows considers active.
    # When the laptop screen turns off (power-saving or lid closed), Windows
    # typically drops it from the enumerated set.
    try:
        MONITORENUMPROC = ctypes.WINFUNCTYPE(
            ctypes.c_int, wintypes.HMONITOR, wintypes.HDC,
            ctypes.POINTER(wintypes.RECT), wintypes.LPARAM,
        )
        count = [0]

        def _cb(hMon, hdc, lprc, lParam):
            count[0] += 1
            return 1

        if ctypes.windll.user32.EnumDisplayMonitors(0, None, MONITORENUMPROC(_cb), 0):
            info["monitor_count"] = count[0]
            info["monitor_on"] = count[0] > 0
    except Exception as e:
        logger.debug("probe_user_session: EnumDisplayMonitors failed: %s", e)

    # ── username + logged-in check (explorer.exe running) ──
    try:
        info["username"] = os.environ.get("USERNAME", "?")
        # Check for any running explorer.exe — quick stdlib subprocess.
        out = ps(
            "Get-Process explorer -ErrorAction SilentlyContinue | "
            "Measure-Object | Select-Object -ExpandProperty Count"
        )
        n = safe_float(out)
        info["user_logged_in"] = (n is not None and n > 0)
        info["explorer_processes"] = int(n) if n is not None else None
    except Exception as e:
        logger.debug("probe_user_session: explorer check failed: %s", e)

    return info


def probe_power_requests():
    """Run `powercfg /requests` and parse out what's actively blocking the
    system from sleeping or the display from turning off. This is the most
    direct diagnostic for "fans keep running when I leave my computer":
    when DISPLAY or SYSTEM has non-empty entries, something is preventing
    the OS from idling.

    Returns:
        {
          "DISPLAY":   ["[PROCESS] chrome.exe", ...],    # keeps screen on
          "SYSTEM":    [...],                            # keeps CPU/disk active
          "AWAYMODE":  [...],
          "EXECUTION": [...],                            # 'don't suspend me'
          "PERFBOOST": [...],
          "ACTIVELOCKSCREEN": [...],
        }
        Empty categories are kept as []. None when powercfg can't be run.
    """
    out = ps("powercfg /requests")
    if not out:
        return None

    categories: dict[str, list[str]] = {}
    current = None
    for raw in out.splitlines():
        line = raw.strip()
        if not line:
            continue
        # Section headers end with ":" (e.g. "DISPLAY:", "SYSTEM:")
        if line.endswith(":") and " " not in line:
            current = line[:-1]
            categories[current] = []
        elif current is not None and line != "None.":
            # Compress to one line — strip Windows path noise.
            entry = re.sub(r"\\Device\\HarddiskVolume\d+", "", line)
            categories[current].append(entry)
    return categories


def probe_oem_sensors():
    if not pcd_state.OEM_DISCOVERY:
        return []
    items = []
    for ns, cls in pcd_state.OEM_DISCOVERY:
        out = ps(
            f"Get-CimInstance -Namespace '{ns}' -ClassName '{cls}' "
            "-ErrorAction SilentlyContinue | "
            "Select-Object Name, CurrentValue, Value, CurrentReading, "
            "ActiveCooling, DesiredSpeed, Status, Temperature | Format-List"
        )
        records, current = [], {}
        for line in out.splitlines():
            if ":" not in line:
                if current:
                    records.append(current); current = {}
                continue
            k, v = [s.strip() for s in line.split(":", 1)]
            if v:
                current[k] = v
        if current:
            records.append(current)
        if records:
            items.append({"namespace": ns, "class": cls, "records": records})
    return items
