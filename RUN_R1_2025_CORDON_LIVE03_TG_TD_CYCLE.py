"""Run from Visum Scripts -> Execute script file.

LIVE03: joint TG/TD cordon calibration on an ISOLATED COPY of R1 2025 (the opened
.ver file name must contain LIVE03/KOPIE/COPY/TEST/TRIAL/CALIB).
Observations = survey semantics (FIRST_LAST pairs on the Transit RPDI matrix +
C17 station margins, year bridge 1.0).  Per cycle: GENERATION (V24917 STEP1 with
native demand prediction on frozen paths), then TD_CORDON (gravity b/c, cordon
objective, IDP guard).  Writes only the TG zone attributes and the TD b/c,
recomputes natively, keeps the last ACCEPTED state (or the restored baseline).
The source .ver is never overwritten; an accepted state is saved as a NEW .ver.
"""
from pathlib import Path
import importlib.util


def main(namespace=None):
    root=Path(__file__).resolve().parent
    spec=importlib.util.spec_from_file_location('_r1_live03_bootstrap',root/'cordon_live03_bootstrap.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.launch(globals() if namespace is None else namespace,root=root)


if __name__=='__main__':
    main(globals())
