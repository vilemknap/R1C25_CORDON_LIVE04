"""Standard-library-only LIVE02 entry with the LIVE01 import isolation."""
from pathlib import Path
import importlib.util
import importlib
import sys
import json
import traceback


def launch(namespace,*,root=None,output_root=None,options=None,config_path=None,config_overrides=None):
    root=Path(root or Path(__file__).resolve().parent).resolve()
    boot=None
    try:
        if namespace.get('Visum') is None:raise RuntimeError('VISUM_NOT_INJECTED')
        if namespace.get('COM') is not None and namespace['COM'] is not namespace['Visum']:
            raise RuntimeError('AMBIGUOUS_INJECTED_VISUM_AND_COM')
        if sys.version_info<(3,10) or sys.maxsize<=2**32:
            raise RuntimeError('PYTHON_310_OR_NEWER_64BIT_REQUIRED')
        if getattr(sys,'_r1_15a2_calibration_busy',False):
            raise RuntimeError('ANOTHER_15A2_RUN_IS_ACTIVE')
        for name,mod in tuple(sys.modules.items()):
            if name.startswith('r1_15a2_') and getattr(mod,'__file__',None):
                if Path(mod.__file__).resolve().parent != root/'parent':
                    raise RuntimeError('LIVE02_FOREIGN_PROFILE_MODULE_COLLISION:'+name)
        sp=importlib.util.spec_from_file_location('_live02_original_bootstrap',root/'cordon_visum_bootstrap.py')
        original=importlib.util.module_from_spec(sp);sp.loader.exec_module(original)
        boot=original._boot_folder()
        with original.isolated_imports(root):
            vs=importlib.util.spec_from_file_location('_live02_verifier',root/'verify_release.py')
            verifier=importlib.util.module_from_spec(vs);vs.loader.exec_module(verifier)
            proof=verifier.verify(root)
            if proof['status']!='RELEASE_INTEGRITY_PASS':raise RuntimeError('LIVE02_RELEASE_INTEGRITY_FAIL:'+str(proof['failures'][:5]))
            run=importlib.import_module('cordon2025.live02_cycle').run
            result=run(namespace['Visum'],output_root=output_root,options=options,config_path=config_path,
                       config_overrides=config_overrides)
    except BaseException as exc:
        try:message=str(exc)
        except Exception:message='<unprintable '+type(exc).__name__+'>'
        result={'status':'LIVE02_STARTUP_OR_RUN_STOPPED','reason':message,
                'source_version_overwritten':False,'direct_od_matrix_writes':False,
                'load_version_called':False,'production_ready':False,
                'hint':'See 00_RESULT.json in the LIVE02 run folder for the model state.'}
        if boot:
            try:(boot/'99_TRACEBACK.txt').write_text(traceback.format_exc(),encoding='utf-8')
            except Exception:pass
    if boot:
        result['boot_log_directory']=str(boot)
        try:(boot/'00_LIVE02_BOOT_RESULT.json').write_text(json.dumps(result,indent=2,ensure_ascii=True,default=str),encoding='utf-8')
        except Exception:pass
    print(json.dumps(result,ensure_ascii=True,indent=2,default=str))
    return result
