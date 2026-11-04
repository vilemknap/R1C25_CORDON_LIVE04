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
    # LIVE04.8 silent entry: nothing may reach Visum's script output (each line would be an
    # "Information" box).  Any output / error of the launcher goes to
    # %LOCALAPPDATA%\R1C25_BOOT\LAST_LAUNCHER_OUTPUT.txt; the run result is in the boot/run folders.
    import io as _io, os as _os, sys as _sys, traceback as _tb
    _saved=(_sys.stdout,_sys.stderr);_buf=_io.StringIO();_sys.stdout=_sys.stderr=_buf
    try:
        main(globals())
    except BaseException:
        _buf.write(_tb.format_exc())
    finally:
        _sys.stdout,_sys.stderr=_saved
        try:
            _d=Path(_os.environ.get('LOCALAPPDATA') or Path.home())/'R1C25_BOOT';_d.mkdir(parents=True,exist_ok=True)
            (_d/'LAST_LAUNCHER_OUTPUT.txt').write_text(_buf.getvalue() or '(no output)\n',encoding='utf-8')
        except Exception:
            pass
