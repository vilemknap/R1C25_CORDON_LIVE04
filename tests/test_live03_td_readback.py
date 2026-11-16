"""TD native-write representation and exact post-write freeze, synthetic only."""
from copy import deepcopy
from types import SimpleNamespace
import math
import pytest
from cordon2025.common import ContractError, parent_module, read_json
from cordon2025.live03_td_parameters import (bind_write_readback, capture_write_readback,
                                           expected_parameters, assert_trial_freeze)


def case():
    before = {'td_values': [
        {'component': 'WORK_E_C', 'current_b': 1.7546875, 'current_c': -0.542615476401332, 'status': 'OK'},
        {'component': 'LONG_E_C', 'current_b': 5.95501408, 'current_c': -0.0623552, 'status': 'OK'}],
        'fixed_link_hash': 'F', 'dseg_hash': 'D', 'operations_hash': 'O',
        'generation_hash': 'G', 'addval1': {}, 'matrices': [], 'dseg_map': {}}
    requested = [dict(before['td_values'][0], candidate_b=1.8171875, candidate_c=-0.5131735862345678)]
    live = expected_parameters(before, requested)
    live[0]['current_b'] = math.nextafter(live[0]['current_b'], math.inf)
    live[0]['current_c'] = math.nextafter(live[0]['current_c'], -math.inf)
    return before, requested, live


def donor():
    return parent_module('r1_15a2_controller_v22')


def test_existing_write_limit_and_exact_freeze_disagree_until_native_readback_is_bound():
    before, requested, live = case()
    before['matrices'] = [{'matrix_no': 9101, 'sha256_float64_le': 'BEFORE'}]
    after = dict(before, td_values=live, matrices=[{'matrix_no': 9101, 'sha256_float64_le': 'AFTER'}])
    cfg = {'matrix_scope_by_block': {'TD_CORDON': {'matrix_nos': [9101]}}}
    err = parent_module('r1_15a2_supply').SupplyContractError
    # Reproduce the old false failure with unchanged donor instructions.
    with pytest.raises(err, match='UNREQUESTED_TD_PARAMETER_CHANGE'):
        donor().assert_freeze(before, after, 'TD_CORDON', rows=requested, cfg=cfg)
    original = deepcopy(requested)
    effective, diffs = bind_write_readback(before, requested, live)
    assert len(diffs) == 2 and max(abs(d['delta']) for d in diffs) < 1e-14
    assert requested == original and effective[0]['requested_c'] == original[0]['candidate_c']
    donor().assert_freeze(before, after, 'TD_CORDON', rows=effective, cfg=cfg)


@pytest.mark.parametrize('damage', ['untargeted_b', 'untargeted_status', 'target_status', 'too_far',
                                    'nan', 'bool', 'missing', 'extra', 'duplicate', 'duplicate_request',
                                    'wrong_parent', 'zero_c', 'negative_b'])
def test_invalid_write_readbacks_remain_blocked(damage):
    before, requested, live = case()
    if damage == 'untargeted_b': live[1]['current_b'] = math.nextafter(live[1]['current_b'], math.inf)
    elif damage == 'untargeted_status': live[1]['status'] = 'OTHER'
    elif damage == 'target_status': live[0]['status'] = 'OTHER'
    elif damage == 'too_far': live[0]['current_c'] -= 2e-8
    elif damage == 'nan': live[0]['current_c'] = float('nan')
    elif damage == 'bool': live[0]['current_b'] = True
    elif damage == 'missing': live.pop()
    elif damage == 'extra': live.append(dict(live[1], component='UNKNOWN'))
    elif damage == 'duplicate': live.append(dict(live[0]))
    elif damage == 'duplicate_request': requested.append(dict(requested[0]))
    elif damage == 'wrong_parent': requested[0]['current_b'] += 0.01
    elif damage == 'zero_c': requested[0]['candidate_c'] = -1e-12; live[0]['current_c'] = 0.
    elif damage == 'negative_b': requested[0]['candidate_b'] = 0.; live[0]['current_b'] = -1e-12
    with pytest.raises(ContractError): bind_write_readback(before, requested, live)


def test_immediate_readback_is_written_before_native_recompute(tmp_path, monkeypatch):
    before, requested, live = case()
    vp = parent_module('r1_15a2_visum_parameters')
    reads = []
    def read(visum): reads.append(visum); return {'rows': live}
    monkeypatch.setattr(vp, 'read_td_parameter_state', read)
    adapter = SimpleNamespace(visum=object())
    # Existing donor persistence accepts this representation difference.
    assert all(r['status'] == 'OK' for r in vp.verify_td_persistence(adapter.visum, requested))
    effective, summary = capture_write_readback(adapter, before, requested, tmp_path)
    audit = read_json(tmp_path / 'TD_PARAMETER_WRITE_READBACK.json')
    assert reads == [adapter.visum, adapter.visum]
    assert summary['status'] == audit['status'] == 'VERIFIED'
    assert summary['representation_changes'] == 2 and audit['effective'] == effective


def test_failed_write_keeps_the_exact_parameter_difference_in_audit(tmp_path, monkeypatch):
    before, requested, live = case(); live[1]['current_b'] += 0.1
    monkeypatch.setattr(parent_module('r1_15a2_visum_parameters'), 'read_td_parameter_state', lambda v: {'rows': live})
    with pytest.raises(ContractError, match='UNREQUESTED_TD_PARAMETER_CHANGE_AT_WRITE'):
        capture_write_readback(SimpleNamespace(visum=None), before, requested, tmp_path)
    audit = read_json(tmp_path / 'TD_PARAMETER_WRITE_READBACK.json')
    assert audit['status'] == 'FAILED'
    assert any(d['component'] == 'LONG_E_C' and d['field'] == 'current_b' for d in audit['differences'])


