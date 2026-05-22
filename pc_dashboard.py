"""
pc_dashboard.py — standalone entry point for the live PC dashboard.

Two-stage bootstrap, then delegate. The actual logic lives in two helper
modules inside ./files/:

  pcd_bootstrap.py — downloads every other helper from GitHub if missing,
                     installs flask/anthropic/ollama via pip if missing.
  pcd_runtime.py   — imports every pcd_* helper, registers the "/" route,
                     and exposes main() which orchestrates startup + Flask.

This file's only job:
  1. Ensure ./files/ exists and is on sys.path.
  2. If ./files/pcd_bootstrap.py is missing, fetch it directly from GitHub.
  3. Delegate to pcd_bootstrap.run_full_bootstrap() — which downloads
     all the other helpers and runs the pip check.
  4. Delegate to pcd_runtime.main() — which runs the dashboard.

Run:    python pc_dashboard.py
Open:   http://localhost:5000
"""

import sys
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
FILES_DIR  = SCRIPT_DIR / "files"
FILES_DIR.mkdir(exist_ok=True)
if str(FILES_DIR) not in sys.path:
    sys.path.insert(0, str(FILES_DIR))

# ── Stage 1: fetch pcd_bootstrap.py directly if it's not already local.
#    Everything else (the rest of the helpers) is the responsibility of
#    pcd_bootstrap once it's available.
_BOOTSTRAP_URL = (
    "https://raw.githubusercontent.com/hamidahady/ai_pc/main/files/pcd_bootstrap.py"
)
_BOOTSTRAP_LOCAL = FILES_DIR / "pcd_bootstrap.py"
if not _BOOTSTRAP_LOCAL.exists():
    print(f"[bootstrap] fetching first-stage module from {_BOOTSTRAP_URL}")
    try:
        req = urllib.request.Request(
            _BOOTSTRAP_URL, headers={"User-Agent": "pc_dashboard-bootstrap"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            _BOOTSTRAP_LOCAL.write_bytes(resp.read())
    except Exception as e:
        print(f"[bootstrap] FATAL: could not fetch {_BOOTSTRAP_URL}: {e}")
        print(f"[bootstrap] manually place pcd_bootstrap.py into {FILES_DIR} and retry.")
        sys.exit(1)

# ── Stage 2: delegate to pcd_bootstrap, then to pcd_runtime.
from pcd_bootstrap import run_full_bootstrap
run_full_bootstrap()

from pcd_runtime import main

if __name__ == "__main__":
    main()
