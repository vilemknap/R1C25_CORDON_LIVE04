"""V24917 mechanics on the cordon whole-matrix objective (LIVE02 V24917 variant).

Unchanged donor modules (byte-identical copies from the V24917 FULL ZIP in parent/):
  zonal_count_fit, targeted_generation, step_search (choose_scale), boundary_generation,
  long_school_generation, combusy2, demand_policy_v1 (option validation), perf_v24917
  (timing), td_count_blend (cl_key only).
Cordon adaptations (this module):
  * the zonal P/A fit uses the cordon incidence (120 unordered station pairs) instead
    of the 248 profile rows;
  * BNDGEN zones are the configured crossings that exist in the model, carry W/S
    synthetic P/A and have NO ADD/ZAHR actuator (consistency check for 2025);
  * LSGEN LONG exposure is the NATIVE_CL saved-path volume of each cordon pair;
  * STEP1 predicts BOTH enumeration methods and decides with the cordon gate.
Run options come only from CORDON_LIVE02_CONFIG.json (validated by the donor
demand_policy_v1.validate); environment variables are not consulted.
"""
from __future__ import annotations
import copy
from contextlib import contextmanager
from pathlib import Path
import numpy as np
from .common import require, parent_module
from .io import write_json, write_csv, mkdir, sha256

DONOR_FILES = {
    'r1_15a2_zonal_count_fit_v24917.py': 'd8b22f2eb7ba99668085d65a8b8a39042031f2d91917208798237024e8230d07',
    'r1_15a2_targeted_generation_v24917.py': '06cc39782779361eecbe498d05ef8b03ee00c270932f05376718ebb42759d206',
    'r1_15a2_step_search_v24917.py': '0db6daaa5b2a5f7b1b7b34a1b2b20c47690f1ecdcea8ff54fbe99978a7dfdecb',
    'r1_15a2_boundary_generation_v24917.py': 'c5d879567bff94e1a3ac02ebe11eb226239570591f12c0e00f7d48eba86aac84',
    'r1_15a2_long_school_generation_v24917.py': '9a9a384878e4414f7447bfd7ad390b63f45caa5e04cda59d8d7560159750db53',
    'r1_15a2_combusy2_v24917.py': 'c0833e7e8e50ade00b29196882733189fff06a426d8b9834faf80db850022204',
    'r1_15a2_demand_policy_v1.py': '3074da35e2269de3fdf023fbc01efdd5bdfff278281930aefff6460fd1e711b6',
    'r1_15a2_perf_v24917.py': 'bec293a7f6514ad7937a62b7f9241b5c63f4e821a5d5c554ff8f31c5e839c088',
    'r1_15a2_td_count_blend_v24917.py': '6e97f9e7e4b1c325e5021f44fb6daca2e3a8e8192e67a2a9e9c6c8a69984c548',
}
RUN_OPTIONS_PIN = 'provenance/v24917/R1_RUN_OPTIONS_V24917.json'
MODE = 'V24917_TARGETED_STEP1'
EPS = 1.0e-12


def verify_donor_files():
    from .common import PARENT
    bad = [n for n, h in DONOR_FILES.items() if sha256(PARENT / n) != h]
    require(not bad, 'V24917_DONOR_FILE_CHANGED:' + ','.join(bad))
    return dict(DONOR_FILES)


def pair_key(a, b):
    return int(a) * 100 + int(b)


def run_options(cfg):
    dp = parent_module('r1_15a2_demand_policy_v1')
    return dp.validate(dict(cfg['v24917']['run_options']))


def targeted_policy(cfg):
    tg = parent_module('r1_15a2_targeted_generation_v24917')
    policy = copy.deepcopy(tg.DEFAULT_POLICY)
    policy['catchup_until_model_obs_ratio'] = float(cfg['v24917']['catchup_until_model_obs_ratio'])
    return tg.validate_policy(policy)


