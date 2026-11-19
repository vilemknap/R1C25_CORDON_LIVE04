"""LIVE04.14: learned GENERATION memories bound to the accepted model state.

The GENSTRUCT1 efficiency factors (eta) and the stage-B IDP response model learn during a
run.  A continuation opens ONE specific accepted state (checkpoint, saved version, state
match); it must get the memories as they were when THAT state was accepted, never values
learned later in the original run (e.g. C03 memory for a C01 checkpoint).

GENERATION_MEMORY_SNAPSHOTS.json in the run folder maps state_hash -> memories, written once
per state at the moment the state becomes the accepted state (first write wins).  A
continuation loads the snapshot of the opened state from the previous run; without one it
starts with fresh memories (recorded).  An EXISTING but corrupted, re-keyed or rejected
record stops the continuation (it is never mistaken for a missing one); delete the file
explicitly to continue with fresh memories.  Memories never decide a trial.

Since review 0eb13bf also the LIVE04.1 RunMemory (TD Jacobian incl. its IDP features, TG
route-choice correction, node curvature) is part of the snapshot; the reused TD Jacobian is
still verified by its native probe as before.
"""
from __future__ import annotations
from pathlib import Path
from .common import read_json, canonical_hash, require
from .io import write_json

FILE = 'GENERATION_MEMORY_SNAPSHOTS.json'
SCHEMA = 'LIVE04_GENERATION_MEMORY_SNAPSHOTS_V1'


def _current(adapter):
    st = getattr(adapter, 'generation_structure', None)
    model = getattr(adapter, 'idp_generation_model', None)
    ref = getattr(adapter, 'idp_run_reference', None)
    rm = getattr(adapter, 'run_memory', None)
    return {'genstruct': st.memory_state() if st is not None else None,
            'idp_model': model.state(ref.record['record_sha256']) if model is not None and ref is not None else None,
            'run_memory': rm.state() if rm is not None else None}


def _load(folder):
    """Missing file -> empty container; an existing unreadable or wrong-schema file fails closed."""
    p = Path(folder) / FILE
    if not p.is_file():
        return {'schema': SCHEMA, 'snapshots': {}}
    try:
        data = read_json(p)
    except Exception as exc:
        require(False, 'LIVE04_MEMORY_SNAPSHOT_FILE_CORRUPTED:%s:%s' % (p, str(exc)[:200]))
    require(data.get('schema') == SCHEMA and isinstance(data.get('snapshots'), dict),
            'LIVE04_MEMORY_SNAPSHOT_FILE_CORRUPTED:%s:SCHEMA' % p)
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
    require(snap.get('sha256') == canonical_hash(body), 'LIVE04_MEMORY_SNAPSHOT_RECORD_CHANGED:' + state_hash[:12])
    # a valid record moved under another key
    require(snap.get('state_hash') == state_hash, 'LIVE04_MEMORY_SNAPSHOT_DECLARES_ANOTHER_STATE:' + state_hash[:12])
    out['status'] = 'SNAPSHOT_OF_OPENED_STATE'
    out['label'] = snap.get('label')
    st = getattr(adapter, 'generation_structure', None)
    if st is not None and snap.get('genstruct') is not None and st.mem_cfg.get('enabled'):
        ok, reason = st.load_memory(snap['genstruct'])
        require(ok, 'LIVE04_MEMORY_SNAPSHOT_GENSTRUCT_REJECTED:' + reason)
        out['genstruct'] = reason
    model = getattr(adapter, 'idp_generation_model', None)
    ref = getattr(adapter, 'idp_run_reference', None)
    if model is not None and ref is not None and snap.get('idp_model') is not None:
        ok, reason = model.load(snap['idp_model'], ref.record['record_sha256'])
        require(ok, 'LIVE04_MEMORY_SNAPSHOT_IDP_MODEL_REJECTED:' + reason)
        out['idp_model'] = reason
    rm = getattr(adapter, 'run_memory', None)
    out['run_memory'] = 'NOT_ACTIVE'
    if rm is not None and snap.get('run_memory') is not None:
        ok, reason = rm.load_state(snap['run_memory'])
        require(ok, 'LIVE04_MEMORY_SNAPSHOT_RUN_MEMORY_REJECTED:' + reason)
        out['run_memory'] = reason
    return out
