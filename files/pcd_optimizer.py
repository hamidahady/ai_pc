"""
pcd_optimizer.py — AI-driven auto-optimizer for the PC dashboard.

When the user clicks "Start" on the AI Auto-Optimize card, a background
thread wakes up every N minutes, packs the current _state plus a slice of
the latest pc_status_*.txt recording plus the last control changes from
log_*.txt into a prompt, and shells out to `claude -p`. Claude returns a
small JSON document classifying the user's state and listing actions to
apply. We validate each action and run it through the same internal
helpers the dashboard's UI buttons use.

Authentication: claude CLI's own OAuth — same as the chat panel — so this
costs no API credit and uses the Claude Code subscription.

States Claude is asked to classify into:
    active       user at the PC, low idle
    working      sustained CPU/GPU work
    brief_away   5–30 min idle
    long_away    >30 min idle, screen on
    screen_off   screen saver running or monitor off
    locked       workstation locked (idle very long, screen off, etc.)

Actions Claude may choose:
    apply_preset    name in {quiet, balanced, performance}
    set_power_mode  mode in {best-efficiency, balanced, best-performance}
    set_cooling     0 (Passive) or 1 (Active)
    set_turbo       0..5
    set_cpu_max     30..100
    set_cpu_min     5..100
    noop            (do nothing — current state is already appropriate)

Safety:
  - We validate every action's args; out-of-range values are skipped.
  - We never apply the same composite preset twice in a row without
    something materially changing (avoids thrash).
  - The user can hit Stop at any time; the thread checks _stop_event
    between calls AND between sleep ticks.
"""

import json
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

from pcd_log import LOG_DIR, logger
from pcd_state import _lock, _state


CLAUDE_BIN        = shutil.which("claude") or "claude"
CLAUDE_TIMEOUT_S  = 120
CLAUDE_MODEL      = "opus"
HISTORY_KEEP      = 20    # last N decisions to surface to the UI
HISTORY_PROMPT    = 12    # last N pc_status samples to send to Claude
LOG_TAIL_LINES    = 40    # last N lines of log_*.txt to send to Claude
MIN_INTERVAL_MIN  = 1     # safety floor: don't hammer Claude
DEFAULT_INTERVAL_MIN = 30    # 30-min cadence reduces churn; lower in UI if you want
FREQ_LOCK_WINDOW  = 3        # cycles required to flag a CPU-freq lock pattern
FREQ_LOCK_IDLE_S  = 300      # ... only flag when user was idle ≥5 min at some point


# ─── module-level state guarded by _rec_lock ───
_rec_lock = threading.Lock()
_active: bool = False
_thread = None
_stop_event = threading.Event()
_interval_s: int = DEFAULT_INTERVAL_MIN * 60

_last_decision: dict | None = None
_last_run_at: datetime | None = None
_next_run_at: datetime | None = None
_history: list[dict] = []
_last_applied_preset: str | None = None
_last_applied_mode:   str | None = None

# Rolling window of (cpu_freq_mhz, idle_s) — used to detect when CPU stays
# pinned at a single frequency across many cycles. If that's true even
# while the user has been idle, the heat is workload-driven and power-mode
# toggles will have limited effect (Claude needs to know this).
_recent_freq_idle: list[tuple] = []

# Cross-module queue: the recorder peeks here once per sample so it can stamp
# the row right after each optimizer decision with an OPT: section.
_decision_queue_lock = threading.Lock()
_decision_queue: dict | None = None


def queue_decision_for_recorder(d: dict) -> None:
    """Push a decision summary to be tagged onto the next pc_status sample."""
    global _decision_queue
    with _decision_queue_lock:
        _decision_queue = d


def pop_decision_for_recorder() -> dict | None:
    """Consume the queued decision (called by the recorder once per sample)."""
    global _decision_queue
    with _decision_queue_lock:
        d = _decision_queue
        _decision_queue = None
        return d


