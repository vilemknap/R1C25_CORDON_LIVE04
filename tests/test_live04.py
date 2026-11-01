"""LIVE04: the cordon calibrator on the v7 (vilemknap/R1_15A2_V24917_v7 @ 977cef4) runtime.

Synthetic host only (tests/fake_live04.py); never native PTV evidence."""
import numpy as np
import pytest
from fake_live04 import Live04Visum, LONG_PERSON, LONG_VEHICLE
from cordon2025.common import ROOT, read_json, ContractError, parent_module
from cordon2025.live04_config import load_config
from cordon2025.live04_cycle import run
from cordon2025.live04_guard import Live04GuardedCOM, Live04WriteAudit
from cordon2025.live02_guard import WriteForbidden
from cordon2025 import live04_v7 as v7
from cordon2025 import live04_long_mask as longmask
from cordon2025.session import verify_run

OPT = {'min_free_disk_gib': 0, 'com_retry_initial_delay_seconds': 0., 'com_retry_max_delay_seconds': 0.}
RELAX = {'idp_guard': {'max_fine_cdf_rmse_degradation': 1.0, 'max_mean_error_degradation': 1.0}}
GEN_ONLY = {'blocks_per_cycle': ['GENERATION'], 'td_cordon': {'enabled': False},
            'write_policy': {'td_parameter_writes': False}}
TG_ATTRS = ('ADD_PROD_W', 'ADD_ATT_W', 'ADD_PROD_S', 'ADD_ATT_S', 'ADD_SALARY')


def go(tmp_path, v, overrides=None):
    over = {'max_cycles': 1}
    over.update(overrides or {})
    return run(v, output_root=tmp_path / 'runs', options=OPT, config_overrides=over)


def folder_of(tmp_path):
    folders = list((tmp_path / 'runs').glob('LIVE04_TGTD_*')); assert len(folders) == 1
    return folders[0]


def zones(v, attrs=TG_ATTRS):
    return {a: [float(r[a]) for r in v.Net.Zones.rows] for a in attrs}


def runtime_globals():
    mb = parent_module('r1_15a2_multiblock'); dp = parent_module('r1_15a2_demand_policy_v1')
    rt = parent_module('r1_15a2_runtime_v1')
    return (list(mb.GENERATION_ATTRS), dict(mb.GENERATION_ATTR_MAP), mb._reference_coefficient,
            mb._multiplicative_coefficient_bounds, mb._soft_multiplier_bounds, mb._signed_generation_refinement,
            mb.design_generation_candidates, mb._constrain_generation_projection, dp.load_options, rt.execute_procseq,
            parent_module('r1_15a2_mobility_guard_v24917').options,
            parent_module('r1_15a2_mobility_guard_v24917').ATTRACTION_BAND)


# ------------------------------------------------------------------ contract
def test_v7_donors_pinned_and_config_is_the_running_profile_policy():
    assert v7.verify_donor_files() == v7.DONOR_FILES
    cfg = load_config()
    opts = v7.run_options(cfg)
    pin = read_json(ROOT / v7.RUN_OPTIONS_PIN)
    # v7 runs P 0.75-2.5 / A 0.75-4.0; the cordon uses the user-approved P 0.5-3.0 / A 0.5-5.0.
    assert pin['mg_min_ratio'] == 0.75 and pin['mg_max_ratio'] == 2.5
    assert opts['mg_min_ratio'] == 0.5 and opts['mg_max_ratio'] == 3.0
    assert all(opts[k] == val for k, val in v7.CORDON_DEVIATIONS.items())
    policy = v7.targeted_policy(cfg)
    assert policy['envelope']['domestic_hard_by_role'] == {'PROD': [0.5, 3.0], 'ATT': [0.5, 5.0]}
    assert policy['envelope']['refine_domestic_soft_by_role'] == {'PROD': [0.5, 3.0], 'ATT': [0.5, 5.0]}
    assert policy['envelope']['zahr_reference_multiplier'] == [0.5, 10.0]
    mob = v7.mobility_options(cfg)
    assert [mob['lo'], mob['hi']] == [0.5, 3.0] and mob['ws_attraction_coefficient_band'] == [0.5, 5.0]
    assert cfg['v7']['source_commit'].startswith('977cef4')


