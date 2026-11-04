"""Run from Visum Scripts -> Execute script file.

LIVE04.8: CONTINUE a previous LIVE04 cordon run.  First open in Visum a .ver that
a LIVE04 run saved:

* a checkpoint  <run>/CHECKPOINTS/..._LIVE04_CKPT_C<cycle>_<block>_<hash>.ver
  (written after every block that accepted a change), or
* the saved accepted state  <run>/..._LIVE04_ACCEPTED_<hash>.ver
  (written at the end of a run or at a verified stop - STOP_REQUESTED).

The run proves the opened file is byte-identical to the saved one, takes the
run-start anchors (generation coefficient reference, ADDVAL1 run-start values)
of the ORIGINAL run, and continues at the interrupted cycle and block.
Everything else is exactly RUN_R1_2025_CORDON_LIVE04_V7_TG_TD_CYCLE.py.
"""
from pathlib import Path
import importlib.util


def main(namespace=None):
    root=Path(__file__).resolve().parent
    spec=importlib.util.spec_from_file_location('_r1_live04_bootstrap',root/'cordon_live04_bootstrap.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.launch(globals() if namespace is None else namespace,root=root,continuation=True)


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