_SYSTEM_PROMPT = """You are an AI PC performance optimizer for a Windows laptop.

Given the live snapshot, a slice of recent history, and a summary of the
last control changes, decide whether any power settings should be adjusted
to balance performance and noise.

USER STATE OPTIONS (pick exactly one for "state"):
- active       user at the PC, idle < 5 min, mouse/keyboard active
- working      sustained CPU or GPU load (>50%) — performance mode justified
- brief_away   5-30 min idle, screen still on
- long_away    >30 min idle, screen on
- screen_off   screen saver running OR monitor off
- locked       likely workstation locked: very long idle AND screen off

POSSIBLE ACTIONS (pick zero or more):

POWER ACTIONS:
- {"name":"apply_preset", "args":{"name": "quiet"|"balanced"|"performance"}}
- {"name":"set_power_mode", "args":{"mode": "best-efficiency"|"balanced"|"best-performance"}}
- {"name":"set_cooling", "args":{"value": 0|1}}            (0=Passive quiet, 1=Active fans first)
- {"name":"set_turbo", "args":{"mode": 0|1|2|3|4|5}}       (0=Off, 2=Aggressive)
- {"name":"set_cpu_max", "args":{"percent": 30..100}}
- {"name":"set_cpu_min", "args":{"percent": 5..100}}

SYSTEM FIX ACTIONS — TIERED:
The user has authorized you to disable ANY Windows service that's hurting
performance. Three tiers govern how you choose:

  PREFERRED tier — known-safe, non-essential auto-updaters. Try these
                   first whenever they appear in TOP_PROCESSES:
    FoxitReaderUpdateService, AdobeUpdateService, AdobeARMservice,
    AdobeAcrobatUpdateService, GoogleChromeElevationService,
    GoogleUpdaterService*, edgeupdate, edgeupdatem,
    MicrosoftEdgeElevationService, ZoomCptService,
    ZoomVideoConferenceService, SpotifyUpdater, SteamService,
    plus anything matching *UpdateService or *UpdaterService.
    These are applied with INFO-level "FIXER APPLIED" log lines.

  ESCALATED tier — anything else NOT in the hard-blocked list. Use only
                   when preferred-tier fixes haven't moved the needle for
                   the last 1–2 OUTCOME blocks (deltas all "no measurable
                   change" or worse). Examples of valid escalations:
    - sspservice, sophosfilescanner, sedservice, sophososquery (Sophos AV)
      WARNING: this is corporate-managed; disabling may violate IT policy.
    - MsMpEng / WinDefend (Microsoft Defender)
    - WSearch (Windows Search Indexer)
    - wuauserv (Windows Update) — paused, not removed
    - LanmanServer / LanmanWorkstation (file sharing) if unused
    Applied with WARNING-level "FIXER ESCALATED" log lines.

  HARD-BLOCKED — will be refused even if you propose them, because they
                 would break Windows or the dashboard itself. Don't waste
                 a cycle proposing these:
    rpcss, rpceptmapper, dcomlaunch, plugplay, schedule, eventlog,
    eventsystem, lsass, samss, lsm, profsvc, netlogon, dnscache, power,
    winmgmt, wmiprvse, trustedinstaller, wininit, http.

Action shapes:
- {"name":"disable_service", "args":{"name": "<windows service name>"}}
  Stop the service and set startup to Disabled. Persistent across reboots.
- {"name":"set_service_manual", "args":{"name": "<windows service name>"}}
  Less aggressive: set startup to Manual. Service can still launch on
  demand but won't auto-start. Prefer this for services the user might
  want occasionally (e.g. Steam if user games).
- {"name":"report_only", "args":{"message": "<one-line note>"}}
  Surface a finding without taking an action. Use sparingly — the user
  has authorized aggressive action, so prefer to actually fix.

RULES:
1. If current settings already match the inferred state, return actions=[].
2. Prefer apply_preset over individual sliders when possible.
3. For active/working → balanced or performance. For brief_away → balanced.
4. For long_away/screen_off/locked → quiet (and keep CPU min at 5%).
5. Don't reverse a recent change unless something materially shifted.
6. Be conservative — small adjustments preferred over large ones.

RULES FOR SYSTEM FIXES:
7. Apply at most ONE system fix action per cycle (compounding too fast
   makes outcomes impossible to attribute).
8. Only propose a fix when the named service appears in TOP_PROCESSES at
   >2% CPU — anchor every fix to actual measured load.
9. Try PREFERRED-tier services first. If multiple preferred candidates
   are present, pick the one with the highest CPU%.
10. ESCALATE to non-preferred services only when:
    - The previous 1–2 cycles applied preferred fixes (or had no fix to
      apply) AND
    - The latest OUTCOME block shows no measurable thermal/fan improvement
      ("(no measurable change)" or worse), AND
    - The candidate process has dominant CPU% in TOP_PROCESSES.
11. When escalating to security software (Sophos, Defender), include in
    your reasoning that this may have IT-policy implications. The user
    has authorized this — they want results — but flag it clearly.
12. Once a service has been disabled in a previous cycle, do not propose
    disabling it again (the fix is persistent across reboots).
13. Avoid HARD-BLOCKED services — they'll be refused. Don't waste a cycle.

EXTRA CONTEXT YOU MAY RECEIVE (treat as load-bearing):

- USER_MANUAL_OVERRIDE: shown when the user changed settings manually since
  your last decision. RESPECT user preferences. Do NOT undo the user's
  changes unless the user state (active/working/away) has materially
  shifted from what it was at your previous decision. If unsure, return
  actions=[] and explain in reasoning that the user just adjusted things.

- CPU_LOCK_WARNING: shown when CPU frequency has been pinned at a single
  value across multiple cycles despite the user being idle for >5 min.
  This means heat is workload-driven (something running in the background),
  not configuration-driven. Power-mode toggles will have limited effect on
  fan noise. Mention this in your reasoning when it applies. Often the
  right action here is actions=[] plus a clear reasoning sentence that
  names the dominant background process from TOP_PROCESSES (so the user
  knows what to investigate).

- TOP_PROCESSES: list of the highest-CPU processes right now (% across all
  cores; on a 24-thread laptop a single thread at 100% shows as ~4%). Each
  entry has: exe_name, cpu_pct, pid, AND CRITICALLY a "service:" tag with
  the EXACT Windows service name + display name (when the process is a
  service host).

  Two essential rules for using this data:
  1. In your REASONING, you may refer to the process by exe_name (e.g.
     "sspservice at 49%"); that's what the user sees in Task Manager.
  2. In your ACTION's args.name field for disable_service or
     set_service_manual, you MUST use the value from the "service:" tag
     (the Windows service Name, NOT the exe_name). exe_name and Windows
     service Name are commonly different (e.g. exe=sspservice but the
     Windows service might be SophosEPDS, or
     "Sophos System Protection Service"). Calling
     disable_service('sspservice') fails with "service not found";
     disable_service('SophosEPDS') works.
  3. If TOP_PROCESSES shows "[no service]" for a process, it is NOT a
     Windows service (e.g. user-launched apps, browsers, Office,
     pycharm64.exe). You CANNOT use disable_service on these. Either
     pick a different target or use report_only to flag the finding.

  Examples of correct reasoning + action:
    Reasoning: "sspservice at 49% is the Sophos AV service consuming a
                full core; setting it to manual."
    Action:    {"name": "set_service_manual",
                "args": {"name": "SophosEPDS"}}   ← uses service: value

OUTPUT STRICT JSON ONLY (no markdown fences, no prose outside JSON):
{
  "state": "<one of the options above>",
  "reasoning": "<one short sentence explaining your judgment>",
  "actions": [<zero or more action objects>],
  "confidence": "high"|"medium"|"low",
  "next_check_minutes": <integer, 1..60, your suggested cadence for the next check>
}
"""