@pytest.mark.parametrize('over,error', [
    ({'v7': {'run_options': {'mg_max_ratio': 2.0}}}, 'LIVE04_V7_CORDON_DEVIATION:mg_max_ratio'),
    ({'v7': {'run_options': {'td_count_weight': 0.5}}}, 'LIVE04_V7_RUN_OPTION_DRIFT'),
    ({'v7': {'coefficient_envelope': {'PROD': [0.5, 3.5]}}}, 'LIVE04_PROD_ENVELOPE_MUST_EQUAL_MOBILITY_BAND'),
    ({'v7': {'coefficient_envelope': {'ATT': [0.5, 6.0]}}}, 'LIVE04_ATTRACTION_FENCE_MUST_EQUAL_ATT_ENVELOPE'),
    ({'v7': {'coefficient_envelope': {'ATT': [1.2, 5.0]}, 'mobility_guards': {'ws_attraction_coefficient_band': [1.2, 5.0]}}},
     'LIVE04_COEFFICIENT_ENVELOPE:ATT'),
    ({'v7': {'run_options': {'long_generation_enabled': True}}}, 'LIVE04_V7_CORDON_DEVIATION'),
    ({'v7': {'run_options_environment_overrides': True}}, 'LIVE04_V7_ENV_OVERRIDES_FORBIDDEN'),
    ({'write_policy': {'long_post_td_mask_matrix_writes': False}}, 'LIVE04_LONG_MASK_WRITE_POLICY_MUST_MATCH'),
    ({'v7': {'long_post_td_mask': {'minimum_km': 100.0}}}, 'LIVE04_V7_LONG_MASK_POLICY'),
    ({'v7': {'source_commit': 'deadbeef'}}, 'LIVE04_V7_SOURCE_IDENTITY'),
    ({'v7': {'run_options': {'ts_enabled': False}}, '_allow_donor_overrides': True}, 'LIVE04_STEP1_REQUIRED'),
])
def test_config_guards(over, error):
    with pytest.raises(ContractError, match=error):
        load_config(overrides=over)


def test_donor_pin_change_fails_closed(monkeypatch):
    monkeypatch.setitem(v7.DONOR_FILES, 'r1_15a2_mobility_guard_v24917.py', '0' * 64)
    with pytest.raises(ContractError, match='V7_DONOR_FILE_CHANGED:r1_15a2_mobility_guard_v24917.py'):
        v7.verify_donor_files()


def test_guard_allows_only_long_mask_matrices(tmp_path):
    v = Live04Visum(tmp_path / 'model')
    audit = Live04WriteAudit(); g = Live04GuardedCOM(v, 'Visum', audit)
    a = np.zeros((681, 681))
    with pytest.raises(WriteForbidden):                      # permission off
        g.Net.Matrices.ItemByKey(9111).SetValues(a, False)
    audit.long_mask_writes = True
    g.Net.Matrices.ItemByKey(9111).SetValues(a, False)
    g.Net.Matrices.ItemByKey(9293).SetValues(a, False)
    for no, payload, add in ((9305, a, False), (9301, a, False), (9116, a, False), (9111, a.tolist(), False),
                             (9111, a, True), (9111, a - 1.0, False)):
        with pytest.raises(WriteForbidden, match='LIVE04_MATRIX_WRITE_FORBIDDEN'):
            g.Net.Matrices.ItemByKey(no).SetValues(payload, add)
    assert audit.summary()['long_mask_matrices_written'] == [9111, 9293] and v.matrix_writes == [9111, 9293]
    assert audit.summary()['direct_od_matrix_writes'] == 0


def test_runtime_scope_restores_every_global(tmp_path):
    before = runtime_globals()
    v = Live04Visum(tmp_path / 'model')
    cfg = load_config()
    with v7.runtime_scope(cfg, v, [int(r['NO']) for r in v.Net.Zones.rows], [], tmp_path) as status:
        inside = runtime_globals()
        assert inside[3] is not before[3] and inside[9] is not before[9] and inside[6] is not before[6]
        assert status['long_post_td_mask']['installed'] and status['multiblock_patch']['role_reference_tagging']
        # the wider envelope reaches every donor bound and guard used by the design
        mb = parent_module('r1_15a2_multiblock'); mg = parent_module('r1_15a2_mobility_guard_v24917')
        from cordon2025.live04_config import adapter_config
        acfg = adapter_config(cfg, 1, [])
        assert mb._signed_generation_policy(acfg)
        for attr, band in (('ADD_PROD_W', (0.5, 3.0)), ('ADD_ATT_S', (0.5, 5.0))):
            ref = mb._reference_coefficient({}, attr, 5, 1.0)
            lo, hi, _ = mb._multiplicative_coefficient_bounds('DOMESTIC', acfg, current=1.0, reference=ref)
            assert (lo, hi) == band, (attr, lo, hi)
        assert [mg.options()['lo'], mg.options()['hi']] == [0.5, 3.0]
        assert mg.options()['ws_attraction_coefficient_band'] == [0.5, 5.0] and mg.ATTRACTION_BAND == (0.5, 5.0)
    assert runtime_globals() == before


