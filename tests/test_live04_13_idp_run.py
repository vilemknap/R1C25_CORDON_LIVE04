"""LIVE04.13: cumulative IDP run reference for GENERATION and TD_CORDON (user decision 2026-11-19).

Synthetic mock only (tests/fake_live04.py) - not native PTV Visum evidence."""
import copy
import json
from pathlib import Path
import pytest
from cordon2025.common import ROOT, read_json, ContractError, canonical_hash
from cordon2025.live04_config import load_config
from cordon2025 import live04_idp_run as ir
from cordon2025.live03_idp import IdpGuard, REFERENCE_SHA256

COMPS = ('A', 'B')


def fake_guard(rmse_tol=0.01, floor=0.03, mean_tol=0.02):
    g = IdpGuard.__new__(IdpGuard)
    g.guarded = list(COMPS)
    g.rmse_tol, g.mean_floor, g.mean_tol = rmse_tol, floor, mean_tol
    g.distance_by_component = {'A': 9726, 'B': 9727}
    g.fixed_distance_hashes = {9726: 'a' * 64, 9727: 'b' * 64}
    g.matrix_nos = [9101, 9102]
    return g


def metrics(**kw):
    out = {}
    for k in COMPS:
        rmse, rel = kw.get(k, (0.05, 0.0))
        out[k] = {'fine_cdf_rmse': rmse, 'mean_relative_error': rel, 'mean_model_km': 10.0 * (1 + rel),
                  'mean_target_km': 10.0, 'objective': 0.0, 'fine_cdf_ks': 0.0}
    return out


def idp_cfg(**cum):
    cfg = copy.deepcopy(load_config()['idp_guard'])
    cfg['cumulative'].update(cum)
    return cfg


def reference(start=None, monkeypatch=None, **cum):
    g = fake_guard()
    if monkeypatch is not None:
        monkeypatch.setattr(ir, 'matrices_sha256', lambda guard: 'm' * 64)
    rec = ir.capture(g, idp_cfg(**cum), start or metrics(), 'S' * 64, '/runs/R1')
    return g, rec, ir.RunReference(rec)


def test_release_policy_is_the_approved_one():
    cfg = load_config()['idp_guard']
    c = cfg['cumulative']
    assert c['enabled'] is True and c['blocks'] == ['GENERATION', 'TD_CORDON']
    assert (c['fine_cdf_rmse_degradation'], c['mean_relative_error_degradation'], c['mean_error_floor']) == (0.01, 0.02, 0.0)
    assert c['reference'] == ir.POLICY
    assert set(cfg['blocks']) == {'TD_CORDON', 'GENERATION'}
    # the local guard is unchanged (TD methodology incl. its floor)
    assert (cfg['max_fine_cdf_rmse_degradation'], cfg['mean_error_floor'], cfg['max_mean_error_degradation']) == (0.01, 0.03, 0.02)
    dflt = read_json(ROOT / 'provenance/live04_user_config/CORDON_LIVE04_CONFIG.RELEASE_DEFAULT.json')['idp_guard']
    assert dflt == cfg


@pytest.mark.parametrize('over,code', [
    ({'idp_guard': {'cumulative': {'fine_cdf_rmse_degradation': -0.1}}}, 'LIVE04_IDP_CUMULATIVE_TOLERANCE'),
    ({'idp_guard': {'cumulative': {'blocks': ['SUPPLY_ADDVAL1']}}}, 'LIVE04_IDP_CUMULATIVE_BLOCKS'),
    ({'idp_guard': {'cumulative': {'reference': 'CURRENT_STATE'}}}, 'LIVE04_IDP_CUMULATIVE_REFERENCE_POLICY'),
    ({'idp_guard': {'cumulative': {'extra': 1}}}, 'LIVE04_IDP_CUMULATIVE_FIELDS'),
    ({'idp_guard': {'blocks': ['TD_CORDON']}}, 'LIVE04_IDP_CUMULATIVE_BLOCK_WITHOUT_LOCAL_GUARD'),
    ({'idp_guard': {'enabled': False}}, 'LIVE04_IDP_CUMULATIVE_NEEDS_IDP_GUARD'),
])
def test_invalid_cumulative_policy_is_rejected(over, code):
    with pytest.raises(ContractError, match=code):
        load_config(overrides=over)


