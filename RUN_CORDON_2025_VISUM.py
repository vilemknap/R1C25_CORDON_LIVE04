"""PTV Visum Scripts > Execute script file: read-only startup checks.

Does not run assignment/TG/TD or change network/demand. Once PREFLIGHT passes,
use RUN_CORDON_2025_CAPTURE.py to capture real saved routes and diagnostics.
"""
from pathlib import Path
import importlib.util


def main():
    filename=globals().get('__file__') or main.__code__.co_filename
    source=Path(filename).resolve()
    if not source.is_file():
        raise RuntimeError('SCRIPT_FILENAME_MISSING_USE_EXECUTE_SCRIPT_FILE')
    root=source.parent
    spec=importlib.util.spec_from_file_location('_cordon_visum_bootstrap', root/'cordon_visum_bootstrap.py')
    boot=importlib.util.module_from_spec(spec);spec.loader.exec_module(boot)
    return boot.launch(globals(),root,action='PREFLIGHT')


if __name__ in ('__main__','builtins'):
    RESULT=main()