def test_long_decision_rejects_new_short_trips():
    clean = {'_measure': {'status': 'MEASURED', 'below_min_km': 0.0}, 'vehicle_support_clean': True}
    dirty = {'_measure': {'status': 'MEASURED', 'below_min_km': 1.0}, 'vehicle_support_clean': True}
    leak = {'_measure': {'status': 'MEASURED', 'below_min_km': 0.0}, 'vehicle_support_clean': False}
    assert longmask.decide(clean, clean)['passes']
    assert 'LONGGUARD1_NEW_TRIPS_BELOW_MIN_KM' in longmask.decide(clean, dirty)['reasons']
    assert 'LIVE04_LONG_VEHICLE_SUPPORT_NOT_CLEAN' in longmask.decide(clean, leak)['reasons']


# ------------------------------------------------------------------ cycles
def test_live04_cycle_v7_generation_long_mask_and_td(tmp_path):
    v = Live04Visum(tmp_path / 'model')
    r = go(tmp_path, v)
    f = folder_of(tmp_path)
    assert r['status'] == 'MOCK_LIVE04_ACCEPTED' and r['accepted_by_block'] == {'GENERATION': 1, 'TD_CORDON': 1}
    assert r['objective_final'] < r['cycles'][0]['blocks'][0]['objective_after'] < r['objective_baseline']
    assert r['v7_source']['commit'].startswith('977cef4')
    assert r['mobility_band'] == [0.5, 3.0] and r['ws_attraction_band'] == [0.5, 5.0]
    gen = read_json(f / 'C01_GENERATION/GENERATION_BLOCK_RESULT.json')
    assert gen['prediction_authority'] == 'FINAL_IMPLEMENTED_EFFECT_ROWS'
    assert [n['status'] for n in gen['native_prediction']['nodes']] == ['NATIVE', 'NATIVE']
    assert not gen['native_prediction']['model_mutated']          # every node restored to the exact parent
    att = gen['attempts'][0]
    assert att['status'] == 'ELIGIBLE' and abs(att['predicted_objective'] - att['measured_objective']) < 1e-6 * att['measured_objective']
    d = att['decision']
    assert d['mobility_guard_live']['passes'] and d['mobility_guard_live']['mobilityzone1']['passes']
    assert d['longguard1']['passes'] and d['longguard1']['parent_status'] == 'MEASURED'
    fit = read_json(f / 'C01_GENERATION/DESIGN/V7_TARGETED_GENERATION/V24917_FIT_SUMMARY.json')
    assert fit['status'] == 'GUARDED_PROPOSAL' and fit['mobility_guard']['passes']
    solver = fit['fit_summary']['solver']
    assert solver['balance_mode'] == 'HARD' and set(solver['nonlinear_pa_repair']) == {'WORK', 'SERVICE'}
    assert all(v['within_bounds'] for v in solver['nonlinear_pa_repair'].values())
    # LONG post-TD mask in the full trial and in every demand-only probe
    plan = read_json(f / 'C01_GENERATION/TRY_01/ASSIGNMENT/LONG_MASK_EXECUTION_PLAN.json')
    assert [p[0] for p in plan['phases']] == ['THROUGH_TD', 'REALIZATION', 'ASSIGNMENT_SKIMS']
    assert read_json(f / 'C01_GENERATION/TRY_01/ASSIGNMENT/MASK_VEHICLE_LONG/LONG_MASK_RESULT.json')['status'] == 'APPLIED_VERIFIED'
    node = read_json(f / 'C01_GENERATION/NATIVE_PREDICTION/NODE_01/LONG_MASK_DEMAND_ONLY_PLAN.json')
    assert [p[0] for p in node['phases']] == ['THROUGH_TD', 'REALIZATION'] and node['assignment_executed'] is False
    assert r['long_post_td_mask']['final_support_clean'] and r['long_post_td_mask']['matrix_writes'] > 0
    assert sorted(set(v.matrix_writes)) == sorted(LONG_PERSON + LONG_VEHICLE)
    km = v.km >= 80.0
    for no in LONG_PERSON + LONG_VEHICLE + (9305,):
        assert not np.any(v.component[no].values[~km])                 # nothing below 80 km survives
    assert v.realizations > 0
    audit = read_json(f / 'WRITE_AUDIT_SUMMARY.json')
    assert not audit['forbidden_attempts'] and audit['direct_od_matrix_writes'] == 0
    assert audit['long_mask_matrices_written'] == sorted(LONG_PERSON + LONG_VEHICLE)
    td = read_json(f / 'C01_TD_CORDON/TD_BLOCK_RESULT.json')
    assert td['status'] == 'ACCEPTED' and td['adopted_in_place']
    assert read_json(f / 'C01_TD_CORDON/TRIAL/ACCEPTANCE.json')['longguard1']['passes']
    assert r['saved_version'] and '_LIVE04_ACCEPTED_' in r['saved_version']['path']
    assert not v.writes and verify_run(f)['status'] == 'OFFLINE_RUN_CHECKPOINT_VERIFIED'


