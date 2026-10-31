r"""Run from Visum Scripts -> Execute script file.

TRANSFER2025 step 3 - READINESS (read-only).
Checks everything the LIVE04 cordon run needs on the open 2025 version (release pins,
model preflight, copy name, operations 17-20, matrix source types, masked LONG support,
mobility authority, optional parameter identity, cordon baseline capture).
"""
from pathlib import Path
import importlib.util


def main(namespace=None):
    root=Path(__file__).resolve().parent
    spec=importlib.util.spec_from_file_location('_r1_transfer_bootstrap',root/'cordon_transfer_bootstrap.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.launch(globals() if namespace is None else namespace,'READINESS',root=root)


if __name__=='__main__':
    main(globals())
