"""LIVE04.4: v7 @ 7b4c681 Generation (no CATCH_UP, +/-5 %, measured zonal refit, prediction audit),
SupplyMix on the cordon rows and SEVRELAX3 on the cordon rows.

Synthetic host only (tests/fake_live04.py); never native PTV evidence."""
import math
import numpy as np
import pytest
from fake_live04 import Live04Visum
from cordon2025.common import read_json, ContractError, parent_module
from cordon2025.live04_config import load_config, row_guard_policy, adapter_config
from cordon2025.live04_cycle import run
from cordon2025 import live04_severity as sev
from cordon2025 import live04_v7 as v7
from cordon2025.live04_evaluation import Live04Evaluator

OPT = {'min_free_disk_gib': 0, 'com_retry_initial_delay_seconds': 0., 'com_retry_max_delay_seconds': 0.}
GEN_ONLY = {'blocks_per_cycle': ['GENERATION'], 'td_cordon': {'enabled': False},
            'write_policy': {'td_parameter_writes': False}}
SUPPLY_FROM_C1 = {'v7': {'run_options': {'sp_start_cycle': 1}}, '_allow_donor_overrides': True}


def go(tmp_path, v, overrides=None):
    over = {'max_cycles': 1}
    over.update(overrides or {})
    return run(v, output_root=tmp_path / 'runs', options=OPT, config_overrides=over)


def folder_of(tmp_path):
    folders = list((tmp_path / 'runs').glob('LIVE04_TGTD_*')); assert len(folders) == 1
    return folders[0]


def merged(*parts):
    out = {}
    for p in parts:
        for k, v in p.items():
            if isinstance(v, dict) and isinstance(out.get(k), dict):
                out[k] = merged(out[k], v)
            else:
                out[k] = v
    return out


def addval(v):
    return {(r['NO'], r['FROMNODENO'], r['TONODENO']): float(r.get('ADDVAL1', 0.0)) for r in v.Net.Links.rows}


# ------------------------------------------------------------------ SEVRELAX3 rules
POLICY = row_guard_policy(load_config())


def test_row_guard_policy_is_the_v7_sevrelax3():
    assert (POLICY['protected_before_geh'], POLICY['protected_after_hard_geh'], POLICY['max_single_row_geh_increase'],
            POLICY['high_geh_threshold'], POLICY['max_high_geh_increase']) == (5.0, 40.0, 50.0, 60.0, 30.0)
    assert POLICY['scope_budgets']['generation'] == {'max_severity20_relative_degradation': 0.2,
                                                     'max_severity30_relative_degradation': 0.25,
                                                     'max_geh40_net_count_increase': 10}
    assert POLICY['scope_budgets']['td']['max_geh40_net_count_increase'] == 25
    assert POLICY['scope_budgets']['supply']['max_severity20_relative_degradation'] == 0.35


def model_for_geh(geh, observed):
    """model > observed with the given GEH."""
    # 2(m-o)^2 = g^2 (m+o)
    g2 = geh * geh
    a = 2.0; b = -4.0 * observed - g2; c = 2.0 * observed * observed - g2 * observed
    return (-b + math.sqrt(b * b - 4 * a * c)) / (2 * a)


def case(before_gehs, after_gehs, observed=10000.0):
    y = np.full(len(before_gehs), observed)
    b = np.array([model_for_geh(g, observed) for g in before_gehs])
    a = np.array([model_for_geh(g, observed) for g in after_gehs])
    return b, a, y


@pytest.mark.parametrize('before,after,block,ok,reason', [
    ([3.0] + [30.0] * 9, [39.0] + [30.0] * 9, 'GENERATION', True, None),
    ([3.0] + [30.0] * 9, [40.5] + [30.0] * 9, 'GENERATION', False, 'PROTECTED_CORDON_ROW_GUARD_FAILED'),
    ([10.0] * 10, [59.0] + [10.0] * 9, 'TD_CORDON', True, None),
    ([10.0] * 10, [61.0] + [10.0] * 9, 'TD_CORDON', False, 'SINGLE_CORDON_ROW_GEH_INCREASE_EXCEEDED'),
    ([45.0] + [10.0] * 9, [74.0] + [10.0] * 9, 'TD_CORDON', True, None),
    ([45.0] + [10.0] * 9, [76.0] + [10.0] * 9, 'TD_CORDON', False, 'HIGH_GEH_CORDON_ROW_DELTA_BUDGET_EXCEEDED'),
])
def test_row_limits(before, after, block, ok, reason):
    b, a, y = case(before, after)
    loose = {s: {'max_severity20_relative_degradation': math.inf, 'max_severity30_relative_degradation': math.inf,
                 'max_geh40_net_count_increase': 5000} for s in ('generation', 'td', 'supply')}
    out = sev.evaluate(b, a, y, None, block, dict(POLICY, scope_budgets=loose))   # row limits only
    assert out['passes'] is ok, out['reasons']
    if reason:
        assert reason in out['reasons']


