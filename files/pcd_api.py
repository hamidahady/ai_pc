"""
pcd_api.py — Flask routes for monitoring and control endpoints.
"""

import json

from flask import jsonify, request

from pcd_config import (
    GUID_RE, OVERLAY_GUIDS, PERFBOOSTMODE, PROCTHROTTLEMAX, PROCTHROTTLEMIN,
    SYSCOOLPOL,
)
from pcd_controls import (
    _apply_proc_value, _set_gpu_power, read_gpu_power_info,
    set_power_overlay_api,
)
from pcd_log import logger
from pcd_shell import ps_full
from pcd_state import _lock, _refresh_state_controls, _state, app

import pcd_state


# Endpoints the UI polls every 2 seconds — too noisy to log every hit.
_NOISY_POLL_PATHS = {"/api/thermal", "/api/recorder/status", "/api/optimizer/status"}


@app.before_request
def _log_api_request():
    if request.path in _NOISY_POLL_PATHS or not request.path.startswith("/api/"):
        return
    body = request.get_json(silent=True) or {}
    if body:
        preview = json.dumps(body, default=str)[:240]
        logger.info("HTTP %s %s  body=%s", request.method, request.path, preview)
    else:
        logger.info("HTTP %s %s", request.method, request.path)


@app.after_request
def _log_api_response(resp):
    if request.path in _NOISY_POLL_PATHS or not request.path.startswith("/api/"):
        return resp
    if request.method == "GET" and request.path not in ("/api/chat/status",):
        return resp
    try:
        body = resp.get_json(silent=True)
        if body is not None:
            preview = json.dumps(body, default=str)[:240]
            level = logger.info if resp.status_code < 400 else logger.error
            level("HTTP %s %s  resp=%s", resp.status_code, request.path, preview)
    except Exception:
        pass
    return resp


@app.route("/api/thermal")
def api_thermal():
    with _lock:
        return jsonify(_state)


@app.route("/api/control/powerplan", methods=["POST"])
def set_powerplan():
    data = request.get_json(silent=True) or {}
    guid = (data.get("guid") or "").lower()
    known = pcd_state.KNOWN_PLAN_GUIDS
    if not GUID_RE.match(guid) or (known and guid not in known):
        return jsonify({"error": "unknown plan guid"}), 400
    rc, _, err = ps_full(f"powercfg /setactive {guid}")
    _refresh_state_controls()
    return jsonify({"ok": rc == 0, "error": err or None})


@app.route("/api/control/overlay", methods=["POST"])
def set_overlay():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").lower()
    if name not in OVERLAY_GUIDS:
        return jsonify({"error": "unknown overlay"}), 400
    ok, err = set_power_overlay_api(OVERLAY_GUIDS[name])
    _refresh_state_controls()
    return jsonify({"ok": ok, "error": err})


@app.route("/api/control/cooling-policy", methods=["POST"])
def set_cooling():
    val = (request.get_json(silent=True) or {}).get("value")
    if val not in (0, 1):
        return jsonify({"error": "value must be 0 or 1"}), 400
    ok, err = _apply_proc_value(SYSCOOLPOL, val)
    _refresh_state_controls()
    return jsonify({"ok": ok, "error": err})


@app.route("/api/control/turbo", methods=["POST"])
def set_turbo():
    val = (request.get_json(silent=True) or {}).get("value")
    if not isinstance(val, int) or not 0 <= val <= 5:
        return jsonify({"error": "value 0..5"}), 400
    ok, err = _apply_proc_value(PERFBOOSTMODE, val)
    _refresh_state_controls()
    return jsonify({"ok": ok, "error": err})


@app.route("/api/control/cpu-max", methods=["POST"])
def set_cpu_max():
    val = (request.get_json(silent=True) or {}).get("value")
    if not isinstance(val, int) or not 30 <= val <= 100:
        return jsonify({"error": "value 30..100"}), 400
    ok, err = _apply_proc_value(PROCTHROTTLEMAX, val)
    _refresh_state_controls()
    return jsonify({"ok": ok, "error": err})


@app.route("/api/control/cpu-min", methods=["POST"])
def set_cpu_min():
    val = (request.get_json(silent=True) or {}).get("value")
    if not isinstance(val, int) or not 5 <= val <= 100:
        return jsonify({"error": "value 5..100"}), 400
    ok, err = _apply_proc_value(PROCTHROTTLEMIN, val)
    _refresh_state_controls()
    return jsonify({"ok": ok, "error": err})


