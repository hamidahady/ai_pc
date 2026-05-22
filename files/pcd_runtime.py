"""
pcd_runtime.py — main() + helper-imports for pc_dashboard.

Extracted from pc_dashboard.py to keep that file tiny. pc_dashboard.py does
the two-stage bootstrap (fetch pcd_bootstrap.py if missing, then sync the
rest), then imports `main` from here and calls it.

This module:
  - imports every pcd_* helper at module load (with abort_on_missing on fail);
  - registers the dashboard's index route ("/") on the Flask app;
  - exposes `main()` which handles argv parsing, admin/UAC elevation, the
    one-time startup probes, the poll thread, and Flask's app.run().
"""

import argparse
import sys
import threading

# ─── Import every helper. Bootstrap should have placed them in ./files/.
#     If any are still missing, the bootstrap's standard FATAL formatter
#     prints exactly which one and exits. ───
try:
    from pcd_log import logger, attach_log_file
    from pcd_config import HOST, PORT, REFRESH_S
    from pcd_admin import (
        install_no_uac_task, is_admin, try_elevate, uninstall_no_uac_task,
    )
    from pcd_probes import oem_discover, probe_system_info
    from pcd_state import _lock, _state, app, poll_loop
    import pcd_state
    import pcd_api    # noqa: F401 — side-effect: registers /api/control/* routes
    import pcd_chat   # noqa: F401 — side-effect: registers /api/chat routes
    from pcd_page import PAGE
    from flask import render_template_string
except ModuleNotFoundError as e:
    from pcd_bootstrap import abort_on_missing
    abort_on_missing(e)


# ─── Dashboard's single non-API route: the HTML index page. ───
@app.route("/")
def _index():
    return render_template_string(PAGE)


# ─── main() — the entry point pc_dashboard.py calls. ───


def main() -> None:
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

    if args.install_no_uac:
        sys.exit(install_no_uac_task())
    if args.uninstall_no_uac:
        sys.exit(uninstall_no_uac_task())

    if not pcd_state.IS_ADMIN and not args.no_elevate:
        print("Not running as Administrator — requesting UAC elevation ...")
        print("  -> If you accept, an elevated console will open and host the dashboard.")
        print("  -> This unprivileged instance will then exit.")
        if try_elevate(["--no-elevate"]):
            print(f"  Elevated instance started. Open http://{HOST}:{PORT} there.")
            return
        print("  Elevation declined or failed. Continuing without admin —")
        print("    CPU / GPU / Cooling / Turbo controls will fail silently.")

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
    try:
        from pcd_vendor_detect import detect as _detect_vendor
        _detect_vendor()
    except Exception as e:
        logger.warning("  vendor detect failed: %s", e)
    logger.info("OEM WMI discovery (one-time, may take ~10s):")
    try:
        pcd_state.OEM_DISCOVERY = oem_discover()
    except Exception as e:
        logger.error("  discovery failed: %s", e)
        pcd_state.OEM_DISCOVERY = []

    logger.info("Dashboard: http://%s:%d  (Ctrl-C to stop)", HOST, PORT)
    threading.Thread(target=poll_loop, daemon=True).start()
    app.run(host=HOST, port=PORT, debug=False, use_reloader=False)