def test_scope_severity_budgets_differ_by_block():
    # one row 60 -> 65.8: severity20 +30.6 %, severity30 +42.4 % (generation 20/25 % fail, supply 35/45 % pass)
    b, a, y = case([60.0, 25.0] + [5.0] * 8, [65.8, 25.0] + [5.0] * 8)
    s20 = sev.relative_degradation(sev.severity(b, y)['severity20'], sev.severity(a, y)['severity20'])
    assert 0.25 < s20 < 0.35
    assert 'CORDON_SEVERITY20_BUDGET_EXCEEDED' in sev.evaluate(b, a, y, None, 'GENERATION', POLICY)['reasons']
    assert sev.evaluate(b, a, y, None, 'SUPPLY_ADDVAL1', POLICY)['passes']
    assert sev.evaluate(b, a, y, None, 'TD_CORDON', POLICY)['passes']
    # rows without an observation are not judged (v7: CAL rows with a count only)
    b2, a2, y2 = b.copy(), a.copy(), y.copy(); y2[0] = 0.0
    assert sev.evaluate(b2, a2, y2, None, 'GENERATION', POLICY)['passes']
    # net GEH40 count budget (generation: 10)
    b, a, y = case([30.0] * 12, [41.0] * 12)
    out = sev.evaluate(b, a, y, None, 'GENERATION', dict(POLICY, scope_budgets={
        'generation': {'max_severity20_relative_degradation': math.inf, 'max_severity30_relative_degradation': math.inf,
                       'max_geh40_net_count_increase': 10}}))
    assert out['geh40_net_count_increase'] == 12 and out['reasons'] == ['CORDON_GEH40_NET_COUNT_BUDGET_EXCEEDED']


def test_zero_parent_severity_follows_v7():
    b, a, y = case([5.0] * 4, [21.0] + [5.0] * 3)
    out = sev.evaluate(b, a, y, None, 'GENERATION', POLICY)
    assert out['severity20_degradation_infinite'] and 'CORDON_SEVERITY20_BUDGET_EXCEEDED' in out['reasons']
    assert sev.relative_degradation(0.0, 0.0) == 0.0


def test_evaluator_gate_applies_guard_to_predicted_and_measured_diags():
    ev = Live04Evaluator.__new__(Live04Evaluator)
    ev.method = 'FIRST_LAST'; ev.secondary = None; ev.row_guard_policy = POLICY
    ev.live02 = {'acceptance': {'minimum_absolute_improvement': 1e-8, 'min_relative_improvement': 0.0,
                                'secondary_max_relative_degradation': 0.0}}
    b, a, y = case([3.0, 80.0, 80.0], [45.0, 20.0, 20.0])
    def diag(m, j):
        return {'valid': True, 'methods': {'FIRST_LAST': {'objective': j, 'metrics': {}, 'model': list(m),
                                                         'observed': list(y), 'pairs': [[1, 2], [1, 3], [2, 3]]}}}
    d = ev.block_gate('GENERATION', diag(b, 10.0), diag(a, 5.0), [])
    assert not d['accepted'] and d['reasons'] == ['PROTECTED_CORDON_ROW_GUARD_FAILED']
    assert d['row_geh_guard']['protected_rows_to_hard'][0]['row'] == '1-2'
    predicted = {'valid': True, 'methods': {'FIRST_LAST': {'objective': 5.0, 'metrics': {}, 'model': list(a)}}}
    assert not ev.block_gate('GENERATION', diag(b, 10.0), predicted, [])['accepted']
    ev.row_guard_policy = dict(POLICY, enabled=False)
    assert ev.block_gate('GENERATION', diag(b, 10.0), diag(a, 5.0), [])['accepted']


