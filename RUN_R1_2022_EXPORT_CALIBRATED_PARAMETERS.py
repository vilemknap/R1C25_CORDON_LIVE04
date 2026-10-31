r"""Run from Visum Scripts -> Execute script file.

TRANSFER2025 step 1 - EXPORT (read-only).
Open the CALIBRATED 2022 version (last accepted state of the v7 profile calibration).
Writes R1_2022_CALIBRATED_PARAMETERS.json (zone coefficients, TD b/c, ADDVAL1) to
%LOCALAPPDATA%\R1C25_TRANSFER2025\EXPORT_<id>\.  No model write at all.
"""
from pathlib import Path
import importlib.util


def main(namespace=None):
    root=Path(__file__).resolve().parent
    spec=importlib.util.spec_from_file_location('_r1_transfer_bootstrap',root/'cordon_transfer_bootstrap.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.launch(globals() if namespace is None else namespace,'EXPORT',root=root)


if __name__=='__main__':
    main(globals())
