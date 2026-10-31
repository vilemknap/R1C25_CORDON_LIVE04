"""Isolated OFFLINE run lifecycle; no live model, discovery or assignment reuse.

Applies FRESH0/IOFIX/SEMRELOAD lessons to a cordon-only runner. A checkpoint is a
verified handoff, NOT an invented continuation of Visum or FISTA solver state.
"""
from __future__ import annotations
from pathlib import Path
import os
import re
import sys
import uuid
from .common import ROOT, require, canonical_hash
from .io import mkdir, native_path, read_json, write_json, sha256, retry

ROOT_MARKER = 'CORDON_2025_ROOT.json'
LOCK = '.cordon2025.lock'
CHECKPOINT = 'RUN_CHECKPOINT.json'


def code_identity():
    files = {}
    for sub in ('cordon2025', 'parent'):
        for path in sorted((ROOT/sub).glob('*.py')):
            files[str(path.relative_to(ROOT))] = sha256(path)
    return canonical_hash(files)


def authority_identity():
    return canonical_hash({p.name: sha256(p) for p in sorted((ROOT/'data/audited').glob('*')) if p.is_file()})


def capture_context(cfg, inputs=None):
    records = {}
    for name, path in sorted((inputs or {}).items()):
        if path is not None:
            path = Path(path).resolve()
            require(path.is_file(), 'CHECKPOINT_INPUT_MISSING:' + name)
            records[name] = {'path': str(path), 'sha256': sha256(path)}
    return {'code_sha256': code_identity(), 'authority_sha256': authority_identity(),
            'config_sha256': canonical_hash(cfg), 'inputs': records,
            'model_year': 2025, 'survey_year': 2026, 'authority_family': 'CORDON_SDP'}


def _no_symlink(path):
    path = Path(path).absolute()
    require(not any(p.is_symlink() for p in (path, *path.parents)), 'SYMLINK_OUTPUT_PATH_FORBIDDEN')


def compact_name(name):
    require(isinstance(name, str) and bool(re.fullmatch(r'[A-Za-z0-9_-]+', name)), 'UNSAFE_OUTPUT_NAME')
    return name if len(name) <= 64 else name[:24] + '_' + canonical_hash(name)[:16]


def default_root():
    if os.name == 'nt' and os.environ.get('LOCALAPPDATA'):
        return Path(os.environ['LOCALAPPDATA'])/'R1C25'
    return ROOT/'OFFLINE_RESULTS'


