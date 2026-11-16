"""User policy: TG secondary ceiling only, equal normalized TD terms."""
from copy import deepcopy
import pytest
from cordon2025.common import ContractError, ROOT, read_json
from cordon2025.live04_config import load_config, adapter_config, row_guard_policy
from cordon2025.live04_evaluation import Live04Evaluator
from cordon2025.live03_td import IdpBlend, blended_gate
from types import SimpleNamespace


def evaluator():
    ev = Live04Evaluator.__new__(Live04Evaluator)
    ev.method = 'FIRST_LAST'; ev.secondary = 'EXACT_TWO_HITS'
    ev.live02 = {'acceptance': deepcopy(load_config()['acceptance'])}
    ev.row_guard_policy = None
    return ev


def diag(primary, secondary, *, valid=True, model=None):
    values = [1000., 1000., 1000.] if model is None else model
    return {'valid': valid, 'methods': {
        'FIRST_LAST': {'objective': primary, 'metrics': {}, 'model': values,
                       'observed': [1000.] * 3, 'pairs': [[1, 2], [1, 3], [2, 3]]},
        'EXACT_TWO_HITS': {'objective': secondary, 'metrics': {}}}}


def test_live_rejected_example_passes_secondary_gate_without_changing_other_blocks():
    ev = evaluator(); before = diag(212007.0794441873, 26631.00910338681)
    after = diag(206812.2377, 27145.0171)
    tg = ev.block_gate('GENERATION', before, after, [])
    assert tg['accepted'] and tg['secondary_relative_degradation'] == pytest.approx(0.019301, rel=1e-4)
    assert tg['secondary_max_relative_degradation'] == 0.02
    for block in ['SUPPLY_ADDVAL1', 'TD_CORDON']:
        decision = ev.block_gate(block, before, after, [])
        assert not decision['accepted'] and 'SECONDARY_METHOD_DEGRADED' in decision['reasons']
    # TD subsequently has its separate blended secondary ceiling, still 1 %.
    assert load_config()['td_cordon']['blended_max_cordon_degradation'] == 0.01
    assert ev.live02['acceptance']['secondary_max_relative_degradation'] == 0.


@pytest.mark.parametrize('secondary,accepted', [(100., True), (101.93, True), (102., True), (102.01, False)])
def test_generation_ceiling_is_inclusive_and_measured_against_parent(secondary, accepted):
    ev = evaluator(); before, after = diag(100., 100.), diag(95., secondary)
    decision = ev.block_gate('GENERATION', before, after, [])
    assert decision['accepted'] is accepted
    assert ('SECONDARY_METHOD_DEGRADED' in decision['reasons']) is (not accepted)


def test_a_relaxed_secondary_gate_does_not_remove_primary_capture_or_geh_failures():
    ev = evaluator(); before = diag(100., 100.)
    no_gain = ev.block_gate('GENERATION', before, diag(101., 101.93), [])
    assert not no_gain['accepted'] and 'CORDON_OBJECTIVE_NOT_IMPROVED' in no_gain['reasons']
    invalid = ev.block_gate('GENERATION', before, diag(95., 101.93, valid=False), [])
    assert not invalid['accepted'] and any(r.startswith('CANDIDATE_CAPTURE_INVALID') for r in invalid['reasons'])
    ev.row_guard_policy = row_guard_policy(load_config())
    guarded = ev.block_gate('GENERATION', before, diag(95., 101.93, model=[0., 1000., 1000.]), [])
    assert not guarded['accepted'] and 'PROTECTED_CORDON_ROW_GUARD_FAILED' in guarded['reasons']
    assert 'SECONDARY_METHOD_DEGRADED' not in guarded['reasons']


def test_legacy_config_without_the_override_retains_its_exact_secondary_limit():
    ev = evaluator(); ev.live02['acceptance'].pop('generation_secondary_max_relative_degradation')
    decision = ev.block_gate('GENERATION', diag(100., 100.), diag(95., 101.93), [])
    assert not decision['accepted'] and decision['reasons'] == ['SECONDARY_METHOD_DEGRADED']


@pytest.mark.parametrize('bad', [True, -0.01, 1.01, float('nan')])
def test_generation_secondary_override_is_validated(bad):
    with pytest.raises(ContractError, match='generation_secondary_max_relative_degradation'):
        load_config(overrides={'acceptance': {'generation_secondary_max_relative_degradation': bad}})


def test_equal_td_terms_use_parent_normalization_in_search_and_acceptance():
    cfg = load_config(); td = cfg['td_cordon']
    parent = {'A': {'fine_cdf_rmse': 0.1, 'mean_relative_error': -0.4}}
    trial = {'A': {'fine_cdf_rmse': 0.08, 'mean_relative_error': -0.2}}
    guard = SimpleNamespace(guarded=['A'])
    blend = IdpBlend(guard, ['A'], parent, td['idp_objective_weight'], q_ref=100.)
    j0 = 0.1**2 + 0.25 * 0.4**2; j1 = 0.08**2 + 0.25 * 0.2**2
    expected = 0.5 * 0.98 + 0.5 * j1 / j0
    assert blend.value(100., parent) == pytest.approx(1.)
    assert blend.value(98., trial) == pytest.approx(expected)
    decision = blended_gate({'reasons': [], 'secondary_relative_degradation': 0.},
                            blend, 100., 98., parent, trial, td)
    assert decision['accepted']
    assert decision['td_blended_acceptance']['blended_value'] == pytest.approx(expected)
    audit = blend.audit()
    assert audit['cordon_weight'] == audit['idp_weight'] == 0.5
    defaults = read_json(ROOT / 'provenance/live04_user_config/CORDON_LIVE04_CONFIG.RELEASE_DEFAULT.json')
    assert defaults == cfg
    runtime = adapter_config(cfg, 1, [1])
    assert runtime['live02']['acceptance']['generation_secondary_max_relative_degradation'] == 0.02
    assert runtime['live03']['td_cordon']['idp_objective_weight'] == 0.5
