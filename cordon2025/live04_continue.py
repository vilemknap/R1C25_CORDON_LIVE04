"""LIVE04.8 - checkpoints and continuation of a previous cordon run.

Checkpoint: after every block that ACCEPTED a change, the open model (proven to be
exactly the accepted state by a fresh snapshot) is saved as a NEW .ver in
``<run>/CHECKPOINTS`` together with a sidecar ``<ver stem>.CHECKPOINT.json``
(position of the next block, state hashes, sha256 of the file).  Only the last
``keep_last`` checkpoints of the run are kept.  The source .ver is never written.

Continuation: open a .ver that a LIVE04 run saved (a checkpoint, or the
``SAVED_ACCEPTED_VERSION`` written at the end / at a verified stop) and start
``RUN_R1_2025_CORDON_LIVE04_CONTINUE.py``.  The run

* proves the opened file is byte-identical to the saved one (sha256 in the
  sidecar or in ``SAVED_ACCEPTED_VERSION.json``);
* takes the RUN-START ANCHORS of the ORIGINAL run (generation coefficient
  reference for the signed refinement / ZAHR envelopes, ADDVAL1 run-start values
  for the cumulative supply bounds), so a continuation can never widen the
  envelopes by re-anchoring them at an already calibrated state;
* continues at the interrupted outer cycle and block (cycle numbering, SupplyMix
  parity and adapter policies stay those of the original run);
* runs its own fresh BASELINE capture; every later decision is taken on fresh
  native assignments exactly as in a new run.
"""
from __future__ import annotations
from pathlib import Path
import copy
import re
from .common import require
from .common import read_json, canonical_hash, parent_module
from .io import write_json, sha256

SCHEMA = 'LIVE04_CONTINUATION_V1'
CKPT_SCHEMA = 'LIVE04_CHECKPOINT_V1'
ANCHORS_SCHEMA = 'LIVE04_RUN_ANCHORS_V1'
ANCHORS_FILE = 'RUN_ANCHORS.json'
CKPT_DIR = 'CHECKPOINTS'
COMPONENT_HASHES = ('addval_hash', 'generation_hash', 'td_hash', 'matrix_hash', 'fixed_link_hash', 'dseg_hash',
                    'operations_hash')
_SUFFIX = re.compile(r'(_LIVE04_(ACCEPTED_[0-9a-f]{8}|CKPT_C\d+_[A-Z0-9_]+?_[0-9a-f]{8}))+$')


def base_stem(source_version):
    """Version stem without previous LIVE04 save suffixes (names do not grow on continuation)."""
    return _SUFFIX.sub('', Path(str(source_version)).stem) or Path(str(source_version)).stem


def sidecar_path(ver):
    ver = Path(ver)
    return ver.with_name(ver.stem + '.CHECKPOINT.json')


def key_tuple(text):
    return tuple(int(x) for x in str(text).split('|'))


# ------------------------------------------------------------------ anchors
def anchors_from_snapshot(snap, run_folder, source_version, outer_cycle_start):
    return {'schema': ANCHORS_SCHEMA, 'origin_run_folder': str(run_folder), 'origin_source_version': str(source_version),
            'origin_state_hash': snap['state_hash'], 'origin_outer_cycle_start': int(outer_cycle_start),
            'generation_values': copy.deepcopy(snap.get('generation_values', {})),
            'addval1': dict(snap.get('addval1', {})), 'chain': []}


def load_anchors(prev_folder):
    prev = Path(prev_folder)
    if (prev / ANCHORS_FILE).is_file():
        a = read_json(prev / ANCHORS_FILE)
        require(a.get('schema') == ANCHORS_SCHEMA, 'LIVE04_CONTINUE_ANCHORS_SCHEMA')
        return a
    rp = prev / 'RESTORE_POINT.json'
    require(rp.is_file(), 'LIVE04_CONTINUE_PREVIOUS_RUN_HAS_NO_RESTORE_POINT:' + str(prev))
    r = read_json(rp)
    require(str(r.get('schema', '')).startswith('LIVE04_RESTORE_POINT'), 'LIVE04_CONTINUE_RESTORE_POINT_SCHEMA')
    snap = r['snapshot']
    require(snap.get('state_hash') == r.get('state_hash'), 'LIVE04_CONTINUE_RESTORE_POINT_HASH')
    eff = prev / 'EFFECTIVE_CONFIG.json'
    start = int(read_json(eff).get('outer_cycle_start', 1)) if eff.is_file() else 1
    return anchors_from_snapshot(snap, prev, r.get('source_version'), start)


# ------------------------------------------------------------------ position
def next_position(names, index, outer):
    return {'outer_cycle': int(outer) + 1, 'block_index': 0} if index + 1 >= len(names) else \
        {'outer_cycle': int(outer), 'block_index': int(index) + 1}