def test_cumulative_rule_per_component_without_floor(monkeypatch):
    _, _, ref = reference(metrics(A=(0.05, 0.0), B=(0.08, -0.10)), monkeypatch)
    assert ref.decide(metrics(A=(0.0599, 0.0199), B=(0.0899, -0.1199)))['passes']
    d = ref.decide(metrics(A=(0.0601, 0.0), B=(0.08, -0.10)))
    assert not d['passes'] and d['reasons'] == ['IDP_CUMULATIVE_FINE_CDF_RMSE_DEGRADED:A']
    # no mean-error floor: from e = 0 at most 2 percentage points (the local floor would allow 5)
    d = ref.decide(metrics(A=(0.05, 0.0201)))
    assert d['reasons'] == ['IDP_CUMULATIVE_MEAN_DISTANCE_DEGRADED:A']
    assert ref.decide(metrics(A=(0.05, -0.0201)))['reasons'] == ['IDP_CUMULATIVE_MEAN_DISTANCE_DEGRADED:A']
    # an improvement of B never compensates A
    d = ref.decide(metrics(A=(0.07, 0.0), B=(0.0, 0.0)))
    assert not d['passes'] and d['reasons'] == ['IDP_CUMULATIVE_FINE_CDF_RMSE_DEGRADED:A']
    row = {r['component']: r for r in d['components']}['A']
    assert row['rmse_start'] == 0.05 and row['rmse_allowed'] == pytest.approx(0.06)
    # missing / failed evaluation fails closed
    assert not ref.decide({'error': 'X'})['passes']
    assert ref.decide({'A': metrics()['A']})['reasons'] == ['IDP_CUMULATIVE_COMPONENT_MISSING:B']


def test_small_local_steps_cannot_accumulate(monkeypatch):
    """Each step passes the local guard (+0.006 RMSE vs its parent); the second one breaks
    the cumulative limit (+0.012 vs the run start) and is rejected."""
    guard, _, ref = reference(metrics(), monkeypatch)
    states = [metrics(), metrics(A=(0.056, 0.0)), metrics(A=(0.062, 0.0))]
    decisions = []
    for parent, cand in zip(states, states[1:]):
        local = guard.decide(parent, cand)
        assert local['passes']
        decisions.append(ir.combine(local, ref.decide(cand)))
    assert decisions[0]['passes'] and not decisions[1]['passes']
    assert decisions[1]['reasons'] == ['IDP_CUMULATIVE_FINE_CDF_RMSE_DEGRADED:A']
    assert decisions[1]['cumulative']['record_sha256'] == ref.record['record_sha256']
    # a local failure is reported first and the candidate fails even if cumulative passes
    local_bad = {'passes': False, 'reasons': ['IDP_FINE_CDF_RMSE_DEGRADED:B']}
    out = ir.combine(local_bad, ref.decide(metrics()))
    assert not out['passes'] and out['reasons'] == ['IDP_FINE_CDF_RMSE_DEGRADED:B']