def test_long_gate_rejects_trial_and_rolls_back(tmp_path, monkeypatch):
    orig = longmask.support_report
    calls = {'trial': 0}

    def report(adapter, folder=None, label='CURRENT'):
        out = orig(adapter, folder, label)
        if label == 'CURRENT':
            calls['trial'] += 1
            if calls['trial'] == 2:                     # the TD_CORDON trial
                out = dict(out, vehicle_support_clean=False, support_clean=False)
        return out
    monkeypatch.setattr(longmask, 'support_report', report)
    v = Live04Visum(tmp_path / 'model')
    td0 = {c: dict(s.GravitationParameters.values) for c, s in v.ops[5].TripDistributionParameters.strata.items()}
    r = go(tmp_path, v, RELAX)
    f = folder_of(tmp_path)
    assert r['accepted_by_block'] == {'GENERATION': 1} and r['generation_counts']['long_gate_rejections'] == 1
    td = read_json(f / 'C01_TD_CORDON/TD_BLOCK_RESULT.json')
    assert td['status'] == 'TRIAL_REJECTED_ROLLED_BACK'
    acc = read_json(f / 'C01_TD_CORDON/TRIAL/ACCEPTANCE.json')
    assert not acc['accepted'] and 'LIVE04_LONG_VEHICLE_SUPPORT_NOT_CLEAN' in acc['reasons']
    assert {c: dict(s.GravitationParameters.values) for c, s in v.ops[5].TripDistributionParameters.strata.items()} == td0
    assert r['long_post_td_mask']['final_support_clean']


def test_unmasked_baseline_blocks_before_any_write(tmp_path):
    v = Live04Visum(tmp_path / 'model', masked_start=False)
    z0 = zones(v)
    with pytest.raises(ContractError, match='LIVE04_BASELINE_LONG_SUPPORT_NOT_MASKED'):
        go(tmp_path, v)
    res = read_json(folder_of(tmp_path) / '00_RESULT.json')
    assert res['status'] == 'LIVE04_BLOCKED_BEFORE_ANY_WRITE' and zones(v) == z0
    assert not v.matrix_writes and v.executions == 0


def test_mobility_data_error_stops_before_any_write(tmp_path):
    v = Live04Visum(tmp_path / 'model')
    v.Net.Zones.rows[3]['FP_1_WORK_E_C'] = -1.0       # domestic zone with invalid production
    z0 = zones(v)
    with pytest.raises(Exception, match='MOBILITY2_BLOCKED_DATA_NOT_A_PLATEAU'):
        go(tmp_path, v, GEN_ONLY)
    f = folder_of(tmp_path)
    gen = read_json(f / 'C01_GENERATION/GENERATION_BLOCK_RESULT.json')
    assert gen['status'] == 'FAILED' and gen['mobility_block']['status'] == 'BLOCKED_MOBILITY_DATA'
    assert zones(v) == z0 and v.executions == 0 and not v.matrix_writes
    assert read_json(f / '00_RESULT.json')['status'] == 'LIVE04_STOPPED_MODEL_VERIFIED_AT_LAST_ACCEPTED_STATE'


