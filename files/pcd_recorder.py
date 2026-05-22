"""
pcd_recorder.py — optional long-running diagnostic recorder.

While ACTIVE, appends one human-readable line per sample to a file named
pc_status_YYYYMMDD_HHMMSS.txt next to pc_dashboard.py. Designed for leaving
the dashboard running for hours (e.g. overnight, to catch a hibernation
issue) and then handing the file to an AI for diagnosis.

This is SEPARATE from the always-on log_YYYYMMDD_HHMMSS.txt that pcd_log
writes. Both can be active simultaneously — they serve different purposes:

    log_*.txt        always present, captures every API call + PowerShell
                     write + tool call. Verbose.
    pc_status_*.txt  only when the user clicks "Start Recording", samples
                     the live state at the chosen interval. Compact, one
                     line per sample, easy to scan over hours of data.

API:
    start(interval_s) -> {ok, file, started_at} | {ok=False, error}
    stop()            -> {ok, file, samples, duration_s} | {ok=False, error}
    status()          -> {active, file, started_at, samples, interval_s, elapsed_s}
    maybe_sample()    -> called by poll_loop every 2 s; writes a row iff
                          recording is active AND interval has elapsed since
                          the previous write. No-op otherwise.
"""

import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import IO, Optional

from pcd_log import logger
from pcd_state import _lock, _state


# pc_status_*.txt sits next to pc_dashboard.py (same dir as log_*.txt).
RECORD_DIR = Path(__file__).resolve().parent.parent

DEFAULT_INTERVAL_S = 10.0  # one sample every 10 s by default — 8 h ≈ 2880 lines
MIN_INTERVAL_S = 1.0
MAX_INTERVAL_S = 300.0     # 5 min cap; below that the line would never write

# Module-level state guarded by _rec_lock. Renamed with rec_ prefix to avoid
# any chance of confusion with the dashboard's _lock / _state.
_rec_lock = threading.Lock()
_active: bool = False
_file: Optional[IO] = None
_file_path: Optional[Path] = None
_started_at: Optional[datetime] = None
_last_sample_t: float = 0.0
_sample_count: int = 0
_interval_s: float = DEFAULT_INTERVAL_S

# regex used to peel the ACPI zone code out of a counter path like
# \\Thermal Zone Information(_TZ.CPUZ)\Temperature   →   CPUZ
_ZONE_CODE_RE = re.compile(r"\(([^)]+)\)")
_TZ_PREFIX_RE = re.compile(r"^\\?_?TZ\.?", re.I)


