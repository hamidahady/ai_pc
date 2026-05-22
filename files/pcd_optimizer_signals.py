"""
pcd_optimizer_signals.py — metric snapshots, deltas, and pattern detectors.

Extracted from pcd_optimizer.py. Pure-ish helpers that read pcd_state but
own no state of their own except a small ring buffer for CPU-lock detection.

Provides:
    _snapshot_metrics()         compact dict of temps/fans/load/clocks/settings
    _fmt_snapshot(snap)         compact "k=v k=v ..." line
    _fmt_delta(before, after)   one-line "k:A→B(±diff)" of metrics that moved
    _settings_diff(b, a)        "cool: 0→1, turbo: 2→0" or "no-op"
    _detect_user_override()     compare current settings vs last AFTER snapshot
    _detect_cpu_lock()          CPU pinned at one freq across N cycles?

pcd_optimizer.py imports all of these by name.
"""

from pcd_log import logger
from pcd_state import _lock, _state


# ─── CPU-lock detection constants ───
FREQ_LOCK_WINDOW = 3      # cycles required to flag a freq lock pattern
FREQ_LOCK_IDLE_S = 300    # only flag when user was idle ≥5 min at some point

# Rolling window of (cpu_freq_mhz, idle_s) for _detect_cpu_lock.
_recent_freq_idle: list[tuple] = []


# ─────────────────────────────────────────────────────────────────────
# Snapshot helpers
# ─────────────────────────────────────────────────────────────────────


def _zone(zones: list, code: str):
    """Look up the value of an ACPI thermal zone by short code (e.g. 'CPUZ')."""
    code = code.upper()
    for z in zones:
        if code in (z.get("name") or "").upper():
            return z.get("value")
    return None


def _fan_rpms(sources: dict) -> tuple[int | None, int | None]:
    """Cross-vendor fan RPM lookup via the provider chain in
    pcd_providers_fans (HP / Dell / Lenovo / ASUS / Acer / Surface).

    The `sources` arg is unused here — kept for signature stability with
    older callers — because the provider chain queries WMI directly each
    cycle. This is cheap enough (~50ms) since the optimizer only calls
    _snapshot_metrics once per decision, not in the 2s poll loop.

    Returns (cpu_rpm, gpu_rpm); either may be None when no OEM provider
    has data for that fan, and both will be None on hardware where no
    vendor sensor class is exposed."""
    from pcd_providers_fans import get_fan_rpms
    return get_fan_rpms()


def _snapshot_metrics() -> dict:
    """Read the metrics that matter for diagnosing whether an optimizer
    decision actually had an effect: temps, fan RPMs, CPU/GPU load and
    clocks, and the active power settings."""
    with _lock:
        sources  = _state.get("sources", {}) or {}
        controls = _state.get("controls", {}) or {}
    zones = sources.get("thermal_zones") or []
    gpu   = (sources.get("nvidia") or [{}])[0]
    cp    = sources.get("cpu_proxy") or {}
    sl    = sources.get("system_load") or {}
    cpu_rpm, gpu_rpm = _fan_rpms(sources)
    return {
        "cpu_temp_c":   _zone(zones, "CPUZ"),
        "gpu_temp_c":   gpu.get("temp_c"),
        "skin_temp_c":  _zone(zones, "SK1Z"),
        "cpu_fan_rpm":  cpu_rpm,
        "gpu_fan_rpm":  gpu_rpm,
        "cpu_load_pct": cp.get("util_pct"),
        "core_max_pct": sl.get("cpu_core_max_pct"),
        "cpu_freq_mhz": cp.get("freq_mhz"),
        "gpu_power_w":  gpu.get("power_w"),
        "gpu_mclk_mhz": gpu.get("clock_mem_mhz"),
        "memory_pct":   sl.get("memory_pct"),
        "_settings": {
            "cooling_policy": controls.get("cooling_policy"),
            "turbo_boost":    controls.get("turbo_boost"),
            "cpu_max_pct":    controls.get("cpu_max_pct"),
            "cpu_min_pct":    controls.get("cpu_min_pct"),
            "overlay":        controls.get("overlay"),
        },
    }


def _fmt_snapshot(snap: dict) -> str:
    """Compact 'k1=v1 k2=v2 ...' line of all the metrics."""
    bits = []
    fields = [
        ("cpu_temp_c",   "cpu",      "°C", 1),
        ("gpu_temp_c",   "gpu",      "°C", 0),
        ("skin_temp_c",  "skin",     "°C", 1),
        ("cpu_fan_rpm",  "cpu_fan",  "rpm", 0),
        ("gpu_fan_rpm",  "gpu_fan",  "rpm", 0),
        ("cpu_load_pct", "load",     "%",  0),
        ("core_max_pct", "core_max", "%",  0),
        ("cpu_freq_mhz", "freq",     "MHz", 0),
        ("gpu_power_w",  "gpu_pwr",  "W",  0),
        ("gpu_mclk_mhz", "gpu_mclk", "MHz", 0),
        ("memory_pct",   "mem",      "%",  0),
    ]
    for key, label, unit, prec in fields:
        v = snap.get(key)
        if v is None:
            continue
        bits.append(f"{label}={v:.{prec}f}{unit}")
    return " ".join(bits) if bits else "(no data)"


