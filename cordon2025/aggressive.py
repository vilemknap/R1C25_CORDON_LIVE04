"""Offline aggressive proposals using the unchanged cordon/15A2 numerical kernel.

A shadow proposal is not a Visum candidate ACCEPT. No COM or live controller is
imported. Budget credits are recomputed for every alternative, never accumulated
across hypothetical trials and never used to optimize held-out observations.
"""
from __future__ import annotations
import copy
from dataclasses import dataclass, replace
from pathlib import Path
import numpy as np
from .common import require, canonical_hash, parent_core, write_json, write_csv
from .aggressive_policy import effective_config, science_hash, META, td_soft_fit_check
from .optimizer import solve, build_problem, CordonSolution, deadzone, _optimize_u, _kkt_x
from .feasibility import parent_projection, evaluate_realizability


def incidence_state_hash(inc):
    """State binding for an optional local actuator response; not a live proof."""
    return canonical_hash({'origin': inc.audit.get('origin'),
        'cache': inc.audit.get('cache_sha256'), 'network': inc.audit.get('network_sha256'),
        'demand': inc.audit.get('demand_sha256'), 'variables': inc.variables,
        'universe': inc.audit.get('all_od_totals', [])})


def bounded_actuator_basis(inc, basis, cfg):
    """Intersect the search schedule with supplied hard bounds; never widen them."""
    if basis is None:
        return None
    require(basis.evidence.get('state_hash') == incidence_state_hash(inc), 'AGGRESSIVE_ACTUATOR_STATE_MISMATCH')
    n = basis.operator.n_cols
    lo = np.array(basis.lower, dtype=float, copy=True); hi = np.array(basis.upper, dtype=float, copy=True)
    require(lo.shape == hi.shape == (n,) and len(basis.column_meta) == n, 'AGGRESSIVE_ACTUATOR_SHAPE')
    require(np.all(np.isfinite(lo)) and np.all(np.isfinite(hi)) and np.all(lo <= 0) and np.all(hi >= 0),
            'AGGRESSIVE_ACTUATOR_HARD_BOUNDS')
    stage = cfg[META]['stage']
    caps = {'ADD_LOG': (stage['max_add_log_down'], stage['max_add_log_up']),
            'FAMILY_GLOBAL_LOG': (stage['signed_max_family_global_log_down'], stage['signed_max_family_global_log_up']),
            'SALARY_ABSOLUTE': (stage['salary_max_abs_delta_per_block'], stage['salary_max_abs_delta_per_block'])}
    for j, m in enumerate(basis.column_meta):
        require(m.get('allowed') is True and m.get('family') in ('WORK', 'SERVICE'), 'AGGRESSIVE_ILLEGAL_ACTUATOR')
        if m.get('type') == 'TG_PARAMETER':
            require(m.get('step_kind') in caps, 'AGGRESSIVE_TG_STEP_KIND_REQUIRED')
            down, up = caps[m['step_kind']]; lo[j] = max(lo[j], -down); hi[j] = min(hi[j], up)
        else:
            require(m.get('type') == 'TD_PARAMETER', 'AGGRESSIVE_NO_DIRECT_OD_ACTUATOR')
    evidence = copy.deepcopy(basis.evidence)
    evidence['search_bound_policy'] = cfg[META]['policy_id']
    return replace(basis, lower=lo, upper=hi, evidence=evidence)