# ─────────────────────────────────────────────────────────────────────
# Building the prompt sent to Claude
# ─────────────────────────────────────────────────────────────────────


def _live_snapshot() -> dict:
    """Compact summary of _state used at the top of every prompt."""
    with _lock:
        sources = _state.get("sources", {}) or {}
        controls = _state.get("controls", {}) or {}
        system   = _state.get("system", {}) or {}

    zones = sources.get("thermal_zones") or []
    cpu_z = next((z for z in zones if "CPUZ" in z.get("name", "").upper()), None)
    skin_z = next((z for z in zones if "SK1Z" in z.get("name", "").upper()), None)
    gpu = (sources.get("nvidia") or [{}])[0]
    cp = sources.get("cpu_proxy") or {}
    sl = sources.get("system_load") or {}
    b  = sources.get("battery") or {}
    us = sources.get("user_session") or {}
    pr = sources.get("power_requests") or {}
    active_plan = next(
        (p.get("name") for p in (controls.get("power_plans") or []) if p.get("active")),
        None,
    )
    return {
        "machine": f"{system.get('Manufacturer', '?')} {system.get('Model', '?')}",
        "temps_c": {
            "cpu": round(cpu_z["value"], 1) if cpu_z else None,
            "skin": round(skin_z["value"], 1) if skin_z else None,
            "gpu": gpu.get("temp_c"),
        },
        "cpu_load": {
            "total_pct": cp.get("util_pct"),
            "core_max_pct": sl.get("cpu_core_max_pct"),
            "perf_pct": cp.get("perf_pct"),
            "freq_mhz": cp.get("freq_mhz"),
        },
        "gpu": {
            "power_w": gpu.get("power_w"),
            "util_pct": gpu.get("util_pct"),
            "clock_gr_mhz": gpu.get("clock_gr_mhz"),
            "clock_mem_mhz": gpu.get("clock_mem_mhz"),
        } if gpu else None,
        "memory_pct": sl.get("memory_pct"),
        "disk_io_pct": sl.get("disk_io_pct"),
        "net_kbps": {"in": sl.get("net_in_kbps"), "out": sl.get("net_out_kbps")},
        "battery": {
            "charge_pct": b.get("charge_pct"),
            "status": b.get("status"),
        },
        "user": {
            "idle_s": us.get("idle_s"),
            "idle_human": us.get("idle_human"),
            "screen_saver_on": us.get("screen_saver_on"),
            "monitor_on": us.get("monitor_on"),
            "monitor_count": us.get("monitor_count"),
            "logged_in": us.get("user_logged_in"),
        },
        "wake_locks": {k: v for k, v in pr.items() if v} if isinstance(pr, dict) else None,
        "active_settings": {
            "power_plan": active_plan,
            "power_mode": controls.get("overlay"),
            "cooling": {0: "Passive", 1: "Active"}.get(controls.get("cooling_policy")),
            "turbo_mode": controls.get("turbo_boost"),
            "cpu_max_pct": controls.get("cpu_max_pct"),
            "cpu_min_pct": controls.get("cpu_min_pct"),
            "gpu_power_limit_w": (controls.get("gpu") or {}).get("limit_w"),
        },
    }


