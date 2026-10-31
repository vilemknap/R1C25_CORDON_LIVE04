"""LIVE03: survey observation contract, FIRST_LAST/C17 incidence, native frozen-path
prediction (TG STEP1 nodes), TD_CORDON block with IDP guard, joint cycles."""
import csv
import json
from pathlib import Path
import numpy as np
import pytest
from fake_live03 import Live03Visum
from cordon2025.common import ROOT, read_json, ContractError, parent_module
from cordon2025.fixtures import create_cache, config
from cordon2025 import incidence as inc1
from cordon2025 import live03_incidence as inc3
from cordon2025.live03_observations import Contract, validate as validate_obs
from cordon2025.live03_config import load_config, validate_config
from cordon2025.live03_cycle import run
from cordon2025.live02_guard import GuardedCOM, WriteAudit, WriteForbidden
from cordon2025.live02_step1 import CordonStepModel
from cordon2025.session import verify_run

SUPERSEDED = pytest.mark.skip(reason='SUPERSEDED_IN_LIVE04_TREE: parent/ holds the v7 @ 977cef4 donors; the V24917-mode LIVE02/LIVE03 entrypoints fail closed on their old donor pins by design (docs/live04)')

OPT = {'min_free_disk_gib': 0, 'com_retry_initial_delay_seconds': 0., 'com_retry_max_delay_seconds': 0.}
RELAX = {'idp_guard': {'max_fine_cdf_rmse_degradation': 1.0, 'max_mean_error_degradation': 1.0}}
A = (101, 1, 2); B = (102, 2, 3); C = (103, 3, 4)
RA = (101, 2, 1); RB = (102, 3, 2); RC = (103, 4, 3)


def obs_cfg():
    return read_json(ROOT / 'CORDON_LIVE03_CONFIG.json')['observations']


def go(tmp_path, v, overrides=None):
    over = {'max_cycles': 1}
    for k, val in (overrides or {}).items():
        over[k] = val
    return run(v, output_root=tmp_path / 'runs', options=OPT, config_overrides=over)


def folder_of(tmp_path):
    folders = list((tmp_path / 'runs').glob('LIVE03_TGTD_*')); assert len(folders) == 1
    return folders[0]


def td_values(v):
    td = v.ops[5].TripDistributionParameters
    return {c: dict(s.GravitationParameters.values) for c, s in td.strata.items()}


# ------------------------------------------------------------------ contract
def test_contract_targets_follow_survey_report():
    c = Contract(obs_cfg())
    a = c.audit
    assert a['transit_interior_sum'] == 71914 and a['pair_target_unordered_sum'] == 71914
    # isolated (both margins) + 2 x cyclic + NonTransit endpoints, crossing units
    assert a['c17_target_crossings_sum'] == 97290 + 2 * 3614 + 2 * 4608 == 113734
    assert a['rows'] == {'FIRST_LAST': 136, 'EXACT_TWO_HITS': 120, 'ALL_ORDERED_UNIQUE_PAIRS': 120}
    assert c.primary == 'FIRST_LAST' and c.secondary == 'EXACT_TWO_HITS' and c.factor == 1.0
    d = np.load(ROOT / 'data/audited/AUDITED_MATRICES.npz')['OA_Transit_D3_RPDI']
    assert c.pair_cells[(1, 2)] == d[0, 1] and c.pair_cells[(2, 1)] == d[1, 0]
    s1 = next(p for p in a['c17_station_parts'] if p['station'] == 1)
    assert s1['target_crossings'] == c.station_cells[(1, 17)] + c.station_cells[(17, 1)]


@pytest.mark.parametrize('patch,error', [
    ({'pair_matrix': 'ALL'}, 'LIVE03_NONTRANSIT_DOUBLE_COUNT'),
    ({'semantics': 'ALL_ORDERED_UNIQUE_PAIRS'}, 'LIVE03_SEMANTICS_MUST_BE_FIRST_LAST'),
    ({'methods': {'FIRST_LAST': 'SECONDARY', 'EXACT_TWO_HITS': 'PRIMARY'}}, 'LIVE03_FIRST_LAST_MUST_BE_PRIMARY'),
    ({'year_bridge': {'survey_year': 2026, 'model_year': 2025, 'factor': 1.0, 'policy': 'x', 'approval': ''}},
     'LIVE03_YEAR_BRIDGE_APPROVAL_MISSING'),
    ({'c17_components': {'isolated': True, 'cyclic': True, 'cyclic_crossings_per_trip': 3, 'nontransit_endpoints': True}},
     'LIVE03_CYCLIC_MULTIPLICITY'),
])
def test_contract_guards(patch, error):
    o = obs_cfg(); o.update(patch)
    with pytest.raises(ContractError, match=error):
        validate_obs(o)