def position_from_progress(progress, planned, origin_start):
    """(outer_cycle, block_index, changed_so_far) after the last COMPLETED block."""
    cycles = progress.get('cycles') or []
    if not cycles:
        return int(origin_start), 0, False
    last = cycles[-1]
    outer = int(last['outer_cycle'])
    done = [b['block'] for b in last.get('blocks') or []]
    names = planned(outer)
    require(names[:len(done)] == done, 'LIVE04_CONTINUE_BLOCK_ORDER_MISMATCH:%s!=%s' % (done, names))
    if len(done) >= len(names):
        return outer + 1, 0, False
    return outer, len(done), any(bool(b.get('changed')) for b in last.get('blocks') or [])


# ------------------------------------------------------------------ resolve
def resolve(source_version, source_sha256, planned, origin_start_default):
    """Identify the opened .ver as a saved LIVE04 state; return the continuation plan."""
    ver = Path(str(source_version))
    side = sidecar_path(ver)
    if side.is_file():
        ck = read_json(side)
        require(ck.get('schema') == CKPT_SCHEMA, 'LIVE04_CONTINUE_CHECKPOINT_SCHEMA')
        require(Path(ck['path']).name == ver.name, 'LIVE04_CONTINUE_CHECKPOINT_NAME_MISMATCH')
        require(ck['sha256'] == source_sha256, 'LIVE04_CONTINUE_CHECKPOINT_FILE_CHANGED_SINCE_SAVE')
        prev = Path(ck['run_folder'])
        if not prev.is_dir():
            prev = ver.parent.parent
        nxt = ck['next']
        plan = {'kind': 'CHECKPOINT', 'previous_run_folder': str(prev), 'saved_record': str(side),
                'outer_cycle': int(nxt['outer_cycle']), 'block_index': int(nxt['block_index']),
                'changed_so_far': bool(nxt.get('cycle_changed_so_far')),
                'expected_state_hash': ck['state_hash'], 'expected_component_hashes': ck.get('component_hashes'),
                'previous_accepted_states': int(ck.get('accepted_states', 0))}
    else:
        prev = ver.parent
        rec_path = prev / 'SAVED_ACCEPTED_VERSION.json'
        if not rec_path.is_file():
            # LIVE04.8.1: a .ver saved by the user / prepared by RECOMPUTE_FOR_LIVE04_BASE from a
            # stopped run: identified after the baseline snapshot by its exact accepted state hash.
            return {'schema': SCHEMA, 'kind': 'STATE_MATCH_PENDING', 'opened_version': str(ver),
                    'opened_version_sha256': source_sha256}
        rec = read_json(rec_path)
        require(Path(rec['path']).name == ver.name, 'LIVE04_CONTINUE_SAVED_VERSION_NAME_MISMATCH')
        require(rec['sha256'] == source_sha256, 'LIVE04_CONTINUE_SAVED_FILE_CHANGED_SINCE_SAVE')
        progress = read_json(prev / 'CYCLE_PROGRESS.json')
        anchors = load_anchors(prev)
        outer, index, changed = position_from_progress(progress, planned,
                                                       anchors.get('origin_outer_cycle_start', origin_start_default))
        plan = {'kind': 'SAVED_ACCEPTED_VERSION', 'previous_run_folder': str(prev), 'saved_record': str(rec_path),
                'outer_cycle': outer, 'block_index': index, 'changed_so_far': changed,
                'expected_state_hash': progress.get('accepted_state_hash'), 'expected_component_hashes': None,
                'previous_accepted_states': int(progress.get('accepted_states', 0))}
    plan['anchors'] = load_anchors(prev)
    plan['schema'] = SCHEMA
    plan['opened_version'] = str(ver)
    plan['opened_version_sha256'] = source_sha256
    return plan


def apply_anchors(adapter, anchors, folder):
    """Replace this run's start anchors by the ORIGINAL run's ones."""
    out = {}
    if adapter.generation_reference_values is not None:
        adapter.generation_reference_values = copy.deepcopy(anchors['generation_values'])
        adapter.generation_reference_hash = canonical_hash(adapter.generation_reference_values)
        write_json(Path(folder) / '00_GENERATION_COEFFICIENT_REFERENCE.json', {
            'schema': 'R1_15A2_GENERATION_COEFFICIENT_REFERENCE_V2492',
            'policy': 'RUN_START_REFERENCE_OF_THE_ORIGINAL_RUN_CARRIED_BY_LIVE04_CONTINUATION',
            'state_hash': anchors['origin_state_hash'], 'origin_run_folder': anchors['origin_run_folder'],
            'generation_reference_hash': adapter.generation_reference_hash,
            'values': adapter.generation_reference_values})
        out['generation_reference_hash'] = adapter.generation_reference_hash
    if adapter.baseline_addval is not None:
        carried = {key_tuple(k): v for k, v in anchors['addval1'].items()}
        require(set(carried) == set(adapter.baseline_addval), 'LIVE04_CONTINUE_ADDVAL_LINK_SET_CHANGED')
        out['addval_links'] = len(carried)
        out['addval_links_changed_since_origin'] = sum(1 for k, v in carried.items() if adapter.baseline_addval[k] != v)
        adapter.baseline_addval = carried
    return out


