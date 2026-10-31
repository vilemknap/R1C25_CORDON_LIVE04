"""Run outside Visum. Default action is a labelled synthetic aggressive demo."""
from pathlib import Path
import sys


def main(argv=None):
    if globals().get('Visum') is not None or globals().get('COM') is not None or getattr(sys,'_r1_15a2_calibration_busy',False):
        raise RuntimeError('OFFLINE_ONLY_DO_NOT_RUN_INSIDE_VISUM_OR_ACTIVE_15A2')
    here=Path(__file__).resolve().parent
    if str(here) not in sys.path:sys.path.insert(0,str(here))
    from verify_release import verify
    proof=verify(here)
    if proof['status']!='RELEASE_INTEGRITY_PASS':
        raise RuntimeError('RELEASE_INTEGRITY_FAIL:'+str(proof['failures']))
    from cordon2025.__main__ import main as run
    args=list(sys.argv[1:] if argv is None else argv)
    if not args or args[0].startswith('--'):args.insert(0,'demo')
    if '--config' in args:raise RuntimeError('USE_MODULE_CLI_FOR_CUSTOM_CONFIG')
    return run(args+['--config',str(here/'CORDON_2025_AGGRESSIVE_CONFIG.json')])

if __name__=='__main__':raise SystemExit(main())
