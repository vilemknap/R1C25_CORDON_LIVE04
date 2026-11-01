"""LIVE04 contract (CORDON_LIVE04_CONFIG.json) = LIVE03 contract on the v7 @ 977cef4 runtime.

Validation:
* the inherited part by the unchanged LIVE02 validator on a LIVE02-shaped view
  (the old V24917 section is not part of LIVE04, so the view carries the plain
  donor generation mode; the v7 section is validated here instead);
* the LIVE03 additions by the unchanged live03_config.validate_sections;
* the v7 section: run options byte-pinned to the v7 file except the three
  documented cordon deviations, policy validated by the v7 demand_policy;
* the only new write permission: LONG post-TD mask matrices (live04_guard).
"""
from copy import deepcopy
from .common import ROOT, require, read_json, sha256, parent_module
from . import live02_config as l2
from . import live03_config as l3
from .live03_observations import validate as validate_observations  # noqa: F401  (re-export for tools)

SCHEMA = 'R1_CORDON_LIVE04_CONFIG_V1'
STAGE = 'LIVE04_V7_TG_TD_CYCLE'
CONFIG_FILE = 'CORDON_LIVE04_CONFIG.json'
LIVE04_KEYS = l3.LIVE03_KEYS + ('v7', 'memory')


def live02_view(cfg):
    v = {k: deepcopy(val) for k, val in cfg.items() if k not in LIVE04_KEYS}
    v['schema'] = l2.SCHEMA; v['live_stage'] = l2.STAGE
    v['max_tg_cycles'] = 1
    v['write_policy'].pop('long_post_td_mask_matrix_writes', None)
    v['write_policy']['td_parameter_writes'] = False
    v['acceptance']['method'] = 'ALL_ORDERED_UNIQUE_PAIRS'
    v['acceptance']['secondary_method'] = 'EXACT_TWO_HITS'
    v['generation_mode'] = 'HOTFIX2_BACKTRACKING'   # v7 STEP1 is validated in validate_v7
    rt = v['donor_runtime']
    rt['matrix_scope_by_block'] = {'GENERATION': rt['matrix_scope_by_block']['GENERATION']}
    rt['min_changed_matrices_by_block'] = {'GENERATION': rt['min_changed_matrices_by_block']['GENERATION']}
    return v


def validate_v7(cfg, allow_donor_overrides=False):
    from .live04_v7 import RUN_OPTIONS_PIN, CORDON_DEVIATIONS, SOURCE_COMMIT, SOURCE_REPOSITORY
    v = cfg.get('v7')
    require(isinstance(v, dict), 'LIVE04_V7_SECTION')
    require(v.get('source_repository') == SOURCE_REPOSITORY and v.get('source_commit') == SOURCE_COMMIT,
            'LIVE04_V7_SOURCE_IDENTITY')
    require(v.get('run_options_pin') == RUN_OPTIONS_PIN and sha256(ROOT / RUN_OPTIONS_PIN) == v.get('run_options_source_sha256'),
            'LIVE04_V7_RUN_OPTIONS_PIN')
    require(v.get('run_options_environment_overrides') is False, 'LIVE04_V7_ENV_OVERRIDES_FORBIDDEN')
    src = read_json(ROOT / RUN_OPTIONS_PIN)
    opts = v.get('run_options')
    require(isinstance(opts, dict) and set(opts) == set(src), 'LIVE04_V7_RUN_OPTIONS_KEYS')
    for key, value in CORDON_DEVIATIONS.items():
        require(type(opts.get(key)) is type(value) or isinstance(value, float), 'LIVE04_V7_CORDON_DEVIATION:' + key)
        require(opts.get(key) == value, 'LIVE04_V7_CORDON_DEVIATION:' + key)
    require(set(v.get('cordon_deviations') or {}) == set(CORDON_DEVIATIONS), 'LIVE04_V7_DEVIATIONS_DOCUMENTED')
    drift = [k for k, val in opts.items() if k not in CORDON_DEVIATIONS and src.get(k) != val]
    require(allow_donor_overrides or not drift, 'LIVE04_V7_RUN_OPTION_DRIFT:' + ','.join(drift))
    validated = parent_module('r1_15a2_demand_policy_v1').validate(dict(opts))
    require(validated['ts_enabled'] is True, 'LIVE04_STEP1_REQUIRED')
    require(validated['mg_enabled'] is True, 'LIVE04_MOBILITY2_REQUIRED')
    require(v.get('targeted_generation_policy') == 'DONOR_DEFAULT_POLICY_V7_ROLE_ENVELOPES', 'LIVE04_V7_POLICY')
    l2._num(v.get('catchup_until_model_obs_ratio'), 'catchup_until_model_obs_ratio', 0.0, 1.5, positive=True)
    require(v.get('boundary_zone_policy') == 'CONFIGURED_ZONES_POSITIVE_WS_PA_AND_NO_ADD_ZAHR_ACTUATOR',
            'LIVE04_V7_BD_POLICY')
    require(v.get('long_school') == 'SCHOOL_TG_FIXED_AMDY_LONG_TG_DEFERRED', 'LIVE04_V7_LONG_SCHOOL_POLICY')
    lm = v.get('long_post_td_mask') or {}
    lg = parent_module('r1_15a2_long_distance_guard_v24917')
    require(isinstance(lm.get('enabled'), bool) and isinstance(lm.get('require_masked_baseline'), bool)
            and lm.get('minimum_km') == lg.MIN_KM and lm.get('distance_matrix_no') == 9697
            and lm.get('distance_matrix_code') == 'R1_OSRM_DIST_KM'
            and lm.get('policy') == 'POST_TD_MULTIPLICATION_ACCEPT_VOLUME_LOSS', 'LIVE04_V7_LONG_MASK_POLICY')
    require(cfg['write_policy'].get('long_post_td_mask_matrix_writes') is lm['enabled'],
            'LIVE04_LONG_MASK_WRITE_POLICY_MUST_MATCH')
    env = v.get('coefficient_envelope') or {}
    require(set(env) == {'PROD', 'ATT', 'approval'} and isinstance(env.get('approval'), str) and env['approval'],
            'LIVE04_COEFFICIENT_ENVELOPE_FIELDS')
    for role in ('PROD', 'ATT'):
        band = env[role]
        require(isinstance(band, list) and len(band) == 2 and all(isinstance(x, (int, float)) for x in band)
                and 0.0 < float(band[0]) < 1.0 < float(band[1]) <= 20.0, 'LIVE04_COEFFICIENT_ENVELOPE:' + role)
    require([float(x) for x in env['PROD']] == [float(validated['mg_min_ratio']), float(validated['mg_max_ratio'])],
            'LIVE04_PROD_ENVELOPE_MUST_EQUAL_MOBILITY_BAND')
    mg = v.get('mobility_guards') or {}
    require(mg.get('production_band_from_run_options') is True and mg.get('mobilityzone1') is True
            and [float(x) for x in mg.get('ws_attraction_coefficient_band') or []] == [float(x) for x in env['ATT']],
            'LIVE04_ATTRACTION_FENCE_MUST_EQUAL_ATT_ENVELOPE')
    return v


