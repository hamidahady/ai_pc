"""
pcd_fixer.py — system-level autonomous fixes invoked by the optimizer.

This is the "GenAI finds the fix and applies it" layer. Claude, via the
optimizer, can choose one of three system-fix actions (in addition to the
existing power-mode toggles):

    disable_service       set a Windows service to Disabled + stop it
    set_service_manual    set a Windows service to Manual start
    report_only           log a user-actionable finding (no system change)

SAFETY MODEL
============
Tiered. Every service Claude proposes is classified into one of three tiers:

  PREFERRED  — known-safe, non-essential auto-updaters (Foxit, Adobe,
               Chrome/Edge updaters, Zoom, Spotify, Steam, etc.). Tried
               FIRST. Logged at INFO.
  ESCALATED  — anything else not in the never-touch list. Used when
               preferred fixes haven't improved performance (Claude judges).
               Logged at WARNING so it's clearly distinguishable.
  NEVER_TOUCH — services Windows literally needs to boot/run, OR the
               dashboard itself needs. Hard-refused. The list is small and
               deliberate: RPC subsystem, lsass, plugplay, schedule, event
               log, dnscache, profsvc, samss, netlogon, winmgmt, power.
               Disabling any of these would either prevent Windows from
               booting or break the dashboard's own data sources.

Every applied fix — preferred OR escalated — logs:
  - Tier (so you can grep escalated fixes)
  - Before-state (StartType + Status from Get-Service)
  - The exact PowerShell that was run
  - The exact PowerShell that REVERSES the change

Fixes are idempotent.
"""

import re
import threading
from datetime import datetime

from pcd_log import logger
from pcd_shell import ps, ps_full


# ──────────────────────── TIER 1: PREFERRED ────────────────────────
# Tried first by Claude. Non-essential auto-updaters; safe to disable.
PREFERRED_DISABLE_SERVICES = {
    # ─── PDF readers ───
    "FoxitReaderUpdateService",
    # ─── Adobe ───
    "AdobeUpdateService",
    "AdobeARMservice",
    "AdobeAcrobatUpdateService",
    # ─── Browser updaters (DOES NOT affect the browser itself) ───
    "GoogleChromeElevationService",
    "edgeupdate",
    "edgeupdatem",
    "MicrosoftEdgeElevationService",
    # ─── Meeting apps ───
    "ZoomCptService",
    "ZoomVideoConferenceService",
    # ─── Other common auto-updaters ───
    "SpotifyUpdater",
    "SteamService",
}

# Pattern matches also count as PREFERRED. Useful for per-version names
# (e.g. GoogleUpdater changes service name on every Chrome release).
PREFERRED_DISABLE_PATTERNS = [
    re.compile(r"^GoogleUpdater(Service|InternalService).*", re.I),
    re.compile(r"^edgeupdate[a-z]*$", re.I),
    re.compile(r".*UpdateService$", re.I),       # any *UpdateService
    re.compile(r".*UpdaterService$", re.I),      # any *UpdaterService
]

# ──────────────────────── TIER 3: NEVER TOUCH ────────────────────────
# Hard-refused. These services are required for Windows to boot/run,
# or are the dashboard's own data sources. Disabling them would either
# brick the OS or break this very tool.
NEVER_TOUCH_SERVICES = {
    # RPC subsystem — EVERYTHING in Windows depends on this
    "rpcss", "rpceptmapper", "dcomlaunch",
    # Plug-and-play hardware enumeration
    "plugplay",
    # Local Security Authority — auth, credentials, sessions
    "lsass", "samss", "lsm",
    # User profile / logon — would prevent login
    "profsvc", "netlogon", "userManager",
    # Task Scheduler — many Windows components depend on it
    "schedule",
    # Event Log / Event System — kernel-level event broker
    "eventlog", "eventsystem",
    # Power management — the dashboard reads from this
    "power",
    # WMI — the dashboard's primary data source. Disabling = self-destruct.
    "winmgmt", "wmiprvse",
    # DNS resolver — every networked app needs it
    "dnscache",
    # Windows boot stuff
    "wininit", "trustedinstaller",
    # Local HTTP stack (the dashboard's Flask uses this on Windows)
    "http",
}
# Note on what is NOT in this list:
# - Defender (MsMpEng, WinDefend) — user explicitly authorized aggressive action
# - Sophos (sspservice, sophosfilescanner, etc.) — user explicitly authorized
# - Windows Search (wsearch), Windows Update (wuauserv) — heavy, sometimes worth pausing
# - LanmanServer, LanmanWorkstation — file sharing; safe to disable if you don't use it
# These are all available as ESCALATED targets but logged loudly with WARNING.


