# -*- coding: utf-8 -*-
"""Visum entrypoint: original Aggressive V1 FIX1 + read-only COM retry.

Run THIS script inside the open PTV Visum 2026 session instead of the original
R1_15A2_AGGRESSIVE_TGTD_V1_FIX1.py.  All parent source/manifest files remain
unchanged and are checked by the original launcher before calibration.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ORIGINAL = HERE / "R1_15A2_AGGRESSIVE_TGTD_V1_FIX1.py"


def main():
    visum = globals().get("Visum")
    if visum is None:
        visum = globals().get("COM")
    if visum is None:
        raise RuntimeError("NO_INJECTED_VISUM: launch inside the already open Visum session")
    if getattr(sys, "_r1_15a2_calibration_busy", False):
        raise RuntimeError("ANOTHER_15A2_RUN_IS_ACTIVE")
    # Mirror the original launcher stale-module purge. Visum can keep the same
    # Python process across runs with different packages on sys.path.
    for name in list(sys.modules):
        if name.startswith("r1_15a2_"):
            del sys.modules[name]
    if not ORIGINAL.is_file():
        raise RuntimeError("ORIGINAL_AGGRESSIVE_FIX1_LAUNCHER_MISSING:" + str(ORIGINAL))

    # Import without Visum in the module's namespace so the original does not
    # autostart. This imports original sealed modules and its protective hooks.
    spec = importlib.util.spec_from_file_location("_r1_aggressive_fix1_sealed_entry", ORIGINAL)
    if spec is None or spec.loader is None:
        raise RuntimeError("ORIGINAL_AGGRESSIVE_FIX1_IMPORT_UNAVAILABLE")
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)

    import r1_15a2_com_busy_snapshot_hotfix_v1 as hotfix
    activation = hotfix.activate(launcher)
    if not activation["active"]:
        raise RuntimeError("COMBUSY_SNAPSHOT_HOTFIX_NOT_ACTIVE")
    # We never Dispatch/GetActiveObject or switch the model/session here.
    launcher.Visum = visum
    return launcher.main("FULL")


if __name__ == "__main__" or globals().get("Visum") is not None or globals().get("COM") is not None:
    main()