def test_mask_write_failure_restores_and_stops_verified(tmp_path):
    v = Live04Visum(tmp_path / 'model')
    z0 = zones(v)
    v.fail_matrix_write = {9293}            # first vehicle-component write of the first probe
    with pytest.raises(Exception):
        go(tmp_path, v, GEN_ONLY)
    f = folder_of(tmp_path)
    res = read_json(f / '00_RESULT.json')
    assert res['status'] == 'LIVE04_STOPPED_MODEL_VERIFIED_AT_LAST_ACCEPTED_STATE'
    result = read_json(f / 'C01_GENERATION/NATIVE_PREDICTION/NODE_01/MASK_VEHICLE_LONG/LONG_MASK_RESULT.json')
    assert result['status'] == 'PREMASK_RESTORED_CALIBRATION_PARENT_RECOMPUTE_REQUIRED' and result['failed_matrix_no'] == 9293
    assert read_json(f / 'C01_GENERATION/NATIVE_PREDICTION/RESTORE_AFTER_ERROR/DEMAND_RESTORE_PROOF.json')['snapshot_equal']
    assert zones(v) == z0


def test_linear_genfix2_prediction_when_native_disabled(tmp_path):
    v = Live04Visum(tmp_path / 'model')
    over = dict(GEN_ONLY, native_prediction={'enabled': False})
    r = go(tmp_path, v, over)
    f = folder_of(tmp_path)
    assert r['prediction'] == 'GENFIX2_FINAL_EFFECT_LINEAR'
    plan = read_json(f / 'C01_GENERATION/STEP1_PLAN_01.json')
    assert plan['prediction'] == 'GENFIX2_FINAL_EFFECT_LINEAR' and plan['grid']
    assert plan['scale'] is not None and all(not row['reasons'] for row in plan['grid'] if row['feasible'])
    gen = read_json(f / 'C01_GENERATION/GENERATION_BLOCK_RESULT.json')
    assert gen['prediction_authority'] == 'FINAL_IMPLEMENTED_EFFECT_ROWS' and 'native_prediction' not in gen
    final = read_json(f / 'C01_GENERATION/TRY_01/GENFIX2_FINAL_MOBILITY_AND_PREDICTION.json')
    assert final['mobility']['passes'] and final['prediction']['available']
    methods = read_json(f / '01_BASELINE_CAPTURE/CORDON_DIAGNOSTIC.json')['methods']
    assert set(final['prediction']['delta']) == set(methods)
    assert all(len(final['prediction']['delta'][m]) == len(methods[m]['model']) for m in methods)


def test_long_school_fixed_and_deferred(tmp_path):
    v = Live04Visum(tmp_path / 'model'); v.enable_long_school()
    attrs = ('ADD_PROD_L', 'ADD_ATT_L', 'ADD_PROD_SCH', 'ADD_ATT_SCH')
    before = zones(v, attrs)
    r = go(tmp_path, v, GEN_ONLY)
    f = folder_of(tmp_path)
    status = read_json(f / 'V7_RUNTIME_STATUS.json')
    assert status['long_school']['active'] is True and 'ADD_PROD_L' in status['generation_attributes']
    fit = read_json(f / 'C01_GENERATION/DESIGN/V7_TARGETED_GENERATION/V24917_FIT_SUMMARY.json')
    assert fit['long_school']['status'] == 'SCHOOL_TG_FIXED_AMDY_LONG_TG_DEFERRED'
    mz = read_json(f / 'C01_GENERATION/DESIGN/V7_TARGETED_GENERATION/MOBILITYZONE1_PARENT.json')
    assert {'WORK', 'SERVICE', 'LONG', 'SCHOOL'} <= set(mz['families'])
    assert r['status'] == 'MOCK_LIVE04_ACCEPTED' and zones(v, attrs) == before
    assert not set(attrs) & set(read_json(f / 'WRITE_AUDIT_SUMMARY.json')['tg_attributes_written'])


def test_boundary_lever_joint_fit(tmp_path):
    v = Live04Visum(tmp_path / 'model')
    crossing = [int(z['NO']) for z in v.Net.Zones.rows][650:681]
    r = go(tmp_path, v, dict(GEN_ONLY, _allow_donor_overrides=True, v7={'run_options': {'bd_zones': crossing}}))
    f = folder_of(tmp_path)
    status = read_json(f / 'V7_RUNTIME_STATUS.json')
    assert status['boundary']['active'] is True and status['boundary']['zones'] == crossing
    assert status['bdpa']['installed'] is True
    fit = read_json(f / 'C01_GENERATION/DESIGN/V7_TARGETED_GENERATION/V24917_FIT_SUMMARY.json')
    # The synthetic crossings carry no cordon path, so the joint fit has no exposed boundary variable.
    assert fit['boundary'] is not None and fit['boundary']['boundary_variables_in_fit'] == 0
    assert r['status'] in ('MOCK_LIVE04_ACCEPTED', 'MOCK_LIVE04_NO_ACCEPTED_CHANGE')
    assert not read_json(f / 'WRITE_AUDIT_SUMMARY.json')['forbidden_attempts']


