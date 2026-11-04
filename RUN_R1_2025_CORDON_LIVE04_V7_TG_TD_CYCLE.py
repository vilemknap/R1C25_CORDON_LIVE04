"""Run from Visum Scripts -> Execute script file.

LIVE04: the LIVE03 joint TG/TD cordon calibration ported onto the v7 profile
calibrator (vilemknap/R1_15A2_V24917_v7 @ 977cef4, P2.5/A4).  Use an ISOLATED
COPY of R1 2025 (the opened .ver file name must contain LIVE04/KOPIE/COPY/TEST/
TRIAL/CALIB) whose LONG demand is already masked by v7 (>= 80 km on 9697).
Per cycle: GENERATION (v7 GENFIX2 STEP1: role envelopes P 0.75-2.5 / A 0.75-4.0,
MOBILITY2 + MOBILITYZONE1, BDPA1, native demand prediction on frozen paths),
then TD_CORDON (gravity b/c, cordon objective, IDP guard).  Every native
recompute runs the v7 LONG post-TD mask.  Writes only TG zone attributes, TD
b/c and the LONG mask matrices 9111-9115/9291-9295; keeps the last ACCEPTED
state (or the restored baseline).  The source .ver is never overwritten; an
accepted state is saved as a NEW .ver.
"""
from pathlib import Path
import importlib.util


def main(namespace=None):
    root=Path(__file__).resolve().parent
    spec=importlib.util.spec_from_file_location('_r1_live04_bootstrap',root/'cordon_live04_bootstrap.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.launch(globals() if namespace is None else namespace,root=root)


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