def test_contract_variants_and_hash_pin():
    o = obs_cfg(); o.update(c17_policy='DISABLED')
    assert Contract(o).row_count('FIRST_LAST') == 120
    o = obs_cfg(); o['c17_components'] = dict(o['c17_components'], nontransit_endpoints=False); o['pair_matrix'] = 'ALL'
    assert Contract(o).audit['pair_target_unordered_sum'] == 76522
    o = obs_cfg(); o['year_bridge'] = dict(o['year_bridge'], factor=1.1)
    assert abs(Contract(o).audit['pair_target_unordered_sum'] - 1.1 * 71914) < 1e-6
    o = obs_cfg(); o['authority_npz_sha256'] = '0' * 64
    with pytest.raises(ContractError, match='LIVE03_AUTHORITY_NPZ_HASH_CHANGED'):
        Contract(o)


# ----------------------------------------------------------------- incidence
def test_first_last_contributions():
    f = inc3.first_last_contributions
    assert f([]) == ()
    assert f([5]) == (((5, 17), 1.0),)
    assert f([1, 2, 3]) == (((1, 3), 1.0),)
    assert f([1, 2, 2, 1]) == (((1, 17), 2.0),)
    assert f([4, 4]) == (((4, 17), 2.0),)
    assert f([1, 2, 1, 3]) == (((1, 3), 1.0),)
    assert f([5], station_rows=False) == ()


def _fixture(tmp_path):
    paths = [('C', 10, 20, 1, [A, B, C], {'NATIVE_CW': 60, 'EXOG_EE_CF': 30}),
             ('C', 10, 20, 2, [A, B], {'NATIVE_CW': 40, 'EXOG_EE_CF': 10}),
             ('C_NOT', 10, 20, 1, [B, C], {'NATIVE_CW_NOT': 50}),
             ('C', 20, 10, 1, [RC, RB, RA], {'NATIVE_CW': 50, 'EXOG_EE_CF': 5}),
             ('C', 30, 40, 1, [], {'NATIVE_CW': 8, 'EXOG_EE_CF': 1}),
             ('C', 50, 60, 1, [A, B, RB, RA, A], {'NATIVE_CW': 7, 'EXOG_EE_CF': 2}),
             ('C', 70, 80, 1, [B], {'NATIVE_CW': 3})]
    p = tmp_path / 'snapshot.sqlite'; m, e = create_cache(p, paths)
    return p, m, e, config(['NATIVE_CW', 'NATIVE_CW_NOT', 'EXOG_EE_CF'])


def test_live03_build_is_identical_to_live01_without_new_methods(tmp_path):
    p, m, e, c = _fixture(tmp_path)
    r1 = inc1.build_from_snapshot(p, m, c, e); r3 = inc3.build_from_snapshot(p, m, c, e)
    assert set(r1) == set(r3) == set(inc1.METHODS)
    for k in r1:
        assert r1[k].rows == r3[k].rows and np.array_equal(r1[k].model, r3[k].model)
        assert np.array_equal(r1[k].operator.values, r3[k].operator.values) and r3[k].frozen is None