def test_live04_launcher_and_import_restoration(tmp_path):
    import sys
    import RUN_R1_2025_CORDON_LIVE04_V7_TG_TD_CYCLE as entry
    assert entry.main({})['reason'] == 'VISUM_NOT_INJECTED'
    import cordon_live04_bootstrap as bootstrap
    import cordon_visum_bootstrap as original
    v = Live04Visum(tmp_path / 'model')
    path_before = list(sys.path); mods = {k: m for k, m in sys.modules.items() if original._owned(k)}
    result = bootstrap.launch({'Visum': v}, output_root=tmp_path / 'runs', options=OPT,
                              config_overrides=dict(GEN_ONLY, max_cycles=1))
    assert result['status'] == 'MOCK_LIVE04_ACCEPTED', result
    assert list(sys.path) == path_before
    assert {k: m for k, m in sys.modules.items() if original._owned(k)} == mods


@pytest.mark.parametrize('native', [True, False])
def test_rejected_generation_trial_then_second_trial_runs(tmp_path, monkeypatch, native):
    """After a rejected trial the TG outputs (FP_*) still hold that trial until the next
    recompute; the next trial must not be blocked as a stale MOBILITYZONE1 parent."""
    from cordon2025.live03_evaluation import Live03Evaluator
    orig = Live03Evaluator.block_gate
    seen = {'measured': 0}

    def gate(self, block, before, after, rows):
        d = orig(self, block, before, after, rows)
        if block == 'GENERATION' and 'diagnostic_hash' in after:
            seen['measured'] += 1
            if seen['measured'] == 1:
                d['accepted'] = False; d.setdefault('reasons', []).append('TEST_FORCED_REJECTION')
        return d
    monkeypatch.setattr(Live03Evaluator, 'block_gate', gate)
    v = Live04Visum(tmp_path / 'model')
    r = go(tmp_path, v, dict(GEN_ONLY, native_prediction={'enabled': native}))
    f = folder_of(tmp_path)
    gen = read_json(f / 'C01_GENERATION/GENERATION_BLOCK_RESULT.json')
    if not native:
        assert read_json(f / 'C01_GENERATION/STEP1_PLAN_02.json')['mode'] == 'SECANT_MEASURED'
    statuses = [a['status'] for a in gen['attempts']]
    assert statuses[0] == 'REJECTED' and statuses[-1] == 'ELIGIBLE', statuses
    assert 'REJECTED_PRE_APPLY_GATE' not in statuses
    assert r['accepted_by_block'] == {'GENERATION': 1}
    assert r['long_post_td_mask']['final_support_clean']


def test_two_cycles_keep_mobility_anchor_and_long_support(tmp_path):
    v = Live04Visum(tmp_path / 'model')
    r = go(tmp_path, v, dict(GEN_ONLY, max_cycles=2, stop_after_cycle_without_change=False))
    f = folder_of(tmp_path)
    assert len(r['cycles']) == 2 and r['accepted_states'] >= 1
    assert (f / 'C02_GENERATION/GENERATION_BLOCK_RESULT.json').exists()
    gen2 = read_json(f / 'C02_GENERATION/GENERATION_BLOCK_RESULT.json')
    assert gen2['status'] in ('ACCEPTED', 'CONFIGURED_GENERATION_SEARCH_EXHAUSTED'), gen2.get('error')
    assert r['long_post_td_mask']['final_support_clean']
    assert not read_json(f / 'WRITE_AUDIT_SUMMARY.json')['forbidden_attempts']


def test_combusy2_rejected_call_in_masked_trial_repeats_block(tmp_path):
    """RPC_E_CALL_REJECTED inside the masked full trial (assignment phase): COMBUSY2 rolls
    back to the verified parent and repeats the GENERATION block."""
    from fake_visum_startup import BusyError
    v = Live04Visum(tmp_path / 'model')
    # 2 native nodes x (2 demand phases + 2 restore phases) = 8; the trial runs 9..11.
    def busy(h):
        if h.executions == 11:
            raise BusyError('Volany odmitl volani (synthetic RPC_E_CALL_REJECTED)')
    v.on_execute = busy
    r = go(tmp_path, v, GEN_ONLY)
    f = folder_of(tmp_path)
    assert (f / 'C01_GENERATION_RETRY1' / 'GENERATION_BLOCK_RESULT.json').exists()
    assert r['accepted_by_block'] == {'GENERATION': 1} and r['long_post_td_mask']['final_support_clean']
    assert not read_json(f / 'WRITE_AUDIT_SUMMARY.json')['forbidden_attempts']


