"""LIVE04.8 - .ver checkpoints and continuation of a previous run (synthetic mock only)."""
import json
from pathlib import Path
import pytest
from fake_live04 import Live04Visum
from cordon2025.common import read_json, ContractError
from cordon2025.live04_cycle import run, planned_blocks
from cordon2025.live04_config import load_config
from cordon2025 import live04_continue as cont

OPT = {'min_free_disk_gib': 0, 'com_retry_initial_delay_seconds': 0., 'com_retry_max_delay_seconds': 0.}
RELAX = {'idp_guard': {'max_fine_cdf_rmse_degradation': 1.0, 'max_mean_error_degradation': 1.0}}


def runs(root):
    return sorted((root / 'runs').glob('LIVE04_TGTD_*'), key=lambda p: p.stat().st_mtime_ns)


def go(root, v, over=None, continuation=False):
    o = dict(RELAX, max_cycles=1); o.update(over or {})
    return run(v, output_root=root / 'runs', options=OPT, config_overrides=o, continuation=continuation)


# ----------------------------------------------------------------- units
def test_base_stem_does_not_grow():
    assert cont.base_stem('R1_2025_X_LIVE04_BASE.ver') == 'R1_2025_X_LIVE04_BASE'
    assert cont.base_stem('R1_2025_X_LIVE04_ACCEPTED_0123abcd.ver') == 'R1_2025_X'
    assert cont.base_stem('R1_2025_X_LIVE04_CKPT_C02_SUPPLY_ADDVAL1_0123abcd_LIVE04_ACCEPTED_89abcdef.ver') == 'R1_2025_X'


def test_position_of_the_real_run_continues_with_supply_in_cycle_2():
    """CYCLE_PROGRESS of the user's run 852bbf8fbea2 (stopped inside C02_SUPPLY_ADDVAL1)."""
    cfg = load_config()
    prog = {'cycles': [
        {'outer_cycle': 1, 'blocks': [{'block': 'GENERATION', 'changed': True}, {'block': 'TD_CORDON', 'changed': False}]},
        {'outer_cycle': 2, 'blocks': [{'block': 'GENERATION', 'changed': True}]}]}
    assert planned_blocks(cfg, 1) == ['GENERATION', 'TD_CORDON']
    assert planned_blocks(cfg, 2) == ['GENERATION', 'SUPPLY_ADDVAL1', 'TD_CORDON']
    assert cont.position_from_progress(prog, lambda o: planned_blocks(cfg, o), 1) == (2, 1, True)
    done = {'cycles': prog['cycles'] + []}
    done['cycles'][-1] = {'outer_cycle': 2, 'blocks': [{'block': b, 'changed': False} for b in planned_blocks(cfg, 2)]}
    assert cont.position_from_progress(done, lambda o: planned_blocks(cfg, o), 1) == (3, 0, False)
    with pytest.raises(ContractError, match='BLOCK_ORDER_MISMATCH'):
        cont.position_from_progress({'cycles': [{'outer_cycle': 2, 'blocks': [{'block': 'TD_CORDON'}]}]},
                                    lambda o: planned_blocks(cfg, o), 1)


def test_next_position():
    assert cont.next_position(['G', 'S', 'T'], 0, 2) == {'outer_cycle': 2, 'block_index': 1}
    assert cont.next_position(['G', 'S', 'T'], 2, 2) == {'outer_cycle': 3, 'block_index': 0}


def test_prune_keeps_only_own_last_checkpoints(tmp_path):
    ck = tmp_path / 'CHECKPOINTS'; ck.mkdir()
    for i in range(4):
        ver = ck / ('R1_2025_LIVE04_CKPT_C01_GENERATION_%08d.ver' % i); ver.write_bytes(b'x')
        cont.write_json(cont.sidecar_path(ver), {'path': str(ver)})
    foreign = ck / 'MY_OWN.ver'; foreign.write_bytes(b'y')
    removed = cont.prune(ck, 2)
    assert len(removed) == 2 and foreign.is_file() and len(list(ck.glob('*_LIVE04_CKPT_*.ver'))) == 2