def test_first_last_rows_and_frozen_share(tmp_path):
    p, m, e, c = _fixture(tmp_path)
    c = dict(c, enumeration_methods=['FIRST_LAST', 'EXACT_TWO_HITS'], full_share_methods=['FIRST_LAST', 'EXACT_TWO_HITS'])
    r = inc3.build_from_snapshot(p, m, c, e)
    fl = r['FIRST_LAST']
    ix = {(x['origin_station'], x['destination_station']): i for i, x in enumerate(fl.rows)}
    st = {mm for mm in m.values()}
    a, b, cc = m[A], m[B], m[C]
    # [A,B,C]: first/last pair only (FIRST_LAST); [A,B]: pair; repeated path [A,B,RB,RA,A] -> cyclic C17 x2
    assert fl.model[ix[a, cc]] == 90 and fl.model[ix[a, b]] == 50 and fl.model[ix[b, cc]] == 50
    assert fl.model[ix[m[RC], m[RA]]] == 55
    assert fl.model[ix[m[A], 17]] == 2 * 9 and fl.model[ix[b, 17]] == 3
    assert len(fl.rows) == len(st) * (len(st) - 1) + len(st)
    assert fl.audit['metrics']['first_last_cyclic_geometry'] == 1 and fl.audit['metrics']['first_last_single_hit_geometry'] == 1
    # frozen share reproduces the captured rows and predicts a scaled demand linearly
    nos = sorted({z for z in (10, 20, 30, 40, 50, 60, 70, 80)})
    pos = {z: i for i, z in enumerate(nos)}
    mats = {}
    for code in ('NATIVE_CW', 'NATIVE_CW_NOT', 'EXOG_EE_CF'):
        M = np.zeros((len(nos), len(nos)))
        for row in fl.audit['all_od_totals']:
            if row['dseg'] == code:
                M[pos[row['orig']], pos[row['dest']]] = row['volume']
        mats[code] = M
    assert np.allclose(fl.frozen.predict(mats, nos), fl.model)
    mats['NATIVE_CW'] = mats['NATIVE_CW'] * 2
    pred = fl.frozen.predict(mats, nos)
    assert pred[ix[m[A], 17]] == 2 * (2 * 7 + 2) and pred[ix[b, 17]] == 6


# ---------------------------------------------------------------- step model
def test_native_step_model_interpolation_and_correction():
    class Ev:
        method = 'M'; methods = ('M',)
    diag = {'_terms': {'M': {'w': np.ones(2), 'y': np.zeros(2), 'eps': np.zeros(2)}},
            'methods': {'M': {'model': [10.0, 10.0]}}}
    sm = CordonStepModel(Ev(), diag, None, 1.0)
    sm.set_nodes({1.0: {'M': np.array([20.0, 0.0])}, 0.5: {'M': np.array([12.0, 6.0])}})
    assert np.allclose(sm.volumes(0.5, 'M'), [12, 6]) and np.allclose(sm.volumes(0.25, 'M'), [11, 8])
    assert np.allclose(sm.volumes(0.75, 'M'), [16, 3]) and np.allclose(sm.volumes(1.2, 'M'), [23.2, 0.0])
    sm.set_measured(1.0, {'methods': {'M': {'model': [22.0, 1.0]}}})
    assert np.allclose(sm.volumes(1.0, 'M'), [22, 1]) and np.allclose(sm.volumes(0.5, 'M'), [13, 6.5])


# -------------------------------------------------------------------- guard
class _Grav:
    def __init__(self): self.values = {}
    def SetAttValue(self, k, v): self.values[k] = v


class _Root:
    def __init__(self):
        g = _Grav()
        td = type('TD', (), {'GravitationParameters': g})()
        self.Procedures = type('P', (), {'Operations': type('O', (), {'GetAll': [type('Op', (), {
            'TripDistributionParameters': type('T', (), {'TripDistributionDStratParameters': lambda self, c: td})()})()]})()})()
        self.g = g


def test_guard_td_writes_only_b_c_and_only_when_enabled():
    root = _Root(); audit = WriteAudit()
    gv = GuardedCOM(root, 'Visum', audit)
    grav = gv.Procedures.Operations.GetAll[0].TripDistributionParameters.TripDistributionDStratParameters('X').GravitationParameters
    with pytest.raises(WriteForbidden):
        grav.SetAttValue('PARA_B', 0.3)
    audit.td_writes = True
    grav.SetAttValue('PARA_B', 0.3); grav.SetAttValue('PARA_C', -0.2)
    assert root.g.values == {'PARA_B': 0.3, 'PARA_C': -0.2} and audit.summary()['td_parameter_writes'] == 2
    for bad in (('PARA_A', 1.0), ('PARA_B', 'x'), ('PARA_C', float('nan'))):
        with pytest.raises(WriteForbidden):
            grav.SetAttValue(*bad)