class RunSession:
    def __init__(self, name, output_root=None):
        self.requested_name = name
        self.name = compact_name(name)
        self.root = Path(output_root) if output_root is not None else default_root()
        self.folder = None
        self.token = uuid.uuid4().hex
        self.locked = False
        self.context = None
        self.stages = []

    def __enter__(self):
        _no_symlink(self.root)
        self.root = self.root.absolute()
        require('2022' not in self.root.parts, 'MODEL_2022_OUTPUT_ROOT_FORBIDDEN')
        protected = (ROOT/'parent', ROOT/'data', ROOT/'cordon2025', ROOT/'tests', ROOT/'docs')
        require(self.root != ROOT and not any(self.root == p or p in self.root.parents for p in protected), 'PROTECTED_SOURCE_OUTPUT_ROOT')
        existed = self.root.exists()
        # Reject adoption of an arbitrary existing directory (including 2022 runs).
        legacy_default = self.root == (ROOT/'OFFLINE_RESULTS').absolute()
        if existed and not (self.root/ROOT_MARKER).is_file():
            require(legacy_default or not any(self.root.iterdir()), 'UNOWNED_NONEMPTY_OUTPUT_ROOT')
        mkdir(self.root)
        try:
            with open(native_path(self.root/LOCK), 'x', encoding='ascii') as f:
                f.write(self.token); f.flush(); os.fsync(f.fileno())
        except FileExistsError as exc:
            raise ValueError('CORDON_RUN_ROOT_LOCKED_NO_AUTOMATIC_STEAL') from exc
        self.locked = True
        try:
            marker = self.root/ROOT_MARKER
            if marker.is_file():
                val = read_json(marker)
                require(val.get('model_year') == 2025 and val.get('authority_family') == 'CORDON_SDP', 'OUTPUT_ROOT_OWNER_MISMATCH')
            else:
                write_json(marker, {'model_year':2025,'authority_family':'CORDON_SDP','schema':'CORDON_RUN_ROOT_V2'})
            folder = self.root/self.name
            mkdir(folder, exist_ok=False)
            self.folder = folder
            artifacts = ['COMMAND_STATUS.json', CHECKPOINT, 'TRACEBACK.txt', 'STATION_HITS.csv',
                         'ALL_ORDERED_UNIQUE_PAIRS/LINEARIZED_PREDICTIONS.csv',
                         'EXACT_TWO_HITS/TG_TD_PROJECTION.json']
            longest = max(len(str(folder/p)) for p in artifacts)
            write_json(folder/'PATH_PREFLIGHT.json', {'requested_name':self.requested_name,'actual_name':self.name,
                'output_root':str(self.root),'longest_planned_path_chars':longest,'win_extended_path_io':True,
                'short_temp_names':True,'live_model_access':False})
            return self
        except BaseException:
            self._release(preserve_primary=True)
            raise

    def _release(self, preserve_primary=False):
        if not self.locked:
            return
        try:
            path = self.root/LOCK
            with open(native_path(path), encoding='ascii') as f:
                require(f.read() == self.token, 'RUN_LOCK_OWNER_CHANGED')
            retry(lambda: os.unlink(native_path(path)))
            self.locked = False
        except Exception as exc:
            if not preserve_primary:
                raise
            try:
                sys.stderr.write('LOCK_CLEANUP_FAILED_PRIMARY_PRESERVED:' + repr(exc) + '\n')
            except Exception:
                pass

    def __exit__(self, exc_type, exc, tb):
        self._release(preserve_primary=exc is not None)
        return False

    def start(self, cfg, inputs=None):
        self.context = capture_context(cfg, inputs)
        self.checkpoint('STARTED', completed=False)

    def checkpoint(self, stage, *, completed=False):
        require(self.folder is not None and self.context is not None, 'RUN_NOT_STARTED')
        # Never seal results if any pinned input or code changed while running.
        validate_context(self.context)
        records = []
        for p in sorted(self.folder.rglob('*')):
            if p.is_symlink():
                raise ValueError('SYMLINK_RUN_ARTIFACT')
            if p.is_file() and p.name != CHECKPOINT and not p.name.endswith('.tmp'):
                records.append({'path':p.relative_to(self.folder).as_posix(), 'bytes':p.stat().st_size,'sha256':sha256(p)})
        self.stages.append(stage)
        state = {'schema':'CORDON_OFFLINE_CHECKPOINT_V2', 'stage':stage, 'completed':completed,
                 'stages':list(self.stages),'context':self.context,'artifacts':records,
                 'apply_permitted':False,'live_visum_tested':False,'production_ready':False,
                 'restart_mode':'VERIFIED_OFFLINE_RESTART_FROM_INPUTS_NOT_SOLVER_CONTINUATION'}
        write_json(self.folder/CHECKPOINT, state)
        return state


def validate_context(context):
    require(context.get('model_year') == 2025 and context.get('authority_family') == 'CORDON_SDP', 'CHECKPOINT_WRONG_MODEL_SCOPE')
    require(code_identity() == context.get('code_sha256'), 'CHECKPOINT_CODE_CHANGED')
    require(authority_identity() == context.get('authority_sha256'), 'CHECKPOINT_AUTHORITY_CHANGED')
    for name, rec in context.get('inputs', {}).items():
        require(Path(rec['path']).is_file() and sha256(rec['path']) == rec['sha256'], 'CHECKPOINT_INPUT_CHANGED:' + name)


def verify_run(folder):
    folder = Path(folder)
    _no_symlink(folder)
    state = read_json(folder/CHECKPOINT)
    require(state.get('schema') == 'CORDON_OFFLINE_CHECKPOINT_V2', 'INVALID_RUN_CHECKPOINT_SCHEMA')
    require(state.get('apply_permitted') is False and state.get('live_visum_tested') is False, 'INVALID_OFFLINE_CHECKPOINT_FLAGS')
    validate_context(state['context'])
    seen = set()
    for rec in state['artifacts']:
        rel = Path(rec['path'])
        require(not rel.is_absolute() and '..' not in rel.parts and rec['path'] not in seen, 'INVALID_CHECKPOINT_ARTIFACT_PATH')
        seen.add(rec['path']);p = folder/rel;_no_symlink(p)
        require(p.is_file() and p.stat().st_size == rec['bytes'] and sha256(p) == rec['sha256'], 'CHECKPOINT_ARTIFACT_CHANGED:' + rec['path'])
    actual = {p.relative_to(folder).as_posix() for p in folder.rglob('*') if p.is_file() and p.name != CHECKPOINT and not p.name.endswith('.tmp')}
    require(actual == seen, 'CHECKPOINT_UNSEALED_ARTIFACTS')
    if (folder/'PERF01_RUN_BINDING.json').is_file():
        from .perf01_cache import verify_run_binding
        verify_run_binding(folder)
    return {'status':'OFFLINE_RUN_CHECKPOINT_VERIFIED','completed':state['completed'],'stage':state['stage'],
            'artifacts_verified':len(seen),'restart_mode':state['restart_mode'],
            'apply_permitted':False,'live_visum_tested':False,'production_ready':False}
