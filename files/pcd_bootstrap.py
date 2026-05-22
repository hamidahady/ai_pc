"""
pcd_bootstrap.py — full bootstrap logic, extracted from pc_dashboard.py.

pc_dashboard.py keeps only a tiny stage-1 stub that fetches THIS file from
GitHub if missing, then calls run_full_bootstrap() to do the rest:

  1. sync_files_from_github() — list the upstream files/ folder and download
     anything not already local. Idempotent. Failures are logged + swallowed.
  2. ensure_packages_installed() — pip-install flask + anthropic + ollama
     if they're missing. (Delegates to pcd_deps.ensure_packages.)
  3. abort_on_missing() — formatter for the FATAL error printed when the
     helper imports in pcd_runtime still fail after bootstrap.

Stdlib-only (urllib + json + subprocess via pcd_deps). Must be importable
before flask/anthropic exist.
"""

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

# ─── upstream source (edit if the repo or branch ever changes) ───
GITHUB_OWNER  = "hamidahady"
GITHUB_REPO   = "ai_pc"
GITHUB_BRANCH = "main"
GITHUB_FOLDER = "files"

FILES_DIR = Path(__file__).resolve().parent     # files/, where this file sits

_API_URL = (
    f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}"
    f"/contents/{GITHUB_FOLDER}?ref={GITHUB_BRANCH}"
)
_HUMAN_URL = (
    f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"
    f"/tree/{GITHUB_BRANCH}/{GITHUB_FOLDER}"
)
_UA = {"User-Agent": "pc_dashboard-bootstrap",
       "Accept": "application/vnd.github+json"}


# ──────────────────────── 1. sync from GitHub ────────────────────────


def sync_files_from_github() -> None:
    """Ensure ./files/ contains every upstream file. Idempotent — only
    downloads what's missing locally. All errors are printed and swallowed;
    the dashboard tries to run with whatever is already local."""
    FILES_DIR.mkdir(exist_ok=True)
    print(f"[bootstrap] checking {_HUMAN_URL}")
    print(f"[bootstrap] local target: {FILES_DIR}")

    # 1) List the upstream folder via GitHub's Contents API.
    try:
        req = urllib.request.Request(_API_URL, headers=_UA)
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        msg = f"GitHub API HTTP {e.code} {e.reason}"
        if e.code == 404:
            msg += (f"  (folder '{GITHUB_FOLDER}' not found in "
                    f"{GITHUB_OWNER}/{GITHUB_REPO}@{GITHUB_BRANCH})")
        elif e.code == 403:
            msg += "  (rate-limited — retry in a few minutes)"
        print(f"[bootstrap] ERROR: {msg}")
        print(f"[bootstrap] continuing with whatever is already in {FILES_DIR}")
        return
    except urllib.error.URLError as e:
        print(f"[bootstrap] ERROR: network error: {e.reason}")
        print(f"[bootstrap] continuing with whatever is already in {FILES_DIR}")
        return
    except Exception as e:
        print(f"[bootstrap] ERROR: unexpected error: {e!r}")
        return

    try:
        entries = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        print(f"[bootstrap] ERROR: GitHub returned non-JSON: {e}")
        return

    if not isinstance(entries, list):
        print(f"[bootstrap] ERROR: unexpected GitHub response: {str(entries)[:200]}")
        return

    # 2) For each upstream file, download iff it isn't already local.
    downloaded = skipped = failed = 0
    for entry in entries:
        if entry.get("type") != "file":
            continue
        name = entry.get("name")
        url  = entry.get("download_url")
        if not name or not url:
            continue
        local = FILES_DIR / name
        if local.exists():
            skipped += 1
            continue
        try:
            req = urllib.request.Request(url, headers=_UA)
            with urllib.request.urlopen(req, timeout=30) as resp:
                content = resp.read()
            local.write_bytes(content)
            print(f"[bootstrap]   downloaded {name} ({len(content)} bytes)")
            downloaded += 1
        except Exception as e:
            print(f"[bootstrap]   failed to download {name}: {e}")
            failed += 1

    print(f"[bootstrap] done: {downloaded} downloaded, {skipped} already present, {failed} failed")


# ──────────────────────── 2. deps check ────────────────────────


def ensure_packages_installed() -> None:
    """Pip-install third-party Python packages (flask, anthropic, ollama)
    if they're missing. Delegates to pcd_deps which must be in ./files/ by
    the time this is called."""
    try:
        from pcd_deps import ensure_packages
        ensure_packages()
    except Exception as e:
        print(f"[deps] dependency check skipped: {e}")


# ──────────────────────── 3. FATAL formatter ────────────────────────


def abort_on_missing(exc: ModuleNotFoundError, files_dir: Path | None = None) -> "NoReturn":
    """Standardised FATAL exit when an expected helper module isn't importable
    even after the bootstrap. Prints a clear message and sys.exit(1)."""
    target = files_dir or FILES_DIR
    print()
    print(f"FATAL: could not import helper modules from {target}")
    print(f"       missing: {exc.name}")
    print()
    print("This usually means the bootstrap couldn't reach GitHub AND the")
    print(f"helper file isn't already present in {target}.")
    print()
    print("Fixes:")
    print("  - Connect to the internet and rerun, OR")
    print(f"  - Manually copy the pcd_*.py files into {target}")
    sys.exit(1)


# ──────────────────────── 4. convenience entry ────────────────────────


def run_full_bootstrap() -> None:
    """One-call wrapper used by pc_dashboard.py — sync files then install deps."""
    sync_files_from_github()
    ensure_packages_installed()