# ------------------------------------------------------------------- config
@pytest.mark.parametrize('path,value,error', [
    (('write_policy', 'td_parameter_writes'), False, 'LIVE03_TD_WRITE_POLICY_MUST_MATCH_BLOCKS'),
    (('td_cordon', 'groups', 'WORK'), ['LONG_E_C'], 'LIVE03_TD_LONG_NOT_IN_CORDON_TD_SCOPE'),
    (('acceptance', 'method'), 'EXACT_TWO_HITS', 'LIVE03_ACCEPTANCE_PRIMARY'),
    (('generation_mode',), 'HOTFIX2_BACKTRACKING', 'LIVE03_REQUIRES_V24917_TARGETED_STEP1'),
    (('blocks_per_cycle',), ['GENERATION', 'SUPPLY'], 'LIVE03_BLOCKS_PER_CYCLE'),
    (('write_policy', 'direct_od_matrix_writes'), True, 'LIVE02_FORBIDDEN_WRITE_FLAG'),
    (('idp_guard', 'role'), 'OBJECTIVE', 'LIVE03_IDP_POLICY'),
])
def test_config_guards(path, value, error):
    cfg = read_json(ROOT / 'CORDON_LIVE03_CONFIG.json'); node = cfg
    for k in path[:-1]:
        node = node[k]
    node[path[-1]] = value
    with pytest.raises(ContractError, match=error):
        validate_config(cfg)


def test_config_loads_and_live02_contract_unchanged():
    cfg = load_config()
    assert cfg['acceptance']['method'] == 'FIRST_LAST' and cfg['write_policy']['td_parameter_writes'] is True
    from cordon2025.live02_config import load_config as load02
    assert load02()['write_policy']['td_parameter_writes'] is False


# ------------------------------------------------------------- end-to-end
@SUPERSEDED
def test_live03_cycle_tg_native_and_td_guarded(tmp_path):
    v = Live03Visum(tmp_path / 'model'); td0 = td_values(v)
    r = go(tmp_path, v)
    f = folder_of(tmp_path)
    assert r['status'] == 'MOCK_LIVE03_ACCEPTED' and r['accepted_by_block'] == {'GENERATION': 1}
    assert r['objective_final'] < r['objective_baseline'] and r['prediction'] == 'NATIVE_DEMAND_ON_FROZEN_PATHS'
    blocks = {b['block']: b for b in r['cycles'][0]['blocks']}
    assert blocks['TD_CORDON']['status'] == 'NO_TD_CANDIDATE'
    # default IDP tolerances reject every TD step of the synthetic model; parameters unchanged
    assert td_values(v) == td0
    td = read_json(f / 'C01_TD_CORDON/TD_BLOCK_RESULT.json')
    assert td['base_parity']['passes'] and any('IDP_' in ' '.join(e['idp'].get('reasons', [])) for e in td['inner'])
    assert read_json(f / 'C01_TD_CORDON/DEMAND_RESTORE/DEMAND_RESTORE_PROOF.json')['snapshot_equal']
    gen = read_json(f / 'C01_GENERATION/GENERATION_BLOCK_RESULT.json')
    nodes = gen['native_prediction']['nodes']
    assert [n['status'] for n in nodes] == ['NATIVE', 'NATIVE']
    att = gen['attempts'][0]
    assert att['status'] == 'ELIGIBLE' and abs(att['predicted_objective'] - att['measured_objective']) < 1e-6 * att['measured_objective']
    plan = read_json(f / 'C01_GENERATION/STEP1_PLAN_01.json')
    assert plan['prediction'] == 'NATIVE_FROZEN_PATHS'
    contract = read_json(f / 'OBSERVATION_CONTRACT.json')
    assert contract['semantics'] == 'FIRST_LAST' and contract['rows']['FIRST_LAST'] == 136
    diag = read_json(f / '01_BASELINE_CAPTURE/CORDON_DIAGNOSTIC.json')
    assert len(diag['methods']['FIRST_LAST']['model']) == 136 and len(diag['methods']['EXACT_TWO_HITS']['model']) == 120
    assert sum(diag['methods']['FIRST_LAST']['model'][120:]) > 0   # single-hit + cyclic mock paths reach C17 rows
    audit = read_json(f / 'WRITE_AUDIT_SUMMARY.json')
    assert not audit['forbidden_attempts'] and audit['td_parameter_writes'] > 0
    assert not v.writes and verify_run(f)['status'] == 'OFFLINE_RUN_CHECKPOINT_VERIFIED'


