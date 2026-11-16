"""Cordon data-term parity and measured-refit contracts; synthetic, no COM."""
from copy import deepcopy
from types import SimpleNamespace
import numpy as np
import pytest
from test_optimizer import example
from test_live04_refit_row_identity import measured
from cordon2025 import live04_fit_objective as fo, live04_generation as gen
from cordon2025 import live02_v24917 as v17
from cordon2025.live02_evaluation import objective_from_model
from cordon2025.live04_step1 import Live04StepModel, planning_minimum, choose_scale_with_audit
from cordon2025.live04_evaluation import Live04Evaluator
from cordon2025.live04_config import load_config
from cordon2025.common import ContractError, parent_module


@pytest.fixture
def objective_case():
    inc = example(matrix=[[100., 0.], [0., 40.], [50., 50.]], targets=[90., 0., 100.])
    for row, w, model in zip(inc.rows, [.618852747755276, 1.4142135623730951, 1.], inc.model):
        row.update(weight=w, model=float(model))
    terms = {'w': np.array([.618852747755276/np.sqrt(90), 1.4142135623730951, .1]),
             'y': np.array([90., 0., 100.]), 'eps': np.zeros(3)}
    zones = [1, 3, 4]
    bounds = {('WORK', role, z): (-.4, .4) for role in ('PROD', 'ATT') for z in zones}
    cfg = {'calibration_role': 'CALIBRATION'}
    contract = v17.incidence_contract(inc)
    problem = fo.build_problem(contract, zones, bounds, cfg, terms, inc.model)
    return inc, contract, terms, problem, zones, bounds, cfg


def test_acceptance_and_fit_data_losses_match_for_100_parameter_directions(objective_case):
    inc, contract, terms, problem, *_ = objective_case
    random = np.random.default_rng(851)
    for x in random.uniform(-.01, .01, (100, len(problem.var_keys))):
        predicted = inc.model + problem.G @ x
        assert np.all(predicted >= 0)
        expected = objective_from_model(terms, predicted)[0]
        residual = problem.G @ x - problem.target
        actual = .5 * np.sum((problem.weight * residual)**2)
        assert actual == pytest.approx(expected, rel=1e-12, abs=1e-12)
    assert problem.objective_weighting['parent_data_objective'] == pytest.approx(objective_from_model(terms, inc.model)[0])


def test_zero_target_is_included_exactly_and_protected_fit_has_no_extra_multiplier(objective_case):
    inc, contract, terms, problem, zones, bounds, cfg = objective_case
    legacy = parent_module('r1_15a2_zonal_count_fit_v24917').build_problem(contract, zones, bounds, cfg)
    assert len(legacy.profile_rows) == 2 and len(problem.profile_rows) == 3
    assert problem.profile_rows[1]['observed'] == 0. and problem.target[1] == -40.
    assert legacy.profile_rows[-1]['weight'] == pytest.approx(.3)
    assert problem.profile_rows[-1]['weight'] == pytest.approx(.1)
    assert problem.objective_weighting['zero_observed_rows'] == 1
    assert problem.objective_weighting['protected_residual_multiplier'] == 1.
    assert contract['profiles'][1]['observed'] == inc.rows[1]['observed'] == 0.


def test_boundary_column_merge_keeps_the_same_row_objective(objective_case):
    _, _, _, problem, *_ = objective_case
    merged = parent_module('r1_15a2_boundary_generation_v24917').merge_pa(problem, [1])
    np.testing.assert_array_equal(merged.weight, problem.weight)
    np.testing.assert_array_equal(merged.target, problem.target)


