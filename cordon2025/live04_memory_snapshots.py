"""LIVE04.14: learned GENERATION memories bound to the accepted model state.

The GENSTRUCT1 efficiency factors (eta) and the stage-B IDP response model learn during a
run.  A continuation opens ONE specific accepted state (checkpoint, saved version, state
match); it must get the memories as they were when THAT state was accepted, never values
learned later in the original run (e.g. C03 memory for a C01 checkpoint).

GENERATION_MEMORY_SNAPSHOTS.json in the run folder maps state_hash -> memories, written once
per state at the moment the state becomes the accepted state (first write wins).  A
continuation loads the snapshot of the opened state from the previous run; without one it
starts with fresh memories (recorded).  Memories never decide a trial.
"""
from __future__ import annotations
from pathlib import Path
from .common import read_json, canonical_hash
from .io import write_json

FILE = 'GENERATION_MEMORY_SNAPSHOTS.json'
SCHEMA = 'LIVE04_GENERATION_MEMORY_SNAPSHOTS_V1'


def _current(adapter):
    st = getattr(adapter, 'generation_structure', None)
    model = getattr(adapter, 'idp_generation_model', None)
    ref = getattr(adapter, 'idp_run_reference', None)
    return {'genstruct': st.memory_state() if st is not None else None,
            'idp_model': model.state(ref.record['record_sha256']) if model is not None and ref is not None else None}


def _load(folder):
    p = Path(folder) / FILE
    if not p.is_file():
        return {'schema': SCHEMA, 'snapshots': {}}
    data = read_json(p)
    if data.get('schema') != SCHEMA or not isinstance(data.get('snapshots'), dict):
        return {'schema': SCHEMA, 'snapshots': {}}
    return data


def record(adapter, folder, state_hash, label):
    """Memories at the moment state_hash became the accepted state (first write wins)."""
    data = _load(folder)
    if state_hash in data['snapshots']:
        return False
    snap = dict(_current(adapter), label=str(label), state_hash=str(state_hash))
    snap['sha256'] = canonical_hash(snap)          # the state hash is part of the hashed content
    data['snapshots'][state_hash] = snap
    write_json(Path(folder) / FILE, data)
    return True


def restore(adapter, previous_run_folder, state_hash):
    """Load the memories of the OPENED state from the previous run (continuation)."""
    out = {'schema': SCHEMA + '_RESTORE', 'state_hash': state_hash, 'genstruct': 'NOT_ACTIVE',
           'idp_model': 'NOT_ACTIVE'}
    if not previous_run_folder:
        out['status'] = 'NO_PREVIOUS_RUN'
        return out
    snap = _load(previous_run_folder)['snapshots'].get(state_hash)
    if snap is None:
        out['status'] = 'NO_SNAPSHOT_FOR_OPENED_STATE_FRESH_MEMORIES'
        return out
    body = {k: v for k, v in snap.items() if k != 'sha256'}
    if snap.get('sha256') != canonical_hash(body):
        out['status'] = 'SNAPSHOT_RECORD_CHANGED_FRESH_MEMORIES'
        return out
    if snap.get('state_hash') != state_hash:      # a valid record moved under another key
        out['status'] = 'SNAPSHOT_DECLARES_ANOTHER_STATE_FRESH_MEMORIES'
        return out
    out['status'] = 'SNAPSHOT_OF_OPENED_STATE'
    out['label'] = snap.get('label')
    st = getattr(adapter, 'generation_structure', None)
    if st is not None and snap.get('genstruct') is not None and st.mem_cfg.get('enabled'):
        ok, reason = st.load_memory(snap['genstruct'])
        out['genstruct'] = reason if ok else 'REJECTED:' + reason
    model = getattr(adapter, 'idp_generation_model', None)
    ref = getattr(adapter, 'idp_run_reference', None)
    if model is not None and ref is not None and snap.get('idp_model') is not None:
        out['idp_model'] = 'LOADED' if model.load(snap['idp_model'], ref.record['record_sha256']) else 'REJECTED'
    return out