@SUPERSEDED
def test_live03_td_accepted_in_place_when_guard_allows(tmp_path):
    v = Live03Visum(tmp_path / 'model'); td0 = td_values(v)
    r = go(tmp_path, v, RELAX)
    f = folder_of(tmp_path)
    assert r['accepted_by_block'] == {'GENERATION': 1, 'TD_CORDON': 1} and r['changed_td_components'] == 10
    td = read_json(f / 'C01_TD_CORDON/TD_BLOCK_RESULT.json')
    assert td['status'] == 'ACCEPTED' and td['adopted_in_place']
    assert abs(td['trial']['predicted_objective'] - td['trial']['measured_objective']) < 1e-6 * td['trial']['measured_objective']
    rows = list(csv.DictReader(open(f / 'ACCEPTED_TD_PARAMETERS.csv', encoding='utf-8-sig'), delimiter=';'))
    assert {x['component'] for x in rows} == set(read_json(ROOT / 'CORDON_LIVE03_CONFIG.json')['td_cordon']['groups']['WORK']) | \
        set(read_json(ROOT / 'CORDON_LIVE03_CONFIG.json')['td_cordon']['groups']['SERVICE'])
    now = td_values(v)
    assert now['5_SCHOOL'] == td0['5_SCHOOL'] and now['1_WORK_E_C'] != td0['1_WORK_E_C']
    assert now['1_WORK_E_C']['PARA_A'] == td0['1_WORK_E_C']['PARA_A']
    assert r['objective_final'] < r['cycles'][0]['blocks'][0]['objective_after']
    assert r['saved_version'] and '_LIVE03_ACCEPTED_' in r['saved_version']['path']


@SUPERSEDED
def test_live03_td_trial_rejected_is_rolled_back(tmp_path, monkeypatch):
    from cordon2025.live03_evaluation import Live03Evaluator
    orig = Live03Evaluator.block_gate

    def gate(self, block, before, after, rows):
        d = orig(self, block, before, after, rows)
        if block == 'TD_CORDON' and 'diagnostic_hash' in after:   # measured trial, not a prediction
            d['accepted'] = False; d.setdefault('reasons', []).append('TEST_FORCED_REJECTION')
        return d
    monkeypatch.setattr(Live03Evaluator, 'block_gate', gate)
    v = Live03Visum(tmp_path / 'model'); td0 = td_values(v)
    r = go(tmp_path, v, RELAX)
    f = folder_of(tmp_path)
    td = read_json(f / 'C01_TD_CORDON/TD_BLOCK_RESULT.json')
    assert td['status'] == 'TRIAL_REJECTED_ROLLED_BACK' and r['accepted_by_block'] == {'GENERATION': 1}
    assert td_values(v) == td0
    assert (f / 'C01_TD_CORDON/TRIAL/ROLLBACK/ROLLBACK_PARAMETER_READBACK.json').exists()


@SUPERSEDED
def test_live03_probe_failure_restores_demand_and_stops_verified(tmp_path):
    v = Live03Visum(tmp_path / 'model'); td0 = td_values(v)
    v.fail_execute_on = {5}           # GENERATION: 2 probes + 1 trial; TD: 2nd Jacobian probe fails
    with pytest.raises(Exception):
        go(tmp_path, v, RELAX)
    f = folder_of(tmp_path)
    res = read_json(f / '00_RESULT.json')
    assert res['status'] == 'LIVE03_STOPPED_MODEL_VERIFIED_AT_LAST_ACCEPTED_STATE'
    assert td_values(v) == td0
    assert read_json(f / 'C01_TD_CORDON/DEMAND_RESTORE_AFTER_ERROR/DEMAND_RESTORE_PROOF.json')['snapshot_equal']


@SUPERSEDED
def test_live03_linear_fallback_when_native_prediction_disabled(tmp_path):
    v = Live03Visum(tmp_path / 'model')
    r = go(tmp_path, v, {'native_prediction': {'enabled': False}, 'blocks_per_cycle': ['GENERATION'],
                         'td_cordon': {'enabled': False}, 'write_policy': {'td_parameter_writes': False}})
    f = folder_of(tmp_path)
    assert r['prediction'] == 'LINEAR_V24917' and 'native_prediction' not in read_json(f / 'C01_GENERATION/GENERATION_BLOCK_RESULT.json')
    assert read_json(f / 'C01_GENERATION/STEP1_PLAN_01.json')['prediction'] == 'LINEAR_V24917'
    assert read_json(f / 'WRITE_AUDIT_SUMMARY.json')['td_parameter_writes'] == 0


