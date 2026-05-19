"""
pcd_shell.py — thin wrappers around PowerShell, with logging.

ps() is for read calls (used by every probe). It only logs on failure, so the
2-second poll loop doesn't flood the log file.

ps_full() is for write calls (powercfg /setacvalueindex, etc.). Every
invocation is logged with command, return code, stdout, and stderr — that's
how you can later confirm whether a Turbo Boost or Cooling Policy change
actually executed.
"""

import subprocess

from pcd_log import logger


def ps(cmd: str, timeout: int = 10) -> str:
    """Run PowerShell, return stripped stdout. Read-only callers — only logs
    on failure to avoid flooding the log with poll-loop traffic."""
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
    """Run PowerShell, return (rc, stdout, stderr). Used by writers — every
    call is logged with its return code so the log shows exactly which
    PowerShell invocations succeeded and which failed."""
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