# ------------------------------------------------------------------ LIVE04.1 run memory
def _force_reject(monkeypatch, block, trials):
    """Reject the measured trials of `block` with these ordinals (1-based)."""
    from cordon2025.live03_evaluation import Live03Evaluator
    orig = Live03Evaluator.block_gate
    seen = {'n': 0}

    def gate(self, blk, before, after, rows):
        d = orig(self, blk, before, after, rows)
        if blk == block and 'diagnostic_hash' in after:
            seen['n'] += 1
            if seen['n'] in trials:
                d['accepted'] = False; d.setdefault('reasons', []).append('TEST_FORCED_REJECTION')
        return d
    monkeypatch.setattr(Live03Evaluator, 'block_gate', gate)


def test_memory_unit_rules():
    from cordon2025.live04_memory import RunMemory, direction_from_rows
    cfg = dict(load_config()['memory'])
    mem = RunMemory(cfg)
    mem.begin_cycle(1)
    d = direction_from_rows([{'family': 'WORK', 'role': 'PROD', 'zone_no': 5, 'log_step': 0.2},
                             {'family': 'WORK', 'role': 'ATT', 'zone_no': 7, 'log_step': -0.1}])
    mem.record_tg_correction(d, 0.5, {'M': [1.0, 2.0]}, {'M': [2.0, 2.0]})
    assert mem.tg_correction(d) == (None, None)                     # same cycle: never
    mem.begin_cycle(2)
    corr, info = mem.tg_correction({k: 2 * v for k, v in d.items()})
    assert info['used'] and abs(info['cosine'] - 1) < 1e-12
    assert np.allclose(corr['M'], 0.5 * 2 * np.array([-2.0, 0.0]))  # weight x norm ratio x (meas-prior)/scale
    corr, info = mem.tg_correction({'WORK|PROD|9': 1.0})
    assert corr is None and info['used'] is False                   # dissimilar direction
    mem.begin_cycle(5)
    assert mem.tg_correction(d) == (None, None)                     # older than max_age_cycles
    mem.begin_cycle(5)
    mem.store_td(['a', 'b'], {'M': np.ones((3, 2))}, 'TEST')
    assert mem.td_jacobian(['a', 'b'], {'M': 3}) is not None
    assert mem.td_jacobian(['a', 'c'], {'M': 3}) is None and mem.td_jacobian(['a', 'b'], {'M': 4}) is None
    mem.record_curvature({1.0: {'M': [3.0]}, 0.5: {'M': [2.0]}}, {'M': [1.0]}, 'M')
    assert mem.node_fractions([1.0, 0.5]) == [1.0]                  # curvature 0 -> one node
    off = RunMemory(dict(cfg, enabled=False)); off.begin_cycle(3)
    off.store_td(['a'], {'M': np.ones((1, 1))}, 'X')
    assert off.td_jacobian(['a'], {'M': 1}) is None and off.node_fractions([1.0, 0.5]) == [1.0, 0.5]


def test_memory_td_jacobian_reused_after_verification(tmp_path, monkeypatch):
    _force_reject(monkeypatch, 'TD_CORDON', {1, 2})
    v = Live04Visum(tmp_path / 'model', route_gamma=0.5)
    r = go(tmp_path, v, dict(RELAX, max_cycles=2, stop_after_cycle_without_change=False, blocks_per_cycle=['TD_CORDON']))
    f = folder_of(tmp_path)
    c1 = read_json(f / 'C01_TD_CORDON/TD_BLOCK_RESULT.json'); c2 = read_json(f / 'C02_TD_CORDON/TD_BLOCK_RESULT.json')
    assert c1['jacobian_source'] == 'NATIVE_PROBES' and c2['jacobian_source'] == 'MEMORY_VERIFIED'
    assert c2['jacobian_memory']['relative_error'] <= c2['jacobian_memory']['tolerance']
    assert not list((f / 'C02_TD_CORDON/NATIVE').glob('JAC_*')) and (f / 'C02_TD_CORDON/NATIVE/MEM_VERIFY').exists()
    assert c2['native_evaluations'] < c1['native_evaluations']
    assert read_json(f / 'MEMORY/RUN_MEMORY.json')['td']['source'] == 'LOCAL_FROZEN_PATH_JACOBIAN'
    assert r['memory']['config']['enabled'] is True


