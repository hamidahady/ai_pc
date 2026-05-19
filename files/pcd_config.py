"""
pcd_config.py — central constants for pc_dashboard. Pure data, no project imports.
"""

import re

REFRESH_S = 2
HOST = "127.0.0.1"
PORT = 5000

ANTHROPIC_MODEL = "claude-opus-4-7"
TASK_NAME = "ThermalDashboard"

SUB_PROCESSOR    = "54533251-82be-4824-96c1-47b60b740d00"
PROCTHROTTLEMAX  = "bc5038f7-23e0-4960-96da-33abaf5935ec"
PROCTHROTTLEMIN  = "893dee8e-2bef-41e0-89c6-b55d0929964c"
PERFBOOSTMODE    = "be337238-0d82-4146-a960-4f3749d470c7"
SYSCOOLPOL       = "94d3a615-a899-4ac5-ae2b-e4d8f634367f"

OVERLAY_GUIDS = {
    "best-efficiency":  "961cc777-2547-4f9d-8174-7d86181b8a7a",
    "balanced":         "00000000-0000-0000-0000-000000000000",
    "best-performance": "ded574b5-45a0-4f42-8737-46345c09c238",
}

GUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)

_PROC_SETTING_NAMES = {
    SYSCOOLPOL: "System Cooling Policy",
    PERFBOOSTMODE: "Turbo Boost Mode",
    PROCTHROTTLEMAX: "CPU Max State %",
    PROCTHROTTLEMIN: "CPU Min State %",
}


def proc_setting_name(guid: str) -> str:
    return _PROC_SETTING_NAMES.get(guid.lower(), f"<setting {guid[:8]}>")


BATTERY_STATUS_NAMES = {
    1: "Discharging", 2: "On AC", 3: "Fully charged", 4: "Low",
    5: "Critical", 6: "Charging", 7: "Charging/high", 8: "Charging/low",
    9: "Charging/critical", 10: "Undefined", 11: "Partially charged",
}

OEM_NAMESPACE_TOKENS = (
    "HP", "Hewlett", "Dell", "Lenovo", "Asus", "AsusAtk", "MSI", "Acer",
    "Razer", "Toshiba", "Sony", "Vaio", "Samsung", "Panasonic", "Fujitsu",
    "Gigabyte", "Aorus", "Clevo", "InstrumentedBIOS", "OEM",
)
OEM_CLASS_PATTERN = (
    r"^(HP_|Dell|Lenovo_|Asus|MSI_|Acer|Razer|Sony|Samsung|Gigabyte|OEM_)"
    r".*(Fan|Thermal|Cool|Temp|Sensor|Rpm)"
)
GENERIC_CLASS_PATTERN = r"^(Fan|Cooling|Sensor|TemperatureProbe)$"


CHAT_SYSTEM_PROMPT = """You are an AI assistant embedded in a live Windows PC system dashboard.

The dashboard already shows the user real-time temperatures, GPU info, battery state, and
active control settings. Your job is to answer questions about the PC's state and to make
changes when asked, using the tools available to you.

Available actions (via tools):
- Read full PC state: temperatures, GPU, storage, battery, CPU performance, controls.
- Switch Windows Power Plans (list_power_plans -> set_power_plan).
- Set the Windows 11 Power Mode overlay: best-efficiency / balanced / best-performance.
- Set the System Cooling Policy: Passive (quiet) or Active (fans first).
- Set the Processor Turbo Boost mode (0=Disabled .. 5=Aggressive at guaranteed).
- Set CPU Max % (30-100) and CPU Min % (5-100) performance state.
- Set NVIDIA GPU power limit in watts.
- Apply quick presets: 'quiet', 'balanced', or 'performance'.

Workflow:
1. Call get_pc_state FIRST for any non-trivial question.
2. Decide the smallest set of changes that solves the request.
3. Briefly explain what you changed and why - one or two sentences.

Safety:
- The BIOS still enforces a minimum cooling floor.
- If a tool returns an error string, surface it; do not silently retry.
- If the user has a managed (corporate) machine and a tool fails because of permissions, say so.
"""