# ----------------------------------------------------------------- mock runs
def test_checkpoint_after_accepted_block_and_continue_next_cycle(tmp_path):
    v = Live04Visum(tmp_path / 'model')
    source = Path(v.IO.CurrentVersionFile); src_bytes = source.read_bytes()
    r1 = go(tmp_path, v)
    assert r1['status'] == 'MOCK_LIVE04_ACCEPTED'
    f1 = runs(tmp_path)[0]
    last = read_json(f1 / 'LAST_CHECKPOINT.json')
    assert last['schema'] == cont.CKPT_SCHEMA and Path(last['path']).is_file()
    assert Path(last['path']).parent == f1 / 'CHECKPOINTS' and len(list((f1 / 'CHECKPOINTS').glob('*.ver'))) <= 2
    assert last['state_hash'] == read_json(f1 / 'CYCLE_PROGRESS.json')['accepted_state_hash']
    assert source.read_bytes() == src_bytes                       # source .ver never written
    anchors1 = read_json(f1 / cont.ANCHORS_FILE)
    ref1 = read_json(f1 / '00_GENERATION_COEFFICIENT_REFERENCE.json')
    saved = read_json(f1 / 'SAVED_ACCEPTED_VERSION.json')
    assert Path(v.IO.CurrentVersionFile).name == Path(saved['path']).name   # the user opens this file
    # continuation: same plan length (max_cycles=1) -> nothing left
    with pytest.raises(ContractError, match='NO_CYCLE_LEFT'):
        go(tmp_path, v, continuation=True)
    # raise max_cycles: continue with cycle 2, anchors of the ORIGINAL run
    r2 = go(tmp_path, v, {'max_cycles': 2}, continuation=True)
    f2 = runs(tmp_path)[-1]
    c = read_json(f2 / 'CONTINUATION.json')
    assert c['kind'] == 'SAVED_ACCEPTED_VERSION' and c['outer_cycle'] == 2 and c['block_index'] == 0
    assert c['previous_run_folder'] == str(f1) and c['opened_state']['state_hash_match'] is True
    assert sorted(p.name for p in f2.iterdir() if p.name.startswith('C0')) and \
        not any(p.name.startswith('C01_') for p in f2.iterdir())
    a2 = read_json(f2 / cont.ANCHORS_FILE)
    assert a2['origin_state_hash'] == anchors1['origin_state_hash'] and a2['addval1'] == anchors1['addval1']
    assert a2['chain'][-1]['run_folder'] == str(f1)
    ref2 = read_json(f2 / '00_GENERATION_COEFFICIENT_REFERENCE.json')
    assert ref2['values'] == ref1['values'] and ref2['generation_reference_hash'] == ref1['generation_reference_hash']
    assert ref2['policy'].endswith('CARRIED_BY_LIVE04_CONTINUATION')
    assert r2['status'].startswith('MOCK_LIVE04_')
    assert '_LIVE04_ACCEPTED_' not in cont.base_stem(read_json(f2 / 'CONTINUATION.json')['opened_version'])


def test_continue_from_checkpoint_and_from_stop(tmp_path, monkeypatch):
    import cordon2025.live03_td as td
    real = td.td_block

    def boom(*a, **k):
        raise RuntimeError('TEST_TD_BLOCK_FAILURE')
    monkeypatch.setattr(td, 'td_block', boom)
    v = Live04Visum(tmp_path / 'model')
    with pytest.raises(RuntimeError, match='TEST_TD_BLOCK_FAILURE'):
        go(tmp_path, v)
    f1 = runs(tmp_path)[0]
    ck = read_json(f1 / 'LAST_CHECKPOINT.json')
    assert ck['block'] == 'GENERATION' and ck['next'] == {'outer_cycle': 1, 'block_index': 1, 'cycle_changed_so_far': True}
    monkeypatch.setattr(td, 'td_block', real)
    # (a) open the checkpoint .ver
    v.IO.CurrentVersionFile = ck['path']
    r = go(tmp_path, v, continuation=True)
    f2 = runs(tmp_path)[-1]
    c = read_json(f2 / 'CONTINUATION.json')
    assert c['kind'] == 'CHECKPOINT' and (c['outer_cycle'], c['block_index']) == (1, 1)
    assert all(c['opened_state']['component_match'][k] for k in ('addval_hash', 'generation_hash', 'td_hash'))
    assert (f2 / 'C01_TD_CORDON').is_dir() and not (f2 / 'C01_GENERATION').exists()
    cyc = read_json(f2 / 'CYCLE_PROGRESS.json')['cycles'][0]
    assert cyc['continued_from_block_index'] == 1 and [b['block'] for b in cyc['blocks']] == ['TD_CORDON']
    assert r['status'].startswith('MOCK_LIVE04_')


