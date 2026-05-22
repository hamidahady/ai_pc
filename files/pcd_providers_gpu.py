"""
pcd_providers_gpu.py — cross-vendor GPU telemetry provider chain.

Public:
    get_gpu_metrics() -> list[dict]   (each dict = one GPU, possibly empty)
    gpu_source()      -> str          ("nvidia-smi"|"amd_wmi"|"intel_wmi"|
                                       "perf_counters"|"none")

GPU dict shape (every numeric field optional, `source` always present):
    {
      "name":         "NVIDIA RTX 4080 Laptop GPU",
      "vendor":       "NVIDIA"|"AMD"|"Intel"|"Generic",
      "source":       "nvidia-smi"|"amd_wmi"|"intel_wmi"|"perf_counters",
      "temp_c":       78.0,
      "fan_pct":      55.0,
      "power_w":      95.0,
      "util_pct":     43.0,
      "clock_gr_mhz": 1450.0,
      "clock_mem_mhz":8001.0,
      "vram_used_mb": 4096,
      "vram_total_mb":12288,
    }

Provider order:
    1. nvidia-smi.exe         → full telemetry on NVIDIA hardware
    2. AMD WMI                → name + sometimes temp on AMD discrete
    3. Intel WMI              → name on Intel iGPU
    4. Windows Perf Counters  → universal fallback — util% + VRAM on ANY GPU

The shape is backward-compatible with the old probe_nvidia() return value
(list[dict] with the same keys), so existing UI/optimizer code keeps working.
"""

import subprocess

from pcd_log import logger
from pcd_shell import ps, safe_float


_last_source: str = "none"


# ─── provider 1: NVIDIA via nvidia-smi.exe ───


def _nvidia_smi() -> list[dict]:
    try:
        r = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=name,temperature.gpu,fan.speed,power.draw,"
             "utilization.gpu,clocks.gr,clocks.mem,memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
    except FileNotFoundError:
        return []
    except Exception as e:
        logger.debug("gpu nvidia-smi failed: %s", e)
        return []

    gpus: list[dict] = []
    for line in (r.stdout or "").strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 7:
            continue
        vram_used = safe_float(parts[7]) if len(parts) > 7 else None
        vram_total = safe_float(parts[8]) if len(parts) > 8 else None
        gpus.append({
            "name":          parts[0],
            "vendor":        "NVIDIA",
            "source":        "nvidia-smi",
            "temp_c":        safe_float(parts[1]),
            "fan_pct":       safe_float(parts[2]),
            "power_w":       safe_float(parts[3]),
            "util_pct":      safe_float(parts[4]),
            "clock_gr_mhz":  safe_float(parts[5]),
            "clock_mem_mhz": safe_float(parts[6]),
            "vram_used_mb":  int(vram_used) if vram_used else None,
            "vram_total_mb": int(vram_total) if vram_total else None,
        })
    return gpus


# ─── provider 2: AMD via WMI ───


def _amd_wmi() -> list[dict]:
    """AMD has no nvidia-smi-equivalent on Windows. Most consumer drivers
    do not expose live temp/power through WMI either — but we still try
    a couple of known namespaces. If they fail, the perf-counter fallback
    will pick up util% and VRAM for any AMD card."""
    out = ps(
        "Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue | "
        "Where-Object { $_.Name -match 'AMD|Radeon' } | "
        "Select-Object Name, AdapterRAM, DriverVersion | Format-List",
        timeout=5,
    )
    if not out.strip():
        return []
    rec = {}
    for line in out.splitlines():
        if ":" not in line:
            continue
        k, v = [s.strip() for s in line.split(":", 1)]
        if v:
            rec[k] = v
    if not rec.get("Name"):
        return []

    vram_total = safe_float(rec.get("AdapterRAM"))
    return [{
        "name":          rec["Name"],
        "vendor":        "AMD",
        "source":        "amd_wmi",
        "vram_total_mb": int(vram_total / (1024 * 1024)) if vram_total else None,
        # temp/power not exposed via standard AMD WMI — leave None
    }]


