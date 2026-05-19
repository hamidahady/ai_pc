"""
pcd_controls.py — read and write Windows power settings.
"""

import ctypes
import re
import subprocess
import sys

from pcd_config import (
    GUID_RE, OVERLAY_GUIDS, PERFBOOSTMODE, PROCTHROTTLEMAX, PROCTHROTTLEMIN,
    SUB_PROCESSOR, SYSCOOLPOL, proc_setting_name,
)
from pcd_log import logger
from pcd_shell import ps, ps_full, safe_float


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]


_powrprof = None
if sys.platform == "win32":
    try:
        _powrprof = ctypes.WinDLL("powrprof.dll")
        _powrprof.PowerSetActiveOverlayScheme.argtypes = [_GUID]
        _powrprof.PowerSetActiveOverlayScheme.restype = ctypes.c_ulong
    except (OSError, AttributeError):
        _powrprof = None


def _guid_from_str(s: str) -> _GUID:
    g = _GUID()
    rc = ctypes.windll.ole32.CLSIDFromString(f"{{{s}}}", ctypes.byref(g))
    if rc != 0:
        raise ValueError(f"invalid GUID: {s}")
    return g


def set_power_overlay_api(guid_str: str):
    is_balanced = guid_str.replace("-", "").strip("{}") == "0" * 32
    name_for_log = next((k for k, v in OVERLAY_GUIDS.items() if v == guid_str), guid_str)
    logger.info("SET Power Mode overlay → %s (%s)", name_for_log, guid_str)

    if _powrprof is not None:
        try:
            g = _guid_from_str(guid_str)
            rc = _powrprof.PowerSetActiveOverlayScheme(g)
            if rc == 0:
                logger.info("  PowerSetActiveOverlayScheme rc=0 (API path)")
                return True, None
            logger.warning("  PowerSetActiveOverlayScheme returned 0x%X; falling back", rc)
        except (OSError, ValueError) as e:
            logger.warning("  PowerSetActiveOverlayScheme raised %r; falling back", e)

    if is_balanced:
        active = read_active_plan_guid()
        if not active:
            return False, "could not read active scheme"
        rc, _, err = ps_full(f"powercfg /setactive {active}")
    else:
        rc, _, err = ps_full(f"powercfg /setactive {guid_str}")
    if rc == 0:
        return True, None
    return False, err or "powercfg fallback failed"


def read_active_plan_guid():
    out = ps("powercfg /getactivescheme")
    m = re.search(r"GUID:\s*([0-9a-f-]{36})", out, re.I)
    return m.group(1).lower() if m else None


def read_power_plans():
    out = ps("powercfg /list")
    active = read_active_plan_guid()
    plans = []
    for line in out.splitlines():
        m = re.search(r"GUID:\s*([0-9a-f-]{36})\s*\(([^)]+)\)", line, re.I)
        if m:
            guid = m.group(1).lower()
            plans.append({
                "guid": guid,
                "name": m.group(2).strip(),
                "active": guid == active,
            })
    return plans


def read_power_overlay():
    raw = ps(
        "Get-ItemProperty -Path "
        "'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Power\\User\\PowerSchemes' "
        "-ErrorAction SilentlyContinue | "
        "Select-Object -ExpandProperty ActiveOverlayAcPowerScheme"
    )
    raw = raw.strip().lower().lstrip("{").rstrip("}")
    if not raw:
        return None
    for name, guid in OVERLAY_GUIDS.items():
        if raw == guid:
            return name
    return raw


def _read_proc_value_from_registry(setting_guid: str):
    if sys.platform != "win32":
        return None
    try:
        import winreg
    except ImportError:
        return None
    active = read_active_plan_guid()
    if not active:
        return None
    key_path = (
        f"SYSTEM\\CurrentControlSet\\Control\\Power\\User\\PowerSchemes"
        f"\\{active}\\{SUB_PROCESSOR}\\{setting_guid}"
    )
    for value_name in ("ACSettingIndex", "DCSettingIndex"):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
                val, _ = winreg.QueryValueEx(key, value_name)
                return int(val)
        except (FileNotFoundError, OSError):
            continue
    return None


