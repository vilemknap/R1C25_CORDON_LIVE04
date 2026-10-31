"""Read-only DIAGFAST entry. Execute only on a separate saved 2025 model copy.
No COM on import; never attaches to another instance. No TG/TD, assignment or APPLY.
"""
from pathlib import Path
import importlib.util
FAST_OPTIONS={'fast_geometry_page_size':256,'fast_parent_page_size':256}

def main():
    filename=globals().get('__file__') or main.__code__.co_filename
    source=Path(filename).resolve()
    if not source.is_file():raise RuntimeError('SCRIPT_FILENAME_MISSING_USE_EXECUTE_SCRIPT_FILE')
    root=source.parent
    spec=importlib.util.spec_from_file_location('_cordon_diagfast_bootstrap',root/'cordon_diagfast_bootstrap.py')
    boot=importlib.util.module_from_spec(spec);spec.loader.exec_module(boot)
    return boot.launch(globals(),root,action='CAPTURE_DIAGNOSTICS',backend='PARITY_AUDIT',repetitions=3,page_sizes=(256,512,1024))

if __name__ in ('__main__','builtins'):
    RESULT=main()