def test_record_is_immutable_and_verified(monkeypatch):
    guard, rec, ref = reference(monkeypatch=monkeypatch)
    assert rec['finecdf_reference_sha256'] == REFERENCE_SHA256 and rec['input_matrices_sha256'] == 'm' * 64
    again = ir.RunReference(json.loads(json.dumps(rec)))            # RUN_ANCHORS.json round trip
    assert again.record == rec
    assert ref.verify(guard, idp_cfg())['passes']
    bad = json.loads(json.dumps(rec)); bad['components']['A']['fine_cdf_rmse'] = 0.5
    with pytest.raises(ContractError, match='LIVE04_IDP_RUN_REFERENCE_RECORD_CHANGED'):
        ir.RunReference(bad)
    with pytest.raises(ContractError, match='MISMATCH:TOLERANCES'):
        ref.verify(guard, idp_cfg(fine_cdf_rmse_degradation=0.02))
    g2 = fake_guard(); g2.fixed_distance_hashes = {9726: 'c' * 64, 9727: 'b' * 64}
    with pytest.raises(ContractError, match='MISMATCH:DISTANCE_SHA256'):
        ref.verify(g2, idp_cfg())
    g3 = fake_guard(); g3.guarded = ['A']
    with pytest.raises(ContractError, match='MISMATCH:COMPONENTS'):
        ref.verify(g3, idp_cfg())


def test_continuation_without_reference_stops(monkeypatch, tmp_path):
    class Adapter:
        visum = None
        zones = [1, 2]
    monkeypatch.setattr('cordon2025.live03_idp.IdpGuard', lambda visum, n, cfg: fake_guard())
    with pytest.raises(ContractError, match='LIVE04_IDP_RUN_REFERENCE_MISSING_IN_CONTINUATION'):
        ir.establish(Adapter(), idp_cfg(), {}, continuation=True, state_hash='S', folder=tmp_path,
                     write_json=lambda p, o: None)
    # a fresh run measures the reference once and puts it into the anchors
    monkeypatch.setattr(ir, 'matrices_sha256', lambda guard: 'm' * 64)
    g = fake_guard()
    g.evaluate = lambda label: metrics()
    monkeypatch.setattr('cordon2025.live03_idp.IdpGuard', lambda visum, n, cfg: g)
    written = {}
    anchors = {}
    a = Adapter()
    ref = ir.establish(a, idp_cfg(), anchors, continuation=False, state_hash='S', folder=tmp_path,
                       write_json=lambda p, o: written.setdefault(Path(p).name, o))
    assert a.idp_run_reference is ref and anchors['idp_run_reference'] == ref.record
    assert written['IDP_RUN_REFERENCE.json']['verification']['source'] == 'MEASURED_AT_RUN_START'
    # the continuation uses the carried record and never re-measures
    g.evaluate = lambda label: pytest.fail('a continuation must not re-measure the reference')
    b = Adapter()
    ref2 = ir.establish(b, idp_cfg(), anchors, continuation=True, state_hash='OTHER', folder=tmp_path,
                        write_json=lambda p, o: written.__setitem__(Path(p).name, o))
    assert ref2.record == ref.record
    assert written['IDP_RUN_REFERENCE.json']['verification']['source'] == 'CARRIED_FROM_ORIGIN_RUN'
    # disabled: nothing measured, no reference
    c = Adapter()
    assert ir.establish(c, idp_cfg(enabled=False), {}, continuation=False, state_hash='S', folder=tmp_path,
                        write_json=lambda p, o: None) is None and c.idp_run_reference is None


# ----------------------------------------------------------------- mock runs
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fake_live04 import Live04Visum                       # noqa: E402
from cordon2025.live04_cycle import run                   # noqa: E402
from cordon2025 import live04_continue as cont            # noqa: E402

OPT = {'min_free_disk_gib': 0, 'com_retry_initial_delay_seconds': 0., 'com_retry_max_delay_seconds': 0.}
GEN_ONLY = {'blocks_per_cycle': ['GENERATION'], 'td_cordon': {'enabled': False},
            'write_policy': {'td_parameter_writes': False}}


def runs(root):
    return sorted((root / 'runs').glob('LIVE04_TGTD_*'), key=lambda p: p.stat().st_mtime_ns)


def go(root, v, over=None, continuation=False):
    o = dict(GEN_ONLY, max_cycles=1); o.update(over or {})
    return run(v, output_root=root / 'runs', options=OPT, config_overrides=o, continuation=continuation)


