"""Run from Visum Scripts -> Execute script file.

LIVE04: the LIVE03 joint TG/TD cordon calibration ported onto the v7 profile
calibrator (vilemknap/R1_15A2_V24917_v7 @ 977cef4, P2.5/A4).  Use an ISOLATED
COPY of R1 2025 (the opened .ver file name must contain LIVE04/KOPIE/COPY/TEST/
TRIAL/CALIB) whose LONG demand is already masked by v7 (>= 80 km on 9697).
Per cycle: GENERATION (v7 GENFIX2 STEP1: role envelopes P 0.75-2.5 / A 0.75-4.0,
MOBILITY2 + MOBILITYZONE1, BDPA1, native demand prediction on frozen paths),
then TD_CORDON (gravity b/c, cordon objective, IDP guard).  Every native
recompute runs the v7 LONG post-TD mask.  Writes only TG zone attributes, TD
b/c and the LONG mask matrices 9111-9115/9291-9295; keeps the last ACCEPTED
state (or the restored baseline).  The source .ver is never overwritten; an
accepted state is saved as a NEW .ver.
"""
from pathlib import Path
import importlib.util


def main(namespace=None):
    root=Path(__file__).resolve().parent
    spec=importlib.util.spec_from_file_location('_r1_live04_bootstrap',root/'cordon_live04_bootstrap.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.launch(globals() if namespace is None else namespace,root=root)


if __name__=='__main__':
    main(globals())
