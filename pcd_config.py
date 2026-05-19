"""
pcd_config.py — central constants for pc_dashboard.

Pure data — no project imports. Holds Windows GUID values that are stable
across versions, OEM vendor tokens used by WMI discovery, the chat system
prompt, and a few network/refresh knobs.
"""

import re

# ─── network + cadence ───
REFRESH_S = 2
HOST = "127.0.0.1"
PORT = 5000

# ─── Claude integration ───
ANTHROPIC_MODEL = "claude-opus-4-7"

# ─── Scheduled-Task name registered by --install-no-uac ───
TASK_NAME = "ThermalDashboard"

# ─── powercfg sub-GUIDs (stable on Windows) ───
SUB_PROCESSOR    = "54533251-82be-4824-96c1-47b60b740d00"
PROCTHROTTLEMAX  = "bc5038f7-23e0-4960-96da-33abaf5935ec"   # max processor state
PROCTHROTTLEMIN  = "893dee8e-2bef-41e0-89c6-b55d0929964c"   # min processor state
PERFBOOSTMODE    = "be337238-0d82-4146-a960-4f3749d470c7"   # processor boost mode
SYSCOOLPOL       = "94d3a615-a899-4ac5-ae2b-e4d8f634367f"   # system cooling policy

# ─── Win11 Power Mode overlay scheme GUIDs (Microsoft-defined) ───
OVERLAY_GUIDS = {
    "best-efficiency":  "961cc777-2547-4f9d-8174-7d86181b8a7a",
    "balanced":         "00000000-0000-0000-0000-000000000000",
    "best-performance": "ded574b5-45a0-4f42-8737-46345c09c238",
}

GUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)

# Human-readable names for the processor sub-setting GUIDs, used in log lines.
_PROC_SETTING_NAMES = {
    SYSCOOLPOL: "System Cooling Policy",
    PERFBOOSTMODE: "Turbo Boost Mode",
    PROCTHROTTLEMAX: "CPU Max State %",
    PROCTHROTTLEMIN: "CPU Min State %",
}


def proc_setting_name(guid: str) -> str:
    return _PROC_SETTING_NAMES.get(guid.lower(), f"<setting {guid[:8]}>")


# ─── Win32_Battery.BatteryStatus codes ───
BATTERY_STATUS_NAMES = {
    1: "Discharging", 2: "On AC", 3: "Fully charged", 4: "Low",
    5: "Critical", 6: "Charging", 7: "Charging/high", 8: "Charging/low",
    9: "Charging/critical", 10: "Undefined", 11: "Partially charged",
}

# ─── OEM WMI discovery ───
# Any namespace whose name contains one of these tokens is scanned at startup.
OEM_NAMESPACE_TOKENS = (
    "HP", "Hewlett", "Dell", "Lenovo", "Asus", "AsusAtk", "MSI", "Acer",
    "Razer", "Toshiba", "Sony", "Vaio", "Samsung", "Panasonic", "Fujitsu",
    "Gigabyte", "Aorus", "Clevo", "InstrumentedBIOS", "OEM",
)
# Class-name prefixes / patterns to surface as sensors regardless of namespace.
OEM_CLASS_PATTERN = (
    r"^(HP_|Dell|Lenovo_|Asus|MSI_|Acer|Razer|Sony|Samsung|Gigabyte|OEM_)"
    r".*(Fan|Thermal|Cool|Temp|Sensor|Rpm)"
)
GENERIC_CLASS_PATTERN = r"^(Fan|Cooling|Sensor|TemperatureProbe)$"


# ─── Claude system prompt ───
CHAT_SYSTEM_PROMPT = """You are an AI assistant embedded in a live Windows PC system dashboard.

The dashboard already shows the user real-time temperatures, GPU info, battery state, and
active control settings. Your job is to answer questions about the PC's state and to make
changes when asked, using the tools available to you.

Available actions (via tools):
- Read full PC state: temperatures, GPU, storage, battery, CPU performance, controls.
- Switch Windows Power Plans (list_power_plans → set_power_plan).
- Set the Windows 11 Power Mode overlay: best-efficiency / balanced / best-performance.
- Set the System Cooling Policy: Passive (quiet — CPU throttles before fans) or Active (fans first).
- Set the Processor Turbo Boost mode (0=Disabled .. 5=Aggressive at guaranteed).
- Set CPU Max % (30–100) and CPU Min % (5–100) performance state.
- Set NVIDIA GPU power limit in watts.
- Apply quick presets: 'quiet', 'balanced', or 'performance' (changes several settings at once).

Workflow:
1. Call get_pc_state FIRST for any non-trivial question — temperatures and the user's current
   power settings are essential context. Skip this only for purely conversational replies.
2. Decide the smallest set of changes that solves the request. For "make it quieter" or
   "reduce noise", apply_preset('quiet') is usually best. For "boost performance",
   apply_preset('performance') or set_power_mode('best-performance').
3. Briefly explain what you changed and why — one or two sentences. The user can see the
   numbers update on the dashboard, so don't repeat them.

Safety:
- The BIOS still enforces a minimum cooling floor — none of these settings can damage the hardware.
- If a tool returns an error string, surface it; do not silently retry.
- If the user has a managed (corporate) machine and a tool fails because of permissions,
   say so — many controls require Administrator.
- When the user asks about absolute values (a specific temperature, exact RPM, etc.),
   read get_pc_state and quote what it says. Don't make up numbers.
"""
