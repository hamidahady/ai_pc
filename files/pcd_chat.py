"""
pcd_chat.py — chat backend using the Claude Code CLI as a subprocess.

This is the SIMPLE path: instead of calling api.anthropic.com directly with an
OAuth token or API key, we run `claude -p "<prompt>"` as a child process and
capture its stdout. Claude Code's CLI authenticates itself using the OAuth
credentials in ~/.claude/.credentials.json — the same way it does when you
type `claude` in a terminal interactively — and Anthropic recognises it as
Claude Code itself, so it uses the FULL subscription quota with no extra
throttling.

Tradeoff: --allowedTools "" disables Claude Code's agentic tools (file ops,
bash, etc.), so the chat is pure text generation. The dashboard's PC state
is injected into Claude's system prompt every turn so it knows what's going
on, and it can SUGGEST actions ("click the Quiet preset"). The user then
clicks the actual dashboard buttons to apply changes.

Routes:
  POST /api/chat         — send a user message, get Claude's reply
  POST /api/chat/reset   — clear the conversation history
  GET  /api/chat/status  — diagnostic: CLI present? path? model?
"""

import json
import re
import shutil
import subprocess

from flask import jsonify, request

from pcd_log import logger
from pcd_state import _chat_history, _chat_lock, _lock, _state, app


# Locate the claude CLI on first import. Cached because shutil.which is cheap
# but not free, and we hit this once per chat request.
CLAUDE_BIN = shutil.which("claude") or "claude"
CLAUDE_MODEL = "opus"      # claude CLI accepts short aliases: opus | sonnet | haiku
CLAUDE_TIMEOUT_S = 180     # tool-less CLI calls typically return in a few seconds

# Strip leading TTY progress markers Claude Code sometimes prints before its
# real output (e.g. "[ ]" or "[*]"). Mirrors what the ai_text project does.
_PROGRESS_RE = re.compile(r"^\s*\[[ \*\.\-]\]\s*", re.MULTILINE)


def _build_state_summary() -> str:
    """Render the dashboard's current _state as a compact JSON snippet for
    Claude's system prompt. Trimmed to the parts a question is likely to care
    about — temperatures, GPU, battery, current power settings."""
    with _lock:
        sources = _state.get("sources", {}) or {}
        controls = _state.get("controls", {}) or {}
        system   = _state.get("system", {}) or {}

    zones = sources.get("thermal_zones") or []
    gpu = (sources.get("nvidia") or [{}])[0]
    cp = sources.get("cpu_proxy") or {}
    b = sources.get("battery") or {}

    active_plan = next(
        (p.get("name") for p in controls.get("power_plans", []) if p.get("active")),
        None,
    )
    cooling_human = {0: "Passive (Quiet)", 1: "Active (Fans first)"}.get(
        controls.get("cooling_policy")
    )

    summary = {
        "machine": f"{system.get('Manufacturer', '?')} {system.get('Model', '?')}",
        "cpu_name": system.get("cpu_Name"),
        "ram_gb": system.get("ram_gb"),
        "temperatures_c": {
            re.search(r"\(([^)]+)\)", z["name"]).group(1) if "(" in z["name"] else z["name"]:
                round(z["value"], 1)
            for z in zones[:12] if "value" in z
        },
        "gpu": {
            "name": gpu.get("name"),
            "temp_c": gpu.get("temp_c"),
            "power_w": gpu.get("power_w"),
            "util_pct": gpu.get("util_pct"),
        } if gpu else None,
        "cpu_load_pct": cp.get("util_pct"),
        "cpu_freq_mhz": cp.get("freq_mhz"),
        "battery_charge_pct": b.get("charge_pct"),
        "battery_status": b.get("status"),
        "active_settings": {
            "power_plan": active_plan,
            "power_mode_overlay": controls.get("overlay"),
            "cooling_policy": cooling_human,
            "turbo_boost_mode_int": controls.get("turbo_boost"),
            "cpu_max_pct": controls.get("cpu_max_pct"),
            "cpu_min_pct": controls.get("cpu_min_pct"),
            "gpu_power_limit_w": (gpu or {}).get("power_w"),
        },
    }
    return json.dumps(summary, default=str, indent=2)


