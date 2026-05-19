"""
pc_dashboard.py — live thermal + power dashboard for any Windows PC.

This is the entry point. The actual implementation is split across
focused helper modules; this file just parses arguments, runs the
admin / elevation / setup dance, starts the background poll thread,
and hands control to Flask.

Module layout:

    pcd_config.py    constants, GUIDs, regex, chat system prompt
    pcd_log.py       logger + per-run log_YYYYMMDD_HHMMSS.txt file handler
    pcd_shell.py     ps() / ps_full() wrappers around PowerShell
    pcd_state.py     Flask app, shared _state dict, poll_loop, KNOWN_PLAN_GUIDS
    pcd_admin.py     is_admin, UAC elevation, Scheduled Task install/uninstall
    pcd_probes.py    monitoring probes + system identity + OEM discovery
    pcd_controls.py  read/write power settings + powrprof.dll overlay API
    pcd_api.py       /api/thermal + /api/control/* + before/after_request hooks
    pcd_chat.py      Claude @beta_tool functions + /api/chat endpoints
    pcd_page.py      HTML PAGE constant (CSS + JS inline)
    pc_dashboard.py  this file — main(), index route, startup sequence

Run:
    python pc_dashboard.py
    (If not already elevated, it requests UAC and relaunches itself as admin.
    Pass --no-elevate to skip the UAC prompt and run unprivileged.)

Skip UAC forever (one-time setup):
    python pc_dashboard.py --install-no-uac
    Then double-click run_dashboard.bat — no UAC prompt thereafter.
    Undo: python pc_dashboard.py --uninstall-no-uac

Open:  http://localhost:5000
Stop:  Ctrl-C in the terminal.

Auto-logging: every actual run creates one log_YYYYMMDD_HHMMSS.txt next to
this file, recording every HTTP API call, every PowerShell write command,
SET / VERIFY pairs for control changes (with before/after registry read-back),
and the Claude chat conversation with tool calls.
"""

import argparse
import sys
import threading

from flask import render_template_string

# Project modules — importing pcd_api and pcd_chat registers their Flask
# routes on pcd_state.app at import time. pcd_log is imported first so its
# logger is available before anything else can call logger.info().
from pcd_log import logger, attach_log_file  # noqa: I001
from pcd_config import HOST, PORT, REFRESH_S
from pcd_admin import (
    install_no_uac_task, is_admin, try_elevate, uninstall_no_uac_task,
)
from pcd_probes import oem_discover, probe_system_info
from pcd_state import _lock, _state, app, poll_loop
import pcd_state  # IS_ADMIN / SYSTEM_INFO / OEM_DISCOVERY assigned in main()
import pcd_api    # noqa: F401 — side-effect: registers /api/control/* routes
import pcd_chat   # noqa: F401 — side-effect: registers /api/chat routes
from pcd_page import PAGE


@app.route("/")
def index():
    return render_template_string(PAGE)


def main():
    parser = argparse.ArgumentParser(description="Live thermal dashboard.")
    parser.add_argument("--no-elevate", action="store_true",
                        help="Skip the UAC self-elevation prompt and run unprivileged.")
    parser.add_argument("--install-no-uac", action="store_true",
                        help="One-time: register a Scheduled Task + write run_dashboard.bat "
                             "so future launches need no UAC prompt.")
    parser.add_argument("--uninstall-no-uac", action="store_true",
                        help="Remove the Scheduled Task and the launcher .bat.")
    args = parser.parse_args()

    pcd_state.IS_ADMIN = is_admin()

    # Short-circuit paths that don't need a log file — install/uninstall the
    # Scheduled Task and exit.
    if args.install_no_uac:
        sys.exit(install_no_uac_task())
    if args.uninstall_no_uac:
        sys.exit(uninstall_no_uac_task())

    # Self-elevation flow. The parent process exits without opening a log file;
    # the elevated child reaches the code below and opens its own.
    if not pcd_state.IS_ADMIN and not args.no_elevate:
        print("Not running as Administrator — requesting UAC elevation ...")
        print("  -> If you accept, an elevated console will open and host the dashboard.")
        print("  -> This unprivileged instance will then exit.")
        if try_elevate(["--no-elevate"]):
            print(f"  Elevated instance started. Open http://{HOST}:{PORT} there.")
            return
        print("  Elevation declined or failed. Continuing without admin —")
        print("    CPU / GPU / Cooling / Turbo controls will fail silently.")

    # We're committed to running the dashboard in this process — open the log
    # file now so the entire run lives in a single file.
    attach_log_file()

    logger.info("Running as Administrator: %s", pcd_state.IS_ADMIN)
    logger.info("Identifying system ...")
    try:
        pcd_state.SYSTEM_INFO = probe_system_info()
    except Exception as e:
        logger.error("  system probe failed: %s", e)
        pcd_state.SYSTEM_INFO = {}
    if pcd_state.SYSTEM_INFO:
        host = pcd_state.SYSTEM_INFO.get("hostname", "?")
        mfg  = pcd_state.SYSTEM_INFO.get("Manufacturer", "?")
        mdl  = pcd_state.SYSTEM_INFO.get("Model") or pcd_state.SYSTEM_INFO.get("SystemFamily", "?")
        logger.info("  %s  ·  %s  ·  %s", host, mfg, mdl)
    with _lock:
        _state["system"] = pcd_state.SYSTEM_INFO

    logger.info("Polling every %ss in background.", REFRESH_S)
    logger.info("OEM WMI discovery (one-time, may take ~10s):")
    try:
        pcd_state.OEM_DISCOVERY = oem_discover()
    except Exception as e:
        logger.error("  discovery failed: %s", e)
        pcd_state.OEM_DISCOVERY = []

    logger.info("Dashboard: http://%s:%d  (Ctrl-C to stop)", HOST, PORT)
    threading.Thread(target=poll_loop, daemon=True).start()
    app.run(host=HOST, port=PORT, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
