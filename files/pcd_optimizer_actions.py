"""
pcd_optimizer_actions.py — single-action dispatcher.

Extracted from pcd_optimizer.py. Provides:
    _apply_one_action(action) -> dict

Each "action" is a dict {"name": ..., "args": {...}} that Claude returned.
This module validates the args, calls into the appropriate helper
(pcd_controls for power-mode toggles, pcd_fixer for service changes),
and returns a structured record.

The orchestrator-level _apply_decision (which handles per-cycle anti-thrash
state) lives in pcd_optimizer.py because it reads the optimizer's globals.
"""

from pcd_log import logger


def _apply_one_action(action: dict) -> dict:
    """Execute a single validated action via internal helpers. Returns
    {action, args, ok, error|None, ...detail}. Never raises."""
    # Imports are lazy so this module is cheap to load and doesn't drag in
    # the entire controls stack until an action actually fires.
    from pcd_config import (
        OVERLAY_GUIDS, PERFBOOSTMODE, PROCTHROTTLEMAX, PROCTHROTTLEMIN, SYSCOOLPOL,
    )
    from pcd_controls import (
        _apply_proc_value, _set_gpu_power, read_gpu_power_info, set_power_overlay_api,
    )
    from pcd_state import _refresh_state_controls

    name = action.get("name", "")
    args = action.get("args", {}) or {}
    record = {"action": name, "args": args, "ok": False, "error": None}

    try:
        if name == "noop":
            record["ok"] = True
            return record

        if name == "apply_preset":
            target = (args.get("name") or "").lower()
            if target not in ("quiet", "balanced", "performance"):
                record["error"] = f"unknown preset {target!r}"
                return record
            gpu = read_gpu_power_info()
            errs = []
            def step(ok, err):
                if not ok and err:
                    errs.append(err)
            if target == "quiet":
                step(*_apply_proc_value(SYSCOOLPOL, 0))
                step(*_apply_proc_value(PERFBOOSTMODE, 0))
                step(*_apply_proc_value(PROCTHROTTLEMAX, 80))
                if gpu and gpu.get("min_w"):
                    step(*_set_gpu_power(int(gpu["min_w"])))
                step(*set_power_overlay_api(OVERLAY_GUIDS["best-efficiency"]))
            elif target == "balanced":
                step(*_apply_proc_value(SYSCOOLPOL, 1))
                step(*_apply_proc_value(PERFBOOSTMODE, 2))
                step(*_apply_proc_value(PROCTHROTTLEMAX, 100))
                if gpu and gpu.get("default_w"):
                    step(*_set_gpu_power(int(gpu["default_w"])))
                step(*set_power_overlay_api(OVERLAY_GUIDS["balanced"]))
            else:  # performance
                step(*_apply_proc_value(SYSCOOLPOL, 1))
                step(*_apply_proc_value(PERFBOOSTMODE, 2))
                step(*_apply_proc_value(PROCTHROTTLEMAX, 100))
                step(*_apply_proc_value(PROCTHROTTLEMIN, 100))
                if gpu and gpu.get("max_w"):
                    step(*_set_gpu_power(int(gpu["max_w"])))
                step(*set_power_overlay_api(OVERLAY_GUIDS["best-performance"]))
            record["ok"] = not errs
            if errs:
                record["error"] = "; ".join(errs)[:200]
            return record

        if name == "set_power_mode":
            mode = (args.get("mode") or "").lower()
            if mode not in OVERLAY_GUIDS:
                record["error"] = f"unknown power mode {mode!r}"
                return record
            ok, err = set_power_overlay_api(OVERLAY_GUIDS[mode])
            record["ok"] = ok
            record["error"] = err
            return record

        if name == "set_cooling":
            val = args.get("value")
            if val not in (0, 1):
                record["error"] = "set_cooling.value must be 0 or 1"
                return record
            ok, err = _apply_proc_value(SYSCOOLPOL, val)
            record["ok"] = ok
            record["error"] = err
            return record

        if name == "set_turbo":
            mode = args.get("mode")
            if not isinstance(mode, int) or not 0 <= mode <= 5:
                record["error"] = "set_turbo.mode must be int 0..5"
                return record
            ok, err = _apply_proc_value(PERFBOOSTMODE, mode)
            record["ok"] = ok
            record["error"] = err
            return record

        if name == "set_cpu_max":
            p = args.get("percent")
            if not isinstance(p, int) or not 30 <= p <= 100:
                record["error"] = "set_cpu_max.percent must be int 30..100"
                return record
            ok, err = _apply_proc_value(PROCTHROTTLEMAX, p)
            record["ok"] = ok
            record["error"] = err
            return record

        if name == "set_cpu_min":
            p = args.get("percent")
            if not isinstance(p, int) or not 5 <= p <= 100:
                record["error"] = "set_cpu_min.percent must be int 5..100"
                return record
            ok, err = _apply_proc_value(PROCTHROTTLEMIN, p)
            record["ok"] = ok
            record["error"] = err
            return record

        # ─── System-fix actions (tier-protected, see pcd_fixer.py) ───
        if name == "disable_service":
            from pcd_fixer import disable_service
            svc = (args.get("name") or "").strip()
            if not svc:
                record["error"] = "disable_service.name required"
                return record
            fix = disable_service(svc)
            record["ok"] = fix["ok"]
            record["error"] = fix.get("error")
            record["fix_record"] = fix
            return record

        if name == "set_service_manual":
            from pcd_fixer import set_service_manual
            svc = (args.get("name") or "").strip()
            if not svc:
                record["error"] = "set_service_manual.name required"
                return record
            fix = set_service_manual(svc)
            record["ok"] = fix["ok"]
            record["error"] = fix.get("error")
            record["fix_record"] = fix
            return record

        if name == "report_only":
            from pcd_fixer import report_only
            fix = report_only(args.get("message", ""))
            record["ok"] = fix["ok"]
            record["fix_record"] = fix
            return record

        record["error"] = f"unknown action name: {name!r}"
        return record

    except Exception as e:
        record["error"] = f"{type(e).__name__}: {e}"[:200]
        return record
    finally:
        try:
            _refresh_state_controls()
        except Exception:
            pass
