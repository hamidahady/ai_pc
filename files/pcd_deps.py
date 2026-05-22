"""
pcd_deps.py — ensure third-party Python packages this project uses are installed.

Called once from pc_dashboard.py AFTER the GitHub bootstrap and BEFORE any
other helper module is imported. For each entry in REQUIRED_PACKAGES, tries
to import it; if that fails, runs `<sys.executable> -m pip install <pip_name>`
so the package lands in the SAME interpreter (and the same venv, if any).

──────────────────────────────────────────────────────────────────────────
Why this list is short
──────────────────────────────────────────────────────────────────────────
The project uses many modules — argparse, ctypes, datetime, importlib, json,
logging, os, pathlib, re, subprocess, sys, threading, time, urllib.error,
urllib.request, winreg — but ALL of those ship with Python itself (Python
standard library). They never need `pip install`; they're available the
moment the interpreter starts.

This file lists ONLY packages from PyPI. The list was derived mechanically:

    grep -rhE "(import |from .* import )" *.py files/*.py \
        | grep -v "^from pcd_" | grep -v "^import pcd_" \
        | sort -u

… filtering the result down to names that aren't in Python's stdlib.

──────────────────────────────────────────────────────────────────────────
Stdlib modules used by this project (NO install needed — for reference)
──────────────────────────────────────────────────────────────────────────
  argparse        CLI argument parsing            (pc_dashboard.py)
  ctypes          Windows DLL bindings (powrprof) (pcd_admin, pcd_controls)
  datetime        Timestamps                      (pcd_log, pcd_state)
  importlib       Dynamic imports                 (pcd_deps)
  json            REST request/response bodies    (pcd_api, pcd_chat, …)
  logging         Project logger                  (pcd_log)
  os              Env vars + paths                (pcd_admin, pcd_chat)
  pathlib.Path    Filesystem paths                (everywhere)
  re              GUID regex + powercfg parsing   (pcd_config, pcd_controls)
  subprocess      Spawn PowerShell + pip          (pcd_shell, pcd_deps)
  sys             argv, executable, path          (everywhere)
  threading       _lock, _chat_lock, poll thread  (pcd_state, pc_dashboard)
  time            Sleep in poll loop              (pcd_state)
  urllib.request  GitHub bootstrap                (pc_dashboard)
  urllib.error    GitHub bootstrap                (pc_dashboard)
  winreg          Registry fallback read          (pcd_controls — Win only)

To add a new PyPI dependency: append a tuple to REQUIRED_PACKAGES.
"""

import importlib
import subprocess
import sys


# Each tuple is (import_name, pip_name, why_we_need_it).
#
# import_name = what `import X` would say in the code that uses it
# pip_name    = what `pip install Y` would say (often identical to import_name)
# why         = human-readable rationale, shown in the install log
REQUIRED_PACKAGES = [

    # ─── Web framework ───
    # Hosts every / and /api/* route. Without this, pc_dashboard cannot start.
    # Imports found in: pcd_state.py (Flask), pcd_api.py + pcd_chat.py
    # (jsonify/request), pc_dashboard.py (render_template_string).
    ("flask", "flask",
     "Web server: hosts the dashboard UI + REST API. Hard requirement."),

    # ─── Cloud AI ───
    # Used by the floating chat panel (claude-opus-4-7). pcd_chat.py imports
    # this inside try/except ModuleNotFoundError, so its absence isn't fatal —
    # /api/chat/status will report sdk_installed=false and the chat panel
    # shows an actionable error. We install it anyway because chat is a
    # headline feature.
    ("anthropic", "anthropic",
     "Cloud Claude SDK (claude-opus-4-7). Powers /api/chat and the floating "
     "AI assistant panel."),

    # ─── Local AI (Ollama HTTP client) ───
    # You already have Ollama installed and running on 127.0.0.1:11434 with
    # 8 local models. This is the Python wrapper for that HTTP API. Not yet
    # wired into pc_dashboard.py — added here so it's ready the moment we
    # add a local-LLM chat option without needing another install step.
    # If you decide you don't want it, remove this tuple and it will neither
    # be required nor installed.
    ("ollama", "ollama",
     "Local LLM client — talks to the Ollama daemon at 127.0.0.1:11434. "
     "Available for use; not yet imported by any helper."),
]


def _pip_install(pip_name: str) -> tuple[bool, str]:
    """Run `<python> -m pip install <pip_name>` and return (ok, error_text)."""
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pip", "install",
             "--disable-pip-version-check", "--quiet", pip_name],
            capture_output=True, text=True, timeout=180,
        )
    except FileNotFoundError:
        return False, "pip is not available in this Python environment"
    except subprocess.TimeoutExpired:
        return False, "install timed out after 180 s — check network"
    except Exception as e:
        return False, repr(e)
    if r.returncode == 0:
        return True, ""
    return False, (r.stderr or r.stdout or "unknown pip error").strip()[:300]


def ensure_packages(packages: list | None = None) -> dict:
    """Check each entry in REQUIRED_PACKAGES (or `packages` if given) and
    pip-install anything that isn't importable.

    Returns a small summary dict: {installed, skipped, failed} for logging.
    Never raises — if pip itself can't be invoked, this returns with failures
    listed and the caller carries on. The next import in pc_dashboard.py
    will surface the real problem if the package was actually required.
    """
    pkgs = packages if packages is not None else REQUIRED_PACKAGES
    print("[deps] checking Python packages used by pc_dashboard ...")
    print(f"[deps]   interpreter: {sys.executable}")
    print(f"[deps]   checking {len(pkgs)} third-party packages "
          f"(stdlib modules don't need installation)")

    installed: list[str] = []
    skipped:   list[str] = []
    failed:    list[tuple[str, str]] = []

    for import_name, pip_name, why in pkgs:
        try:
            importlib.import_module(import_name)
            skipped.append(import_name)
        except ImportError:
            print(f"[deps]   {import_name}: missing — installing {pip_name}  ({why})")
            ok, err = _pip_install(pip_name)
            if not ok:
                failed.append((pip_name, err))
                print(f"[deps]     FAILED: {err}")
                continue
            importlib.invalidate_caches()
            try:
                importlib.import_module(import_name)
                installed.append(pip_name)
                print(f"[deps]     installed {pip_name}")
            except ImportError as e:
                failed.append((pip_name, f"installed but still not importable: {e}"))
                print(f"[deps]     installed but cannot import: {e}")

    if skipped:
        print(f"[deps]   already present: {', '.join(skipped)}")
    if installed:
        print(f"[deps]   newly installed: {', '.join(installed)}")
    if failed:
        print(f"[deps]   failed: {len(failed)} package(s)")
        for name, err in failed:
            print(f"[deps]     - {name}: {err}")

    return {"installed": installed, "skipped": skipped, "failed": failed}