# ------------------------------------------------------------------ scope
@contextmanager
def runtime_scope(cfg, guarded_visum, zones, actuatable_zones, folder):
    """Install the V24917 runtime for ONE cordon run and restore everything after."""
    verify_donor_files()
    dp = parent_module('r1_15a2_demand_policy_v1')
    tg = parent_module('r1_15a2_targeted_generation_v24917')
    mb = parent_module('r1_15a2_multiblock')
    com = parent_module('r1_15a2_com_compat')
    lsgen = parent_module('r1_15a2_long_school_generation_v24917')
    bdgen = parent_module('r1_15a2_boundary_generation_v24917')
    step = parent_module('r1_15a2_step_search_v24917')
    cb = parent_module('r1_15a2_combusy2_v24917')
    perf = parent_module('r1_15a2_perf_v24917')
    opts = run_options(cfg)
    saved = {'load_options': dp.load_options, 'hard': mb._multiplicative_coefficient_bounds,
             'soft': mb._soft_multiplier_bounds, 'refine': mb._signed_generation_refinement,
             'attrs': list(mb.GENERATION_ATTRS), 'attr_map': dict(mb.GENERATION_ATTR_MAP),
             'bd_state': copy.deepcopy(bdgen.STATE), 'step_state': copy.deepcopy(step._STATE),
             'retry_budget': com._retry_budget, 'perf_timing': copy.deepcopy(perf._STATE['timing'])}
    status = {'schema': 'LIVE02_V24917_RUNTIME_V1', 'mode': MODE, 'donor_files': verify_donor_files(),
              'run_options': {k: v for k, v in opts.items() if not k.startswith('_')}}
    filter_info = None
    try:
        dp.load_options = lambda root=None, environ=None: dict(opts)
        status['multiblock_patch'] = tg.patch_multiblock(mb)
        step._STATE.update(rho=None, rho_history=[], blocks=0, trials=0, kept=0, exhausted=0)
        perf._STATE['timing'] = {}
        status['long_school'] = lsgen.activate(guarded_visum)
        status['boundary'] = activate_boundary(cfg, opts, guarded_visum, zones, actuatable_zones, bdgen)
        cb.install_budget_floor(com, float(opts['cb_max_wait_seconds']))
        filter_info = cb.install_message_filter(float(opts['cb_max_wait_seconds']))
        status['combusy2'] = {'budget_floor_seconds': float(opts['cb_max_wait_seconds']),
                              'message_filter': filter_info, 'block_retries': int(opts['cb_block_retries'])}
        status['generation_attributes'] = list(mb.GENERATION_ATTRS)
        write_json(Path(folder) / 'V24917_RUNTIME_STATUS.json', status)
        print('R1 CORDON V24917: STEP1=%s catch-up=%s LSGEN=%s BNDGEN=%s zones=%s COMBUSY2 %.0fs filter=%s'
              % (opts['ts_enabled'], opts['tg_catchup_enabled'], status['long_school'].get('active'),
                 status['boundary'].get('active'), status['boundary'].get('zones'),
                 float(opts['cb_max_wait_seconds']), (filter_info or {}).get('registered')))
        yield status
    finally:
        dp.load_options = saved['load_options']
        mb._multiplicative_coefficient_bounds = saved['hard']
        mb._soft_multiplier_bounds = saved['soft']
        mb._signed_generation_refinement = saved['refine']
        mb.GENERATION_ATTRS[:] = saved['attrs']
        mb.GENERATION_ATTR_MAP.clear(); mb.GENERATION_ATTR_MAP.update(saved['attr_map'])
        bdgen.STATE.clear(); bdgen.STATE.update(saved['bd_state'])
        step._STATE.clear(); step._STATE.update(saved['step_state'])
        com._retry_budget = saved['retry_budget']
        perf._STATE['timing'] = saved['perf_timing']
        if filter_info and filter_info.get('registered'):
            try:
                import pythoncom  # type: ignore
                pythoncom.CoRegisterMessageFilter(cb._STATE.get('previous_filter'))
            except Exception:
                pass


def activate_boundary(cfg, opts, visum, zones, actuatable_zones, bdgen):
    """Donor bdgen.activate on the configured crossings that are consistent in this model."""
    audit = {'policy': cfg['v24917']['boundary_zone_policy'], 'configured': list(opts['bd_zones'])}
    if not opts['bd_enabled']:
        bdgen.STATE.update(active=False, reason='bd_enabled=false')
        return dict(bdgen.STATE, audit=audit)
    model = set(int(z) for z in zones)
    actuators = set(int(z) for z in actuatable_zones)
    present = [z for z in opts['bd_zones'] if int(z) in model]
    with_actuator = [z for z in present if int(z) in actuators]
    audit.update(present_in_model=present, excluded_has_add_or_zahr_actuator=with_actuator)
    candidates = [z for z in present if int(z) not in actuators]
    if not candidates:
        bdgen.STATE.update(active=False, reason='NO_CONFIGURED_CROSSING_ZONE_WITHOUT_ACTUATOR_IN_MODEL')
        return dict(bdgen.STATE, audit=audit)
    dp = parent_module('r1_15a2_demand_policy_v1')
    restricted = dict(opts, bd_zones=candidates)
    old = dp.load_options
    try:
        dp.load_options = lambda root=None, environ=None: dict(restricted)
        state = bdgen.activate(visum)
    finally:
        dp.load_options = old
    return dict(state, audit=audit)


# ------------------------------------------------------------------ design
def incidence_contract(inc):
    """Cordon incidence in the zonal-fit schema (profiles = unordered station pairs)."""
    c = inc.parent_contract()
    profiles = []
    for r in inc.rows:
        profiles.append(dict(r, profile_weight=float(r.get('weight', 1.0)),
                             countlocation_no=pair_key(r['origin_station'], r['destination_station'])))
    c['profiles'] = profiles
    return c


