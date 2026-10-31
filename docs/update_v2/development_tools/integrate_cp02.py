from pathlib import Path
r=Path('/mnt/data/R1_CORDON_UPDATE_20261022/release/cordon2025');p=r/'common.py';s=p.read_text()
a=s.index('def parent_core():');b=s.index('\nclass ContractError',a)
s=s[:a]+'''def parent_module(name):
    """Only import library modules from this isolated 2025 parent tree."""
    require(name.startswith('r1_15a2_') and name.replace('_', '').isalnum(), 'INVALID_PARENT_MODULE')
    expected = (PARENT / (name + '.py')).resolve()
    require(expected.is_file(), 'PARENT_MODULE_MISSING:' + name)
    # Reject already-imported dependencies from a running/different 2022 source.
    for key, module in tuple(sys.modules.items()):
        if key.startswith('r1_15a2_') and getattr(module, '__file__', None):
            origin = Path(module.__file__).resolve()
            if origin.parent != PARENT.resolve():
                raise ContractError('PARENT_MODULE_COLLISION:' + key)
    if str(PARENT) not in sys.path:
        sys.path.insert(0, str(PARENT))
    import importlib
    module = importlib.import_module(name)
    require(Path(module.__file__).resolve() == expected, 'PARENT_MODULE_COLLISION:' + name)
    return module


def parent_core():
    return parent_module('r1_15a2_core')
''' + s[b:]
a=s.index('def sha256(path):');b=s.index('\ndef canonical_hash',a)
s=s[:a]+'''def sha256(path):
    from .io import sha256 as secure_sha256
    return secure_sha256(path)
''' + s[b:]
a=s.index('def read_csv(path):');b=s.index('\ndef read_config',a)
s=s[:a]+'''def read_csv(path):
    from .io import read_csv as secure_read_csv
    return secure_read_csv(path)


def read_json(path):
    from .io import read_json as secure_read_json
    return secure_read_json(path)


def write_json(path, data):
    from .io import write_json as secure_write_json
    return secure_write_json(path, data)


def write_csv(path, rows, fields=None):
    from .io import write_csv as secure_write_csv
    return secure_write_csv(path, rows, fields)


def write_npz(path, **arrays):
    from .io import write_npz as secure_write_npz
    return secure_write_npz(path, **arrays)
''' + s[b:]
s=s.replace("cfg = json.loads(p.read_text(encoding='utf-8'))","cfg = read_json(p)")
p.write_text(s)
for name in ('incidence.py','optimizer.py','authority.py'):
 p=r/name;s=p.read_text();s=s.replace('np.savez_compressed(', 'write_npz(')
 # Additional import, keeping existing APIs unchanged.
 s=s.replace('import numpy as np','import numpy as np\nfrom .common import write_npz')
 p.write_text(s)
p=r/'__main__.py';s=p.read_text();s=s.replace('from .demos import synthetic_demo','from .demos import synthetic_demo\nfrom .io import read_json, safe_failure_report')
s=s.replace("evidence=json.loads(Path(evidence_path).read_text(encoding='utf-8'))","evidence=read_json(evidence_path)")
a=s.index('    except Exception as exc:\n',s.index('def main'))
b=s.index("\nif __name__",a)
s=s[:a]+'''    except Exception as exc:
        safe_failure_report(folder, exc, traceback_text=traceback.format_exc(), emergency_stream=sys.stderr)
        return 2
''' + s[b:]
p.write_text(s)
# Atomic streaming station-hit CSV with source hash/sidecar checks before publish.
p=r/'incidence.py';s=p.read_text();s=s.replace('import struct','import struct\nimport sys\nfrom contextlib import ExitStack\nfrom .io import atomic_output, native_path')
s=s.replace("con=sqlite3.connect('file:'+quote(str(p),safe='/:')+'?mode=ro',uri=True)","con=sqlite3.connect('file:'+quote(str(p).replace(chr(92),'/'),safe='/:')+'?mode=ro',uri=True)")
s=s.replace('    stream=None\n    try:', '    stream=None\n    output_stack=ExitStack()\n    try:')
s=s.replace("hp=Path(hits_output);hp.parent.mkdir(parents=True,exist_ok=True)\n            stream=hp.open('w',newline='',encoding='utf-8')", "hp=Path(hits_output)\n            stream=output_stack.enter_context(atomic_output(hp,newline='',encoding='utf-8'))")
a=s.index('    finally:\n        if stream:stream.close()')
b=s.index('\ndef aggregate_observations',a)
s=s[:a]+'''    finally:
        primary = sys.exc_info()
        db.close()
        if primary[0] is not None:
            # Preserve the primary parsing error; failed diagnostics never publish.
            output_stack.__exit__(*primary)
        else:
            try:
                require(not any(Path(str(p)+ext).exists() for ext in ('-wal','-shm','-journal')), 'SOURCE_CACHE_SIDECAR_APPEARED_DURING_READ')
                require(sha256(p)==digest,'SOURCE_CACHE_CHANGED_DURING_READ')
            except BaseException:
                output_stack.__exit__(*sys.exc_info())
                raise
            output_stack.close()
''' + s[b:]
p.write_text(s)