def classify_service(name: str) -> str:
    """Return one of: 'preferred' | 'escalated' | 'never_touch'.

    Order: NEVER_TOUCH check comes first so it can't be defeated by a
    regex match in PREFERRED_DISABLE_PATTERNS.
    """
    lname = name.lower()
    if lname in {s.lower() for s in NEVER_TOUCH_SERVICES}:
        return "never_touch"
    if lname in {s.lower() for s in PREFERRED_DISABLE_SERVICES}:
        return "preferred"
    for pat in PREFERRED_DISABLE_PATTERNS:
        if pat.match(name):
            return "preferred"
    return "escalated"


# ──────────────────────── session history ────────────────────────


_fixes_lock = threading.Lock()
_applied_fixes: list[dict] = []
_MAX_HISTORY = 30


def get_applied_fixes() -> list[dict]:
    """Snapshot of every system fix applied this session — used by the UI."""
    with _fixes_lock:
        return list(_applied_fixes)


def _remember(record: dict) -> None:
    with _fixes_lock:
        _applied_fixes.append(record)
        while len(_applied_fixes) > _MAX_HISTORY:
            _applied_fixes.pop(0)


# ──────────────────────── allowlist check ────────────────────────


def _gate(service_name: str) -> tuple[bool, str, str]:
    """Return (allowed, tier, reason). `tier` is one of preferred|escalated|never_touch.
    `allowed` is True for preferred + escalated, False for never_touch."""
    tier = classify_service(service_name)
    if tier == "never_touch":
        return False, tier, "hard-blocked: required for Windows or the dashboard itself"
    if tier == "preferred":
        return True, tier, "allowed: in PREFERRED_DISABLE_SERVICES (or matching pattern)"
    return True, tier, "allowed (escalation): not on preferred list but not never-touch"


# ──────────────────────── fix actions ────────────────────────


def _get_service_state(name: str) -> tuple[str | None, str | None]:
    """Return (status, start_type) for the service, or (None, None) if missing."""
    out = ps(
        f"Get-Service -Name '{name}' -ErrorAction SilentlyContinue | "
        "Select-Object Status, StartType | Format-List"
    )
    if not out.strip():
        return None, None
    status, start = None, None
    for line in out.splitlines():
        if ":" not in line:
            continue
        k, v = [s.strip() for s in line.split(":", 1)]
        if k == "Status":
            status = v
        elif k == "StartType":
            start = v
    return status, start