def validate_memory(m):
    """LIVE04.1 run memory: prediction and step choice only, never acceptance."""
    require(isinstance(m, dict) and m.get('role') == 'PREDICTION_AND_STEP_CHOICE_ONLY_NEVER_ACCEPTANCE',
            'LIVE04_MEMORY_ROLE')
    for key in ('enabled', 'td_jacobian_reuse', 'tg_route_correction'):
        require(isinstance(m.get(key), bool), 'LIVE04_MEMORY_FLAG:' + key)
    for key, lo, hi in (('td_verify_tolerance', 0.0, 1.0), ('tg_correction_weight', 0.0, 1.0),
                        ('tg_correction_decay', 0.0, 1.0), ('tg_min_direction_cosine', 0.0, 1.0),
                        ('tg_single_node_curvature', 0.0, 1.0)):
        l2._num(m.get(key), key, lo, hi)
    l2._int(m.get('max_age_cycles'), 'max_age_cycles', 1, 10)
    return m


def validate_config(cfg, *, allow_donor_overrides=False):
    require(cfg.get('schema') == SCHEMA and cfg.get('live_stage') == STAGE, 'LIVE04_CONFIG_SCHEMA')
    require(set(cfg) == set(read_json(ROOT / CONFIG_FILE)), 'LIVE04_UNKNOWN_OR_MISSING_CONFIG_FIELD')
    l2.validate_config(live02_view(cfg), allow_donor_overrides=allow_donor_overrides)
    require(cfg['generation_mode'] == 'V24917_TARGETED_STEP1', 'LIVE04_REQUIRES_STEP1')
    require(set(cfg['write_policy']) == {'tg_zone_parameter_writes', 'td_parameter_writes', 'direct_od_matrix_writes',
                                         'load_version', 'overwrite_source_version', 'save_accepted_version_new_file',
                                         'long_post_td_mask_matrix_writes'}, 'LIVE04_WRITE_POLICY_FIELDS')
    l3.validate_sections(cfg)
    validate_v7(cfg, allow_donor_overrides)
    validate_memory(cfg['memory'])
    return cfg


def load_config(path=None, overrides=None):
    cfg = read_json(path or ROOT / CONFIG_FILE)
    if overrides:
        cfg = l2.merge(cfg, overrides)
    validate_config(cfg, allow_donor_overrides=bool(overrides and overrides.get('_allow_donor_overrides')))
    return cfg


def adapter_config(cfg, outer_cycle, actuatable_zones=None):
    from .live04_v7 import targeted_policy, run_options
    view = live02_view(cfg)
    out = l2.adapter_config(view, outer_cycle, actuatable_zones)
    out['matrix_scope_by_block'] = deepcopy(cfg['donor_runtime']['matrix_scope_by_block'])
    out['min_changed_matrices_by_block'] = deepcopy(cfg['donor_runtime']['min_changed_matrices_by_block'])
    out['live02']['acceptance'] = deepcopy(cfg['acceptance'])
    out['live02']['generation_mode'] = cfg['generation_mode']
    out['live03'] = {'blocks_per_cycle': list(cfg['blocks_per_cycle']), 'native_prediction': deepcopy(cfg['native_prediction']),
                     'td_cordon': deepcopy(cfg['td_cordon']), 'idp_guard': deepcopy(cfg['idp_guard'])}
    out['v24917_targeted_generation'] = targeted_policy(cfg)
    gs = cfg['generation_search']
    trials = min(int(run_options(cfg)['tg_max_trials']), int(gs['max_trials']))
    out['trial_calibration']['max_trials_per_block'] = {'GENERATION': trials}
    out['backtracking_scales'] = list(gs['backtracking_scales'])[:trials]
    out['live04'] = {'v7_source_commit': cfg['v7']['source_commit'],
                     'long_post_td_mask': deepcopy(cfg['v7']['long_post_td_mask'])}
    return out


live01_view = l2.live01_view
