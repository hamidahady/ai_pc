"""
pcd_vendor_detect.py — one-time hardware vendor detection at startup.

Runs two PowerShell queries:
  - Win32_ComputerSystem.Manufacturer → OEM label (HP / Dell / Lenovo / ASUS /
    Acer / Surface / MSI / Razer / Samsung / Toshiba / Sony / Fujitsu /
    Gigabyte / Apple / Other)
  - Win32_VideoController.Name        → GPU vendors present (NVIDIA / AMD /
    Intel — any combination)

Results are cached in module globals. detect() is idempotent.

This is purely informational. The provider chains in pcd_providers_fans.py
and pcd_providers_gpu.py still TRY every provider regardless — vendor
detection only gives nicer logs and lets the UI show "running on Dell".
"""

from pcd_log import logger
from pcd_shell import ps


_OEM: str | None = None
_GPU_VENDORS: list[str] = []
_DETECTED = False


_OEM_PATTERNS = (
    # (label, exact-match strings, substring-match strings)
    ("HP",       ("hp",),                     ("hewlett", "hp inc", "compaq")),
    ("Dell",     (),                          ("dell",)),
    ("Lenovo",   (),                          ("lenovo", "thinkpad")),
    ("ASUS",     ("asus",),                   ("asustek",)),
    ("Acer",     (),                          ("acer",)),
    ("Surface",  (),                          ("microsoft", "surface")),
    ("MSI",      ("msi",),                    ("micro-star", "msi computer")),
    ("Razer",    (),                          ("razer",)),
    ("Samsung",  (),                          ("samsung",)),
    ("Toshiba",  (),                          ("toshiba", "dynabook")),
    ("Sony",     (),                          ("sony", "vaio")),
    ("Fujitsu",  (),                          ("fujitsu",)),
    ("Gigabyte", (),                          ("gigabyte", "aorus")),
    ("Apple",    (),                          ("apple",)),
)


def _classify_oem(manufacturer: str) -> str:
    m = (manufacturer or "").strip().lower()
    if not m:
        return "Other"
    for label, exact, substrs in _OEM_PATTERNS:
        if m in exact:
            return label
        if any(s in m for s in substrs):
            return label
    return "Other"


def _classify_gpus(controller_lines: list[str]) -> list[str]:
    vendors: list[str] = []
    for line in controller_lines:
        s = line.lower()
        if "nvidia" in s and "NVIDIA" not in vendors:
            vendors.append("NVIDIA")
        elif ("amd" in s or "radeon" in s) and "AMD" not in vendors:
            vendors.append("AMD")
        elif "intel" in s and "Intel" not in vendors:
            vendors.append("Intel")
    return vendors


def detect() -> dict:
    """Run vendor detection (once). Subsequent calls return the cached result."""
    global _OEM, _GPU_VENDORS, _DETECTED
    if _DETECTED:
        return {"oem": _OEM, "gpu_vendors": list(_GPU_VENDORS)}

    try:
        man = ps(
            "(Get-CimInstance Win32_ComputerSystem -ErrorAction SilentlyContinue)"
            ".Manufacturer"
        )
        _OEM = _classify_oem(man)
    except Exception as e:
        logger.warning("vendor_detect: Win32_ComputerSystem failed: %s", e)
        _OEM = "Other"

    try:
        ctrl = ps(
            "Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue "
            "| Select-Object -ExpandProperty Name"
        )
        _GPU_VENDORS = _classify_gpus(ctrl.splitlines())
    except Exception as e:
        logger.warning("vendor_detect: Win32_VideoController failed: %s", e)

    _DETECTED = True
    logger.info("Vendor detect: OEM=%s, GPU vendors=%s",
                _OEM, ", ".join(_GPU_VENDORS) or "(none recognized)")
    return {"oem": _OEM, "gpu_vendors": list(_GPU_VENDORS)}


def oem() -> str:
    if not _DETECTED:
        detect()
    return _OEM or "Other"


def gpu_vendors() -> list[str]:
    if not _DETECTED:
        detect()
    return list(_GPU_VENDORS)