def test_demand_plan_excludes_every_assignment(tmp_path):
    from cordon2025.live03_predictor import demand_plan
    from cordon2025.live03_config import adapter_config
    v = Live03Visum(tmp_path / 'model')
    cfg = adapter_config(load_config(), 1, [])
    for block in ('GENERATION', 'TD_CORDON'):
        plan = demand_plan(v, cfg, block)
        types = {int(r['no']): int(r['type']) for r in plan['inventory']}
        assert plan['selected_operation_positions'] and all(p < 20 for p in plan['selected_operation_positions'])
        assert not any(types[p] in (100, 101) for p in plan['selected_operation_positions'])
        assert 6 in plan['selected_operation_positions']
        if block == 'GENERATION' or plan['source_plan_mode'] != 'PHASE_SPECIFIC':
            assert 5 in plan['selected_operation_positions']   # TG runs (full-sequence fallback for unknown pre-TD ops)
        else:
            assert 5 not in plan['selected_operation_positions']


@SUPERSEDED
def test_live03_launcher_and_import_restoration(tmp_path):
    import sys
    import RUN_R1_2025_CORDON_LIVE03_TG_TD_CYCLE as entry
    assert entry.main({})['reason'] == 'VISUM_NOT_INJECTED'
    import cordon_live03_bootstrap as bootstrap
    import cordon_visum_bootstrap as original
    v = Live03Visum(tmp_path / 'model')
    path_before = list(sys.path); mods = {k: m for k, m in sys.modules.items() if original._owned(k)}
    result = bootstrap.launch({'Visum': v}, output_root=tmp_path / 'runs', options=OPT,
                              config_overrides={'max_cycles': 1, 'blocks_per_cycle': ['GENERATION'],
                                                'td_cordon': {'enabled': False},
                                                'write_policy': {'td_parameter_writes': False}})
    assert result['status'] == 'MOCK_LIVE03_ACCEPTED', result
    assert list(sys.path) == path_before
    assert {k: m for k, m in sys.modules.items() if original._owned(k)} == mods


@SUPERSEDED
def test_live03_native_prediction_without_gain_does_not_run_a_blind_trial(tmp_path, monkeypatch):
    step = parent_module('r1_15a2_step_search_v24917')
    orig = step.choose_scale

    def none_scale(model, gate, min_improvement, opts, upper):
        plan = orig(model, gate, min_improvement, opts, upper)
        plan.update(scale=None, predicted_rel_improvement=None)
        return plan
    monkeypatch.setattr(step, 'choose_scale', none_scale)
    v = Live03Visum(tmp_path / 'model')
    zones0 = [dict(r) for r in v.Net.Zones.rows]
    r = go(tmp_path, v, {'blocks_per_cycle': ['GENERATION'], 'td_cordon': {'enabled': False},
                         'write_policy': {'td_parameter_writes': False}})
    f = folder_of(tmp_path)
    gen = read_json(f / 'C01_GENERATION/GENERATION_BLOCK_RESULT.json')
    assert gen['stop_reason'] == 'NATIVE_PREDICTION_NO_ROBUST_IMPROVING_SCALE' and not gen['attempts']
    assert read_json(f / 'C01_GENERATION/NATIVE_PREDICTION/RESTORE/DEMAND_RESTORE_PROOF.json')['snapshot_equal']
    assert r['accepted_states'] == 0 and v.executions == 3          # 2 native probes + 1 demand restore, no assignment trial
    assert [dict(r_) for r_ in v.Net.Zones.rows] == zones0


@SUPERSEDED
def test_live03_td_fails_closed_without_idp_reference(tmp_path, monkeypatch):
    from cordon2025 import live03_idp
    def broken(self, label='CURRENT'):
        raise RuntimeError('No conditioned demand in LONG_COMPOSITE')
    monkeypatch.setattr(live03_idp.IdpGuard, 'evaluate', broken)
    v = Live03Visum(tmp_path / 'model'); td0 = td_values(v)
    go(tmp_path, v, RELAX)
    f = folder_of(tmp_path)
    td = read_json(f / 'C01_TD_CORDON/TD_BLOCK_RESULT.json')
    assert td['status'] == 'NO_TD_CANDIDATE' and td['stop_reason'] == 'IDP_BASELINE_UNAVAILABLE'
    assert td_values(v) == td0 and read_json(f / 'WRITE_AUDIT_SUMMARY.json')['td_parameter_writes'] == 0
