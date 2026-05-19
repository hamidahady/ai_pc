"""
pcd_log.py — logger setup for pc_dashboard.

At module import we only attach a console handler. The file handler is opened
later via attach_log_file() — `main()` calls this once it has decided this
process will actually run the dashboard (not a short-lived UAC parent or an
install helper). Result: exactly one log_YYYYMMDD_HHMMSS.txt per real launch.

Used by every other pcd_* module: `from pcd_log import logger`.
"""

import logging
from datetime import datetime
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent
LOG_FILE: Path | None = None  # populated by attach_log_file()

logger = logging.getLogger("pc_dashboard")
logger.setLevel(logging.DEBUG)
logger.propagate = False  # don't double up via the root logger

_console_h = logging.StreamHandler()
_console_h.setLevel(logging.INFO)
_console_h.setFormatter(logging.Formatter("%(message)s"))
logger.addHandler(_console_h)


def attach_log_file() -> None:
    """Open the per-run log file and attach a DEBUG handler. Idempotent."""
    global LOG_FILE
    if LOG_FILE is not None:
        return
    LOG_FILE = LOG_DIR / f"log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s.%(msecs)03d [%(levelname)-5s] %(message)s",
        datefmt="%H:%M:%S",
    ))
    logger.addHandler(fh)
    logger.info("=" * 72)
    logger.info("pc_dashboard.py launched at %s", datetime.now().isoformat(timespec="seconds"))
    logger.info("Log file: %s", LOG_FILE)
    logger.info("=" * 72)
