"""v7 Generation design (GENFIX2 / MOBILITY2 / MOBILITYZONE1 / BDPA1) on the cordon incidence.

Port of r1_15a2_trial_adapter_v24917._generation_design_live (v7 @ 7b4c681) with
the profile-only parts replaced by their cordon equivalents:

  v7 (498 count profiles)                        LIVE04 (cordon, 136 observations)
  ---------------------------------------------  -------------------------------------------
  parent FISTA/FlowBundle design, then zonal fit  zonal fit only (LIVE03 rule; no FISTA)
  FlowBundle target mask (factor 1.0 = OFF)       not ported; policy must keep it OFF
  LONG cache incidence + LONGGUARD1 parent        LONG TG deferred (long_generation_enabled
                                                  = false); support audited on 9697 instead
  lsgen.design -> guard_ls -> defer_long          SCHOOL fixed per AMDY and LONG deferred:
                                                  v7 yields zero LS steps, LIVE04 writes none
  _final_step_prediction on profile rows          the same operator on BOTH cordon methods

LIVE04.4 adds the v7 measured zonal refit (refine_generation_design of v7 @ 7b4c681):
after the first fully measured and rejected trial of a block the W/S + boundary
direction is re-solved ONCE from the same parent with the minimum-change secant
operator (zf.measured_refit_problem, half the original box x measured scale),
then the same masks and mobility guards; the cordon effect operators of both
methods get the same secant correction.  Native acceptance stays the authority.

Unchanged donor calls: tg.zone_bounds (role envelopes P 0.5..3.15 / A 0.5..5.5 from config),
zguard.enrich/capture/constrain_fit_bounds/guard_projection, zf.build_problem/
solve(nonlinear_pa_repair=True)/projection_rows/summary, bdgen.bounds/merge_pa/
split_rows/design_payload (boundary_reference_multiplier), bdpa.margins_from_problem,
mguard.guard/check_candidate, zguard.check_candidate.
"""
from __future__ import annotations
import copy
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from .common import require, parent_module
from .io import write_json, write_csv, mkdir
from . import live02_v24917 as v17

RELEASE = 'LIVE04_V7_CORDON_GUARDED_GENERATION'
LS_STATUS = 'SCHOOL_TG_FIXED_AMDY_LONG_TG_DEFERRED'


def _mods():
    return SimpleNamespace(
        tg=parent_module('r1_15a2_targeted_generation_v24917'), zf=parent_module('r1_15a2_zonal_count_fit_v24917'),
        mb=parent_module('r1_15a2_multiblock'), core=parent_module('r1_15a2_core'),
        bdgen=parent_module('r1_15a2_boundary_generation_v24917'), bdpa=parent_module('r1_15a2_boundary_pa_v24917'),
        mguard=parent_module('r1_15a2_mobility_guard_v24917'), zguard=parent_module('r1_15a2_mobility_zone_v24917'),
        supply=parent_module('r1_15a2_supply_visum'), dp=parent_module('r1_15a2_demand_policy_v1'))


def fit_with_boundary(adapter, incidence, bounds, cfg, policy):
    """Exact port of v7 _fit_with_boundary; also returns the bounds of the joint fit."""
    m = _mods()
    fit_cfg = dict(policy.get('fit', {}), nonlinear_pa_repair=True)
    if not m.bdgen.active():
        rows, summary, problem, solution = m.zf.fit(incidence, adapter.zones, bounds, cfg, fit_cfg)
        return rows, summary, problem, solution, None, dict(bounds)
    current = m.bdgen.current_values(adapter.visum, m.bdgen.STATE['zones'])
    env = (policy.get('envelope') or {}).get('boundary_reference_multiplier', [0.5, 2.0])
    all_bounds = dict(bounds)
    all_bounds.update(m.bdgen.bounds(current, adapter.generation_reference_values, cfg, env))
    problem = m.zf.build_problem(incidence, adapter.zones, all_bounds, cfg)
    bd_margins = m.bdpa.margins_from_problem(problem, m.bdgen.STATE['zones'])
    problem = m.bdgen.merge_pa(problem, m.bdgen.STATE['zones'])
    solution = m.zf.solve(problem, fit_cfg)
    all_rows = m.zf.projection_rows(problem, solution, float(cfg.get('min_add_log_step', 1.0e-5)))
    rows, steps = m.bdgen.split_rows(all_rows)
    summary = m.zf.summary(problem, solution, rows)
    bd = m.bdgen.design_payload(steps, current)
    bd['margins'] = {k: v for k, v in bd_margins.items() if k in bd['steps']}
    bd['summary']['boundary_variables_in_fit'] = int(getattr(problem, 'boundary_variables', 0))
    summary['boundary'] = bd['summary']
    return rows, summary, problem, solution, bd, all_bounds


