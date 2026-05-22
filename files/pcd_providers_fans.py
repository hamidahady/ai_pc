"""
pcd_providers_fans.py — cross-vendor fan RPM provider chain.

Public:
    get_fan_rpms() -> (cpu_rpm:int|None, gpu_rpm:int|None)
    fans_source()  -> str  ("HP"|"Dell"|"Lenovo"|"ASUS"|"Acer"|"Surface"|"none")

Each provider is wrapped in try/except — a missing WMI namespace, a
denied query, or a hung driver simply returns (None, None) so the next
provider in the chain is tried.

Provider order:
    1. HP       root\\HP\\InstrumentedBIOS :: HP_BIOSSensor / HP_BIOSNumericSensor
    2. Dell     root\\WMI Dell_NumericSensor  or  root\\DCIM\\SYSMAN DCIM_NumericSensor
    3. Lenovo   root\\WMI Lenovo_FanSpeed / Lenovo_PlatformSettingValue
    4. ASUS     root\\WMI AsusAtkWmi_WMIMethodFunction / ATKACPI
    5. Acer     root\\WMI AcerWMID_Sensor
    6. Surface  root\\WMI Microsoft_Surface_Sensor

If all six return empty we report "none" — the UI then renders "fan RPM
not available on this hardware (no OEM sensor found)" instead of a blank.
"""

from pcd_log import logger
from pcd_shell import ps


_last_source: str = "none"


def _wmi_records(namespace: str, classname: str, timeout: int = 5) -> list[dict]:
    """Generic CIM-list parser. Returns a list of dicts, one per record."""
    out = ps(
        f"Get-CimInstance -Namespace '{namespace}' -ClassName '{classname}' "
        "-ErrorAction SilentlyContinue | "
        "Select-Object Name, Description, CurrentReading, CurrentValue, "
        "Value, DesiredSpeed, Speed | Format-List",
        timeout=timeout,
    )
    records: list[dict] = []
    current: dict = {}
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
    return records


def _extract_cpu_gpu(records: list[dict]) -> tuple[int | None, int | None]:
    """Walk records, find ones identified as a CPU/GPU fan, return
    (cpu_rpm, gpu_rpm). Values < 100 are dropped as status codes."""
    cpu = gpu = None
    value_keys = ("CurrentReading", "CurrentValue", "Speed", "DesiredSpeed", "Value")
    for rec in records:
        name = (rec.get("Name") or rec.get("Description") or "").lower()
        if "fan" not in name:
            continue
        val = None
        for k in value_keys:
            v = rec.get(k)
            if v is None:
                continue
            try:
                fv = int(float(v))
            except (ValueError, TypeError):
                continue
            if fv > 100:
                val = fv
                break
        if val is None:
            continue
        if "cpu" in name and cpu is None:
            cpu = val
        elif "gpu" in name and gpu is None:
            gpu = val
        elif cpu is None:
            cpu = val  # generic fan — attribute to CPU side
    return cpu, gpu


# ─── per-vendor providers ───


def _fans_hp() -> tuple[int | None, int | None]:
    for cls in ("HP_BIOSSensor", "HP_BIOSNumericSensor"):
        try:
            recs = _wmi_records("root\\HP\\InstrumentedBIOS", cls)
        except Exception as e:
            logger.debug("fans HP %s failed: %s", cls, e)
            continue
        c, g = _extract_cpu_gpu(recs)
        if c or g:
            return c, g
    return None, None


def _fans_dell() -> tuple[int | None, int | None]:
    for ns, cls in [
        ("root\\WMI",         "Dell_NumericSensor"),
        ("root\\DCIM\\SYSMAN","DCIM_NumericSensor"),
    ]:
        try:
            recs = _wmi_records(ns, cls)
            c, g = _extract_cpu_gpu(recs)
            if c or g:
                return c, g
        except Exception as e:
            logger.debug("fans Dell %s/%s failed: %s", ns, cls, e)
    return None, None


def _fans_lenovo() -> tuple[int | None, int | None]:
    for ns, cls in [
        ("root\\WMI", "Lenovo_FanSpeed"),
        ("root\\WMI", "Lenovo_PlatformSettingValue"),
    ]:
        try:
            recs = _wmi_records(ns, cls)
            c, g = _extract_cpu_gpu(recs)
            if c or g:
                return c, g
        except Exception as e:
            logger.debug("fans Lenovo %s/%s failed: %s", ns, cls, e)
    return None, None


def _fans_asus() -> tuple[int | None, int | None]:
    for ns, cls in [
        ("root\\WMI", "AsusAtkWmi_WMIMethodFunction"),
        ("root\\WMI", "ATKACPI"),
    ]:
        try:
            recs = _wmi_records(ns, cls)
            c, g = _extract_cpu_gpu(recs)
            if c or g:
                return c, g
        except Exception as e:
            logger.debug("fans ASUS %s/%s failed: %s", ns, cls, e)
    return None, None


def _fans_acer() -> tuple[int | None, int | None]:
    try:
        recs = _wmi_records("root\\WMI", "AcerWMID_Sensor")
        return _extract_cpu_gpu(recs)
    except Exception as e:
        logger.debug("fans Acer failed: %s", e)
        return None, None


def _fans_surface() -> tuple[int | None, int | None]:
    try:
        recs = _wmi_records("root\\WMI", "Microsoft_Surface_Sensor")
        return _extract_cpu_gpu(recs)
    except Exception as e:
        logger.debug("fans Surface failed: %s", e)
        return None, None


_PROVIDERS: list[tuple[str, callable]] = [
    ("HP",      _fans_hp),
    ("Dell",    _fans_dell),
    ("Lenovo",  _fans_lenovo),
    ("ASUS",    _fans_asus),
    ("Acer",    _fans_acer),
    ("Surface", _fans_surface),
]


def get_fan_rpms() -> tuple[int | None, int | None]:
    """Try every fan provider; return the first (cpu, gpu) where at least
    one value is non-None. Updates `fans_source()`."""
    global _last_source
    for label, fn in _PROVIDERS:
        try:
            c, g = fn()
        except Exception as e:
            logger.debug("fan provider %s raised: %s", label, e)
            continue
        if c or g:
            _last_source = label
            return c, g
    _last_source = "none"
    return None, None


def fans_source() -> str:
    return _last_source