def _state(inc, cfg, x, budget=None):
    """Fair conditional score: optimize C17 for x=0 as well as every candidate."""
    from .limits import numerical
    numeric=numerical(cfg)
    problem, selected, y, base, eps = build_problem(inc, cfg)
    x = np.asarray(x, dtype=float)
    require(x.shape == (len(inc.variables),) and np.all(np.isfinite(x)), 'AGGRESSIVE_INVALID_STEP')
    require(np.all(x >= problem.lower - 1e-10) and np.all(x <= problem.upper + 1e-10), 'AGGRESSIVE_STEP_OUTSIDE_BOUNDS')
    bcal = None
    if budget is not None:
        require(budget.pairs == [(r['origin_station'], r['destination_station']) for r in inc.rows], 'C17_OBSERVATION_ORDER_MISMATCH')
        bcal = budget.subset(selected.tolist())
    residual = base + problem.operator.forward(x) - y
    ridgeu = float(cfg['c17_ridge'])
    u, uit, gap = _optimize_u(residual, problem.row_weight, eps, bcal, np.zeros(len(selected)), ridgeu,
        tol=numeric['c17_solver_tolerance'],projection_tolerance=numeric['c17_projection_tolerance'])
    require(gap <= float(cfg.get('kkt_tolerance', 1e-6)), 'AGGRESSIVE_C17_SCORE_NOT_CONVERGED')
    data = 0.5 * float(np.sum((problem.row_weight * deadzone(residual - u, eps)) ** 2))
    parts = {'cordon_data_loss': data,
             'od_ridge_loss': 0.5 * float(np.sum(problem.ridge_diag * x*x)),
             'od_l1_loss': float(np.sum(problem.l1_diag * abs(x))),
             'c17_credit_loss': 0.5 * ridgeu * float(u@u)}
    fullu = np.zeros(len(inc.rows)); fullu[selected] = u
    predicted = inc.model + inc.operator.forward(x)
    require(np.all(np.isfinite(predicted)) and np.min(predicted, initial=0) >= -1e-7, 'AGGRESSIVE_NONPHYSICAL_PREDICTION')
    ledger = bcal.ledger(u) if bcal is not None else {'policy': 'DISABLED', 'global_credits_consumed': 0,
        'physical_pair_allocation': 'PRODUCTION_DISABLED'}
    return {'problem': problem, 'selected': selected, 'x': x, 'u': fullu,
            'prediction': predicted, 'parts': parts, 'objective': sum(parts.values()),
            'raw_cal_loss': 0.5 * float(np.sum((problem.row_weight * deadzone(residual, eps)) ** 2)),
            'c17': ledger, 'kkt_u': gap, 'c17_iterations': uit}


def _solution(inc, raw, baseline, state, status):
    """Keep standard CordonSolution/GuidanceResult for parent TG projection."""
    core = parent_core(); problem = state['problem']; selected = state['selected']
    x = state['x']; pred = state['prediction']; unc = state['u']
    y = np.array([inc.rows[i]['observed'] for i in selected])
    problem.target = y + unc[selected] - inc.model[selected]
    report = copy.deepcopy(raw.report)
    report.update(status=status, objective_initial=baseline['objective'], objective_final=state['objective'],
        initial_breakdown=baseline['parts'], final_breakdown=state['parts'], c17=state['c17'],
        kkt_x=_kkt_x(problem, x) if len(x) else 0., kkt_u=state['kkt_u'],
        numeric_converged=bool(raw.report['numeric_converged']),
        convergence_kind='UNDERLYING_GUIDANCE_SOLVER_NOT_BACKTRACKED_CANDIDATE_OPTIMALITY',
        candidate_is_full_solver_optimum=bool(np.allclose(x, raw.x, atol=1e-12, rtol=0)),
        actual_assignment_verified=False)
    for i, row in enumerate(report['relations']):
        target = inc.rows[i].get('observed')
        row.update(after_LINEARIZED=float(pred[i]), c17_scenario_relaxation=float(unc[i]),
            raw_difference_after=float(pred[i]-target) if target is not None else None,
            residual_after_relaxation=float(pred[i]-target-unc[i]) if target is not None else None)
        # The raw proposal may have a different unmet-target flag after damping.
        flags = [f for f in row.get('flags', '').split(',') if f and f != 'UNMET_TARGET_OUTSIDE_RELAXATION']
        if target is not None and abs(pred[i]-target-unc[i]) > row['epsilon_abs']+1e-7:
            flags.append('UNMET_TARGET_OUTSIDE_RELAXATION')
        row['flags'] = ','.join(flags)
    g = core.GuidanceResult(x, problem.operator.forward(x), pred[selected]-y-unc[selected],
        baseline['objective'], state['objective'], raw.guidance.iterations,
        raw.guidance.converged, raw.guidance.lipschitz, raw.guidance.history)
    return CordonSolution(x, x*inc.q_current, unc, pred, report, problem, g)


@dataclass
class AggressiveProposal:
    solution: CordonSolution
    raw_solution: CordonSolution
    report: dict
    projection: dict
    feasibility: dict

    def save(self, folder, inc):
        folder = Path(folder)
        self.solution.save(folder, inc)
        self.raw_solution.save(folder/'RAW_UNDAMPED_GUIDANCE', inc)
        write_json(folder/'AGGRESSIVE_REPORT.json', self.report)
        write_csv(folder/'AGGRESSIVE_TRIALS.csv', self.report['trials'])
        write_json(folder/'TG_TD_PROJECTION.json', self.projection)
        write_json(folder/'FULL_OD_FEASIBILITY.json', self.feasibility)