def _fmt_delta(before: dict, after: dict) -> str:
    """One-line delta showing only metrics that actually moved."""
    bits = []
    fields = [
        ("cpu_temp_c",   "cpu",      "°C", 1, 0.3),    # ignore noise < 0.3°C
        ("gpu_temp_c",   "gpu",      "°C", 0, 1),
        ("skin_temp_c",  "skin",     "°C", 1, 0.3),
        ("cpu_fan_rpm",  "cpu_fan",  "rpm", 0, 30),    # fan RPMs jitter ±20
        ("gpu_fan_rpm",  "gpu_fan",  "rpm", 0, 30),
        ("cpu_load_pct", "load",     "%",  0, 3),
        ("core_max_pct", "core_max", "%",  0, 5),
        ("cpu_freq_mhz", "freq",     "MHz", 0, 50),
        ("gpu_power_w",  "gpu_pwr",  "W",  0, 1),
        ("gpu_mclk_mhz", "gpu_mclk", "MHz", 0, 100),
        ("memory_pct",   "mem",      "%",  0, 1),
    ]
    for key, label, unit, prec, thresh in fields:
        b, a = before.get(key), after.get(key)
        if b is None or a is None:
            continue
        diff = a - b
        if abs(diff) < thresh:
            continue
        sign = "+" if diff > 0 else ""
        bits.append(f"{label}:{b:.{prec}f}→{a:.{prec}f}({sign}{diff:.{prec}f}{unit})")
    return " ".join(bits) if bits else "(no measurable change)"


def _settings_diff(before: dict, after: dict) -> str:
    """Show only the settings that actually changed. 'no-op' if none."""
    bs = (before.get("_settings") or {})
    as_ = (after.get("_settings") or {})
    bits = []
    labels = {
        "cooling_policy": "cool",
        "turbo_boost":    "turbo",
        "cpu_max_pct":    "cpu_max",
        "cpu_min_pct":    "cpu_min",
        "overlay":        "mode",
    }
    for k, label in labels.items():
        b = bs.get(k)
        a = as_.get(k)
        if b != a:
            bits.append(f"{label}: {b}→{a}")
    return ", ".join(bits) if bits else "no-op (settings already at target)"


# ─────────────────────────────────────────────────────────────────────
# Pattern detectors
# ─────────────────────────────────────────────────────────────────────


def _detect_user_override(pre_snap: dict, prev: dict | None) -> dict | None:
    """Compare current power settings to what THIS optimizer set last time.
    If they differ, the user must have moved a slider in between → flag it
    so Claude knows to respect the user's preference."""
    if not prev or not prev.get("after_snapshot"):
        return None
    prev_set = (prev["after_snapshot"].get("_settings") or {})
    curr_set = (pre_snap.get("_settings") or {})
    diffs = []
    for k in ("cooling_policy", "turbo_boost", "cpu_max_pct", "cpu_min_pct", "overlay"):
        a = prev_set.get(k)
        b = curr_set.get(k)
        if a != b:
            diffs.append({"setting": k, "from": a, "to": b})
    if not diffs:
        return None
    return {
        "previous_decision_at": prev.get("started_at"),
        "settings_user_changed": diffs,
        "guidance": (
            "Do NOT revert these changes unless user state has materially "
            "shifted from the state of the previous decision."
        ),
    }


def _detect_cpu_lock(pre_snap: dict) -> dict | None:
    """Add this cycle's (freq, idle) to the ring buffer and check for the
    'CPU pinned at base clock despite idle' pattern."""
    with _lock:
        sources = _state.get("sources", {}) or {}
    idle_s = (sources.get("user_session") or {}).get("idle_s") or 0
    freq = pre_snap.get("cpu_freq_mhz")
    _recent_freq_idle.append((freq, idle_s))
    while len(_recent_freq_idle) > FREQ_LOCK_WINDOW + 2:
        _recent_freq_idle.pop(0)

    if len(_recent_freq_idle) < FREQ_LOCK_WINDOW:
        return None
    window = _recent_freq_idle[-FREQ_LOCK_WINDOW:]
    freqs = [f for f, _ in window if f is not None]
    idles = [i for _, i in window]
    if not freqs or len(set(freqs)) > 1:
        return None
    if not any(i >= FREQ_LOCK_IDLE_S for i in idles):
        return None
    return {
        "cpu_freq_mhz": freqs[0],
        "consecutive_cycles": FREQ_LOCK_WINDOW,
        "max_idle_seconds_in_window": max(idles),
        "interpretation": (
            f"CPU has stayed at {freqs[0]:.0f} MHz across {FREQ_LOCK_WINDOW} "
            f"consecutive cycles despite user being idle for up to "
            f"{max(idles)//60} min. Heat is workload-driven (something "
            f"running in the background), not configuration-driven. "
            f"Power-mode toggles will have limited effect on fan noise."
        ),
    }