def read_proc_value(setting_guid: str):
    out = ps(f"powercfg /query SCHEME_CURRENT {SUB_PROCESSOR} {setting_guid}")
    patterns = [
        r"Current AC Power Setting Index:\s*0x([0-9a-f]+)",
        r"Current DC Power Setting Index:\s*0x([0-9a-f]+)",
        r"Current\s+[\w ]*Setting Index:\s*0x([0-9a-f]+)",
    ]
    for pattern in patterns:
        m = re.search(pattern, out, re.I)
        if m:
            return int(m.group(1), 16)
    return _read_proc_value_from_registry(setting_guid)


def read_gpu_power_info():
    try:
        r = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=power.draw,power.limit,power.min_limit,"
             "power.max_limit,power.default_limit,persistence_mode",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
    except FileNotFoundError:
        return None
    lines = (r.stdout or "").strip().splitlines()
    if not lines:
        return None
    parts = [p.strip() for p in lines[0].split(",")]
    if len(parts) < 6:
        return None
    return {
        "draw_w":      safe_float(parts[0]),
        "limit_w":     safe_float(parts[1]),
        "min_w":       safe_float(parts[2]),
        "max_w":       safe_float(parts[3]),
        "default_w":   safe_float(parts[4]),
        "persistence": parts[5],
    }


def probe_controls():
    import pcd_state
    plans = read_power_plans()
    pcd_state.KNOWN_PLAN_GUIDS = {p["guid"] for p in plans}
    gpu = read_gpu_power_info()
    if gpu and gpu.get("min_w") is not None and gpu.get("max_w") is not None:
        gpu["limit_locked"] = abs(gpu["min_w"] - gpu["max_w"]) < 0.5
    return {
        "is_admin":       pcd_state.IS_ADMIN,
        "power_plans":    plans,
        "overlay":        read_power_overlay(),
        "cooling_policy": read_proc_value(SYSCOOLPOL),
        "turbo_boost":    read_proc_value(PERFBOOSTMODE),
        "cpu_max_pct":    read_proc_value(PROCTHROTTLEMAX),
        "cpu_min_pct":    read_proc_value(PROCTHROTTLEMIN),
        "gpu":            gpu,
    }


def _apply_proc_value(setting_guid: str, value: int):
    name = proc_setting_name(setting_guid)
    before = read_proc_value(setting_guid)
    overlay_before = read_power_overlay()
    logger.info("SET %s → %s  (before=%s, overlay=%s)", name, value, before, overlay_before)

    rc1, _, e1 = ps_full(
        f"powercfg /setacvalueindex SCHEME_CURRENT {SUB_PROCESSOR} {setting_guid} {value}"
    )
    rc2, _, e2 = ps_full(
        f"powercfg /setdcvalueindex SCHEME_CURRENT {SUB_PROCESSOR} {setting_guid} {value}"
    )
    ps_full("powercfg /setactive SCHEME_CURRENT")

    if overlay_before:
        guid = OVERLAY_GUIDS.get(overlay_before, overlay_before)
        if GUID_RE.match(guid):
            set_power_overlay_api(guid)

    after = read_proc_value(setting_guid)
    if after == value:
        logger.info("VERIFY %s: %s → %s  OK", name, before, after)
    else:
        logger.error("VERIFY %s: expected %s, read %s  MISMATCH", name, value, after)

    err = (e1 + " " + e2).strip()
    return rc1 == 0 and rc2 == 0, err or None


def _set_gpu_power(watts: int):
    before = read_gpu_power_info() or {}
    logger.info("SET GPU power limit → %s W  (before=%s W)", watts, before.get("limit_w"))
    r = subprocess.run(
        ["nvidia-smi", "-i", "0", "-pl", str(int(watts))],
        capture_output=True, text=True, timeout=10,
    )
    out = (r.stdout or "")
    if r.returncode != 0:
        err = (r.stderr or out).strip()
        logger.error("  nvidia-smi rc=%d: %s", r.returncode, err[:200])
        return False, err
    if "not supported" in out.lower():
        msg = next((line.strip() for line in out.splitlines() if line.strip()), "limit not supported")
        logger.error("  nvidia-smi rejected the limit: %s", msg)
        return False, msg
    return True, None