@pytest.mark.station_profiles
def test_all_298_release_row_identities_share_the_captured_group_weights():
    from cordon2025.live03_observations import Contract
    from cordon2025.incidence import Incidence
    contract = Contract(load_config()['observations'])
    pairs = {tuple(sorted(k)) for k in contract.pair_cells}
    pairs.update(tuple(sorted(k)) for k in contract.station_cells)
    pairs.update(tuple(sorted(k)) for k in contract.extra_cells)
    pairs.update((s, p) for s in range(1, 17) for p in (18, 19))
    assert len(pairs) == 298
    extra_weights = contract.extra_weights()
    ext = {r['row_id']: r['group'] for r in contract.extra_rows}
    rows = []
    for i, (a, b) in enumerate(sorted(pairs)):
        # Synthetic volumes; real release identities and group coefficients.
        weight = extra_weights[ext[b]] if b in ext else 1.
        rows.append({'origin_station': a, 'destination_station': b, 'weight': weight,
                     'observed': 0. if i == 0 else 100., 'role': 'CALIBRATION'})
    template = example()
    sparse = parent_module('r1_15a2_core').SparseOperator
    rr = np.arange(298, dtype=np.int64); cc = rr % 2; vals = np.full(298, 80.)
    op = sparse(rr, cc, vals, 298, 2); sh = sparse(rr, cc, vals/100., 298, 2)
    model = np.full(298, 80.)
    inc = Incidence(rows, template.variables, template.projection_base_variables, template.q_current,
                    op, sh, model, model.copy(), np.zeros(298), template.audit)
    terms = {'y': np.array([r['observed'] for r in rows]), 'eps': np.zeros(298)}
    terms['w'] = np.array([r['weight'] for r in rows])/np.sqrt(np.maximum(1., terms['y']))
    bounds = {('WORK', role, z): (-.2, .2) for role in ('PROD', 'ATT') for z in [1, 3, 4]}
    problem = fo.build_problem(v17.incidence_contract(inc), [1, 3, 4], bounds,
                               {'calibration_role': 'CALIBRATION'}, terms, model)
    assert len(problem.profile_rows) == len(set(fo.row_ids(problem.profile_rows))) == 298
    np.testing.assert_array_equal(problem.weight, terms['w'])
    assert problem.objective_weighting['parent_data_objective'] == pytest.approx(objective_from_model(terms, model)[0])


@pytest.mark.parametrize('damage', ['duplicate', 'missing', 'nonfinite', 'nonzero_deadband'])
def test_corrupt_objective_authority_fails_closed(objective_case, damage):
    inc, contract, terms, _, zones, bounds, cfg = objective_case
    terms = deepcopy(terms); contract = deepcopy(contract)
    if damage == 'duplicate': contract['profiles'][1]['countlocation_no'] = contract['profiles'][0]['countlocation_no']
    elif damage == 'missing': contract['profiles'].pop()
    elif damage == 'nonfinite': terms['w'][0] = np.nan
    else: terms['eps'][0] = 1.
    with pytest.raises(ContractError): fo.build_problem(contract, zones, bounds, cfg, terms, inc.model)


def test_measured_refit_preserves_weights_and_does_not_mutate_parent_problem(measured, tmp_path):
    adapter, context, preview, before, after, *_ = measured
    original = context['_genfix2_effect_model']['problem']
    rows, weights, target, G = deepcopy(original.profile_rows), original.weight.copy(), original.target.copy(), original.G.copy()
    out, audit = gen.refine(adapter, context, 1., preview, before, after, tmp_path)
    problem = out['_genfix2_effect_model']['problem']
    np.testing.assert_array_equal(problem.weight, before['_terms']['FIRST_LAST']['w'])
    assert original.profile_rows == rows
    np.testing.assert_array_equal(original.weight, weights)
    np.testing.assert_array_equal(original.target, target)
    np.testing.assert_array_equal(original.G, G)
    assert audit['objective_weighting']['authority'] == 'CAPTURED_CORDON_OBJECTIVE_TERMS'


@pytest.mark.parametrize('damage', ['reordered_pairs', 'changed_weight'])
def test_refit_rejects_a_different_observation_or_objective_authority(measured, tmp_path, damage):
    adapter, context, preview, before, after, *_ = measured
    for m, inc in before['_incidence'].items():
        pairs = [[r['origin_station'], r['destination_station']] for r in inc.rows]
        before['methods'][m]['pairs'] = pairs
        after['methods'][m]['pairs'] = deepcopy(pairs)
    if damage == 'reordered_pairs':
        after['methods']['FIRST_LAST']['pairs'].reverse()
    else:
        after['_terms'] = deepcopy(before['_terms'])
        after['_terms']['FIRST_LAST']['w'][0] *= 2.
    with pytest.raises(ContractError, match='REFIT_(OBSERVATION_ROSTER|OBJECTIVE_AUTHORITY)_CHANGED'):
        gen.refine(adapter, context, 1., preview, before, after, tmp_path)