def effect_problems(adapter, diag, bounds, cfg):
    """One response operator per method on ALL its rows (y = 0 rows included).

    The fit drops rows without observation; the cordon objective does not, so the
    auxiliary problems floor the observation (targets/weights are not used)."""
    m = _mods()
    out = {}
    for method in adapter.evaluator.methods:
        inc = diag['_incidence'][method]
        contract = v17.incidence_contract(inc)
        contract['profiles'] = [dict(p, observed=max(float(p['observed'] or 0.0), 1.0e-9))
                                for p in contract['profiles']]
        problem = m.zf.build_problem(contract, adapter.zones, bounds, cfg)
        if m.bdgen.active():
            problem = m.bdgen.merge_pa(problem, m.bdgen.STATE['zones'])
        index = {int(r['countlocation_no']): i for i, r in enumerate(problem.profile_rows)}
        order = [index.get(v17.pair_key(r['origin_station'], r['destination_station'])) for r in inc.rows]
        out[method] = {'G': np.asarray(problem.G, dtype=float), 'var_keys': [tuple(k) for k in problem.var_keys],
                       'order': order}
    return out


def _delta(model, x_by_key):
    x = np.array([x_by_key.get(k, 0.0) for k in model['var_keys']], dtype=float)
    d = model['G'] @ x if len(x) else np.zeros(model['G'].shape[0])
    out = np.array([float(d[i]) if i is not None else 0.0 for i in model['order']])
    if not np.isfinite(out).all():
        raise ValueError('GENFIX2_NONFINITE_FINAL_PREDICTION')
    return out


def step_model(context, rows, bd):
    """Linear response of the guarded (implementable) proposal at scale 1, both methods."""
    effect = context.get('_genfix2_effect_model') or {}
    problems = effect.get('problems')
    if not problems:
        return {'available': False, 'delta_full': {}, 'reason': 'NO_EFFECT_OPERATOR'}
    by = {(r['family'], r['role'], int(r['zone_no'])): float(r.get('log_step', 0.0)) for r in rows}
    for key, step in ((bd or {}).get('steps') or {}).items():
        fam, z = key.split('|')
        by[(fam, 'PA', int(z))] = float(step)
    return {'available': True, 'source': 'GENFIX2_GUARDED_PROPOSAL_LINEAR_CORDON',
            'delta_full': {m: _delta(p, by).tolist() for m, p in problems.items()}}


def final_prediction(context, design, scale):
    """v7 _final_step_prediction: implemented effect rows (after masks, bounds, P/A
    rebalance and salary) + boundary steps at this scale, on both cordon methods."""
    effect = context.get('_genfix2_effect_model') or {}
    problems = effect.get('problems')
    if not problems:
        return {'available': False, 'reason': 'NO_FINAL_EFFECT_OPERATOR'}
    by = {(r['family'], r['role'], int(r['zone_no'])): float(r['implemented_total_log_effect'])
          for r in design.get('effect_rows', [])}
    for key, value in ((effect.get('bd') or {}).get('steps') or {}).items():
        fam, z = key.split('|')
        by[(fam, 'PA', int(z))] = float(scale) * float(value)
    return {'available': True, 'scale': float(scale), 'source': 'GENFIX2_FINAL_EFFECT_ROWS_INCLUDING_SALARY_BOUNDARY',
            'delta': {m: _delta(p, by).tolist() for m, p in problems.items()}}