def start(interval_s: float = DEFAULT_INTERVAL_S) -> dict:
    """Begin a new recording session. Idempotent — second call while already
    active returns ok=False with an error so the UI can show 'already running'."""
    global _active, _file, _file_path, _started_at
    global _last_sample_t, _sample_count, _interval_s
    interval_s = max(MIN_INTERVAL_S, min(MAX_INTERVAL_S, float(interval_s)))

    with _rec_lock:
        if _active:
            return {
                "ok": False,
                "error": f"Already recording to {_file_path.name if _file_path else '?'}",
            }
        _started_at = datetime.now()
        _file_path = RECORD_DIR / f"pc_status_{_started_at.strftime('%Y%m%d_%H%M%S')}.txt"
        try:
            _file = open(_file_path, "w", encoding="utf-8", buffering=1)
        except OSError as e:
            _file = None
            _file_path = None
            _started_at = None
            return {"ok": False, "error": f"Could not open {RECORD_DIR}: {e}"}

        _interval_s = interval_s
        _last_sample_t = 0.0
        _sample_count = 0
        _active = True

        # Header block — machine identity + format key.
        with _lock:
            sys_info = _state.get("system", {}) or {}
        host = sys_info.get("hostname", "?")
        mfg = sys_info.get("Manufacturer", "?")
        mdl = sys_info.get("Model") or sys_info.get("SystemFamily", "?")
        cpu = sys_info.get("cpu_Name", "?")

        _file.write(f"=== pc_status recording started at "
                    f"{_started_at.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        _file.write(f"host: {host}  ({mfg} · {mdl})\n")
        _file.write(f"cpu:  {cpu}\n")
        _file.write(f"sample_interval: {_interval_s:.1f}s\n")
        _file.write(
            "format (one line per sample, pipe-delimited sections):\n"
            "  <timestamp>\n"
            "  | T:<zone>=<°C> ...            ACPI thermal zones (CPUZ, GFXZ, SK1Z, BATZ, ...)\n"
            "  | CPU:load=<%> core_max=<%>   _Total + worst-single-core load + freq\n"
            "       core_avg=<%> perf=<%> freq=<MHz>\n"
            "  | MEM:used=<%> free=<MB>      committed-bytes %, available physical memory\n"
            "  | DISK:io=<%> r=<KB/s> w=<KB/s>  _Total physical-disk activity\n"
            "  | NET:in=<KB/s> out=<KB/s>    summed across non-loopback NICs\n"
            "  | PROC:<count>                total Windows process count\n"
            "  | GPU:<°C> <W> util=<%> fan=<%>  nvidia-smi: temp/power/util/fan/clocks\n"
            "       gclk=<MHz> mclk=<MHz>\n"
            "  | NVMe:<name>=<°C>(max=<°C>) ...  SMART reported per drive\n"
            "  | BAT:<%> <status> rt=<min> <°C>  charge / status / runtime / firmware temp\n"
            "  | PWR:plan=<n> mode=<o> cool=<P|A> turbo=<m>  active power settings\n"
            "       cpu=<min>-<max>% gpu=<W>/<max>[*locked]\n"
            "  | USR:idle=<h:m:s> ss=<on|off> mon=<on|off>(<count>)  user-presence signals\n"
            "       <logged_in|logged_out> user=<name>\n"
            "  | AWAKE:<DISPLAY|SYSTEM|EXECUTION|...>=<entry>;...  what powercfg /requests\n"
            "       says is keeping the system or display awake (empty = none)\n"
            "  | OPT:state=<x> changed=<a:b,c:d> conf=<high|medium|low> at=<ts>\n"
            "       Present ONLY on rows immediately after an optimizer decision\n"
            "       (pop-once semantics). Use `grep OPT:` to find every decision.\n"
            "  | OEM:<class>[<key>=<value> ...] ...  vendor (e.g. HP_BIOSSensor) data\n"
        )
        _file.write("-" * 88 + "\n")

        logger.info("RECORDER started → %s (interval %.1fs)", _file_path, _interval_s)
        return {
            "ok": True,
            "file": str(_file_path),
            "started_at": _started_at.strftime("%Y-%m-%d %H:%M:%S"),
            "interval_s": _interval_s,
        }


def stop() -> dict:
    """End the current recording session and close the file."""
    global _active, _file, _file_path, _started_at, _sample_count

    with _rec_lock:
        if not _active or _file is None:
            return {"ok": False, "error": "Not currently recording"}

        elapsed = (datetime.now() - _started_at).total_seconds() if _started_at else 0.0
        try:
            _file.write("-" * 88 + "\n")
            _file.write(f"=== pc_status recording stopped at "
                        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n")
            _file.write(f"samples: {_sample_count}, duration: {elapsed:.1f}s "
                        f"(~{elapsed/60:.1f} min)\n")
            _file.close()
        except Exception as e:
            logger.warning("RECORDER stop: error finalising file: %s", e)

        result = {
            "ok": True,
            "file": str(_file_path),
            "samples": _sample_count,
            "duration_s": elapsed,
        }
        logger.info(
            "RECORDER stopped → %s (%d samples, %.1fs / %.1f min)",
            _file_path, _sample_count, elapsed, elapsed / 60,
        )
        _active = False
        _file = None
        return result


def status() -> dict:
    """Snapshot of the recorder's state — used by /api/recorder/status."""
    with _rec_lock:
        elapsed = (datetime.now() - _started_at).total_seconds() if (_active and _started_at) else 0.0
        return {
            "active": _active,
            "file": str(_file_path) if _file_path else None,
            "filename": _file_path.name if _file_path else None,
            "started_at": _started_at.strftime("%Y-%m-%d %H:%M:%S") if _started_at else None,
            "samples": _sample_count,
            "interval_s": _interval_s,
            "elapsed_s": elapsed,
        }


def maybe_sample() -> None:
    """Hook called from poll_loop. Writes one row iff active AND enough time
    has elapsed since the previous row to satisfy the configured interval.
    Never raises — failures are logged but don't break the poll loop."""
    global _last_sample_t, _sample_count
    with _rec_lock:
        if not _active or _file is None:
            return
        now = time.time()
        if now - _last_sample_t < _interval_s:
            return
        _last_sample_t = now
        try:
            line = _format_sample()
            _file.write(line + "\n")
            _sample_count += 1
        except Exception as e:
            logger.warning("RECORDER write failed: %s", e)


# ─────────────────── sample formatter ───────────────────


def _format_sample() -> str:
    """Render one comprehensive row from the current _state.

    Format (single line, pipe-delimited sections — section prefix tells you
    what's inside so grep "MEM:" or "NET:" works):

        <ts> | T:<zone>=<°C> ... | CPU:<load>%/<core_max>%/<freq>MHz perf=<%>
              | MEM:<used%> (<avail>MB free) | DISK:<io%> r=<KB/s> w=<KB/s>
              | NET:in=<KB/s> out=<KB/s> | PROC:<count>
              | GPU:<name> <°C> <W> util=<%> fan=<%> gclk=<MHz> mclk=<MHz>
              | NVMe:<name>=<°C> ...
              | BAT:<%> <status> rt=<min> <°C>
              | PWR:plan=<name> mode=<overlay> cool=<P|A> turbo=<mode>
                   cpu=<min>-<max>% gpu=<W>/<limit>
              | OEM:<class>[<key>=<value> ...] ...
    """
    with _lock:
        sources = _state.get("sources", {}) or {}
        controls = _state.get("controls", {}) or {}

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    parts: list[str] = [ts]

    # --- T: thermal zones ---
    temp_parts = []
    for z in (sources.get("thermal_zones") or []):
        m = _ZONE_CODE_RE.search(z.get("name", ""))
        label = _TZ_PREFIX_RE.sub("", m.group(1)) if m else "z"
        v = z.get("value")
        if v is not None:
            temp_parts.append(f"{label.upper()}={v:.1f}")
    parts.append("T:" + (" ".join(temp_parts) if temp_parts else "?"))

    # --- CPU: load + per-core + freq ---
    cp = sources.get("cpu_proxy") or {}
    sl = sources.get("system_load") or {}
    cpu_bits = []
    if cp.get("util_pct") is not None:
        cpu_bits.append(f"load={cp['util_pct']:.0f}%")
    if sl.get("cpu_core_max_pct") is not None:
        cpu_bits.append(f"core_max={sl['cpu_core_max_pct']:.0f}%")
    if sl.get("cpu_core_avg_pct") is not None:
        cpu_bits.append(f"core_avg={sl['cpu_core_avg_pct']:.0f}%")
    if cp.get("perf_pct") is not None:
        cpu_bits.append(f"perf={cp['perf_pct']:.0f}%")
    if cp.get("freq_mhz") is not None:
        cpu_bits.append(f"freq={cp['freq_mhz']:.0f}MHz")
    parts.append("CPU:" + (" ".join(cpu_bits) if cpu_bits else "?"))

    # --- MEM: % committed + free MB ---
    mem_bits = []
    if sl.get("memory_pct") is not None:
        mem_bits.append(f"used={sl['memory_pct']:.0f}%")
    if sl.get("memory_avail_mb") is not None:
        mem_bits.append(f"free={sl['memory_avail_mb']:.0f}MB")
    parts.append("MEM:" + (" ".join(mem_bits) if mem_bits else "?"))

    # --- DISK: io% + read/write rates ---
    disk_bits = []
    if sl.get("disk_io_pct") is not None:
        disk_bits.append(f"io={sl['disk_io_pct']:.0f}%")
    if sl.get("disk_read_kbps") is not None:
        disk_bits.append(f"r={sl['disk_read_kbps']:.0f}KB/s")
    if sl.get("disk_write_kbps") is not None:
        disk_bits.append(f"w={sl['disk_write_kbps']:.0f}KB/s")
    parts.append("DISK:" + (" ".join(disk_bits) if disk_bits else "?"))

    # --- NET: in/out rates ---
    net_bits = []
    if sl.get("net_in_kbps") is not None:
        net_bits.append(f"in={sl['net_in_kbps']:.0f}KB/s")
    if sl.get("net_out_kbps") is not None:
        net_bits.append(f"out={sl['net_out_kbps']:.0f}KB/s")
    parts.append("NET:" + (" ".join(net_bits) if net_bits else "?"))

    # --- PROC: process count ---
    if sl.get("process_count") is not None:
        parts.append(f"PROC:{sl['process_count']}")

    # --- GPU: full nvidia-smi snapshot + clocks ---
    gpus = sources.get("nvidia") or []
    if gpus:
        g = gpus[0]
        gbits = []
        if g.get("temp_c") is not None:
            gbits.append(f"{g['temp_c']:.0f}°C")
        if g.get("power_w") is not None:
            gbits.append(f"{g['power_w']:.0f}W")
        if g.get("util_pct") is not None:
            gbits.append(f"util={g['util_pct']:.0f}%")
        if g.get("fan_pct") is not None:
            gbits.append(f"fan={g['fan_pct']:.0f}%")
        if g.get("clock_gr_mhz") is not None:
            gbits.append(f"gclk={g['clock_gr_mhz']:.0f}MHz")
        if g.get("clock_mem_mhz") is not None:
            gbits.append(f"mclk={g['clock_mem_mhz']:.0f}MHz")
        parts.append("GPU:" + " ".join(gbits) if gbits else "GPU:?")

    # --- NVMe: per-drive temps with short names ---
    stor = sources.get("storage") or []
    if stor:
        nvme_bits = []
        for d in stor:
            if d.get("temp_c") is None:
                continue
            # Use first word of drive name to keep things compact
            name = (d.get("name") or "?").split()[0][:18]
            piece = f"{name}={d['temp_c']:.0f}°C"
            if d.get("temp_max_c") is not None:
                piece += f"(max={d['temp_max_c']:.0f})"
            nvme_bits.append(piece)
        parts.append("NVMe:" + " ".join(nvme_bits) if nvme_bits else "NVMe:?")

    # --- BAT: charge + status + runtime + temp ---
    b = sources.get("battery") or {}
    if b:
        bbits = []
        if b.get("charge_pct") is not None:
            bbits.append(f"{b['charge_pct']:.0f}%")
        if b.get("status"):
            bbits.append(b["status"].replace(" ", "_"))
        if b.get("runtime_min") is not None:
            bbits.append(f"rt={b['runtime_min']:.0f}min")
        if b.get("temp_c") is not None:
            bbits.append(f"{b['temp_c']:.1f}°C")
        parts.append("BAT:" + " ".join(bbits) if bbits else "BAT:?")

    # --- PWR: active power settings + GPU power limit ---
    plan = next(
        (p.get("name") for p in (controls.get("power_plans") or []) if p.get("active")),
        "?",
    )
    overlay = controls.get("overlay") or "?"
    cool = {0: "P", 1: "A"}.get(controls.get("cooling_policy"), "?")
    turbo = {0: "Off", 1: "On", 2: "Agg", 3: "EffOn",
             4: "EffAgg", 5: "AggGuar"}.get(
        controls.get("turbo_boost"), str(controls.get("turbo_boost")))
    cpu_max = controls.get("cpu_max_pct")
    cpu_min = controls.get("cpu_min_pct")
    gpu_ctrl = controls.get("gpu") or {}
    pwr_bits = [
        f"plan={plan.replace(' ', '_')}",
        f"mode={overlay}",
        f"cool={cool}",
        f"turbo={turbo}",
        f"cpu={cpu_min if cpu_min is not None else '?'}-{cpu_max if cpu_max is not None else '?'}%",
    ]
    if gpu_ctrl.get("limit_w") is not None:
        gp = f"gpu={gpu_ctrl['limit_w']:.0f}W"
        if gpu_ctrl.get("max_w") is not None:
            gp += f"/{gpu_ctrl['max_w']:.0f}"
        if gpu_ctrl.get("limit_locked"):
            gp += "*locked"
        pwr_bits.append(gp)
    parts.append("PWR:" + " ".join(pwr_bits))

    # --- OPT: optimizer decision marker (only present on the sample written
    # right after an optimizer decision — pop-once semantics, so a long
    # recording has exactly one OPT: line per decision, making it trivial to
    # find decision boundaries with `grep "OPT:" pc_status_*.txt`) ---
    try:
        from pcd_optimizer import pop_decision_for_recorder
        od = pop_decision_for_recorder()
    except Exception:
        od = None
    if od:
        obits = []
        if od.get("state"):
            obits.append(f"state={od['state']}")
        if od.get("changes"):
            obits.append("changed=" + str(od["changes"]).replace(" ", "_"))
        if od.get("confidence"):
            obits.append(f"conf={od['confidence']}")
        if od.get("at"):
            obits.append(f"at={od['at'].replace(' ', '_')}")
        parts.append("OPT:" + " ".join(obits) if obits else "OPT:noop")

    # --- USR: user presence — idle time, screen saver, monitor, login state ---
    us = sources.get("user_session") or {}
    if us:
        ubits = []
        if us.get("idle_human"):
            ubits.append(f"idle={us['idle_human']}")
        if us.get("screen_saver_on") is not None:
            ubits.append(f"ss={'on' if us['screen_saver_on'] else 'off'}")
        if us.get("monitor_on") is not None:
            mon = "on" if us["monitor_on"] else "off"
            if us.get("monitor_count") is not None:
                mon += f"({us['monitor_count']})"
            ubits.append(f"mon={mon}")
        if us.get("user_logged_in") is not None:
            ubits.append("logged_in" if us["user_logged_in"] else "logged_out")
        if us.get("username"):
            ubits.append(f"user={us['username']}")
        if ubits:
            parts.append("USR:" + " ".join(ubits))

    # --- AWAKE: what powercfg /requests says is blocking sleep/screen-off ---
    pr = sources.get("power_requests") or {}
    if pr:
        awake_bits = []
        for cat in ("DISPLAY", "SYSTEM", "AWAYMODE", "EXECUTION", "PERFBOOST", "ACTIVELOCKSCREEN"):
            entries = pr.get(cat) or []
            if entries:
                # Compress entries (strip noise, take first ~3 per category)
                compact = ";".join(e.replace(" ", "_")[:60] for e in entries[:3])
                awake_bits.append(f"{cat}={compact}")
        parts.append("AWAKE:" + (" ".join(awake_bits) if awake_bits else "none"))

    # --- OEM: vendor sensor data (HP_BIOSSensor, etc.) ---
    oem = sources.get("oem") or []
    if oem:
        oem_chunks = []
        for h in oem:
            cls = h.get("class", "?")
            recs = h.get("records") or []
            # Take the first record's key/value pairs (most OEM classes have
            # one instance per sensor type). Collapse spaces to keep one-line.
            kv_strs = []
            for rec in recs[:3]:  # cap at 3 records per class to bound width
                for k, v in rec.items():
                    if k in ("Status",):  # skip noisy fields
                        continue
                    vs = str(v).strip().replace(" ", "_")
                    if vs and vs != "0" and len(vs) < 40:
                        kv_strs.append(f"{k}={vs}")
            if kv_strs:
                oem_chunks.append(f"{cls}[{' '.join(kv_strs[:8])}]")
        if oem_chunks:
            parts.append("OEM:" + " ".join(oem_chunks))

    return " | ".join(parts)