# ------------------------------------------------------------------ checkpoint
def save_checkpoint(visum, adapter, folder, state, current_state, outer, block, nxt, accepted_states, keep_last):
    rt = parent_module('r1_15a2_runtime_v1')
    require(adapter.snapshot() == current_state, 'LIVE04_CHECKPOINT_MODEL_NOT_AT_ACCEPTED_STATE')
    ck = Path(folder) / CKPT_DIR
    ck.mkdir(parents=True, exist_ok=True)
    source = Path(state['source_version'])
    target = ck / ('%s_LIVE04_CKPT_C%02d_%s_%s%s' % (base_stem(source), int(outer), block,
                                                       current_state['state_hash'][:8], source.suffix or '.ver'))
    require(target.resolve() != source.resolve() and not target.exists(), 'LIVE04_CHECKPOINT_TARGET_INVALID')
    before = sha256(source) if source.is_file() else None
    saved = rt.save_version(visum, target)
    require(before is None or sha256(source) == before, 'LIVE04_SOURCE_VERSION_CHANGED_BY_CHECKPOINT')
    ev = getattr(adapter, 'evaluator', None)
    if ev is not None:
        ev.__dict__.setdefault('checkpoint_pointers', set()).add(str(target))
    try:
        pointer = str(visum.IO.CurrentVersionFile)
    except Exception:
        pointer = None
    rec = {'schema': CKPT_SCHEMA, 'path': str(target), 'sha256': saved['sha256'], 'bytes': saved['size'],
           'run_folder': str(folder), 'outer_cycle': int(outer), 'block': block, 'next': nxt,
           'state_hash': current_state['state_hash'],
           'component_hashes': {k: current_state.get(k) for k in COMPONENT_HASHES},
           'accepted_states': int(accepted_states), 'source_version': str(source),
           'visum_current_version_after_save': pointer,
           'note': 'Open this .ver and run RUN_R1_2025_CORDON_LIVE04_CONTINUE.py to continue.'}
    write_json(sidecar_path(target), rec)
    write_json(Path(folder) / 'LAST_CHECKPOINT.json', rec)
    removed = prune(ck, keep_last)
    rec['pruned'] = removed
    return rec


def prune(ck, keep_last):
    sides = sorted(Path(ck).glob('*.CHECKPOINT.json'), key=lambda p: (p.stat().st_mtime_ns, p.name))
    removed = []
    for side in sides[:max(0, len(sides) - int(keep_last))]:
        rec = read_json(side)
        ver = Path(rec['path'])
        if ver.parent.resolve() == Path(ck).resolve() and '_LIVE04_CKPT_' in ver.name and ver.is_file():
            ver.unlink()
        side.unlink()
        removed.append(ver.name)
    return removed


def verify_opened_state(plan, snap0):
    out = {'state_hash_expected': plan.get('expected_state_hash'), 'state_hash_opened': snap0['state_hash'],
           'state_hash_match': plan.get('expected_state_hash') == snap0['state_hash']}
    exp = plan.get('expected_component_hashes')
    if exp:
        out['component_match'] = {k: exp.get(k) == snap0.get(k) for k in exp}
        # Parameters must be exactly the checkpointed accepted values.
        for k in ('addval_hash', 'generation_hash', 'td_hash'):
            require(exp.get(k) == snap0.get(k), 'LIVE04_CONTINUE_OPENED_PARAMETERS_DIFFER_FROM_CHECKPOINT:' + k)
    return out


def resolve_by_state(plan, snap0, output_root, planned, origin_start_default, current_folder=None):
    """Find the previous LIVE04 run whose LAST ACCEPTED state is exactly the opened model state."""
    found = []
    for run in sorted(Path(output_root).glob('LIVE04_TGTD_*')):
        if current_folder is not None and run.resolve() == Path(current_folder).resolve():
            continue
        cp = run / 'CYCLE_PROGRESS.json'
        if not cp.is_file():
            continue
        try:
            prog = read_json(cp)
        except Exception:
            continue
        if prog.get('accepted_state_hash') == snap0['state_hash'] and int(prog.get('accepted_states', 0)) > 0:
            found.append((cp.stat().st_mtime_ns, run, prog))
    require(found, 'LIVE04_CONTINUE_NO_PREVIOUS_RUN_WITH_THIS_ACCEPTED_STATE:' + snap0['state_hash'][:12])
    _, prev, progress = max(found, key=lambda x: x[0])
    anchors = load_anchors(prev)
    outer, index, changed = position_from_progress(progress, planned,
                                                   anchors.get('origin_outer_cycle_start', origin_start_default))
    return dict(plan, kind='ACCEPTED_STATE_MATCH', previous_run_folder=str(prev),
                saved_record=str(prev / 'CYCLE_PROGRESS.json'), outer_cycle=outer, block_index=index,
                changed_so_far=changed, expected_state_hash=progress['accepted_state_hash'],
                expected_component_hashes=None, previous_accepted_states=int(progress.get('accepted_states', 0)),
                anchors=anchors, candidates=len(found))