def blocked(context, folder, exc, stage):
    """v7 _blocked_generation: the cause stays in the block result; no candidate."""
    m = _mods()
    detail = Path(folder) / 'V24917_MOBILITY_BLOCKED.json'
    context['projection'] = m.core.ProjectionResult(rows=[], weighted_rmse=0.0, family_summaries=[
        {'family': f, 'converged': False, 'proposal_usable': False} for f in m.zf.FAMILIES])
    context['result'] = SimpleNamespace(converged=False, source='LIVE04_BLOCKED_MOBILITY_DATA')
    context['v24917'] = {'release': RELEASE, 'status': 'BLOCKED_MOBILITY_DATA', 'failure_stage': str(stage),
                         'exception_type': type(exc).__name__, 'error': type(exc).__name__ + ':' + str(exc),
                         'detail_path': str(detail), 'proposal_usable': False}
    context['v24917_step_model'] = {'available': False, 'delta_full': {}, 'reason': 'BLOCKED_MOBILITY_DATA'}
    context.pop('v24917_ls', None); context.pop('v24917_bd', None)
    write_json(detail, context['v24917'])
    return context


def design(adapter, diag, folder, context):
    m = _mods()
    folder = Path(folder) / 'V7_TARGETED_GENERATION'; mkdir(folder)
    policy = m.tg.policy_of(adapter.cfg)
    require(policy is not None, 'LIVE04_V7_POLICY_MISSING')
    factors = policy.get('flowbundle_mask_non_target_factor') or {}
    require(all(float(v) >= 1.0 for v in factors.values()), 'LIVE04_FLOWBUNDLE_MASK_NOT_PORTED_TO_CORDON')
    method = adapter.evaluator.method
    inc = diag['_incidence'][method]
    phase, ratio = m.tg.phase_for(inc.rows, policy)
    adapter.v24917_status.update(last_phase=phase, last_ratio=ratio)
    stage = 'ZONE_AUTHORITY_READ'
    try:
        with adapter.v24917_overlay(phase) as cfg:
            zone_rows, attrs = m.supply.base.zone_state_rows(adapter.visum, adapter.zones, cfg,
                                                              zone_indices=adapter.zone_write_index_by_no,
                                                              retry_policy=adapter.com_retry_policy)
        stage = 'MOBILITY_OPTIONS'
        mg_opts = m.mguard.options()
    except Exception as exc:
        return blocked(context, folder, exc, stage)
    context['_genfix2_mobility'] = {'zone_rows': copy.deepcopy(zone_rows), 'options': mg_opts, 'zone_attributes': attrs}
    adapter._genfix2_mobility_parent = context['_genfix2_mobility']
    try:
        mz_rows, mz_families, mz_errors = m.zguard.enrich(adapter, zone_rows)
        mz = m.zguard.capture(mz_rows, mg_opts, mz_families, mz_errors,
                              anchor=getattr(adapter, '_mobilityzone1_anchor', None))
        if getattr(adapter, '_mobilityzone1_anchor', None) is None:
            adapter._mobilityzone1_anchor = copy.deepcopy(mz)
        else:
            for key, entry in mz['entries'].items():
                adapter._mobilityzone1_anchor['entries'].setdefault(key, copy.deepcopy(entry))
        context['_mobilityzone1'] = mz
        adapter._mobilityzone1_parent = mz
        write_json(folder / 'MOBILITYZONE1_PARENT.json', mz)
    except Exception as exc:
        return blocked(context, folder, exc, 'MOBILITYZONE1_PARENT')
    solution = bd = summary = None
    rows, all_bounds, fallback, mobility_fit_bounds = [], {}, None, None
    try:
        with adapter.v24917_overlay(phase) as cfg:
            bounds = m.tg.zone_bounds(m.mb, zone_rows, cfg, adapter.generation_reference_values)
            bounds, mobility_fit_bounds = m.zguard.constrain_fit_bounds(bounds, mz)
            incidence = v17.incidence_contract(inc)
            rows, summary, _problem, solution, bd, all_bounds = fit_with_boundary(adapter, incidence, bounds, cfg, policy)
            if not rows:
                raise RuntimeError('V24917_FIT_PRODUCED_NO_ROWS')
            context['_genfix2_effect_model'] = {'problems': effect_problems(adapter, diag, all_bounds, cfg), 'bd': bd,
                                                'problem': _problem}
    except Exception as exc:
        fallback = type(exc).__name__ + ':' + str(exc)
        adapter.v24917_counts['fit_fallbacks'] += 1
        rows, solution, bd = [], None, None
        context.pop('_genfix2_effect_model', None)
    try:
        zonal_rows, zonal_projection = m.zguard.guard_projection(rows, mz)
        rows, mobility = m.mguard.guard(zonal_rows, zone_rows, mg_opts)
        if not mobility.get('passes', mobility.get('status') == 'DISABLED'):
            raise ValueError(mobility['status'])
    except Exception as exc:
        return blocked(context, folder, exc, 'MOBILITY_GUARD')
    adapter.v24917_status['last_mobility_guard'] = mobility
    if solution is not None:
        converged = bool(solution['converged'])
        usable = bool(converged or solution['objective_final'] < solution['objective_initial'])
        summaries = [{'family': f, 'method': m.zf.METHOD, 'converged': usable, 'solver_converged': converged,
                      'proposal_usable': usable, 'fit_solver_converged': converged,
                      'iterations': int(solution['iterations'])} for f in m.zf.FAMILIES]
    else:
        # LIVE03 rule: no parent FISTA proposal; a fit error yields no candidate.
        converged = usable = False
        summaries = [{'family': 'NONE', 'converged': True, 'method': 'LIVE04_NO_PARENT_FISTA'}]
    context['projection'] = m.core.ProjectionResult(rows=rows, family_summaries=summaries, weighted_rmse=0.0)
    context['result'] = SimpleNamespace(converged=bool(summaries) and all(f.get('converged') for f in summaries),
                                        source='LIVE04_V7_ZONAL_FIT')
    ls_activation = dict(adapter.v24917_status.get('long_school') or {})
    long_school = {'status': LS_STATUS if ls_activation.get('active') else 'INACTIVE', 'activation': ls_activation,
                   'school_generation_status': 'FIXED_AMDY_NO_SCHOOL_ADD_COEFFICIENT',
                   'school_fp_link_policy': m.zguard.SCHOOL_FP_LINK_POLICY, 'school_generation_search_complete': True,
                   'long_generation_permitted': False,
                   'long_deferred_reason': 'LONG_ZONAL_GENERATION_EXPLICITLY_DISABLED',
                   'v7_equivalence': 'v7 guard_ls zeroes SCHOOL steps and defer_long zeroes LONG steps'}
    context['v24917'] = {'release': RELEASE, 'phase': phase, 'overlay_phase': phase if not fallback else None,
                         'model_obs_ratio': ratio, 'method': method, 'fit_summary': summary,
                         'flowbundle_mask': {'status': 'OFF_NOT_PORTED', 'factors': factors},
                         'bounds_count': len(all_bounds), 'mobility_fit_bounds': mobility_fit_bounds,
                         'long_school': long_school, 'boundary': (bd or {}).get('summary'),
                         'mobilityzone1': zonal_projection, 'mobility_guard': mobility,
                         'mobility_target_satisfied': bool(mz['target_satisfied']),
                         'solver_converged': converged, 'proposal_usable': usable,
                         'search_incomplete': bool(fallback or not mz['target_satisfied']),
                         'status': 'FIT_FALLBACK_NO_CANDIDATE' if fallback else 'GUARDED_PROPOSAL'}
    context['v24917_ls'] = None
    context['v24917_bd'] = bd
    context['v24917_step_model'] = step_model(context, rows, bd)
    if fallback:
        context['v24917']['error'] = fallback
        write_json(folder / 'V24917_FIT_FALLBACK.json', context['v24917'])
    if bd:
        write_json(folder / 'V24917_BOUNDARY_STEPS.json', bd)
    write_json(folder / 'V24917_FIT_SUMMARY.json', context['v24917'])
    write_json(folder / 'V24917_STEP_MODEL.json', context['v24917_step_model'])
    write_csv(folder / 'V24917_FIT_PROJECTION_ROWS.csv', rows)
    if summary:
        lp = summary.get('linear_prediction') or {}
        print('R1 CORDON LIVE04 TG: phase=%s ratio=%.3f rows=%d clipped=%d mobility=%s predicted_ratio=%.3f'
              % (phase, ratio, len(rows), int(zonal_projection.get('rows_clipped', 0) or 0),
                 mobility.get('status'), lp.get('ratio_after') or 0.0))
    return context