def propose(inc, config, budget=None, *, allow_unapproved_scenario=False, basis=None, zone_rows=None):
    cfg = effective_config(config)
    from .limits import numerical
    numeric=numerical(cfg)
    require(all(m['dseg_code'] in cfg['mutable_dsegs'] for m in inc.variables), 'AGGRESSIVE_VARIABLE_SCOPE_MISMATCH')
    require(np.all(np.isfinite(inc.q_current)) and np.all(inc.q_current > 0), 'AGGRESSIVE_INVALID_OD_TOTAL')
    raw = solve(inc, cfg, budget, allow_unapproved_scenario=allow_unapproved_scenario)
    bounded = bounded_actuator_basis(inc, basis, cfg)
    baseline = _state(inc, cfg, np.zeros(len(inc.variables)), budget)
    best = baseline; best_solution = None; best_feasibility = None; best_scale = 0.; trials = []
    for alpha in cfg['generation_backtracking_scales']:
        state = _state(inc, cfg, raw.x*alpha, budget)
        candidate = _solution(inc, raw, baseline, state, 'OFFLINE_AGGRESSIVE_TRIAL')
        feas = evaluate_realizability(inc, candidate, bounded)
        decrease = baseline['objective'] - state['objective']
        rel = decrease / max(baseline['objective'], 1e-12)
        losses_ok = (decrease > 0 and rel >= cfg['generation_min_cal_relative_improvement']
            and state['parts']['cordon_data_loss'] <= baseline['parts']['cordon_data_loss']+numeric['objective_comparison_atol']+numeric['objective_comparison_rtol']*abs(baseline['parts']['cordon_data_loss']))
        feasible = bounded is None or feas['status'] in ('SYNTHETIC_FEASIBLE_TG_TD', 'LINEARIZED_FEASIBLE_TG_TD_NOT_LIVE_VERIFIED')
        eligible = raw.report['numeric_converged'] and losses_ok and feasible
        reasons = []
        if not raw.report['numeric_converged']: reasons.append('GUIDANCE_SOLVER_NOT_CONVERGED')
        if not losses_ok: reasons.append('CAL_IMPROVEMENT_GATE')
        if not feasible: reasons.append(feas['status'])
        trials.append({'scale': alpha, 'objective': state['objective'], 'relative_improvement': rel,
            'cordon_data_loss': state['parts']['cordon_data_loss'], 'raw_cal_loss': state['raw_cal_loss'],
            'max_abs_relative_od_step': float(np.max(abs(state['x']), initial=0)),
            'c17_global_credits': state['c17']['global_credits_consumed'],
            'feasibility': feas['status'], 'eligible_shadow_proposal': bool(eligible),
            'reason': ','.join(reasons), 'actual_visum_accept': False})
        # CAL only: no holdout value enters this ranking or any C17 update.
        if eligible and state['objective'] < best['objective']:
            best, best_solution, best_feasibility, best_scale = state, candidate, feas, alpha
    if not raw.report['numeric_converged']:
        status = 'OFFLINE_AGGRESSIVE_SOLVER_NOT_CONVERGED'
    elif best_solution is None:
        status = 'OFFLINE_AGGRESSIVE_NO_IMPROVING_CANDIDATE'
    else:
        status = 'OFFLINE_AGGRESSIVE_SHADOW_PROPOSAL_READY'
    if best_solution is None:
        best_solution = _solution(inc, raw, baseline, baseline, status)
        best_feasibility = evaluate_realizability(inc, best_solution, bounded)
    best_solution.report['status'] = status
    projection = parent_projection(inc, best_solution, cfg, zone_rows=zone_rows)
    if zone_rows is not None:
        projection['zone_parameter_design_origin'] = 'EXPLICIT_ZONE_SNAPSHOT_NOT_LIVE_VISUM'
        projection['zone_parameters_sha256'] = canonical_hash(zone_rows)
        projection['parent_live_authority_labels_are_algorithm_metadata_only'] = True
        projection['native_generation_executed'] = False
    report = {'status': status, 'effective_policy': cfg[META], 'trials': trials, 'selected_scale': best_scale,
        'selected_objective': best['objective'], 'profiled_baseline_objective': baseline['objective'],
        'profiled_baseline_c17': baseline['c17'], 'selected_c17': best['c17'],
        'guidance_solver_converged': raw.report['numeric_converged'], 'raw_guidance_objective': raw.report['objective_final'],
        'realization_status': best_feasibility['status'], 'state_sha256': incidence_state_hash(inc),
        'ranking_uses_CAL_only': True, 'validation_used_for_optimization': False,
        'budget_accounting': 'ALTERNATIVE_SCENARIOS_RESET_SAME_SHARED_BUDGET_NOT_CUMULATIVE',
        'C17_no_model_change_cannot_create_improvement': True,
        'actual_assignment_verified': False, 'apply_permitted': False, 'production_ready': False,
        'live_visum_tested': False, 'origin': inc.audit.get('origin'),
        'TG_projection_kind': 'PARENT_MARGINALS_NOT_FULL_OD_PROOF',
        'TG_signed_design_kind': 'AVAILABLE_IF_ZONE_AUTHORITY_SUPPLIED',
        'TD_status': 'SCALE_API_AVAILABLE_NATIVE_TD_NOT_RUN',
        'objective_scenario_sha256': canonical_hash({
            'effective_config': cfg[META]['effective_science_sha256'],
            'observations': inc.rows, 'state': incidence_state_hash(inc),
            'budget': None if budget is None else {
                'policy': budget.policy, 'authorized': budget.scenario_authorized,
                'station_ids': budget.station_ids, 'caps': budget.station_caps.tolist(),
                'global_cap': budget.global_cap, 'pairs': budget.pairs, 'source': budget.provenance}})}
    best_solution.report['aggressive_policy'] = cfg[META]
    return AggressiveProposal(best_solution, raw, report, projection, best_feasibility)