def test_row_guard_rejects_native_trial(tmp_path):
    v = Live04Visum(tmp_path / 'model')
    r = go(tmp_path, v, merged(GEN_ONLY, {'v7': {'run_options': {'sev_scope_budgets': {
        'generation': {'max_severity20_relative_degradation': 0.0, 'max_severity30_relative_degradation': 0.0,
                       'max_geh40_net_count_increase': 0}}, 'sev_max_single_profile_geh_increase': 0.0}},
        '_allow_donor_overrides': True}))
    f = folder_of(tmp_path)
    plans = sorted(f.glob('C01_GENERATION/STEP1_PLAN_*.json'))
    assert plans
    # a single-row GEH increase of 0 forbids every step that worsens any row
    assert r['row_geh_guard']['max_single_row_geh_increase'] == 0.0
    for acc in f.glob('C01_GENERATION/TRY_*/ACCEPTANCE.json'):
        d = read_json(acc)
        assert 'row_geh_guard' in d
        if not d['row_geh_guard']['passes']:
            assert not d['accepted']


# ------------------------------------------------------------------ Generation (v7 @ 7b4c681)
def test_generation_refine_only_with_fine_caps(tmp_path):
    cfg = load_config()
    tg = parent_module('r1_15a2_targeted_generation_v24917')
    assert v7.run_options(cfg)['tg_catchup_enabled'] is False
    acfg = adapter_config(cfg, 1, [])
    policy = acfg['v24917_targeted_generation']
    for cycle in (1, 7, 19, 60):
        stage = adapter_config(cfg, cycle, [])
        over = tg.overlay_cfg(stage, 'REFINE')
        assert over['max_add_log_up'] <= math.log(1.05) + 1e-12
        assert over['max_add_log_down'] <= -math.log(0.95) + 1e-12
    assert policy['refine_max_log_up'] == pytest.approx(math.log(1.05))
    v = Live04Visum(tmp_path / 'model')
    go(tmp_path, v, GEN_ONLY)
    f = folder_of(tmp_path)
    design = read_json(f / 'C01_GENERATION' / 'GENERATION_BLOCK_RESULT.json')['design']
    assert design['phase'] == 'REFINE'
    assert (f / 'C01_GENERATION' / 'TRY_01' / 'STEP1_PRED_AUDIT.json').exists()
    audit = read_json(f / 'C01_GENERATION' / 'TRY_01' / 'STEP1_PRED_AUDIT.json')
    assert audit['status'] == 'MEASURED_PREDICTION_COMPARISON' and audit['acceptance_authority'] is False
    assert audit['new_com_reads'] == 0 and len(audit['rows']) == 136
    # production coefficients carry their P effect directly: one accepted step stays within +/-5 %
    rows = list(__import__('csv').DictReader(open(f / 'ACCEPTED_TG_PARAMETERS.csv', encoding='utf-8-sig'), delimiter=';'))
    ratios = [float(r['ratio']) for r in rows if r['attr'] in ('ADD_PROD_W', 'ADD_PROD_S')]
    assert ratios and all(0.95 - 1e-9 <= x <= 1.05 + 1e-9 for x in ratios), (min(ratios), max(ratios))


def test_measured_zonal_refit_after_rejected_trial(tmp_path, monkeypatch):
    from cordon2025.live03_evaluation import Live03Evaluator
    original = Live03Evaluator.block_gate
    calls = {'n': 0}

    def first_native_trial_rejected(self, block, before, after, rows):
        d = original(self, block, before, after, rows)
        if block == 'GENERATION' and after.get('label') == 'STEP1_TRIAL':
            calls['n'] += 1
            if calls['n'] == 1:
                d = dict(d, accepted=False, reasons=list(d.get('reasons') or []) + ['TEST_FORCED_REJECTION'])
        return d
    monkeypatch.setattr(Live03Evaluator, 'block_gate', first_native_trial_rejected)
    v = Live04Visum(tmp_path / 'model')
    r = go(tmp_path, v, GEN_ONLY)
    f = folder_of(tmp_path)
    rec = read_json(f / 'C01_GENERATION' / 'GENERATION_BLOCK_RESULT.json')
    refit = read_json(f / 'C01_GENERATION' / 'MEASURED_ZONAL_REFIT.json')
    assert refit['status'] == 'ZONAL_DIRECTION_REFITTED', refit
    assert refit['authority'] == 'LOCAL_PROPOSAL_ONLY_NOT_NATIVE_ZONAL_JACOBIAN'
    assert refit['trust_fraction_of_original_box'] <= 0.5
    assert refit['prediction_error_l2_after'] <= refit['prediction_error_l2_before'] + 1e-9
    assert rec['attempts'][0]['status'] == 'REJECTED' and len(rec['attempts']) >= 2
    plan2 = read_json(f / 'C01_GENERATION' / 'STEP1_PLAN_02.json')
    assert plan2['mode'] == 'MEASURED_ZONAL_REFIT'
    assert rec['attempts'][1]['plan_mode'] == 'MEASURED_ZONAL_REFIT'
    assert r['status'] in ('MOCK_LIVE04_ACCEPTED', 'MOCK_LIVE04_NO_ACCEPTED_CHANGE')
    # the refit never bypasses the native gate: the model is the last accepted state or the baseline
    assert r['write_audit']


