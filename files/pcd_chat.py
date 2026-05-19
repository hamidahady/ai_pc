"""
pcd_chat.py — Claude AI assistant: tools + chat endpoints.
"""

import json
import os

from flask import jsonify, request

from pcd_config import (
    ANTHROPIC_MODEL, CHAT_SYSTEM_PROMPT, GUID_RE, OVERLAY_GUIDS,
    PERFBOOSTMODE, PROCTHROTTLEMAX, PROCTHROTTLEMIN, SYSCOOLPOL,
)
from pcd_controls import (
    _apply_proc_value, _set_gpu_power, read_gpu_power_info,
    read_power_plans, set_power_overlay_api,
)
from pcd_log import logger
from pcd_shell import ps_full
from pcd_state import _chat_history, _chat_lock, _lock, _refresh_state_controls, _state, app

import pcd_state

try:
    import anthropic
    from anthropic import beta_tool
    _ANTHROPIC_AVAILABLE = True
except ModuleNotFoundError:
    _ANTHROPIC_AVAILABLE = False
    anthropic = None
    def beta_tool(f):
        return f


@beta_tool
def get_pc_state() -> str:
    """Get the current PC state as JSON."""
    with _lock:
        snapshot = {
            "system":     _state.get("system", {}),
            "sources":    _state.get("sources", {}),
            "controls":   _state.get("controls", {}),
            "updated_at": _state.get("updated"),
        }
    return json.dumps(snapshot, default=str)


@beta_tool
def list_power_plans() -> str:
    """List Windows power plans as JSON."""
    return json.dumps(read_power_plans())


@beta_tool
def set_power_plan(guid: str) -> str:
    """Switch the active power plan by GUID."""
    g = guid.strip().lower()
    if not GUID_RE.match(g):
        return f"error: invalid GUID format: {guid}"
    if pcd_state.KNOWN_PLAN_GUIDS and g not in pcd_state.KNOWN_PLAN_GUIDS:
        return "error: unknown plan GUID"
    rc, _, err = ps_full(f"powercfg /setactive {g}")
    _refresh_state_controls()
    return "ok" if rc == 0 else f"failed: {err}"


@beta_tool
def set_power_mode(mode: str) -> str:
    """Set Win11 Power Mode overlay (best-efficiency / balanced / best-performance)."""
    m = mode.strip().lower()
    if m not in OVERLAY_GUIDS:
        return f"error: mode must be one of {list(OVERLAY_GUIDS.keys())}"
    ok, err = set_power_overlay_api(OVERLAY_GUIDS[m])
    _refresh_state_controls()
    return "ok" if ok else f"failed: {err}"


@beta_tool
def set_cooling_policy(value: int) -> str:
    """Set System Cooling Policy: 0=Passive, 1=Active."""
    if value not in (0, 1):
        return "error: value must be 0 or 1"
    ok, err = _apply_proc_value(SYSCOOLPOL, value)
    _refresh_state_controls()
    return "ok" if ok else f"failed: {err}"


@beta_tool
def set_turbo_boost(mode: int) -> str:
    """Set Processor Boost Mode (0=Disabled .. 5=Aggressive at guaranteed)."""
    if not isinstance(mode, int) or not 0 <= mode <= 5:
        return "error: mode must be 0..5"
    ok, err = _apply_proc_value(PERFBOOSTMODE, mode)
    _refresh_state_controls()
    return "ok" if ok else f"failed: {err}"


@beta_tool
def set_cpu_max_percent(percent: int) -> str:
    """Set CPU maximum performance state (30..100)."""
    if not isinstance(percent, int) or not 30 <= percent <= 100:
        return "error: 30..100"
    ok, err = _apply_proc_value(PROCTHROTTLEMAX, percent)
    _refresh_state_controls()
    return "ok" if ok else f"failed: {err}"


@beta_tool
def set_cpu_min_percent(percent: int) -> str:
    """Set CPU minimum performance state (5..100)."""
    if not isinstance(percent, int) or not 5 <= percent <= 100:
        return "error: 5..100"
    ok, err = _apply_proc_value(PROCTHROTTLEMIN, percent)
    _refresh_state_controls()
    return "ok" if ok else f"failed: {err}"


@beta_tool
def set_gpu_power_limit_watts(watts: int) -> str:
    """Set NVIDIA GPU power limit in watts (5..300)."""
    if not isinstance(watts, int) or not 5 <= watts <= 300:
        return "error: 5..300"
    ok, err = _set_gpu_power(watts)
    _refresh_state_controls()
    return "ok" if ok else f"failed: {err}"