def test_generation_trial_is_measured_against_parent_and_run_reference_then_continued(tmp_path):
    v = Live04Visum(tmp_path / 'model')
    r = go(tmp_path, v)
    f1 = runs(tmp_path)[0]
    ref = read_json(f1 / 'IDP_RUN_REFERENCE.json')
    assert ref['verification']['source'] == 'MEASURED_AT_RUN_START' and ref['schema'] == ir.SCHEMA
    assert ref['state_hash'] == read_json(f1 / 'RESTORE_POINT.json')['state_hash']
    anchors = read_json(f1 / cont.ANCHORS_FILE)
    assert anchors['idp_run_reference']['record_sha256'] == ref['record_sha256']
    gen = read_json(f1 / 'C01_GENERATION/GENERATION_BLOCK_RESULT.json')
    assert (f1 / 'C01_GENERATION/IDP_BEFORE.json').is_file() and gen['idp_before_vs_run_reference']['passes']
    att = gen['attempts'][-1]
    assert set(att['idp']) == set(ref['guarded']) and all('fine_cdf_rmse' in x for x in att['idp'].values())
    gd = att['decision']['idp_guard']
    assert gd['schema'] == 'LIVE03_IDP_GUARD_V1' and gd['cumulative']['record_sha256'] == ref['record_sha256']
    assert [row['component'] for row in gd['cumulative']['components']] == ref['guarded']
    assert r['accepted_by_block'] == {'GENERATION': 1}
    # continuation: the ORIGINAL run reference is carried and verified, never re-measured
    go(tmp_path, v, {'max_cycles': 2}, continuation=True)
    f2 = runs(tmp_path)[-1]
    ref2 = read_json(f2 / 'IDP_RUN_REFERENCE.json')
    assert ref2['verification']['source'] == 'CARRIED_FROM_ORIGIN_RUN'
    assert ref2['record_sha256'] == ref['record_sha256'] and ref2['origin_run_folder'] == str(f1)
    assert read_json(f2 / cont.ANCHORS_FILE)['idp_run_reference'] == anchors['idp_run_reference']
    # a previous run without a verifiable reference: the continuation stops, no silent re-capture
    a = read_json(f2 / cont.ANCHORS_FILE)
    a['idp_run_reference']['components'][ref['guarded'][0]]['fine_cdf_rmse'] = 0.0
    (f2 / cont.ANCHORS_FILE).write_text(json.dumps(a), encoding='utf-8')
    with pytest.raises(ContractError, match='LIVE04_IDP_RUN_REFERENCE_RECORD_CHANGED'):
        go(tmp_path, v, {'max_cycles': 3}, continuation=True)
    del a['idp_run_reference']
    (f2 / cont.ANCHORS_FILE).write_text(json.dumps(a), encoding='utf-8')
    with pytest.raises(ContractError, match='LIVE04_IDP_RUN_REFERENCE_MISSING_IN_CONTINUATION'):
        go(tmp_path, v, {'max_cycles': 3}, continuation=True)


def test_cumulative_rejection_rolls_generation_back(tmp_path, monkeypatch):
    calls = []

    def reject(self, after):
        calls.append(after is not None and 'error' not in after)
        return {'passes': False, 'reasons': ['IDP_CUMULATIVE_FINE_CDF_RMSE_DEGRADED:TEST'],
                'record_sha256': self.record['record_sha256']}
    monkeypatch.setattr(ir.RunReference, 'decide', reject)
    v = Live04Visum(tmp_path / 'model')
    r = go(tmp_path, v)
    f = runs(tmp_path)[0]
    gen = read_json(f / 'C01_GENERATION/GENERATION_BLOCK_RESULT.json')
    measured = [a for a in gen['attempts'] if a.get('decision')]
    assert measured and all(a['status'] == 'REJECTED' for a in measured)
    assert all('IDP_CUMULATIVE_FINE_CDF_RMSE_DEGRADED:TEST' in a['decision']['reasons'] for a in measured)
    assert gen['status'] != 'ACCEPTED' and r['accepted_by_block'] == {}
    assert all(calls)                         # decided on real FineCDF evaluations of the trials
    assert read_json(f / 'CYCLE_PROGRESS.json')['accepted_state_hash'] == read_json(f / 'RESTORE_POINT.json')['state_hash']
    assert not read_json(f / 'WRITE_AUDIT_SUMMARY.json')['forbidden_attempts']