def _newest_status_tail(n_samples: int = HISTORY_PROMPT) -> str:
    """Return the most recent N sample lines from the latest pc_status_*.txt."""
    files = sorted(LOG_DIR.glob("pc_status_*.txt"))
    if not files:
        return "(no pc_status recording present — start a recording for more context)"
    try:
        with open(files[-1], encoding="utf-8") as f:
            lines = f.readlines()
    except Exception as e:
        return f"(could not read {files[-1].name}: {e})"
    samples = [ln.rstrip() for ln in lines if ln and ln[0].isdigit()]
    if not samples:
        return f"(file {files[-1].name} has header only, no samples yet)"
    tail = samples[-n_samples:]
    return f"# from {files[-1].name} (last {len(tail)} samples)\n" + "\n".join(tail)


def _recent_log_changes(n_lines: int = LOG_TAIL_LINES) -> str:
    """Last N lines of the current launch's log_*.txt — captures recent
    SET/VERIFY pairs, optimizer actions, errors."""
    files = sorted(LOG_DIR.glob("log_*.txt"))
    if not files:
        return "(no log file)"
    try:
        with open(files[-1], encoding="utf-8") as f:
            lines = f.readlines()
    except Exception as e:
        return f"(could not read {files[-1].name}: {e})"
    interesting = [ln.rstrip() for ln in lines
                   if any(tok in ln for tok in ("SET ", "VERIFY", "OPTIMIZER", "RECORDER", "ERROR"))]
    tail = interesting[-n_lines:]
    return "\n".join(tail) if tail else "(no recent SET/VERIFY/OPTIMIZER lines)"


def _build_prompt(
    outcome: dict | None = None,
    user_override: dict | None = None,
    cpu_lock_warning: dict | None = None,
    top_processes: list[dict] | None = None,
) -> str:
    """Render the user-side prompt body (system prompt is appended separately).

    Optional context blocks are inserted near the top so they catch Claude's
    attention before the bulkier history sections:
        outcome          how the previous decision played out
        user_override    settings the user manually changed since last cycle
        cpu_lock_warning CPU stuck at one freq across several cycles
        top_processes    highest CPU consumers right now
    """
    parts = [
        "CURRENT LIVE SNAPSHOT (just polled):",
        json.dumps(_live_snapshot(), indent=2, default=str),
    ]
    if user_override:
        parts.append("\nUSER_MANUAL_OVERRIDE (the user changed these settings since your last decision — respect them):")
        parts.append(json.dumps(user_override, indent=2, default=str))
    if cpu_lock_warning:
        parts.append("\nCPU_LOCK_WARNING (heat is workload-driven, not config-driven):")
        parts.append(json.dumps(cpu_lock_warning, indent=2, default=str))
    if top_processes:
        parts.append(
            "\nTOP_PROCESSES (right-now CPU consumers, % across all cores)."
            "\n  Each entry: exe_name  cpu_pct  pid  [service: <service_name> / <display>]"
            "\n  CRITICAL: use the value AFTER 'service:' (not exe_name) when calling"
            "\n  disable_service or set_service_manual — exe_name and Windows service"
            "\n  Name are different (e.g. exe=sspservice but service=SophosEPDS)."
            "\n  Entries with [no service] are standalone apps — disable_service WILL"
            "\n  FAIL on them; consider report_only instead."
        )
        for p in top_processes:
            svc = p.get("service_name")
            disp = p.get("service_display_name")
            if svc:
                svc_str = f"[service: {svc} / {disp}]"
            else:
                svc_str = "[no service]"
            parts.append(
                f"  {p.get('name', '?'):30s}  "
                f"{p.get('cpu_pct', 0):5.1f}%  "
                f"pid={p.get('pid') or '?'}  "
                f"{svc_str}"
            )
    if outcome:
        parts.append("\nPREVIOUS DECISION OUTCOME (learn from this — your last choice and what happened):")
        parts.append(json.dumps(outcome, indent=2, default=str))
    parts.append("\nRECENT pc_status SAMPLES:")
    parts.append(_newest_status_tail())
    parts.append("\nRECENT CONTROL CHANGES FROM log_*.txt:")
    parts.append(_recent_log_changes())
    parts.append("\nWhat adjustments should be made? Output JSON only.")
    return "\n".join(parts)


# ─────────────────────────────────────────────────────────────────────
# User-override + CPU-freq-lock detection — pre-cycle analysis
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


# ─────────────────────────────────────────────────────────────────────
# Metric snapshots — used to log before/after each decision and to grade
# the OUTCOME of the previous decision against current state.
# ─────────────────────────────────────────────────────────────────────


