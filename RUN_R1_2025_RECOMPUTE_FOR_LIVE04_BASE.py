r"""Run from Visum Scripts -> Execute script file.

TRANSFER2025 alternative to step 2 - for a 2025 copy whose calibrated coefficients are
ALREADY in place (no 2022 export, no parameter import, no parameter write).
Open the 2025 copy (file name contains 2025 and LIVE04/KOPIE/COPY/TEST/TRIAL/CALIB, not 2022).
Checks the 32 cordon station links, recomputes once with the v7 LONG post-TD mask (this also
creates the assignment paths), verifies that no procedure changed zone coefficients / TD b/c /
ADDVAL1, saves a NEW version <copy>_LIVE04_BASE_<id>.ver and runs the LIVE04 readiness check.
Never LoadVersion, never overwrites the open .ver.
"""
from pathlib import Path
import importlib.util


def main(namespace=None):
    root=Path(__file__).resolve().parent
    spec=importlib.util.spec_from_file_location('_r1_transfer_bootstrap',root/'cordon_transfer_bootstrap.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.launch(globals() if namespace is None else namespace,'RECOMPUTE',root=root)


if __name__=='__main__':
    main(globals())