@pytest.mark.parametrize('damage', ['target_one_ulp', 'untargeted_one_ulp', 'generation', 'links'])
def test_recompute_never_rebases_away_a_later_native_change(tmp_path, damage):
    before, requested, live = case()
    effective, _ = bind_write_readback(before, requested, live)
    after = dict(before, td_values=deepcopy(live))
    if damage == 'target_one_ulp': after['td_values'][0]['current_c'] = math.nextafter(live[0]['current_c'], 0.)
    elif damage == 'untargeted_one_ulp': after['td_values'][1]['current_b'] = math.nextafter(live[1]['current_b'], 0.)
    elif damage == 'generation': after['generation_hash'] = 'CHANGED'
    elif damage == 'links': after['fixed_link_hash'] = 'CHANGED'
    with pytest.raises(parent_module('r1_15a2_supply').SupplyContractError):
        assert_trial_freeze(donor(), before, after, 'TD_CORDON', effective, {}, {}, tmp_path)
    audit = read_json(tmp_path / 'TD_PARAMETER_FREEZE.json')
    assert audit['status'] == 'FAILED'
    assert bool(audit['differences']) == damage.endswith('ulp')


def test_exact_native_readback_does_not_allow_a_fixed_matrix_change(tmp_path):
    before, requested, live = case()
    before['matrices'] = [{'matrix_no': n, 'sha256_float64_le': 'BEFORE'} for n in (9101, 9116)]
    after = dict(before, td_values=live,
                 matrices=[{'matrix_no': n, 'sha256_float64_le': 'AFTER'} for n in (9101, 9116)])
    effective, _ = bind_write_readback(before, requested, live)
    cfg = {'matrix_scope_by_block': {'TD_CORDON': {'matrix_nos': [9101]}}}
    with pytest.raises(parent_module('r1_15a2_supply').SupplyContractError, match='DEMAND_MUTATED_FIXED_MATRIX:9116'):
        assert_trial_freeze(donor(), before, after, 'TD_CORDON', effective, {}, cfg, tmp_path)
    assert read_json(tmp_path / 'TD_PARAMETER_FREEZE.json')['status'] == 'FAILED'


@pytest.mark.parametrize('native_drift', [False, True])
def test_quantized_td_write_runs_through_the_real_trial_and_rollback(tmp_path, monkeypatch, native_drift):
    from fake_live03 import GravAttr
    from fake_live04 import Live04Visum
    from cordon2025.live04_adapter import CordonLive04Adapter
    from cordon2025.live04_cycle import run
    original_set = GravAttr.SetAttValue
    def quantized(self, name, value):
        return original_set(self, name, float(format(float(value), '.15g')))
    monkeypatch.setattr(GravAttr, 'SetAttValue', quantized)
    original_persistence = CordonLive04Adapter.parameter_persistence
    def persistence(self, block, rows):
        result = original_persistence(self, block, rows)
        if native_drift and block == 'TD_CORDON':
            state = parent_module('r1_15a2_visum_parameters').read_td_parameter_state(self.visum)
            info = state['objects'][rows[0]['component']]
            value = info['grav'].AttValue(info['c_attr'])
            # A second drift during the procedure is within the write tolerance,
            # yet must fail the exact post-write guard and roll back.
            info['grav'].SetAttValue(info['c_attr'], value + 1e-10)
        return result
    monkeypatch.setattr(CordonLive04Adapter, 'parameter_persistence', persistence)
    model = Live04Visum(tmp_path / 'model')
    overrides = {'max_cycles': 1, 'blocks_per_cycle': ['TD_CORDON'],
                 'checkpoint': {'enabled': False}, 'idp_guard': {'enabled': False},
                 'td_cordon': {'grouping': 'FAMILY', 'max_inner_evaluations': 1,
                              'idp_constrained_step': False, 'idp_objective_weight': 0.}}
    def execute():
        return run(model, output_root=tmp_path / 'runs',
                   options={'min_free_disk_gib': 0, 'com_retry_initial_delay_seconds': 0.,
                            'com_retry_max_delay_seconds': 0.}, config_overrides=overrides)
    if native_drift:
        with pytest.raises(Exception, match='UNREQUESTED_TD_PARAMETER_CHANGE'): execute()
    else: execute()
    folder = next((tmp_path / 'runs').glob('LIVE04_TGTD_*'))
    trial = folder / 'C01_TD_CORDON/TRIAL'
    readback = read_json(trial / 'TD_PARAMETER_WRITE_READBACK.json')
    freeze = read_json(trial / 'TD_PARAMETER_FREEZE.json')
    assert readback['status'] == 'VERIFIED' and readback['representation_changes'] > 0
    assert freeze['status'] == ('FAILED' if native_drift else 'VERIFIED')
    result = read_json(folder / '00_RESULT.json')
    if native_drift:
        assert result['model_state_verified'] is True
        assert read_json(trial / 'ROLLBACK/ROLLBACK_VERIFICATION.json')['passes']
        assert freeze['differences'] and not model.saved_versions
    else:
        assert result['status'] == 'MOCK_LIVE04_ACCEPTED' and result['accepted_states'] == 1
        assert result['model_state'] == 'LAST_ACCEPTED_STATE_IN_OPEN_VISUM'
        assert result['source_version_overwritten'] is False
        assert result['load_version_called'] is False and result['direct_od_matrix_writes'] is False
    assert not model.writes  # no forbidden COM writes