def _zone(zones: list, code: str):
    code = code.upper()
    for z in zones:
        if code in (z.get("name") or "").upper():
            return z.get("value")
    return None


def _hp_fan_rpms(sources: dict) -> tuple[int | None, int | None]:
    """Pull CPU / GPU fan RPMs out of the HP_BIOSSensor / HP_BIOSNumericSensor
    OEM data. Returns (cpu_rpm, gpu_rpm) — either may be None."""
    cpu_rpm = None
    gpu_rpm = None
    for h in (sources.get("oem") or []):
        for rec in (h.get("records") or []):
            name = (rec.get("Name") or "").strip().lower()
            cur = rec.get("CurrentReading")
            try:
                val = int(cur) if cur is not None else None
            except (ValueError, TypeError):
                val = None
            # HP_BIOSSensor returns 0 or status codes for non-fan sensors;
            # real fan RPMs are > 100.
            if val is None or val < 100:
                continue
            if "cpu" in name and "fan" in name and cpu_rpm is None:
                cpu_rpm = val
            if "gpu" in name and "fan" in name and gpu_rpm is None:
                gpu_rpm = val
    return cpu_rpm, gpu_rpm


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
    cpu_rpm, gpu_rpm = _hp_fan_rpms(sources)
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
# Calling Claude
# ─────────────────────────────────────────────────────────────────────


def _extract_json(text: str) -> dict:
    """Pull the first {...} blob out of Claude's stdout (in case it wrapped
    in markdown fences despite the instructions)."""
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        raise ValueError(f"no JSON object in claude output: {text[:200]!r}")
    return json.loads(m.group(0))


