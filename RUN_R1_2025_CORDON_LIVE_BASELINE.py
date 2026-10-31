"""Run from Visum Scripts -> Execute script file. LIVE01: no model changes."""
from pathlib import Path
import importlib.util


def main(namespace=None):
    root=Path(__file__).resolve().parent
    spec=importlib.util.spec_from_file_location('_r1_live01_bootstrap',root/'cordon_live01_bootstrap.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.launch(globals() if namespace is None else namespace,root=root)


if __name__=='__main__':
    main(globals())