@beta_tool
def apply_preset(name: str) -> str:
    """Apply composite preset: 'quiet', 'balanced', or 'performance'."""
    n = name.strip().lower()
    if n not in ("quiet", "balanced", "performance"):
        return "error: 'quiet'/'balanced'/'performance'"

    gpu = read_gpu_power_info()
    errors: list[str] = []

    def step(ok, err):
        if not ok and err:
            errors.append(err)

    if n == "quiet":
        step(*_apply_proc_value(SYSCOOLPOL, 0))
        step(*_apply_proc_value(PERFBOOSTMODE, 0))
        step(*_apply_proc_value(PROCTHROTTLEMAX, 80))
        if gpu and gpu.get("min_w"):
            step(*_set_gpu_power(int(gpu["min_w"])))
        step(*set_power_overlay_api(OVERLAY_GUIDS["best-efficiency"]))
    elif n == "balanced":
        step(*_apply_proc_value(SYSCOOLPOL, 1))
        step(*_apply_proc_value(PERFBOOSTMODE, 2))
        step(*_apply_proc_value(PROCTHROTTLEMAX, 100))
        if gpu and gpu.get("default_w"):
            step(*_set_gpu_power(int(gpu["default_w"])))
        step(*set_power_overlay_api(OVERLAY_GUIDS["balanced"]))
    else:
        step(*_apply_proc_value(SYSCOOLPOL, 1))
        step(*_apply_proc_value(PERFBOOSTMODE, 2))
        step(*_apply_proc_value(PROCTHROTTLEMAX, 100))
        step(*_apply_proc_value(PROCTHROTTLEMIN, 100))
        if gpu and gpu.get("max_w"):
            step(*_set_gpu_power(int(gpu["max_w"])))
        step(*set_power_overlay_api(OVERLAY_GUIDS["best-performance"]))

    _refresh_state_controls()
    if errors:
        return f"applied {n} with errors: {'; '.join(errors)}"
    return f"ok: applied {n} preset"


_CHAT_TOOLS = [
    get_pc_state, list_power_plans, set_power_plan, set_power_mode,
    set_cooling_policy, set_turbo_boost, set_cpu_max_percent,
    set_cpu_min_percent, set_gpu_power_limit_watts, apply_preset,
]


@app.route("/api/chat", methods=["POST"])
def api_chat():
    if not _ANTHROPIC_AVAILABLE:
        return jsonify({"error": "anthropic SDK not installed. pip install anthropic"}), 501
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return jsonify({"error": "ANTHROPIC_API_KEY not set"}), 501

    data = request.get_json(silent=True) or {}
    user_msg = (data.get("message") or "").strip()
    if not user_msg:
        return jsonify({"error": "empty message"}), 400

    with _chat_lock:
        _chat_history.append({"role": "user", "content": user_msg})
        messages = list(_chat_history)

    logger.info("CHAT user: %r", user_msg)

    try:
        client = anthropic.Anthropic()
        runner = client.beta.messages.tool_runner(
            model=ANTHROPIC_MODEL,
            max_tokens=8192,
            system=[
                {"type": "text", "text": CHAT_SYSTEM_PROMPT,
                 "cache_control": {"type": "ephemeral"}},
            ],
            tools=_CHAT_TOOLS,
            messages=messages,
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},
        )

        tool_calls: list[dict] = []
        last_text = ""
        for message in runner:
            for block in message.content:
                if block.type == "text":
                    last_text = block.text
                elif block.type == "tool_use":
                    logger.info("CHAT tool_use: %s args=%s", block.name,
                                json.dumps(block.input, default=str)[:200])
                    tool_calls.append({"name": block.name, "input": block.input})

        with _chat_lock:
            _chat_history.append({"role": "assistant", "content": last_text})

        logger.info("CHAT assistant: %r", last_text[:400])
        return jsonify({"reply": last_text, "tool_calls": tool_calls})

    except Exception as e:
        with _chat_lock:
            if _chat_history and _chat_history[-1]["role"] == "user":
                _chat_history.pop()
        err = str(e)
        if anthropic is not None and isinstance(e, anthropic.APIError):
            err = f"Anthropic API error: {err}"
        logger.error("CHAT error: %s", err)
        return jsonify({"error": err}), 500


@app.route("/api/chat/reset", methods=["POST"])
def api_chat_reset():
    with _chat_lock:
        _chat_history.clear()
    return jsonify({"ok": True})


@app.route("/api/chat/status", methods=["GET"])
def api_chat_status():
    return jsonify({
        "sdk_installed": _ANTHROPIC_AVAILABLE,
        "api_key_set": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "model": ANTHROPIC_MODEL,
    })