def _call_claude(prompt: str) -> dict:
    """Invoke `claude -p` and parse the JSON it returns."""
    if not (shutil.which(CLAUDE_BIN) or shutil.which("claude")):
        raise RuntimeError("claude CLI not on PATH")

    cmd = [
        CLAUDE_BIN, "-p", prompt,
        "--allowedTools", "",                       # no agentic tools, pure text
        "--append-system-prompt", _SYSTEM_PROMPT,
        "--model", CLAUDE_MODEL,
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True, text=True,
        encoding="utf-8", errors="replace",
        timeout=CLAUDE_TIMEOUT_S,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()[:300]
        raise RuntimeError(f"claude rc={proc.returncode}: {err}")
    return _extract_json(proc.stdout or "")


# ─────────────────────────────────────────────────────────────────────
# Applying a decision
# ─────────────────────────────────────────────────────────────────────


def _apply_one_action(action: dict) -> dict:
    """Execute a single validated action via internal helpers. Returns
    {action, ok, error|None, detail}. Never raises."""
    from pcd_config import (
        OVERLAY_GUIDS, PERFBOOSTMODE, PROCTHROTTLEMAX, PROCTHROTTLEMIN, SYSCOOLPOL,
    )
    from pcd_controls import _apply_proc_value, _set_gpu_power, read_gpu_power_info, set_power_overlay_api
    from pcd_state import _refresh_state_controls

    name = action.get("name", "")
    args = action.get("args", {}) or {}
    record = {"action": name, "args": args, "ok": False, "error": None}

    try:
        if name == "noop":
            record["ok"] = True
            return record

        if name == "apply_preset":
            target = (args.get("name") or "").lower()
            if target not in ("quiet", "balanced", "performance"):
                record["error"] = f"unknown preset {target!r}"
                return record
            gpu = read_gpu_power_info()
            errs = []
            def step(ok, err):
                if not ok and err:
                    errs.append(err)
            if target == "quiet":
                step(*_apply_proc_value(SYSCOOLPOL, 0))
                step(*_apply_proc_value(PERFBOOSTMODE, 0))
                step(*_apply_proc_value(PROCTHROTTLEMAX, 80))
                if gpu and gpu.get("min_w"):
                    step(*_set_gpu_power(int(gpu["min_w"])))
                step(*set_power_overlay_api(OVERLAY_GUIDS["best-efficiency"]))
            elif target == "balanced":
                step(*_apply_proc_value(SYSCOOLPOL, 1))
                step(*_apply_proc_value(PERFBOOSTMODE, 2))
                step(*_apply_proc_value(PROCTHROTTLEMAX, 100))
                if gpu and gpu.get("default_w"):
                    step(*_set_gpu_power(int(gpu["default_w"])))
                step(*set_power_overlay_api(OVERLAY_GUIDS["balanced"]))
            else:  # performance
                step(*_apply_proc_value(SYSCOOLPOL, 1))
                step(*_apply_proc_value(PERFBOOSTMODE, 2))
                step(*_apply_proc_value(PROCTHROTTLEMAX, 100))
                step(*_apply_proc_value(PROCTHROTTLEMIN, 100))
                if gpu and gpu.get("max_w"):
                    step(*_set_gpu_power(int(gpu["max_w"])))
                step(*set_power_overlay_api(OVERLAY_GUIDS["best-performance"]))
            record["ok"] = not errs
            if errs:
                record["error"] = "; ".join(errs)[:200]
            return record

        if name == "set_power_mode":
            mode = (args.get("mode") or "").lower()
            if mode not in OVERLAY_GUIDS:
                record["error"] = f"unknown power mode {mode!r}"
                return record
            ok, err = set_power_overlay_api(OVERLAY_GUIDS[mode])
            record["ok"] = ok
            record["error"] = err
            return record

        if name == "set_cooling":
            val = args.get("value")
            if val not in (0, 1):
                record["error"] = "set_cooling.value must be 0 or 1"
                return record
            ok, err = _apply_proc_value(SYSCOOLPOL, val)
            record["ok"] = ok
            record["error"] = err
            return record

        if name == "set_turbo":
            mode = args.get("mode")
            if not isinstance(mode, int) or not 0 <= mode <= 5:
                record["error"] = "set_turbo.mode must be int 0..5"
                return record
            ok, err = _apply_proc_value(PERFBOOSTMODE, mode)
            record["ok"] = ok
            record["error"] = err
            return record

        if name == "set_cpu_max":
            p = args.get("percent")
            if not isinstance(p, int) or not 30 <= p <= 100:
                record["error"] = "set_cpu_max.percent must be int 30..100"
                return record
            ok, err = _apply_proc_value(PROCTHROTTLEMAX, p)
            record["ok"] = ok
            record["error"] = err
            return record

        if name == "set_cpu_min":
            p = args.get("percent")
            if not isinstance(p, int) or not 5 <= p <= 100:
                record["error"] = "set_cpu_min.percent must be int 5..100"
                return record
            ok, err = _apply_proc_value(PROCTHROTTLEMIN, p)
            record["ok"] = ok
            record["error"] = err
            return record

        # ─── System-fix actions (allowlist-protected, see pcd_fixer.py) ───
        if name == "disable_service":
            from pcd_fixer import disable_service
            svc = (args.get("name") or "").strip()
            if not svc:
                record["error"] = "disable_service.name required"
                return record
            fix = disable_service(svc)
            record["ok"] = fix["ok"]
            record["error"] = fix.get("error")
            record["fix_record"] = fix
            return record

        if name == "set_service_manual":
            from pcd_fixer import set_service_manual
            svc = (args.get("name") or "").strip()
            if not svc:
                record["error"] = "set_service_manual.name required"
                return record
            fix = set_service_manual(svc)
            record["ok"] = fix["ok"]
            record["error"] = fix.get("error")
            record["fix_record"] = fix
            return record

        if name == "report_only":
            from pcd_fixer import report_only
            fix = report_only(args.get("message", ""))
            record["ok"] = fix["ok"]
            record["fix_record"] = fix
            return record

        record["error"] = f"unknown action name: {name!r}"
        return record

    except Exception as e:
        record["error"] = f"{type(e).__name__}: {e}"[:200]
        return record
    finally:
        try:
            _refresh_state_controls()
        except Exception:
            pass


def _apply_decision(decision: dict) -> list[dict]:
    """Apply every action in the decision; dedupe trivial repeats."""
    global _last_applied_preset, _last_applied_mode
    results = []
    for action in decision.get("actions") or []:
        # De-thrash: don't re-apply the same preset/mode twice in a row.
        if action.get("name") == "apply_preset":
            target = (action.get("args") or {}).get("name", "").lower()
            if target == _last_applied_preset:
                results.append({"action": "apply_preset", "args": action["args"],
                                "ok": True, "error": None, "skipped": "same as last preset"})
                continue
            _last_applied_preset = target
            _last_applied_mode = None
        elif action.get("name") == "set_power_mode":
            mode = (action.get("args") or {}).get("mode", "").lower()
            if mode == _last_applied_mode:
                results.append({"action": "set_power_mode", "args": action["args"],
                                "ok": True, "error": None, "skipped": "same as last mode"})
                continue
            _last_applied_mode = mode

        r = _apply_one_action(action)
        results.append(r)
        if not r.get("ok"):
            logger.warning("OPTIMIZER action failed: %s args=%s err=%s",
                           r["action"], r["args"], r["error"])
        else:
            logger.info("OPTIMIZER action ok: %s args=%s", r["action"], r["args"])
    return results


# ─────────────────────────────────────────────────────────────────────
# The thread loop
# ─────────────────────────────────────────────────────────────────────


def _run_once() -> dict:
    """One decision cycle:

      1. Snapshot the metrics RIGHT NOW (this is both 'outcome end' for the
         previous decision and 'before' for this one).
      2. If there was a previous decision, log an OPTIMIZER OUTCOME block
         comparing that decision's AFTER to current. This gives a closed
         feedback loop in the log file. Feed it back to Claude in the prompt.
      3. Build the prompt + call Claude.
      4. Log BEFORE snapshot.
      5. Apply the decision's actions.
      6. Wait one poll cycle (+1s) so _state reflects the new settings.
      7. Snapshot AFTER. Log: actions actually applied (settings diff),
         AFTER metrics, immediate delta.
      8. Persist the record. Queue a summary for the recorder's next pc_status
         sample so OPT: appears in the row right after the decision.
    """
    global _last_decision, _last_run_at, _next_run_at

    started = datetime.now()
    logger.info("=" * 72)
    logger.info("OPTIMIZER cycle starting at %s (interval=%dmin)",
                started.strftime("%Y-%m-%d %H:%M:%S"), _interval_s // 60)

    record = {
        "started_at": started.strftime("%Y-%m-%d %H:%M:%S"),
        "state": None,
        "reasoning": None,
        "actions": [],
        "results": [],
        "confidence": None,
        "before_snapshot": None,
        "after_snapshot": None,
        "changes_summary": None,
        "immediate_delta": None,
        "outcome_of_previous": None,
        "ok": False,
        "error": None,
    }

    # ─── 1. Snapshot the current metrics (used both for outcome of previous
    #       decision AND as the BEFORE for this one) ───
    pre_snap = _snapshot_metrics()
    record["before_snapshot"] = pre_snap

    # ─── 2. Build OUTCOME-of-previous block, if we can ───
    outcome_block = None
    with _rec_lock:
        prev = _last_decision
    if prev and prev.get("after_snapshot"):
        try:
            prev_t = datetime.strptime(prev["started_at"], "%Y-%m-%d %H:%M:%S")
            elapsed_min = (started - prev_t).total_seconds() / 60
        except Exception:
            elapsed_min = None
        delta = _fmt_delta(prev["after_snapshot"], pre_snap)
        outcome_block = {
            "previous_decision_at":   prev["started_at"],
            "elapsed_minutes":        round(elapsed_min, 1) if elapsed_min is not None else None,
            "previous_state":         prev.get("state"),
            "previous_reasoning":     prev.get("reasoning"),
            "previous_changes":       prev.get("changes_summary"),
            "delta_since_then":       delta,
        }
        record["outcome_of_previous"] = outcome_block
        logger.info(
            "OPTIMIZER OUTCOME of %s decision (%s min ago, state=%s, applied: %s):",
            prev["started_at"],
            f"{elapsed_min:.0f}" if elapsed_min is not None else "?",
            prev.get("state"),
            prev.get("changes_summary"),
        )
        logger.info("  delta since then: %s", delta)

    # ─── 2a. Detect user manual override since last cycle ───
    user_override = _detect_user_override(pre_snap, prev)
    if user_override:
        diffs_str = ", ".join(
            f"{d['setting']}: {d['from']}→{d['to']}"
            for d in user_override["settings_user_changed"]
        )
        logger.warning(
            "OPTIMIZER USER OVERRIDE DETECTED: %s — respecting user preference "
            "unless state has shifted dramatically",
            diffs_str,
        )
        record["user_override"] = user_override

    # ─── 2b. Detect CPU-frequency lock pattern (workload-driven heat) ───
    cpu_lock_warning = _detect_cpu_lock(pre_snap)
    if cpu_lock_warning:
        logger.warning("OPTIMIZER WARNING: %s", cpu_lock_warning["interpretation"])
        record["cpu_lock_warning"] = cpu_lock_warning

    # ─── 2c. Fetch top CPU processes (per-cycle, not per-poll — too slow) ───
    top_processes = []
    try:
        from pcd_probes import probe_top_processes
        top_processes = probe_top_processes(n=8)
        if top_processes:
            tp_str = ", ".join(f"{p['name']}={p['cpu_pct']:.1f}%" for p in top_processes[:5])
            logger.info("OPTIMIZER TOP CPU PROCESSES: %s", tp_str)
            record["top_processes"] = top_processes
    except Exception as e:
        logger.warning("OPTIMIZER could not probe top processes: %s", e)

    # ─── 3. Build prompt + call Claude ───
    try:
        prompt = _build_prompt(
            outcome=outcome_block,
            user_override=user_override,
            cpu_lock_warning=cpu_lock_warning,
            top_processes=top_processes,
        )
        decision = _call_claude(prompt)
        record["state"]              = decision.get("state")
        record["reasoning"]          = decision.get("reasoning")
        record["actions"]            = decision.get("actions") or []
        record["confidence"]         = decision.get("confidence")
        record["next_check_minutes"] = decision.get("next_check_minutes")
        logger.info(
            "OPTIMIZER decision: state=%s confidence=%s actions=%d  reasoning=%r",
            record["state"], record["confidence"], len(record["actions"]),
            (record["reasoning"] or "")[:160],
        )
    except subprocess.TimeoutExpired:
        record["error"] = f"claude CLI timed out after {CLAUDE_TIMEOUT_S}s"
        logger.error("OPTIMIZER: %s", record["error"])
    except Exception as e:
        record["error"] = f"{type(e).__name__}: {e}"[:200]
        logger.error("OPTIMIZER: %s", record["error"])

    # If Claude call failed entirely, still persist the record (with error)
    # so the next cycle can show the outcome of NOTHING-was-done if needed.
    if record["error"]:
        record["after_snapshot"] = pre_snap
        record["changes_summary"] = f"(skipped — claude error: {record['error'][:60]})"
        with _rec_lock:
            _last_decision = record
            _last_run_at = started
            _next_run_at = datetime.fromtimestamp(time.time() + _interval_s)
            _history.append(record)
            if len(_history) > HISTORY_KEEP:
                _history.pop(0)
        return record

    # ─── 4. Log BEFORE snapshot ───
    logger.info("OPTIMIZER BEFORE: %s", _fmt_snapshot(pre_snap))

    # ─── 5. Apply the decision's actions ───
    record["results"] = _apply_decision(decision)
    record["ok"] = True

    # ─── 6. Brief settle so the poll loop refreshes _state with the new
    #       control values before we snapshot AFTER. _apply_proc_value already
    #       calls _refresh_state_controls() so controls are immediately fresh,
    #       but thermal/load metrics need one poll cycle to update. ───
    try:
        from pcd_config import REFRESH_S
    except ImportError:
        REFRESH_S = 2
    time.sleep(REFRESH_S + 1)

    # ─── 7. Snapshot AFTER + log delta ───
    post_snap = _snapshot_metrics()
    record["after_snapshot"] = post_snap
    changes_summary = _settings_diff(pre_snap, post_snap)
    immediate_delta = _fmt_delta(pre_snap, post_snap)
    record["changes_summary"] = changes_summary
    record["immediate_delta"] = immediate_delta
    logger.info("OPTIMIZER applied: %s", changes_summary)
    logger.info("OPTIMIZER AFTER:  %s", _fmt_snapshot(post_snap))
    logger.info("OPTIMIZER immediate delta: %s", immediate_delta)
    logger.info("OPTIMIZER cycle complete — outcome will be evaluated at next cycle")

    # ─── 8. Persist + queue a marker for the recorder ───
    with _rec_lock:
        _last_decision = record
        _last_run_at = started
        _next_run_at = datetime.fromtimestamp(time.time() + _interval_s)
        _history.append(record)
        if len(_history) > HISTORY_KEEP:
            _history.pop(0)

    # The recorder will pick this up on its next pc_status sample and emit an
    # OPT: section so post-decision rows are findable with a single grep.
    queue_decision_for_recorder({
        "state":      record["state"],
        "changes":    changes_summary,
        "confidence": record["confidence"],
        "at":         record["started_at"],
    })

    return record


def _loop():
    """Background driver — first run immediately, then sleep _interval_s,
    waking early if _stop_event is set."""
    try:
        _run_once()
        while not _stop_event.is_set():
            if _stop_event.wait(timeout=_interval_s):
                break
            _run_once()
    finally:
        logger.info("OPTIMIZER loop exited")


# ─────────────────────────────────────────────────────────────────────
# Public API used by pcd_api.py
# ─────────────────────────────────────────────────────────────────────


def start(interval_minutes: float = DEFAULT_INTERVAL_MIN) -> dict:
    """Begin the auto-optimize loop. Returns ok/error."""
    global _active, _thread, _interval_s
    interval_minutes = max(MIN_INTERVAL_MIN, float(interval_minutes))
    with _rec_lock:
        if _active:
            return {"ok": False, "error": "Optimizer is already running."}
        _interval_s = int(interval_minutes * 60)
        _stop_event.clear()
        _thread = threading.Thread(target=_loop, daemon=True, name="pcd_optimizer")
        _thread.start()
        _active = True
        logger.info("OPTIMIZER started (interval=%d min)", interval_minutes)
        return {"ok": True, "interval_minutes": interval_minutes}


def stop() -> dict:
    global _active
    with _rec_lock:
        if not _active:
            return {"ok": False, "error": "Optimizer is not running."}
        _stop_event.set()
        _active = False
        logger.info("OPTIMIZER stop requested")
        return {"ok": True}


def status() -> dict:
    with _rec_lock:
        return {
            "active": _active,
            "interval_minutes": _interval_s // 60,
            "last_run_at":  _last_run_at.strftime("%Y-%m-%d %H:%M:%S") if _last_run_at else None,
            "next_run_at":  _next_run_at.strftime("%Y-%m-%d %H:%M:%S") if _next_run_at else None,
            "last_decision": _last_decision,
            "history": list(_history),
        }


def run_now() -> dict:
    """Synchronous one-shot run — invoked by the UI's 'Run Now' button.
    Resets the next-run timer so the background thread waits a full interval
    from this call rather than firing again immediately."""
    global _next_run_at
    rec = _run_once()
    with _rec_lock:
        _next_run_at = datetime.fromtimestamp(time.time() + _interval_s)
    return rec