@pytest.mark.parametrize('improving', [True, False])
def test_nonconverged_refit_is_usable_only_if_improving_and_never_certifies_stationarity(measured, tmp_path, monkeypatch, improving):
    adapter, context, preview, before, after, *_, mods = measured
    original = mods.zf.solve
    def solve(*args):
        out = dict(original(*args), converged=False)
        if not improving: out['objective_final'] = out['objective_initial']
        return out
    monkeypatch.setattr(mods.zf, 'solve', solve)
    out, audit = gen.refine(adapter, context, 1., preview, before, after, tmp_path)
    assert audit['solver_converged'] is False
    assert audit['proposal_usable'] is improving
    if improving:
        assert out is not None and out['v24917']['solver_converged'] is False
        assert out['v24917']['proposal_usable'] is True
    else: assert out is None


def test_planner_does_not_apply_the_100_times_larger_early_stop_threshold():
    cfg = load_config(); ev = Live04Evaluator.__new__(Live04Evaluator)
    ev.live02 = {'acceptance': cfg['acceptance']}; ev.row_guard_policy = None
    ev.method = 'FIRST_LAST'; ev.secondary = 'EXACT_TWO_HITS'; ev.methods = ('FIRST_LAST', 'EXACT_TWO_HITS')
    terms = {'w': np.array([.1]), 'y': np.array([100.]), 'eps': np.zeros(1)}
    models = {'FIRST_LAST': np.array([110.]), 'EXACT_TWO_HITS': np.array([100.])}
    before = {'valid': True, '_terms': {m: deepcopy(terms) for m in ev.methods}, 'methods': {}}
    for m, v in models.items():
        q, _, _, metrics = objective_from_model(terms, v)
        before['methods'][m] = {'objective': q, 'metrics': metrics, 'model': v.tolist()}
    model = Live04StepModel(ev, before, {'delta_full': {'FIRST_LAST': [-.0025], 'EXACT_TWO_HITS': [0.]}}, 1.)
    opts = {'min_scale': .05, 'max_scale': 1., 'grid': 20, 'margin': .15}
    choose = parent_module('r1_15a2_step_search_v24917').choose_scale
    old = choose(model, lambda b,a:ev.block_gate('GENERATION',b,a,[]), .001, opts, 1.)
    new = choose(model, lambda b,a:ev.block_gate('GENERATION',b,a,[]), planning_minimum(ev), opts, 1.)
    assert old['scale'] is None
    assert new['scale'] == 1. and planning_minimum(ev) == 1e-5
    assert 1e-5 < new['predicted_rel_improvement'] < .001


def test_robustness_audit_explains_a_smaller_scale_without_relaxing_the_gate():
    model = SimpleNamespace(objective=lambda s:100.-s, rows=lambda s:{'scale':s},
                            final_prediction=lambda s:({}, True, []), base_rows={},
                            measured=None, rho=1., mapped=1)
    opts = {'min_scale':.1, 'max_scale':1., 'grid':7, 'margin':.15}
    def gate(before, after):
        return {'accepted':after['scale']<=.5,
                'reasons':[] if after['scale']<=.5 else ['SECONDARY_METHOD_DEGRADED']}
    donor = parent_module('r1_15a2_step_search_v24917').choose_scale(model, gate, 1e-5, opts, .7)
    audited = choose_scale_with_audit(model, gate, 1e-5, opts, .7)
    assert audited['scale'] == donor['scale'] == .4
    point = next(p for p in audited['grid'] if p['scale'] == .5)
    assert point['feasible'] and not point['robust']
    assert point['robust_probe_scale'] == .575
    assert point['robust_probe_reasons'] == ['SECONDARY_METHOD_DEGRADED']