# ─── provider 3: Intel via Win32_VideoController ───


def _intel_wmi() -> list[dict]:
    out = ps(
        "Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue | "
        "Where-Object { $_.Name -match 'Intel' } | "
        "Select-Object Name, AdapterRAM, DriverVersion | Format-List",
        timeout=5,
    )
    if not out.strip():
        return []
    rec = {}
    for line in out.splitlines():
        if ":" not in line:
            continue
        k, v = [s.strip() for s in line.split(":", 1)]
        if v:
            rec[k] = v
    if not rec.get("Name"):
        return []

    vram_total = safe_float(rec.get("AdapterRAM"))
    return [{
        "name":          rec["Name"],
        "vendor":        "Intel",
        "source":        "intel_wmi",
        "vram_total_mb": int(vram_total / (1024 * 1024)) if vram_total else None,
    }]


# ─── provider 4: Windows Perf Counters — UNIVERSAL fallback ───


def _perf_counters() -> list[dict]:
    """Reads \\GPU Engine(*)\\Utilization Percentage and
    \\GPU Adapter Memory(*)\\Dedicated Usage — the same counters Task
    Manager uses on Windows 10/11. Works on every GPU including Intel
    iGPU, NVIDIA, and AMD without any driver-specific tooling."""
    out = ps(
        r"Get-Counter -Counter "
        r"'\GPU Engine(*)\Utilization Percentage',"
        r"'\GPU Adapter Memory(*)\Dedicated Usage' "
        r"-ErrorAction SilentlyContinue | "
        r"ForEach-Object { $_.CounterSamples } | "
        r"ForEach-Object { '{0}|{1:N2}' -f $_.Path, $_.CookedValue }",
        timeout=8,
    )
    util_sum = 0.0
    vram_bytes = 0.0
    for line in out.splitlines():
        if "|" not in line:
            continue
        path, v = line.split("|", 1)
        fv = safe_float(v)
        if fv is None:
            continue
        p = path.lower()
        if "utilization percentage" in p:
            util_sum += fv
        elif "dedicated usage" in p and "adapter memory" in p:
            vram_bytes = max(vram_bytes, fv)

    # Adapter name from Win32_VideoController so we can label the tile.
    name = (ps(
        "Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue | "
        "Select-Object -First 1 -ExpandProperty Name",
        timeout=5,
    ).strip() or "GPU")

    vendor = "Generic"
    n = name.lower()
    if "nvidia" in n:
        vendor = "NVIDIA"
    elif "amd" in n or "radeon" in n:
        vendor = "AMD"
    elif "intel" in n:
        vendor = "Intel"

    util_pct = min(util_sum, 100.0) if util_sum > 0 else None
    vram_used_mb = round(vram_bytes / (1024 * 1024)) if vram_bytes > 0 else None

    if util_pct is None and vram_used_mb is None:
        return []
    return [{
        "name":         name,
        "vendor":       vendor,
        "source":       "perf_counters",
        "util_pct":     util_pct,
        "vram_used_mb": vram_used_mb,
    }]


# ─── chain orchestration ───


_PROVIDERS: list[tuple[str, callable]] = [
    ("nvidia-smi",    _nvidia_smi),
    ("amd_wmi",       _amd_wmi),
    ("intel_wmi",     _intel_wmi),
    ("perf_counters", _perf_counters),
]


def get_gpu_metrics() -> list[dict]:
    """Try each provider; return the first non-empty list. If all return
    empty, returns [] and the UI shows 'not available on this hardware'.

    Note: NVIDIA + Intel iGPU systems will return NVIDIA from this call
    (priority #1). The perf-counter fallback runs only when nothing
    upstream produced data, so dual-GPU laptops don't double-count."""
    global _last_source
    for label, fn in _PROVIDERS:
        try:
            gpus = fn()
        except Exception as e:
            logger.debug("gpu provider %s raised: %s", label, e)
            continue
        if gpus:
            _last_source = label
            return gpus
    _last_source = "none"
    return []


def gpu_source() -> str:
    return _last_source
