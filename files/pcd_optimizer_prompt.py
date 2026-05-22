"""
pcd_optimizer_prompt.py — system prompt, prompt builders, and Claude call.

Extracted from pcd_optimizer.py. Owns:
  - _SYSTEM_PROMPT (~150 lines of instructions Claude reads every cycle)
  - prompt-building helpers: _live_snapshot, _newest_status_tail,
    _recent_log_changes, _build_prompt
  - Claude invocation: _extract_json + _call_claude

pcd_optimizer.py imports _build_prompt + _call_claude from here.
"""

import json
import re
import shutil
import subprocess

from pcd_log import LOG_DIR
from pcd_state import _lock, _state


# ─── Claude CLI invocation constants ───
CLAUDE_BIN       = shutil.which("claude") or "claude"
CLAUDE_TIMEOUT_S = 120
CLAUDE_MODEL     = "opus"

# ─── How much history to send into the prompt ───
HISTORY_PROMPT = 12   # last N pc_status samples
LOG_TAIL_LINES = 40   # last N lines of log_*.txt


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