def test_memory_td_rejected_jacobian_falls_back_to_probes(tmp_path, monkeypatch):
    _force_reject(monkeypatch, 'TD_CORDON', {1, 2})
    v = Live04Visum(tmp_path / 'model')
    go(tmp_path, v, dict(RELAX, max_cycles=2, stop_after_cycle_without_change=False, blocks_per_cycle=['TD_CORDON'],
                         memory={'td_verify_tolerance': 0.0}))
    f = folder_of(tmp_path)
    c2 = read_json(f / 'C02_TD_CORDON/TD_BLOCK_RESULT.json')
    assert c2['jacobian_source'] == 'NATIVE_PROBES_MEMORY_REJECTED'
    assert len(list((f / 'C02_TD_CORDON/NATIVE').glob('JAC_*'))) == 6


def test_memory_route_correction_improves_tg_prediction(tmp_path, monkeypatch):
    _force_reject(monkeypatch, 'GENERATION', {1, 2, 3})       # cycle 1 stays at the baseline
    v = Live04Visum(tmp_path / 'model', route_gamma=0.5)
    over = dict(GEN_ONLY, max_cycles=2, stop_after_cycle_without_change=False,
                generation_search={'max_trials': 1})
    go(tmp_path, v, over)
    f = folder_of(tmp_path)
    g1 = read_json(f / 'C01_GENERATION/GENERATION_BLOCK_RESULT.json')
    g2 = read_json(f / 'C02_GENERATION/GENERATION_BLOCK_RESULT.json')
    a1 = g1['attempts'][0]
    assert abs(a1['predicted_objective'] - a1['measured_objective']) > 1e-3 * a1['measured_objective']  # route choice
    assert g2['memory_route_correction']['used'] and g2['memory_route_correction']['cosine'] > 0.99
    a2 = g2['attempts'][0]
    err_with = abs(a2['predicted_objective'] - a2['measured_objective'])
    err_without = abs(a2['predicted_objective_without_memory'] - a2['measured_objective'])
    assert err_with < err_without


def test_memory_disabled_is_live04_behaviour(tmp_path):
    results = []
    for enabled in (True, False):
        v = Live04Visum(tmp_path / ('model_%s' % enabled))
        r = run(v, output_root=tmp_path / ('runs_%s' % enabled), options=OPT,
                config_overrides=dict(GEN_ONLY, max_cycles=1, memory={'enabled': enabled}))
        results.append((r['objective_final'], zones(v)))
    assert results[0] == results[1]


def test_wider_domestic_envelope_reaches_the_model(tmp_path):
    """User decision 2026-11-01: ADD_PROD 0.5-3.0, ADD_ATT 0.5-5.0 (v7 profile run: 0.75-2.5 / 0.75-4.0)."""
    v = Live04Visum(tmp_path / 'model')
    for r in v.Net.Zones.rows[:16]:
        r['ADD_PROD_W'] = 2.4; r['ADD_PROD_S'] = 2.4; r['ADD_ATT_W'] = 3.9; r['ADD_ATT_S'] = 3.9
    v._capture_fp_units()                       # FP_* follow the start coefficients
    v.base_params.update({a: v.zone_vector(a) for a in ('ADD_PROD_W', 'ADD_PROD_S', 'ADD_ATT_W', 'ADD_ATT_S')})
    r = go(tmp_path, v, GEN_ONLY)
    assert r['accepted_by_block'] == {'GENERATION': 1}
    prod = [float(z[a]) for z in v.Net.Zones.rows for a in ('ADD_PROD_W', 'ADD_PROD_S')]
    att = [float(z[a]) for z in v.Net.Zones.rows for a in ('ADD_ATT_W', 'ADD_ATT_S')]
    assert max(prod) > 2.5 and max(prod) <= 3.0 + 1e-9 and min(prod) >= 0.5 - 1e-9
    assert max(att) > 4.0 and max(att) <= 5.0 + 1e-9 and min(att) >= 0.5 - 1e-9
    d = read_json(folder_of(tmp_path) / 'C01_GENERATION/GENERATION_BLOCK_RESULT.json')['attempts'][-1]['decision']
    assert d['mobility_guard_live']['passes']
