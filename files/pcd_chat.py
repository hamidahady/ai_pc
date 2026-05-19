"""
pcd_chat.py — Claude AI assistant: tools + chat endpoints.

Importing this module registers the chat routes on `pcd_state.app`:
  POST /api/chat         — single Claude tool-runner turn
  POST /api/chat/reset   — clear the conversation history
  GET  /api/chat/status  — SDK / API key availability check

Each @beta_tool function below is a thin wrapper around the same internal
helpers the HTTP endpoints use, so the agent has parity with the UI buttons.
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

import pcd_state  # KNOWN_PLAN_GUIDS accessed at call time

try:
    import anthropic
    from anthropic import beta_tool
    _ANTHROPIC_AVAILABLE = True
except ModuleNotFoundError:
    _ANTHROPIC_AVAILABLE = False
    anthropic = None
    def beta_tool(f):
        return f


# ─── Claude tools ───


@beta_tool
def get_pc_state() -> str:
    """Get the current PC state: temperatures, GPU info, storage, battery,
    CPU performance counters, and active control settings.

    Always call this first when the user asks a question or requests a change,
    so you know the current state before deciding what to do.

    Returns a JSON string with system identity, live sensor readings (CPU/skin
    thermal zones, NVIDIA telemetry, NVMe temperatures, battery), and the
    currently active power plan, overlay, cooling policy, turbo mode, CPU
    max/min percent, and GPU power limit.
    """
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
    """List every Windows power plan registered on this machine, including
    custom (OEM/IT-managed) plans. Use this to find the GUID needed for
    set_power_plan.

    Returns a JSON list of {guid, name, active} entries.
    """
    return json.dumps(read_power_plans())


@beta_tool
def set_power_plan(guid: str) -> str:
    """Switch the active Windows power plan by GUID.

    Args:
        guid: 36-character power-plan GUID from list_power_plans.
    """
    g = guid.strip().lower()
    if not GUID_RE.match(g):
        return f"error: invalid GUID format: {guid}"
    if pcd_state.KNOWN_PLAN_GUIDS and g not in pcd_state.KNOWN_PLAN_GUIDS:
        return "error: unknown plan GUID — call list_power_plans first"
    rc, _, err = ps_full(f"powercfg /setactive {g}")
    _refresh_state_controls()
    return "ok" if rc == 0 else f"failed: {err}"


@beta_tool
def set_power_mode(mode: str) -> str:
    """Set the Windows 11 Power Mode overlay.

    Args:
        mode: One of 'best-efficiency', 'balanced', or 'best-performance'.
    """
    m = mode.strip().lower()
    if m not in OVERLAY_GUIDS:
        return f"error: mode must be one of {list(OVERLAY_GUIDS.keys())}"
    ok, err = set_power_overlay_api(OVERLAY_GUIDS[m])
    _refresh_state_controls()
    return "ok" if ok else f"failed: {err}"


@beta_tool
def set_cooling_policy(value: int) -> str:
    """Set the System Cooling Policy. This is the biggest fan-noise lever on
    laptops: Passive throttles the CPU before the fans spin up; Active prefers
    to spin fans first to keep the CPU at full performance.

    Args:
        value: 0 for Passive (quiet), 1 for Active (fans first).
    """
    if value not in (0, 1):
        return "error: value must be 0 (Passive) or 1 (Active)"
    ok, err = _apply_proc_value(SYSCOOLPOL, value)
    _refresh_state_controls()
    return "ok" if ok else f"failed: {err}"


@beta_tool
def set_turbo_boost(mode: int) -> str:
    """Set the Processor Boost Mode.

    Args:
        mode: 0=Disabled, 1=Enabled, 2=Aggressive, 3=Efficient Enabled,
              4=Efficient Aggressive, 5=Aggressive at guaranteed.
    """
    if not isinstance(mode, int) or not 0 <= mode <= 5:
        return "error: mode must be an integer 0..5"
    ok, err = _apply_proc_value(PERFBOOSTMODE, mode)
    _refresh_state_controls()
    return "ok" if ok else f"failed: {err}"


@beta_tool
def set_cpu_max_percent(percent: int) -> str:
    """Set the CPU maximum performance state as a percent of full speed.
    99% disables turbo. 80% noticeably caps power and drops fan speed.

    Args:
        percent: integer 30..100.
    """
    if not isinstance(percent, int) or not 30 <= percent <= 100:
        return "error: percent must be an integer 30..100"
    ok, err = _apply_proc_value(PROCTHROTTLEMAX, percent)
    _refresh_state_controls()
    return "ok" if ok else f"failed: {err}"


@beta_tool
def set_cpu_min_percent(percent: int) -> str:
    """Set the CPU minimum performance state as a percent of full speed.

    Args:
        percent: integer 5..100.
    """
    if not isinstance(percent, int) or not 5 <= percent <= 100:
        return "error: percent must be an integer 5..100"
    ok, err = _apply_proc_value(PROCTHROTTLEMIN, percent)
    _refresh_state_controls()
    return "ok" if ok else f"failed: {err}"


@beta_tool
def set_gpu_power_limit_watts(watts: int) -> str:
    """Set the NVIDIA GPU power limit in watts. Use get_pc_state to read the
    valid range (controls.gpu.min_w to controls.gpu.max_w).

    Args:
        watts: integer 5..300, within the GPU's supported range.
    """
    if not isinstance(watts, int) or not 5 <= watts <= 300:
        return "error: watts must be an integer 5..300"
    ok, err = _set_gpu_power(watts)
    _refresh_state_controls()
    return "ok" if ok else f"failed: {err}"


@beta_tool
def apply_preset(name: str) -> str:
    """Apply a composite preset that adjusts cooling policy, turbo, CPU cap,
    GPU power limit, and Windows Power Mode at once.

    Args:
        name: 'quiet' (passive cooling, turbo off, 80% CPU cap, GPU at min, best-efficiency overlay),
              'balanced' (active cooling, aggressive turbo, 100% CPU, GPU default, balanced overlay),
              or 'performance' (active, aggressive, 100% min/max, GPU max, best-performance overlay).
    """
    n = name.strip().lower()
    if n not in ("quiet", "balanced", "performance"):
        return "error: name must be 'quiet', 'balanced', or 'performance'"

    gpu = read_gpu_power_info()
    errors: list[str] = []

    def step(ok: bool, err):
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
    else:  # performance
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
    get_pc_state,
    list_power_plans,
    set_power_plan,
    set_power_mode,
    set_cooling_policy,
    set_turbo_boost,
    set_cpu_max_percent,
    set_cpu_min_percent,
    set_gpu_power_limit_watts,
    apply_preset,
]


# ─── chat endpoints ───


@app.route("/api/chat", methods=["POST"])
def api_chat():
    if not _ANTHROPIC_AVAILABLE:
        return jsonify({
            "error": "anthropic SDK not installed. Run:  pip install anthropic"
        }), 501
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return jsonify({
            "error": "ANTHROPIC_API_KEY environment variable is not set. "
                     "Get a key from https://console.anthropic.com and set it before launching the dashboard."
        }), 501

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
                {"type": "text",
                 "text": CHAT_SYSTEM_PROMPT,
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