def model_obs_ratio(inc):
    obs = sum(float(r['observed']) for r in inc.rows if float(r['observed'] or 0) > 0)
    model = sum(float(r['model']) for r in inc.rows if float(r['observed'] or 0) > 0)
    return model / obs if obs > 0 else 1.0


def _fit(zf, bdgen, incidence, zones, bounds, cfg, policy, visum, reference_values):
    """Exact port of V24917 adapter._fit_with_boundary (W/S fit + border lever jointly)."""
    fit_cfg = policy.get('fit', {})
    if not bdgen.active():
        problem = zf.build_problem(incidence, zones, bounds, cfg)
        solution = zf.solve(problem, fit_cfg)
        rows = zf.projection_rows(problem, solution, float(cfg.get('min_add_log_step', 1.0e-5)))
        return rows, zf.summary(problem, solution, rows), problem, solution, None, bounds
    current = bdgen.current_values(visum, bdgen.STATE['zones'])
    env = (policy.get('envelope') or {}).get('zahr_reference_multiplier', [0.25, 5.0])
    all_bounds = dict(bounds)
    all_bounds.update(bdgen.bounds(current, reference_values, cfg, env))
    problem = zf.build_problem(incidence, zones, all_bounds, cfg)
    problem = bdgen.merge_pa(problem, bdgen.STATE['zones'])
    solution = zf.solve(problem, fit_cfg)
    all_rows = zf.projection_rows(problem, solution, float(cfg.get('min_add_log_step', 1.0e-5)))
    rows, steps = bdgen.split_rows(all_rows)
    summary = zf.summary(problem, solution, rows)
    bd = bdgen.design_payload(steps, current)
    bd['summary']['boundary_variables_in_fit'] = int(getattr(problem, 'boundary_variables', 0))
    summary['boundary'] = bd['summary']
    return rows, summary, problem, solution, bd, all_bounds


def _long_school(lsgen, visum, cfg, zones, incidence, problem, solution, ref, fit_cfg, cl_pair):
    """Donor lsgen.design with the LONG exposure taken from cordon NATIVE_CL pair volumes."""
    keys = [int(r['countlocation_no']) for r in problem.profile_rows]
    cl = {k: float(cl_pair.get(k, 0.0)) for k in keys}
    cfg2 = dict(cfg, api_approved_observations=[
        {'no': k, 'edge_key': [k, 0, 0], 'direction': 'DIRECTED'} for k in keys])
    old = lsgen._cl_volume
    try:
        lsgen._cl_volume = lambda _visum, edge, both: cl.get(int(edge[0]), 0.0)
        return lsgen.design(visum, cfg2, zones, incidence, problem, solution, ref, fit_cfg)
    finally:
        lsgen._cl_volume = old


def _predict(zf, bdgen, inc, zones, bounds, cfg, problem, solution, ls):
    """First-order pair response of the full step for one enumeration method."""
    # The fit drops rows with zero observation; the cordon objective does not
    # (y=0 still contributes 0.5*m^2).  For the response operator only, every
    # pair is admitted; targets/weights of this auxiliary problem are unused.
    contract = incidence_contract(inc)
    contract['profiles'] = [dict(p, observed=max(float(p['observed'] or 0.0), 1.0e-9))
                            for p in contract['profiles']]
    sec = zf.build_problem(contract, zones, bounds, cfg)
    if bdgen.active():
        sec = bdgen.merge_pa(sec, bdgen.STATE['zones'])
    xmap = {k: float(v) for k, v in zip(problem.var_keys, solution['x'])}
    x = np.array([xmap.get(k, 0.0) for k in sec.var_keys])
    by_key = {int(r['countlocation_no']): float(d) for r, d in zip(sec.profile_rows, sec.G @ x)}
    lsd = {}
    if ls and ls.get('predicted_change') is not None:
        lsd = {int(r['countlocation_no']): float(d) for r, d in zip(problem.profile_rows, ls['predicted_change'])}
    return [by_key.get(pair_key(r['origin_station'], r['destination_station']), 0.0) +
            lsd.get(pair_key(r['origin_station'], r['destination_station']), 0.0) for r in inc.rows]


