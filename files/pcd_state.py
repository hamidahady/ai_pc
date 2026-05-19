"""
pcd_state.py — shared in-memory state, Flask app, and the polling thread.
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

OEM_DISCOVERY: list[tuple[str, str]] = []
SYSTEM_INFO: dict = {}
IS_ADMIN = False
KNOWN_PLAN_GUIDS: set[str] = set()

_chat_history: list[dict] = []
_chat_lock = threading.Lock()


def _refresh_state_controls():
    from pcd_controls import probe_controls
    try:
        ctrl = probe_controls()
        with _lock:
            _state["controls"] = ctrl
    except Exception as e:
        logger.error("  refresh-state failed: %s", e)


def poll_loop():
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