# ------------------------------------------------------------------ SupplyMix on the cordon rows
SUPPLY_HOST = dict(route_gamma=0.3, addval_beta=0.4, bypass_anchor=True)


def test_supply_mix_options_are_the_v7_ones():
    from cordon2025.live04_supply import options, supply_policy, due
    o = options(load_config())
    assert (o['max_groups'], o['max_edges'], o['max_trials'], o['step_units']) == (24, 240, 4, [8, 6, 4, 2])
    assert (o['every_n'], o['start_cycle']) == (2, 2)
    assert [due(c, o)[0] for c in (1, 2, 3, 4)] == [False, True, False, True]
    policy, seq, steps, repl = supply_policy(o)
    assert (policy.lattice, policy.max_step, policy.max_cumulative) == (0.5, 8.0, 15.0)
    assert steps == [16, 8, 6, 4, 2, 1] and repl == {'min_attribution_coverage': 0.5, 'max_candidates': 144}


def lock_station_links(monkeypatch):
    """Counted station links are not ADDVAL1 actuators in this test (no collateral on every pair of a station)."""
    from cordon2025.live04_adapter import CordonLive04Adapter
    from cordon2025.authority import mapping
    from cordon2025.common import ROOT
    stations, _ = mapping(ROOT / 'data/audited/STATION_MAPPING.csv')
    original = CordonLive04Adapter.read_links

    def read_links(self):
        links = original(self)
        for key in stations:
            if key in links:
                links[key]['eligible'] = False
        return links
    monkeypatch.setattr(CordonLive04Adapter, 'read_links', read_links)


def test_supply_mix_accepts_cordon_driven_addval1_trial(tmp_path, monkeypatch):
    lock_station_links(monkeypatch)
    v = Live04Visum(tmp_path / 'model', **SUPPLY_HOST)
    a0 = addval(v)
    r = go(tmp_path, v, merged(GEN_ONLY, SUPPLY_FROM_C1))
    f = folder_of(tmp_path)
    rec = read_json(f / 'C01_SUPPLY_ADDVAL1' / 'SUPPLYMIX_BLOCK_RESULT.json')
    assert rec['status'] == 'ACCEPTED', rec.get('error') or rec.get('stop_reason') or rec['attempts']
    assert r['accepted_by_block'].get('SUPPLY_ADDVAL1') == 1
    assert [b['block'] for b in r['cycles'][0]['blocks']] == ['GENERATION', 'SUPPLY_ADDVAL1']
    cand = read_json(f / 'C01_SUPPLY_ADDVAL1' / ('TRY_%02d' % rec['accepted_trial']) / 'SUPPLYMIX_CANDIDATE.json')
    assert 0 < len(cand['members']) <= 24 and 0 < len(cand['changes']) <= 240
    assert all(float(c['new']).is_integer() for c in cand['changes'])
    keys = [tuple(c['key']) for c in cand['changes']]
    assert len(set(keys)) == len(keys)
    a1 = addval(v)
    changed = {k for k in a1 if a1[k] != a0[k]}
    assert changed == set(keys) and r['changed_addval1_links'] == len(keys)
    assert r['supply_mix']['addval1_writes'] >= len(keys)
    acc = read_json(f / 'C01_SUPPLY_ADDVAL1' / ('TRY_%02d' % rec['accepted_trial']) / 'ACCEPTANCE.json')
    assert acc['accepted'] and acc['row_geh_guard']['scope'] == 'supply' and acc['row_geh_guard']['passes']
    assert acc['longguard1']['passes']
    design = read_json(f / 'C01_SUPPLY_ADDVAL1' / 'DESIGN' / 'SUPPLY_PATH_SEQUENCE_DESIGN.json')
    assert design['authority']['authority'] == 'CORDON_DIAGNOSTIC_PATH_STORE_OF_THE_PARENT'
    kinds = {b['kind'] for c in design['candidates'] for b in c['bundles']}
    assert {'ON', 'OFF'} <= kinds                   # diverge/rejoin branches around the station link
    assert r['objective_final'] < r['cycles'][0]['blocks'][0]['objective_after']
    plan = read_json(next((f / 'C01_SUPPLY_ADDVAL1').glob('TRY_*/ASSIGNMENT/**/*PLAN*.json'))) \
        if list((f / 'C01_SUPPLY_ADDVAL1').glob('TRY_*/ASSIGNMENT/**/*PLAN*.json')) else None
    assert v.matrix_writes == [] or set(v.matrix_writes) <= set(range(9111, 9116)) | set(range(9291, 9296))


