"""
pcd_shell.py — thin wrappers around PowerShell, with logging.
"""

import subprocess

from pcd_log import logger


def ps(cmd: str, timeout: int = 10) -> str:
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command", cmd],
        capture_output=True, text=True, timeout=timeout,
    )
    out = (r.stdout or "").strip()
    if r.returncode != 0:
        logger.warning(
            "PS-read failed rc=%d cmd=%r stderr=%r",
            r.returncode, cmd[:120], (r.stderr or "").strip()[:200],
        )
    return out


def ps_full(cmd: str, timeout: int = 10):
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command", cmd],
        capture_output=True, text=True, timeout=timeout,
    )
    out = (r.stdout or "").strip()
    err = (r.stderr or "").strip()
    rc = r.returncode
    if rc == 0:
        msg = f"PS> {cmd[:240]}\n           rc=0"
        if out:
            msg += f"  stdout={out[:200]!r}"
        logger.info(msg)
    else:
        logger.error(
            "PS> %s\n           rc=%d stdout=%r stderr=%r",
            cmd[:240], rc, out[:200], err[:200],
        )
    return rc, out, err


def safe_float(s):
    try:
        return float(s)
    except (ValueError, TypeError):
        return None