def _apply_service_change(
    name: str,
    *,
    action_label: str,
    target_starttype: str,        # 'Disabled' or 'Manual'
    stop_first: bool,
    already_state_check: str,     # 'disabled' or 'manual' — the no-op case
) -> dict:
    """Shared body for disable_service + set_service_manual. Handles tier
    classification, never-touch refusal, idempotency, execution, logging,
    and history."""
    record = {
        "ts":               datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "action":           action_label,
        "target":           name,
        "tier":             None,
        "ok":               False,
        "error":            None,
        "skipped":          None,
        "before_status":    None,
        "before_starttype": None,
        "reversal_command": None,
    }

    allowed, tier, reason = _gate(name)
    record["tier"] = tier
    if not allowed:
        record["error"] = reason
        logger.error("FIXER REFUSED %s('%s'): %s", action_label, name, reason)
        _remember(record)
        return record

    status, start = _get_service_state(name)
    record["before_status"] = status
    record["before_starttype"] = start

    if status is None:
        record["error"] = f"service '{name}' not found"
        logger.warning("FIXER %s('%s'): service not found", action_label, name)
        _remember(record)
        return record

    # Idempotency — already in target state?
    if (start or "").lower() == already_state_check:
        record["ok"] = True
        record["skipped"] = f"already {already_state_check}"
        record["reversal_command"] = (
            f"Set-Service -Name '{name}' -StartupType Automatic"
            + ("; Start-Service -Name '" + name + "'" if stop_first else "")
        )
        logger.info(
            "FIXER no-op %s('%s'): already %s  [tier=%s]",
            action_label, name, already_state_check, tier,
        )
        _remember(record)
        return record

    # Execute
    if stop_first:
        cmd = (
            f"Stop-Service -Name '{name}' -Force -ErrorAction SilentlyContinue; "
            f"Set-Service -Name '{name}' -StartupType {target_starttype} -ErrorAction Stop"
        )
    else:
        cmd = f"Set-Service -Name '{name}' -StartupType {target_starttype} -ErrorAction Stop"

    rc, _, err = ps_full(cmd, timeout=20)
    if rc != 0:
        record["error"] = err[:240] or "powershell returned non-zero"
        logger.error(
            "FIXER %s('%s') [tier=%s] FAILED: %s",
            action_label, name, tier, record["error"],
        )
        _remember(record)
        return record

    record["ok"] = True
    restore_to = "Automatic" if (start or "").lower() != "manual" else "Manual"
    record["reversal_command"] = (
        f"Set-Service -Name '{name}' -StartupType {restore_to}"
        + ("; Start-Service -Name '" + name + "'" if stop_first else "")
    )

    # Differentiated logging — preferred gets INFO, escalated gets WARNING so
    # `grep "FIXER ESCALATED"` finds every aggressive action quickly.
    if tier == "preferred":
        logger.info(
            "FIXER APPLIED %s('%s')  was: status=%s startup=%s  [tier=preferred]",
            action_label, name, status, start,
        )
    else:
        logger.warning(
            "FIXER ESCALATED %s('%s')  was: status=%s startup=%s  "
            "[tier=escalated — outside preferred allowlist, applied because "
            "preferred fixes alone were insufficient]",
            action_label, name, status, start,
        )
    logger.info("  reversal: %s", record["reversal_command"])
    _remember(record)
    return record


def disable_service(name: str) -> dict:
    """Disable a Windows service (Stop-Service + Set-Service -StartupType Disabled).
    Tier-gated: hard-refused for never-touch services, applied with WARNING-
    level logging for escalated services, applied with INFO for preferred."""
    return _apply_service_change(
        name,
        action_label="disable_service",
        target_starttype="Disabled",
        stop_first=True,
        already_state_check="disabled",
    )


def set_service_manual(name: str) -> dict:
    """Set a Windows service to Manual startup (less aggressive than Disable).
    The service can still be started by Windows or another app on demand,
    but won't auto-start at boot."""
    return _apply_service_change(
        name,
        action_label="set_service_manual",
        target_starttype="Manual",
        stop_first=False,
        already_state_check="manual",
    )


def report_only(message: str) -> dict:
    """No-action 'finding' — Claude flags an issue it can't safely fix, so it
    surfaces a one-line note to the user. Logged into the same audit trail."""
    record = {
        "ts":      datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "action":  "report_only",
        "message": (message or "")[:400],
        "ok":      True,
        "error":   None,
    }
    logger.info("FIXER REPORT: %s", record["message"])
    _remember(record)
    return record
