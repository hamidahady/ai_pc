"""
pcd_probes.py — read-only monitoring probes.

One function per data source. Each returns a JSON-serializable Python value.
None of them depend on each other; the poll loop runs them all in sequence.

Also owns the one-time WMI namespace walk (oem_discover) and the one-time
system identity probe (probe_system_info).
"""

import re
import subprocess

from pcd_config import (
    BATTERY_STATUS_NAMES, GENERIC_CLASS_PATTERN, OEM_CLASS_PATTERN,
    OEM_NAMESPACE_TOKENS,
)
from pcd_log import logger
from pcd_shell import ps, safe_float

import pcd_state  # OEM_DISCOVERY accessed at call time


# ─── one-time at startup: identify the machine ───


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


# ─── one-time at startup: walk WMI for OEM/vendor sensor classes ───


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


# ─── live monitoring probes (called every REFRESH_S seconds) ───


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
        # Drop offline zones (0 K → about -273°C) and bogus near-zero values
        if v is not None and v > 5:
            sensors.append({"name": name.strip(), "value": v})
    return sensors


def probe_nvidia():
    try:
        r = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=name,temperature.gpu,fan.speed,power.draw,"
             "utilization.gpu,clocks.gr,clocks.mem",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
    except FileNotFoundError:
        return []
    gpus = []
    for line in (r.stdout or "").strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 7:
            gpus.append({
                "name": parts[0],
                "temp_c": safe_float(parts[1]),
                "fan_pct": safe_float(parts[2]),
                "power_w": safe_float(parts[3]),
                "util_pct": safe_float(parts[4]),
                "clock_gr_mhz": safe_float(parts[5]),
                "clock_mem_mhz": safe_float(parts[6]),
            })
    return gpus


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
    # Fallback for freq (the perf counter sometimes returns nothing on Win11)
    if "freq_mhz" not in info:
        raw = ps(
            "(Get-CimInstance Win32_Processor | "
            "Select-Object -First 1 -ExpandProperty CurrentClockSpeed)"
        )
        fv = safe_float(raw)
        if fv is not None:
            info["freq_mhz"] = fv
    return info


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