_SYSTEM_PROMPT = """You are an AI assistant embedded in a live Windows PC dashboard.
The user can see live temperatures, GPU/CPU/battery readings, and the active
power settings on screen. You CANNOT change settings yourself — you only
read state and talk. When you recommend a change, name the specific
dashboard button or slider the user should click (Quick Presets, Power Plan,
Power Mode, System Cooling Policy, Turbo Boost, CPU Max/Min State, GPU Power
Limit).

Be concise — usually 2–3 short sentences. Quote exact values from the state
snippet below when the user asks about temperatures, power, etc.

CURRENT PC STATE (refreshed every chat turn):
"""


def _claude_is_available() -> bool:
    return shutil.which(CLAUDE_BIN) is not None or shutil.which("claude") is not None


def _build_full_prompt(messages: list[dict]) -> str:
    """Flatten chat history into a single text prompt the way the ai_text
    project does — [USER] / [ASSISTANT] sections, separated by blank lines."""
    parts = []
    for m in messages:
        role = m.get("role", "user").upper()
        parts.append(f"[{role}]\n{m.get('content', '')}")
    return "\n\n".join(parts)


@app.route("/api/chat", methods=["POST"])
def api_chat():
    if not _claude_is_available():
        return jsonify({
            "error": "Claude Code CLI is not on PATH. Install it from "
                     "https://claude.com/code (or check that `claude` runs from a terminal)."
        }), 501

    data = request.get_json(silent=True) or {}
    user_msg = (data.get("message") or "").strip()
    if not user_msg:
        return jsonify({"error": "empty message"}), 400

    # Append user message and snapshot history under the lock
    with _chat_lock:
        _chat_history.append({"role": "user", "content": user_msg})
        history = list(_chat_history)

    logger.info("CHAT user: %r  (via claude CLI: %s)", user_msg, CLAUDE_BIN)

    full_prompt = _build_full_prompt(history)
    system_prompt = _SYSTEM_PROMPT + _build_state_summary()

    cmd = [
        CLAUDE_BIN, "-p", full_prompt,
        "--allowedTools", "",                       # text-only, no agentic tools
        "--append-system-prompt", system_prompt,    # inject live PC state
        "--model", CLAUDE_MODEL,
    ]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=CLAUDE_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        with _chat_lock:
            if _chat_history and _chat_history[-1]["role"] == "user":
                _chat_history.pop()
        logger.error("CHAT error: claude CLI timed out after %ss", CLAUDE_TIMEOUT_S)
        return jsonify({"error": f"Claude CLI timed out after {CLAUDE_TIMEOUT_S}s. Try a shorter question."}), 504
    except FileNotFoundError as e:
        with _chat_lock:
            if _chat_history and _chat_history[-1]["role"] == "user":
                _chat_history.pop()
        return jsonify({"error": f"Could not run claude CLI: {e}"}), 501

    if proc.returncode != 0:
        with _chat_lock:
            if _chat_history and _chat_history[-1]["role"] == "user":
                _chat_history.pop()
        err = (proc.stderr or proc.stdout or "").strip()[:400]
        logger.error("CHAT error: claude rc=%d  stderr=%r", proc.returncode, err)
        return jsonify({
            "error": f"Claude CLI exited with code {proc.returncode}. "
                     f"{('Details: ' + err) if err else 'Run `claude` in a terminal to check it works there.'}"
        }), 500

    reply = _PROGRESS_RE.sub("", proc.stdout or "").strip()
    if not reply:
        with _chat_lock:
            if _chat_history and _chat_history[-1]["role"] == "user":
                _chat_history.pop()
        logger.error("CHAT error: claude returned empty output")
        return jsonify({"error": "Claude CLI returned empty output. Try again."}), 500

    with _chat_lock:
        _chat_history.append({"role": "assistant", "content": reply})

    logger.info("CHAT assistant: %r", reply[:300])
    # tool_calls is kept in the response for API compatibility with the page JS,
    # but is always empty in this simplified mode.
    return jsonify({"reply": reply, "tool_calls": []})


@app.route("/api/chat/reset", methods=["POST"])
def api_chat_reset():
    with _chat_lock:
        _chat_history.clear()
    return jsonify({"ok": True})


@app.route("/api/chat/status", methods=["GET"])
def api_chat_status():
    cli_path = shutil.which("claude")
    available = cli_path is not None
    return jsonify({
        "claude_cli_available": available,
        "claude_cli_path": cli_path,
        "model": CLAUDE_MODEL,
        "active_source": "claude_code_cli" if available else None,
        # legacy fields kept so older page.js still parses correctly
        "sdk_installed": True,
        "api_key_set": False,
    })
