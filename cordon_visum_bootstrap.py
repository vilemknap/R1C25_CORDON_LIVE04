"""Standard-library-only Visum entry isolation. Never attach through ROT/Dispatch.

A successful bootstrap is NOT a successful calibration. The live module performs
read-only preflight/capture; APPLY and procedure execution remain unavailable.
"""
from contextlib import contextmanager
from pathlib import Path
import importlib
import importlib.util
import json
import os
import platform
import sys
import tempfile
import threading
import traceback
import uuid

PREFIXES = ('cordon2025', 'r1_15a2_')
BUSY = ('_r1_15a2_calibration_busy', '_r1_cordon2025_busy')


def _message(exc):
    for func in (str, repr):
        try:
            return func(exc)
        except Exception:
            pass
    return '<unprintable %s>' % type(exc).__name__


def _owned(name):
    return name == 'cordon2025' or name.startswith(('cordon2025.', 'r1_15a2_'))


@contextmanager
def isolated_imports(root):
    """Restore all old release modules after success AND failure, not a global patch."""
    if any(getattr(sys, flag, False) for flag in BUSY):
        raise RuntimeError('ANOTHER_15A2_OR_CORDON_RUN_IS_ACTIVE')
    token = uuid.uuid4().hex
    sys._r1_cordon2025_busy = token
    root = Path(root).resolve()
    path_before = list(sys.path)
    no_bytecode = sys.dont_write_bytecode
    old = {k: v for k, v in tuple(sys.modules.items()) if _owned(k)}
    before = set(sys.modules)
    try:
        for key in old:
            del sys.modules[key]
        sys.path[:] = [str(root), str(root/'parent')] + [p for p in path_before if p not in (str(root),str(root/'parent'))]
        sys.dont_write_bytecode = True
        importlib.invalidate_caches()
        yield
    finally:
        for key, module in tuple(sys.modules.items()):
            local = False
            file = getattr(module, '__file__', None)
            if key not in before and isinstance(file, str):
                try:
                    local = root in Path(file).resolve().parents
                except (OSError, ValueError):
                    pass
            if _owned(key) or local:
                sys.modules.pop(key, None)
        sys.modules.update(old)
        sys.path[:] = path_before
        sys.dont_write_bytecode = no_bytecode
        if getattr(sys, '_r1_cordon2025_busy', None) == token:
            del sys._r1_cordon2025_busy


def _boot_folder():
    errors = []
    candidates = []
    if os.environ.get('LOCALAPPDATA'):
        candidates.append(Path(os.environ['LOCALAPPDATA'])/'R1C25_BOOT')
    candidates.append(Path(tempfile.gettempdir())/'R1C25_BOOT')
    for base in candidates:
        try:
            folder = base/uuid.uuid4().hex[:12]
            folder.mkdir(parents=True,exist_ok=False)
            return folder
        except OSError as exc:
            errors.append(_message(exc))
    raise RuntimeError('NO_WRITABLE_BOOT_LOG_DIRECTORY:' + ';'.join(errors))


def launch(namespace, root, *, action='PREFLIGHT', output_root=None, options=None):
    """Called from Execute Script; does not parse host sys.argv or call SystemExit."""
    folder = None
    try:
        folder = _boot_folder()
        (folder/'00_BOOT_STARTED.json').write_text(json.dumps({'status':'BOOT_STARTED','action':action,
            'python':sys.version,'executable':sys.executable,'bits':64 if sys.maxsize > 2**32 else 32,
            'platform':platform.platform(),'com_thread_id':threading.get_ident(),'apply_permitted':False}),encoding='utf-8')
        visum, other = namespace.get('Visum'), namespace.get('COM')
        if visum is not None and other is not None and visum is not other:
            raise RuntimeError('AMBIGUOUS_INJECTED_VISUM_AND_COM')
        instance = visum if visum is not None else other
        if instance is None:
            raise RuntimeError('NO_INJECTED_VISUM_RUN_FROM_TARGET_VISUM_SCRIPTS_MENU')
        if sys.version_info < (3,10) or sys.maxsize <= 2**32:
            raise RuntimeError('PYTHON_310_OR_NEWER_64BIT_REQUIRED')
        with isolated_imports(root):
            # A saved module from another release must not become the verifier.
            spec=importlib.util.spec_from_file_location('_cordon_independent_verifier', Path(root)/'verify_release.py')
            verifier=importlib.util.module_from_spec(spec);spec.loader.exec_module(verifier)
            proof=verifier.verify(root)
            if proof['status'] != 'RELEASE_INTEGRITY_PASS':
                raise RuntimeError('RELEASE_INTEGRITY_FAIL:' + json.dumps(proof['failures'][:12]))
            try:
                np=importlib.import_module('numpy')
                if not hasattr(np,'asarray') or not hasattr(np,'savez_compressed'):
                    raise ImportError('numpy API missing')
            except Exception as exc:
                raise RuntimeError('NUMPY_UNAVAILABLE_IN_THIS_VISUM_PYTHON:' + _message(exc)) from exc
            runtime=importlib.import_module('cordon2025.visum_startup')
            result=runtime.run(instance,action=action,output_root=output_root,options=options)
        result=dict(result,boot_log_directory=str(folder))
    except BaseException as exc:
        result={'status':'STARTUP_BLOCKED','reason':_message(exc),'error_type':type(exc).__name__,
                'apply_permitted':False,'assignment_executed':False,'live_calibration_verified':False,
                'boot_log_directory':str(folder) if folder else None}
        if folder is not None:
            try:
                (folder/'99_TRACEBACK.txt').write_text(traceback.format_exc(),encoding='utf-8')
            except Exception:
                pass
    if folder is not None:
        try:
            (folder/'00_BOOT_RESULT.json').write_text(json.dumps(result,indent=2,ensure_ascii=True,allow_nan=False),encoding='utf-8')
        except Exception:
            pass
    try:
        print(json.dumps(result,indent=2,ensure_ascii=True,allow_nan=False))
    except Exception:
        pass
    return result