def test_generation_without_idp_baseline_writes_nothing(tmp_path, monkeypatch):
    import cordon2025.live03_idp as idpmod
    real = idpmod.IdpGuard.evaluate

    def failing(self, label='CURRENT'):
        if label == 'BEFORE':
            raise RuntimeError('TEST_IDP_UNAVAILABLE')
        return real(self, label)
    monkeypatch.setattr(idpmod.IdpGuard, 'evaluate', failing)
    v = Live04Visum(tmp_path / 'model')
    r = go(tmp_path, v)
    gen = read_json(runs(tmp_path)[0] / 'C01_GENERATION/GENERATION_BLOCK_RESULT.json')
    assert gen['status'] == 'NO_GENERATION_CANDIDATE' and gen['stop_reason'] == 'IDP_BASELINE_UNAVAILABLE'
    assert not gen['attempts'] and r['accepted_by_block'] == {}


# ----------------------------------------------------------------- stage B (LIVE04.14)
def test_generation_idp_model_learns_and_caps_the_scale(monkeypatch):
    _, _, ref = reference(metrics(A=(0.05, 0.0), B=(0.05, 0.0)), monkeypatch)
    local = load_config()['idp_guard']
    m = ir.GenerationIdpModel(COMPS, {'slack_use': 0.7, 'min_direction_norm': 0.0})
    d = {'WORK|PROD': 0.1, 'WORK|ATT': 0.05}
    now = metrics(A=(0.05, 0.0), B=(0.05, 0.0))
    assert m.max_scale(d, now, now, ref, local) == (None, {'status': 'NO_MODEL'})
    # one measured trial at scale 0.5: RMSE_A +0.004, e_B +0.01
    after = metrics(A=(0.054, 0.0), B=(0.05, 0.01))
    assert m.update(d, 0.5, now, after)['status'] == 'UPDATED'
    cap, audit = m.max_scale(d, now, now, ref, local)
    # rates per unit scale: RMSE_A 0.008 -> 0.7*0.01/0.008 = 0.875 ; |e_B| 0.02 -> 0.7*0.02/0.02 = 0.7
    assert cap == pytest.approx(0.7) and audit['binding']['component'] == 'B' and audit['binding']['feature'] == 'MEAN'
    # the same step predicted exactly afterwards (Broyden secant)
    assert m.update(d, 0.5, now, after)['error_before'] == pytest.approx(0.0, abs=1e-12)
    # a direction that improves IDP is not capped
    m2 = ir.GenerationIdpModel(COMPS, {'slack_use': 0.7, 'min_direction_norm': 0.0})
    m2.update(d, 1.0, now, metrics(A=(0.04, 0.0), B=(0.05, 0.0)))
    assert m2.max_scale(d, now, now, ref, local)[0] is None
    assert ir.direction([{'family': 'WORK', 'role': 'PROD', 'log_step': 0.2},
                         {'family': 'WORK', 'role': 'PROD', 'log_step': 0.0}]) == {'WORK|PROD': 0.1}


def test_generation_prediction_config():
    with pytest.raises(ContractError, match='LIVE04_IDP_GENERATION_PREDICTION_SLACK'):
        load_config(overrides={'idp_guard': {'generation_prediction': {'slack_use': 0.0}}})
