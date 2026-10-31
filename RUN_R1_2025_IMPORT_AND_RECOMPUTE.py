r"""Run from Visum Scripts -> Execute script file.

TRANSFER2025 step 2 - IMPORT into an ISOLATED COPY of the 2025 model.
Open the 2025 copy (file name contains LIVE04/KOPIE/COPY/TEST/TRIAL/CALIB, not 2022).
Takes the newest export (or TRANSFER_2025_CONFIG.json -> parameter_file), writes the
planned zone coefficients / TD b/c / ADDVAL1 with readback, recomputes once with the
v7 LONG post-TD mask, saves a NEW version <copy>_LIVE04_BASE_<id>.ver and runs the
LIVE04 readiness check.  Never LoadVersion, never overwrites the open .ver.
"""
from pathlib import Path
import importlib.util


def main(namespace=None):
    root=Path(__file__).resolve().parent
    spec=importlib.util.spec_from_file_location('_r1_transfer_bootstrap',root/'cordon_transfer_bootstrap.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.launch(globals() if namespace is None else namespace,'IMPORT',root=root)


if __name__=='__main__':
    main(globals())
