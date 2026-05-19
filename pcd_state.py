"""
pcd_state.py — shared in-memory state and the polling thread.

Owns:
  - The Flask `app` (so route modules can `from pcd_state import app` and
    register routes with @app.route at import time).
  - The `_state` dict served by /api/thermal — populated by poll_loop().
  - Mutable globals other modules update (IS_ADMIN, OEM_DISCOVERY,
    SYSTEM_INFO, KNOWN_PLAN_GUIDS).
  - The chat history shared between Claude turns.

Other modules MUST access these via `pcd_state.X` (not `from pcd_state
import X`) so they see the live value rather than an import-time snapshot.
"""

import threading
import time
from datetime import datetime

from flask import Flask

from pcd_config import REFRESH_S
from pcd_log import logger

app = Flask(__name__)

_state = {
    "updated": None,
    "system": {},
    "sources": {
        "thermal_zones": [], "nvidia": [], "storage": [],
        "battery": {}, "cpu_proxy": {}, "oem": [],
    },
    "controls": {},
}
_lock = threading.Lock()

# Mutable module-level globals — accessed via pcd_state.X by other modules.
OEM_DISCOVERY: list[tuple[str, str]] = []
SYSTEM_INFO: dict = {}
IS_ADMIN = False
KNOWN_PLAN_GUIDS: set[str] = set()

# Conversation history for the AI assistant: list of {role, content (str)}.
_chat_history: list[dict] = []
_chat_lock = threading.Lock()


def _refresh_state_controls():
    """Re-probe control state immediately so /api/thermal reflects the change
    on the very next request, instead of waiting up to 2s for poll_loop."""
    # Local import to avoid circular dependency at module load time.
    from pcd_controls import probe_controls
    try:
        ctrl = probe_controls()
        with _lock:
            _state["controls"] = ctrl
    except Exception as e:
        logger.error("  refresh-state failed: %s", e)


def poll_loop():
    """Background thread — every REFRESH_S seconds, rebuild the snapshot."""
    from pcd_probes import (
        probe_thermal_zones, probe_nvidia, probe_storage,
        probe_battery, probe_cpu_proxy, probe_oem_sensors,
    )
    from pcd_controls import probe_controls

    while True:
        try:
            snap = {
                "thermal_zones": probe_thermal_zones(),
                "nvidia":        probe_nvidia(),
                "storage":       probe_storage(),
                "battery":       probe_battery(),
                "cpu_proxy":     probe_cpu_proxy(),
                "oem":           probe_oem_sensors(),
            }
            ctrl = probe_controls()
            with _lock:
                _state["updated"] = datetime.now().isoformat(timespec="seconds")
                _state["sources"] = snap
                _state["controls"] = ctrl
        except Exception as e:
            with _lock:
                _state["error"] = str(e)
        time.sleep(REFRESH_S)