def test_continue_from_saved_at_stop(tmp_path, monkeypatch):
    import cordon2025.live03_td as td
    real = td.td_block
    monkeypatch.setattr(td, 'td_block', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('TEST_TD_BLOCK_FAILURE')))
    v = Live04Visum(tmp_path / 'model')
    with pytest.raises(RuntimeError):
        go(tmp_path, v)
    f1 = runs(tmp_path)[0]
    saved = read_json(f1 / 'SAVED_ACCEPTED_VERSION.json')
    assert Path(v.IO.CurrentVersionFile) == Path(saved['path'])
    monkeypatch.setattr(td, 'td_block', real)
    go(tmp_path, v, continuation=True)
    c = read_json(runs(tmp_path)[-1] / 'CONTINUATION.json')
    assert c['kind'] == 'SAVED_ACCEPTED_VERSION' and (c['outer_cycle'], c['block_index']) == (1, 1)
    assert c['changed_so_far'] is True


def test_continue_refuses_changed_or_foreign_file(tmp_path):
    v = Live04Visum(tmp_path / 'model')
    with pytest.raises(ContractError, match='NO_PREVIOUS_RUN_WITH_THIS_ACCEPTED_STATE'):
        go(tmp_path, v, continuation=True)                       # plain source .ver
    go(tmp_path, v)
    f1 = runs(tmp_path)[-1]
    saved = Path(read_json(f1 / 'SAVED_ACCEPTED_VERSION.json')['path'])
    saved.write_bytes(saved.read_bytes() + b'EDITED')
    with pytest.raises(ContractError, match='CHANGED_SINCE_SAVE'):
        go(tmp_path, v, {'max_cycles': 2}, continuation=True)


def test_checkpoint_can_be_disabled_and_is_validated(tmp_path):
    with pytest.raises(ContractError, match='LIVE04_INVALID_CHECKPOINT'):
        load_config(overrides={'checkpoint': {'enabled': True, 'keep_last': 0}})
    v = Live04Visum(tmp_path / 'model')
    go(tmp_path, v, {'checkpoint': {'enabled': False}})
    f = runs(tmp_path)[0]
    assert not (f / 'CHECKPOINTS').exists() and not (f / 'LAST_CHECKPOINT.json').exists()


def test_continue_launcher_passes_continuation():
    src = (Path(__file__).resolve().parents[1] / 'RUN_R1_2025_CORDON_LIVE04_CONTINUE.py').read_text()
    assert 'continuation=True' in src
    boot = (Path(__file__).resolve().parents[1] / 'cordon_live04_bootstrap.py').read_text()
    assert 'continuation=continuation' in boot


# ----------------------------------------------------------------- LIVE04.8.1 assignment repair
def _pathless_tracking(v):
    """Fixture extension: the procedure-sequence reset (op 1 / op 15, type 9) deletes the saved PrT
    paths unless the same execution also runs the assignment (op 20) - as in Visum."""
    orig = v.execute
    v.paths_gone = False
    v.saves_without_paths = []

    def execute():
        active = [bool(o.values['ACTIVE']) for o in v.ops]
        orig()
        if active[19]:
            v.paths_gone = False
        elif active[0] or active[14]:
            v.paths_gone = True
    v.execute = execute
    save = v.IO.SaveVersion

    def save_version(path):
        if v.paths_gone:
            v.saves_without_paths.append(str(path))
        return save(path)
    v.IO.SaveVersion = save_version
    return v