def td_trial_plan(inc, cfg, basis, parameter_direction, *, budget=None, component_losses=None, allow_unapproved_scenario=False):
    """Evaluate 7 scaled TD PARAMETER steps through an explicit local Jacobian.

    This is NOT scaling independent routes, nor a TG/TD simulator. Missing native
    component losses are explicit; no native acceptance can be returned here.
    """
    cfg = effective_config(cfg)
    require(basis is not None, 'TD_ACTUATOR_BASIS_REQUIRED')
    basis = bounded_actuator_basis(inc, basis, cfg)
    require(all(m.get('type') == 'TD_PARAMETER' for m in basis.column_meta), 'TD_PLAN_REQUIRES_TD_ONLY_BASIS')
    direction = np.asarray(parameter_direction, dtype=float)
    require(direction.shape == (basis.operator.n_cols,) and np.all(np.isfinite(direction)), 'TD_INVALID_DIRECTION')
    # Reuse the parent full-OD/frozen-scope contracts on the zero proposal first.
    zero_state = _state(inc, cfg, np.zeros(len(inc.variables)), budget)
    raw = solve(inc, cfg, budget, allow_unapproved_scenario=allow_unapproved_scenario)
    zero_solution = _solution(inc, raw, zero_state, zero_state, 'TD_PLAN_ZERO')
    evaluate_realizability(inc, zero_solution, basis)
    keys = {tuple(k): i for i, k in enumerate(basis.row_keys)}
    rows = []
    for scale in cfg['td_realization_backtracking_scales']:
        step = direction*scale
        rec = {'scale': scale, 'apply_permitted': False, 'native_ipf_verified': False}
        if np.any(step < basis.lower-1e-12) or np.any(step > basis.upper+1e-12):
            rows.append(dict(rec, status='TD_HARD_PARAMETER_BOUND')); continue
        delta = basis.operator.forward(step)
        x = np.array([delta[keys[(m['dseg_code'], m['origin'], m['destination'])]]/q
                      for m, q in zip(inc.variables, inc.q_current)])
        if np.any(x < cfg['relative_od_lower']-1e-10) or np.any(x > cfg['relative_od_upper']+1e-10):
            rows.append(dict(rec, status='TD_LOCAL_OD_TRUST_REGION')); continue
        state = _state(inc, cfg, x, budget)
        rel = (zero_state['objective'] - state['objective']) / max(zero_state['objective'], 1e-12)
        soft = {'status': 'NATIVE_TD_COMPONENT_LOSSES_NOT_SUPPLIED', 'passes_soft_fit_only': False}
        if component_losses is not None:
            require(scale in component_losses, 'TD_SCALED_COMPONENT_EVIDENCE_MISSING')
            evidence = component_losses[scale]
            soft = td_soft_fit_check(evidence['before'], evidence['after'], evidence['selected'], cfg)
        rows.append(dict(rec, status='OFFLINE_LOCAL_TD_PREDICTION', parameter_step=step.tolist(),
            objective=state['objective'], relative_cal_improvement=rel,
            passes_shadow_cal_gate=bool(rel >= cfg['generation_min_cal_relative_improvement']),
            component_gate=soft, native_accept_permitted=False, c17=state['c17']))
    return {'status': 'OFFLINE_TD_BACKTRACK_PLAN_NOT_VISUM_RESULT', 'trials': rows,
            'source_policy_sha256': cfg[META]['source_policy_sha256'],
            'basis_sha256': basis.evidence['source_sha256'], 'apply_permitted': False,
            'native_ipf_tolerance_relaxed': False, 'native_ipf_verified': False}