def test_supply_mix_rejected_trials_roll_back_exactly(tmp_path):
    v = Live04Visum(tmp_path / 'model', route_gamma=0.3, addval_beta=-0.4, bypass_anchor=True)   # wrong-way response
    r = go(tmp_path, v, merged(GEN_ONLY, SUPPLY_FROM_C1))
    f = folder_of(tmp_path)
    rec = read_json(f / 'C01_SUPPLY_ADDVAL1' / 'SUPPLYMIX_BLOCK_RESULT.json')
    assert rec['status'] == 'NO_ACCEPTED_TRIAL' and rec['attempts']
    assert all(a['status'] == 'REJECTED' for a in rec['attempts'])
    assert len(rec['attempts']) <= 4
    rb = read_json(f / 'C01_SUPPLY_ADDVAL1' / 'ROLLBACK_SUMMARY.json')
    assert rb['passes'] and rb['diagnostic_equal'] and rb['snapshot_equal']
    assert r['changed_addval1_links'] == 0 and all(x == 0.0 for x in addval(v).values())
    assert 'SUPPLY_ADDVAL1' not in r['accepted_by_block']


def test_supply_mix_not_due_and_disabled(tmp_path):
    v = Live04Visum(tmp_path / 'model', **SUPPLY_HOST)
    r = go(tmp_path / 'a', v, GEN_ONLY)                       # v7 schedule: first SupplyMix in cycle 2
    assert [b['block'] for b in r['cycles'][0]['blocks']] == ['GENERATION']
    v = Live04Visum(tmp_path / 'm2', **SUPPLY_HOST)
    r = go(tmp_path / 'b', v, merged(GEN_ONLY, SUPPLY_FROM_C1, {'supply_mix': {'enabled': False},
                                                                'write_policy': {'supply_addval1_writes': False}}))
    assert [b['block'] for b in r['cycles'][0]['blocks']] == ['GENERATION'] and not r['supply_mix']['enabled']


def test_supply_mix_config_guards():
    for over, err in (({'write_policy': {'supply_addval1_writes': False}}, 'LIVE04_SUPPLY_WRITE_POLICY_MUST_MATCH'),
                      ({'supply_mix': {'drivers': 'PROFILES'}}, 'LIVE04_SUPPLY_MIX_POLICY'),
                      ({'row_geh_guard': {'row_weight': 2.0}}, 'LIVE04_ROW_GEH_GUARD_POLICY'),
                      ({'v7': {'run_options': {'sp_max_groups': 12}}}, 'LIVE04_V7_RUN_OPTION_DRIFT')):
        with pytest.raises(ContractError, match=err):
            load_config(overrides=over)


def test_supply_writes_need_permission(tmp_path):
    from cordon2025.live04_guard import Live04GuardedCOM, Live04WriteAudit
    from cordon2025.live02_guard import WriteForbidden
    v = Live04Visum(tmp_path / 'model', **SUPPLY_HOST)
    audit = Live04WriteAudit(); g = Live04GuardedCOM(v, 'Visum', audit)
    link = list(g.Net.Links.GetAll)[0]
    with pytest.raises(WriteForbidden):
        link.SetAttValue('ADDVAL1', 1)
    audit.supply_addval_writes = True
    link.SetAttValue('ADDVAL1', 1)
    for attr, value in (('TYPENO', 1), ('ADDVAL1', float('nan')), ('ADDVAL1', True)):
        with pytest.raises(WriteForbidden):
            link.SetAttValue(attr, value)
    assert audit.summary()['supply_addval1_writes'] == 1