def test_demand_only_probes_never_leave_a_pathless_model(tmp_path, monkeypatch):
    from cordon2025 import live02_evaluation as le
    v = _pathless_tracking(Live04Visum(tmp_path / 'model'))
    captured_without_paths = []
    orig = le.CordonEvaluator.evaluate

    def evaluate(self, visum, folder, label, **kw):
        if v.paths_gone:
            captured_without_paths.append(str(label))
        return orig(self, visum, folder, label, **kw)
    monkeypatch.setattr(le.CordonEvaluator, 'evaluate', evaluate)
    demand_only = []
    from cordon2025.live04_adapter import CordonLive04Adapter
    orig_do = CordonLive04Adapter.execute_demand_only

    def do(self, plan, folder):
        demand_only.append(str(folder))
        return orig_do(self, plan, folder)
    monkeypatch.setattr(CordonLive04Adapter, 'execute_demand_only', do)
    r = go(tmp_path, v)
    f = runs(tmp_path)[0]
    assert demand_only, 'the fixture run must exercise demand-only probes'
    assert not captured_without_paths, captured_without_paths
    assert not v.saves_without_paths, v.saves_without_paths
    assert not v.paths_gone
    repairs = [read_json(p) for p in f.rglob('ASSIGNMENT_REPAIR.json')]
    assert all(x['status'] == 'REPAIRED_VERIFIED' for x in repairs)
    assert r['status'].startswith('MOCK_LIVE04_')


def test_stop_during_probe_repairs_assignment_before_saving(tmp_path, monkeypatch):
    v = _pathless_tracking(Live04Visum(tmp_path / 'model'))
    from cordon2025.live04_adapter import CordonLive04Adapter
    orig_do = CordonLive04Adapter.execute_demand_only
    calls = {'n': 0}

    def do(self, plan, folder):
        out = orig_do(self, plan, folder)
        calls['n'] += 1
        if 'TD_CORDON' in str(folder):          # stop requested right after a TD probe
            (runs(tmp_path)[0] / 'STOP_REQUESTED').write_text('')
        return out
    monkeypatch.setattr(CordonLive04Adapter, 'execute_demand_only', do)
    with pytest.raises(BaseException):
        go(tmp_path, v)
    f = runs(tmp_path)[0]
    res = read_json(f / '00_RESULT.json')
    assert 'STOP' in res['reason'] and res['status'] == 'LIVE04_STOPPED_MODEL_VERIFIED_AT_LAST_ACCEPTED_STATE'
    assert res['assignment_repair_at_stop']['status'] == 'REPAIRED_VERIFIED'
    assert res['saved_version_at_stop'] and not v.saves_without_paths and not v.paths_gone


def test_continue_from_manually_saved_recomputed_version(tmp_path, monkeypatch):
    """Stopped run without a saved .ver: the user saves the model, RECOMPUTE gives a new BASE .ver;
    the continuation finds the previous run by its exact last accepted state."""
    import cordon2025.live03_td as td
    real = td.td_block
    monkeypatch.setattr(td, 'td_block', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('TEST_TD_BLOCK_FAILURE')))
    v = Live04Visum(tmp_path / 'model')
    with pytest.raises(RuntimeError):
        go(tmp_path, v, {'checkpoint': {'enabled': False}})
    f1 = runs(tmp_path)[0]
    for p in f1.glob('*_LIVE04_ACCEPTED_*'):
        p.unlink()                                   # as in an old release: nothing saved at the stop
    (f1 / 'SAVED_ACCEPTED_VERSION.json').unlink()
    manual = tmp_path / 'model' / 'R1_2025_KOPIE_LIVE04_BASE_MANUAL.ver'
    v.IO.SaveVersion(str(manual))
    monkeypatch.setattr(td, 'td_block', real)
    go(tmp_path, v, continuation=True)
    c = read_json(runs(tmp_path)[-1] / 'CONTINUATION.json')
    assert c['kind'] == 'ACCEPTED_STATE_MATCH' and c['previous_run_folder'] == str(f1)
    assert (c['outer_cycle'], c['block_index']) == (1, 1) and c['opened_state']['state_hash_match'] is True

