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

This module is intentionally thin. The bulky pieces live in three siblings:

    pcd_optimizer_prompt.py    _SYSTEM_PROMPT + prompt builders + Claude call
    pcd_optimizer_signals.py   snapshots, deltas, user-override + CPU-lock detection
    pcd_optimizer_actions.py   _apply_one_action — per-action dispatcher

This file owns: module state (active flag, history, anti-thrash flags),
the run loop (_run_once + _loop), the public API (start/stop/status/run_now),
the recorder-notification queue, and _apply_decision (which needs the
anti-thrash globals).
"""

import threading
import time
from datetime import datetime

from pcd_log import logger

# Sibling modules — most of the heavy logic lives in these three.
from pcd_optimizer_prompt import _build_prompt, _call_claude, CLAUDE_TIMEOUT_S
from pcd_optimizer_signals import (
    _detect_cpu_lock, _detect_user_override,
    _fmt_delta, _fmt_snapshot, _settings_diff, _snapshot_metrics,
)
from pcd_optimizer_actions import _apply_one_action

import subprocess  # for catching subprocess.TimeoutExpired in _run_once


HISTORY_KEEP         = 20    # last N decisions to surface to the UI
MIN_INTERVAL_MIN     = 1     # safety floor: don't hammer Claude
DEFAULT_INTERVAL_MIN = 30    # 30-min cadence reduces churn; lower in UI if you want


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


# ─────────────────────────────────────────────────────────────────────
# Applying a decision (uses _last_applied_preset / _last_applied_mode
# for anti-thrash, so it stays in the orchestrator module).
# ─────────────────────────────────────────────────────────────────────


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
# The decision cycle
# ─────────────────────────────────────────────────────────────────────


def _run_once() -> dict:
    """One decision cycle. See module docstring for the eight-step flow."""
    global _last_decision, _last_run_at, _next_run_at

    started = datetime.now()
    logger.info("=" * 72)
    logger.info("OPTIMIZER cycle starting at %s (interval=%dmin)",
                started.strftime("%Y-%m-%d %H:%M:%S"), _interval_s // 60)

    record = {
        "started_at": started.strftime("%Y-%m-%d %H:%M:%S"),
        "state": None, "reasoning": None, "actions": [], "results": [],
        "confidence": None, "before_snapshot": None, "after_snapshot": None,
        "changes_summary": None, "immediate_delta": None,
        "outcome_of_previous": None, "ok": False, "error": None,
    }

    # 1. Snapshot the current metrics (= 'outcome end' for previous + BEFORE for this).
    pre_snap = _snapshot_metrics()
    record["before_snapshot"] = pre_snap

    # 2. OUTCOME-of-previous block (if we have a previous decision to grade).
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
            prev.get("state"), prev.get("changes_summary"),
        )
        logger.info("  delta since then: %s", delta)

    # 2a. User manual override detection.
    user_override = _detect_user_override(pre_snap, prev)
    if user_override:
        diffs_str = ", ".join(
            f"{d['setting']}: {d['from']}→{d['to']}"
            for d in user_override["settings_user_changed"]
        )
        logger.warning(
            "OPTIMIZER USER OVERRIDE DETECTED: %s — respecting user preference "
            "unless state has shifted dramatically", diffs_str,
        )
        record["user_override"] = user_override

    # 2b. CPU-frequency-lock pattern (workload-driven heat).
    cpu_lock_warning = _detect_cpu_lock(pre_snap)
    if cpu_lock_warning:
        logger.warning("OPTIMIZER WARNING: %s", cpu_lock_warning["interpretation"])
        record["cpu_lock_warning"] = cpu_lock_warning

    # 2c. Top CPU processes (per-cycle, expensive — not in the 2s poll loop).
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

    # 3. Build prompt + call Claude.
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

    # If Claude call failed entirely, still persist (with error) so the next
    # cycle's OUTCOME block can show "nothing was done" rather than crashing.
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

    # 4. Log BEFORE snapshot.
    logger.info("OPTIMIZER BEFORE: %s", _fmt_snapshot(pre_snap))

    # 5. Apply the decision's actions.
    record["results"] = _apply_decision(decision)
    record["ok"] = True

    # 6. Brief settle so poll loop refreshes _state with new control values.
    try:
        from pcd_config import REFRESH_S
    except ImportError:
        REFRESH_S = 2
    time.sleep(REFRESH_S + 1)

    # 7. Snapshot AFTER + log delta.
    post_snap = _snapshot_metrics()
    record["after_snapshot"]  = post_snap
    record["changes_summary"] = _settings_diff(pre_snap, post_snap)
    record["immediate_delta"] = _fmt_delta(pre_snap, post_snap)
    logger.info("OPTIMIZER applied: %s", record["changes_summary"])
    logger.info("OPTIMIZER AFTER:  %s", _fmt_snapshot(post_snap))
    logger.info("OPTIMIZER immediate delta: %s", record["immediate_delta"])
    logger.info("OPTIMIZER cycle complete — outcome will be evaluated at next cycle")

    # 8. Persist + queue a marker for the recorder.
    with _rec_lock:
        _last_decision = record
        _last_run_at = started
        _next_run_at = datetime.fromtimestamp(time.time() + _interval_s)
        _history.append(record)
        if len(_history) > HISTORY_KEEP:
            _history.pop(0)

    queue_decision_for_recorder({
        "state":      record["state"],
        "changes":    record["changes_summary"],
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