@app.route("/api/control/gpu-power", methods=["POST"])
def set_gpu_power():
    val = (request.get_json(silent=True) or {}).get("value")
    if not isinstance(val, (int, float)) or not 5 <= val <= 300:
        return jsonify({"error": "value 5..300 W"}), 400
    ok, err = _set_gpu_power(int(val))
    _refresh_state_controls()
    return jsonify({"ok": ok, "error": err})


# ─── AI auto-optimizer ───


@app.route("/api/optimizer/start", methods=["POST"])
def optimizer_start():
    """Begin the auto-optimize loop. Body: {interval_minutes: float}."""
    from pcd_optimizer import start
    data = request.get_json(silent=True) or {}
    try:
        m = float(data.get("interval_minutes", 5))
    except (TypeError, ValueError):
        m = 5
    return jsonify(start(m))


@app.route("/api/optimizer/stop", methods=["POST"])
def optimizer_stop():
    from pcd_optimizer import stop
    return jsonify(stop())


@app.route("/api/optimizer/status", methods=["GET"])
def optimizer_status():
    from pcd_optimizer import status
    return jsonify(status())


@app.route("/api/optimizer/run-now", methods=["POST"])
def optimizer_run_now():
    """Fire one Claude decision right now (synchronous). The background
    loop, if running, has its next scheduled tick reset."""
    from pcd_optimizer import run_now
    return jsonify(run_now())


# ─── diagnostic recorder ───


@app.route("/api/recorder/start", methods=["POST"])
def recorder_start():
    """Start writing one line per sample to pc_status_YYYYMMDD_HHMMSS.txt."""
    from pcd_recorder import start
    data = request.get_json(silent=True) or {}
    interval = data.get("interval_s", 10)
    try:
        interval = float(interval)
    except (TypeError, ValueError):
        interval = 10
    return jsonify(start(interval))


@app.route("/api/recorder/stop", methods=["POST"])
def recorder_stop():
    """Stop the current recording and close the file."""
    from pcd_recorder import stop
    return jsonify(stop())


@app.route("/api/recorder/status", methods=["GET"])
def recorder_status():
    """Report whether a recording is active, plus elapsed time and sample count."""
    from pcd_recorder import status
    return jsonify(status())


@app.route("/api/control/preset", methods=["POST"])
def apply_preset():
    name = ((request.get_json(silent=True) or {}).get("name") or "").lower()
    errors = []

    def step(ok, err):
        if not ok and err:
            errors.append(err)

    gpu = read_gpu_power_info()
    if name == "quiet":
        step(*_apply_proc_value(SYSCOOLPOL, 0))
        step(*_apply_proc_value(PERFBOOSTMODE, 0))
        step(*_apply_proc_value(PROCTHROTTLEMAX, 80))
        if gpu and gpu.get("min_w"):
            step(*_set_gpu_power(int(gpu["min_w"])))
        step(*set_power_overlay_api(OVERLAY_GUIDS["best-efficiency"]))
    elif name == "balanced":
        step(*_apply_proc_value(SYSCOOLPOL, 1))
        step(*_apply_proc_value(PERFBOOSTMODE, 2))
        step(*_apply_proc_value(PROCTHROTTLEMAX, 100))
        if gpu and gpu.get("default_w"):
            step(*_set_gpu_power(int(gpu["default_w"])))
        step(*set_power_overlay_api(OVERLAY_GUIDS["balanced"]))
    elif name == "performance":
        step(*_apply_proc_value(SYSCOOLPOL, 1))
        step(*_apply_proc_value(PERFBOOSTMODE, 2))
        step(*_apply_proc_value(PROCTHROTTLEMAX, 100))
        step(*_apply_proc_value(PROCTHROTTLEMIN, 100))
        if gpu and gpu.get("max_w"):
            step(*_set_gpu_power(int(gpu["max_w"])))
        step(*set_power_overlay_api(OVERLAY_GUIDS["best-performance"]))
    else:
        return jsonify({"error": "preset must be quiet/balanced/performance"}), 400
    _refresh_state_controls()
    return jsonify({"ok": not errors, "errors": errors})