def targeted_design(adapter, diag, folder, context):
    """Replace the parent (FISTA->MARGINALS) proposal by the V24917 zonal fit."""
    tg = parent_module('r1_15a2_targeted_generation_v24917')
    zf = parent_module('r1_15a2_zonal_count_fit_v24917')
    mb = parent_module('r1_15a2_multiblock')
    core = parent_module('r1_15a2_core')
    lsgen = parent_module('r1_15a2_long_school_generation_v24917')
    bdgen = parent_module('r1_15a2_boundary_generation_v24917')
    supply = parent_module('r1_15a2_supply_visum')
    folder = Path(folder) / 'V24917_TARGETED_GENERATION'; mkdir(folder)
    policy = tg.policy_of(adapter.cfg)
    require(policy is not None, 'LIVE02_V24917_POLICY_MISSING')
    method = adapter.evaluator.method
    inc = diag['_incidence'][method]
    phase, ratio = tg.phase_for(inc.rows, policy)
    record = {'release': 'LIVE02_V24917_CORDON_TARGETED_DESIGN', 'phase': phase, 'overlay_phase': phase,
              'model_obs_ratio': ratio, 'method': method}
    try:
        with adapter.v24917_overlay(phase) as cfg:
            zone_rows, _ = supply.base.zone_state_rows(adapter.visum, adapter.zones, cfg,
                                                       zone_indices=adapter.zone_write_index_by_no,
                                                       retry_policy=adapter.com_retry_policy)
            bounds = tg.zone_bounds(mb, zone_rows, cfg, adapter.generation_reference_values)
            incidence = incidence_contract(inc)
            rows, summary, problem, solution, bd, all_bounds = _fit(
                zf, bdgen, incidence, adapter.zones, bounds, cfg, policy, adapter.visum,
                adapter.generation_reference_values)
            ls = None
            if (adapter.v24917_status or {}).get('long_school', {}).get('active'):
                try:
                    ls = _long_school(lsgen, adapter.visum, cfg, adapter.zones, incidence, problem, solution,
                                      adapter.generation_reference_values, policy.get('fit', {}),
                                      diag.get('native_cl_pair_volume', {}).get(method, {}))
                except Exception as exc:
                    ls = {'steps': {}, 'summary': {'status': 'LS_DESIGN_ERROR', 'error': type(exc).__name__ + ':' + str(exc)}}
            step_model = {'source': 'V24917_ZONAL_FIT_PLUS_LSGEN_LINEAR_CORDON_PAIRS', 'delta_full': {}}
            for m in adapter.evaluator.methods:
                step_model['delta_full'][m] = _predict(zf, bdgen, diag['_incidence'][m], adapter.zones, all_bounds,
                                                       cfg, problem, solution, ls)
        if not rows:
            raise RuntimeError('V24917_FIT_PRODUCED_NO_ROWS')
        converged = bool(solution['converged']) or (solution['objective_final'] < solution['objective_initial'])
        summaries = [{'family': f, 'method': zf.METHOD, 'converged': converged,
                      'fit_solver_converged': bool(solution['converged']),
                      'iterations': int(solution['iterations'])} for f in zf.FAMILIES]
        parent_projection = context['projection']
        record['parent_projection_summary'] = {'rows': len(parent_projection.rows),
                                               'family_summaries': copy.deepcopy(parent_projection.family_summaries)}
        context['projection'] = core.ProjectionResult(rows=rows, family_summaries=summaries, weighted_rmse=0.0)
        record.update(fit_summary=summary, bounds_count=len(bounds), long_school=(ls or {}).get('summary'),
                      boundary=(bd or {}).get('summary'), status='V24917_TARGETED_FIT')
        context['v24917'] = record
        context['v24917_ls'] = ls
        context['v24917_bd'] = bd
        context['v24917_step_model'] = step_model
        if bd:
            write_json(folder / 'V24917_BOUNDARY_STEPS.json', bd)
        write_json(folder / 'V24917_STEP_MODEL.json', step_model)
        write_json(folder / 'V24917_FIT_SUMMARY.json', record)
        write_csv(folder / 'V24917_FIT_PROJECTION_ROWS.csv', rows)
        lp = summary['linear_prediction']
        print('R1 CORDON V24917 TG: phase=%s ratio=%.3f zones=%d rows=%d at_upper=%d predicted_ratio=%.3f'
              % (phase, ratio, summary['zones_changed'], summary['rows'], summary['rows_at_upper'],
                 lp['ratio_after'] or 0.0))
    except Exception as exc:
        record.update(status='FIT_FALLBACK_PARENT_PROPOSAL', error=type(exc).__name__ + ':' + str(exc))
        context['v24917'] = record
        write_json(folder / 'V24917_FIT_FALLBACK.json', record)
        print('R1 CORDON V24917 TG: fit fallback to parent proposal: %s' % record['error'])
    return context


def extra_rows(context, scale):
    """LSGEN + BNDGEN rows at a scale (donor rows_at_scale functions)."""
    lsgen = parent_module('r1_15a2_long_school_generation_v24917')
    bdgen = parent_module('r1_15a2_boundary_generation_v24917')
    return lsgen.rows_at_scale((context or {}).get('v24917_ls'), scale) + \
        bdgen.rows_at_scale((context or {}).get('v24917_bd'), scale)
