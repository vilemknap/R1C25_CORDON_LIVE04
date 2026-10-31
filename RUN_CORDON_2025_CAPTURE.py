"""Read-only full saved-path capture from the injected 2025 Visum session.

Uses 15A2 bounded COM lists and original TwoModeRouteCollector. Never computes
replacement routes, runs assignment, saves/loads a version or alters matrices.
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
    return boot.launch(globals(),root,action='CAPTURE_DIAGNOSTICS')


if __name__ in ('__main__','builtins'):
    RESULT=main()
