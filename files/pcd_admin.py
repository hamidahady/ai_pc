"""
pcd_admin.py — admin detection, UAC self-elevation, Scheduled Task install.
"""

import ctypes
import os
import sys
from pathlib import Path

from pcd_config import HOST, PORT, TASK_NAME
from pcd_log import logger
from pcd_shell import ps_full

import pcd_state


def is_admin() -> bool:
    if sys.platform != "win32":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def try_elevate(extra_args: list[str]) -> bool:
    if sys.platform != "win32":
        return False
    script = sys.argv[0]
    params = " ".join(f'"{a}"' for a in [script, *sys.argv[1:], *extra_args])
    ret = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, params, None, 1
    )
    return ret > 32


def install_no_uac_task() -> int:
    if not pcd_state.IS_ADMIN:
        print("Need admin to register the scheduled task. Requesting UAC ...")
        if try_elevate(["--install-no-uac", "--no-elevate"]):
            print("  Elevated installer started.")
            return 0
        print("  Elevation declined.")
        return 1

    py = sys.executable
    script = str(Path(__file__).resolve().parent.parent / "pc_dashboard.py")
    workdir = str(Path(script).parent)
    user_id = f"{os.environ.get('USERDOMAIN', '')}\\{os.environ.get('USERNAME', '')}".strip("\\")

    ps_cmd = (
        f"$action = New-ScheduledTaskAction -Execute '{py}' "
        f"-Argument '\"{script}\" --no-elevate' -WorkingDirectory '{workdir}'; "
        f"$principal = New-ScheduledTaskPrincipal -UserId '{user_id}' "
        f"-LogonType Interactive -RunLevel Highest; "
        f"$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries "
        f"-DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero); "
        f"Register-ScheduledTask -TaskName '{TASK_NAME}' -Action $action "
        f"-Principal $principal -Settings $settings -Force | Out-Null"
    )
    rc, _, err = ps_full(ps_cmd, timeout=30)
    if rc != 0:
        print(f"Failed to register task: {err}")
        return 1
    print(f"Scheduled task '{TASK_NAME}' registered (runs elevated, no UAC).")

    bat_path = Path(workdir) / "run_dashboard.bat"
    bat_path.write_text(
        "@echo off\r\n"
        f'schtasks /run /tn "{TASK_NAME}" >nul 2>&1\r\n'
        "if errorlevel 1 (\r\n"
        '  echo Could not start the scheduled task.\r\n'
        f'  echo   python "{script}" --install-no-uac\r\n'
        "  pause\r\n"
        "  exit /b 1\r\n"
        ")\r\n"
        "echo Dashboard starting...\r\n"
        "timeout /t 2 >nul\r\n"
        f'start "" "http://{HOST}:{PORT}"\r\n',
        encoding="ascii",
    )
    print(f"Launcher written: {bat_path}")
    return 0


def uninstall_no_uac_task() -> int:
    if not pcd_state.IS_ADMIN:
        if try_elevate(["--uninstall-no-uac", "--no-elevate"]):
            return 0
        return 1
    rc, _, err = ps_full(
        f"Unregister-ScheduledTask -TaskName '{TASK_NAME}' -Confirm:$false", timeout=15
    )
    if rc != 0:
        print(f"Failed: {err}")
        return 1
    print(f"Scheduled task '{TASK_NAME}' removed.")
    bat_path = Path(__file__).resolve().parent.parent / "run_dashboard.bat"
    if bat_path.exists():
        bat_path.unlink()
    return 0
