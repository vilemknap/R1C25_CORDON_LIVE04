"""Run from Visum Scripts -> Execute script file.

LIVE02: first real TG cycle on an ISOLATED COPY of R1 2025 (the opened .ver file
name must contain LIVE02/KOPIE/COPY/TEST/TRIAL/CALIB).  Writes only the 9 TG zone
attributes, recomputes natively, evaluates the whole cordon matrix and keeps the
model in the last ACCEPTED state (or the restored baseline).  The source .ver is
never overwritten; an accepted state is saved as a NEW .ver in the run folder.
"""
from pathlib import Path
import importlib.util


def main(namespace=None):
    root=Path(__file__).resolve().parent
    spec=importlib.util.spec_from_file_location('_r1_live02_bootstrap',root/'cordon_live02_bootstrap.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.launch(globals() if namespace is None else namespace,root=root)


if __name__=='__main__':
    main(globals())