def implemented_vector(var_keys, design, scale, bd):
    """v7 _implemented_fit_vector: implemented log effects of the applied candidate."""
    effects = {(r['family'], r['role'], int(r['zone_no'])): float(r['implemented_total_log_effect'])
               for r in design.get('effect_rows', [])}
    for key, value in ((bd or {}).get('steps') or {}).items():
        fam, z = key.split('|')
        effects[(fam, 'PA', int(z))] = float(scale) * float(value)
    return np.array([effects.get(tuple(k), 0.0) for k in var_keys], dtype=float)


def secant_operator(G, x, delta):
    """Minimum-change (Broyden) correction G_new @ x = delta; never mutates G."""
    G = np.asarray(G, dtype=float); x = np.asarray(x, dtype=float); delta = np.asarray(delta, dtype=float)
    den = float(x @ x)
    if den <= 1.0e-12:
        raise ValueError('V24917_REFIT_NO_MEASURED_PARAMETER_DIRECTION')
    out = G + np.outer(delta - G @ x, x / den)
    if not np.isfinite(out).all():
        raise ValueError('V24917_REFIT_NONFINITE_OPERATOR')
    return out


def refine(adapter, context, scale, preview, before, after, folder):
    """v7 refine_generation_design on the cordon rows (one pure re-solve, no COM)."""
    m = _mods()
    folder = Path(folder); mkdir(folder)
    policy = m.tg.policy_of(adapter.cfg)
    effect = context.get('_genfix2_effect_model') or {}
    problem, bd = effect.get('problem'), effect.get('bd')
    if policy is None or problem is None:
        return None, {'status': 'NO_ZONAL_EFFECT_OPERATOR'}
    # LIVE04: SCHOOL TG fixed and LONG TG deferred, so no mixed LONG/SCHOOL actuator exists.
    require(before.get('valid', True) and after.get('valid', True), 'V24917_REFIT_INVALID_MEASUREMENT')
    require(before['observed_hash'] == after['observed_hash'], 'V24917_REFIT_OBSERVATION_AUTHORITY_CHANGED')
    method = adapter.evaluator.method
    inc = before['_incidence'][method]
    index = {v17.pair_key(r['origin_station'], r['destination_station']): i for i, r in enumerate(inc.rows)}
    mb = np.asarray(before['methods'][method]['model'], dtype=float)
    ma = np.asarray(after['methods'][method]['model'], dtype=float)
    delta = []
    for row in problem.profile_rows:
        i = index[int(row['countlocation_no'])]
        if not np.isclose(mb[i], float(row['model']), rtol=1e-12, atol=1e-9):
            raise ValueError('V24917_REFIT_PARENT_DIAGNOSTICS_MISMATCH')
        delta.append(float(ma[i] - mb[i]))
    x = implemented_vector(problem.var_keys, preview, scale, bd)
    refined, audit = m.zf.measured_refit_problem(problem, x, np.array(delta), min(0.5, 0.5 * float(scale)))
    fit_cfg = dict(policy.get('fit', {}), nonlinear_pa_repair=True)
    solution = m.zf.solve(refined, fit_cfg)
    audit['solver_converged'] = bool(solution['converged'])
    if not solution['converged']:
        return None, dict(audit, status='REFIT_SOLVER_NOT_CONVERGED')
    rows = m.zf.projection_rows(refined, solution, float(adapter.cfg.get('min_add_log_step', 1.0e-5)))
    rows, steps = m.bdgen.split_rows(rows)
    new_bd = None
    if bd is not None:
        new_bd = m.bdgen.design_payload(steps, bd['current'])
        new_bd['margins'] = copy.deepcopy(bd.get('margins', {}))
    rows, zproj = m.zguard.guard_projection(rows, context['_mobilityzone1'])
    authority = context['_genfix2_mobility']
    rows, mobility = m.mguard.guard(rows, authority['zone_rows'], authority['options'])
    if not mobility.get('passes', mobility.get('status') == 'DISABLED'):
        return None, dict(audit, status='REFIT_MOBILITY_REJECTED')
    if not rows and not (new_bd or {}).get('steps'):
        return None, dict(audit, status='REFIT_NO_PARAMETER_DIRECTION')
    # The cordon effect operators (both methods, all rows) get the same measured secant.
    problems, operators = {}, {}
    for meth, p in effect['problems'].items():
        xm = implemented_vector(p['var_keys'], preview, scale, bd)
        b = np.asarray(before['methods'][meth]['model'], dtype=float)
        a = np.asarray(after['methods'][meth]['model'], dtype=float)
        d = np.zeros(p['G'].shape[0])
        for i, k in enumerate(p['order']):
            if k is not None:
                d[k] = a[i] - b[i]
        G = secant_operator(p['G'], xm, d)
        problems[meth] = dict(p, G=G)
        operators[meth] = {'prediction_error_l2_before': float(np.linalg.norm(d - p['G'] @ xm)),
                           'prediction_error_l2_after': float(np.linalg.norm(d - G @ xm))}
    out = dict(context)
    out['projection'] = m.core.ProjectionResult(rows=rows, weighted_rmse=0.0, family_summaries=[
        {'family': f, 'method': m.zf.METHOD, 'converged': True} for f in m.zf.FAMILIES])
    out['v24917_bd'] = new_bd
    out['_genfix2_effect_model'] = {'problems': problems, 'bd': new_bd, 'problem': refined}
    out['v24917_step_model'] = step_model(out, rows, new_bd)
    audit.update(status='ZONAL_DIRECTION_REFITTED', fit=m.zf.summary(refined, solution, rows),
                 cordon_effect_operators=operators, mobilityzone1=zproj, mobility_guard=mobility,
                 rows=len(rows), boundary_steps=len((new_bd or {}).get('steps') or {}))
    out['v24917'] = dict(context['v24917'], measured_zonal_refit=audit)
    write_json(folder / 'MEASURED_ZONAL_REFIT.json', audit)
    write_csv(folder / 'MEASURED_ZONAL_REFIT_ROWS.csv', rows)
    return out, audit


def validate_mobility_plan(context, design):
    """v7 _validate_mobility_plan on the complete final candidate rows."""
    m = _mods()
    authority = context.get('_genfix2_mobility')
    if authority is None:
        if m.mguard.options().get('enabled', True):
            raise m.supply.SupplyContractError('MOBILITY2_PARENT_AUTHORITY_MISSING')
        return {'passes': True, 'status': 'DISABLED'}
    proof = m.mguard.check_candidate(design.get('candidate_rows') or [], authority['zone_rows'], authority['options'])
    mz = context.get('_mobilityzone1')
    if mz is not None:
        zonal = m.zguard.check_candidate(design.get('candidate_rows') or [], mz)
        proof['mobilityzone1'] = zonal
        proof['passes'] = bool(proof['passes'] and zonal['passes'])
        if not proof['passes']:
            proof['status'] = 'REJECTED_FINAL_CANDIDATE_OUTSIDE_ENVELOPE'
    design['genfix2_mobility'] = proof
    return proof
