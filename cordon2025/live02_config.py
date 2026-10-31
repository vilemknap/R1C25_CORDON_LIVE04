"""LIVE02 contract: one explicit TG trial write policy on top of the LIVE01 view.

The LIVE01 read-only contract is NOT weakened.  LIVE02 derives an immutable
LIVE01-shaped view (writes disabled) only for the existing cordon mathematics,
and keeps every write permission in this separate, validated file.
"""
from copy import deepcopy
from .common import ROOT, require, read_json, sha256, canonical_hash
from .live01_config import validate_config as validate_live01, donor_config

SCHEMA = 'R1_CORDON_LIVE02_CONFIG_V1'
STAGE = 'LIVE02_TG_CYCLE'
METHODS = ('ALL_ORDERED_UNIQUE_PAIRS', 'EXACT_TWO_HITS')
GENERATION_ATTRS = ('ADD_PROD_W', 'ADD_ATT_W', 'ADD_SALARY', 'ADD_PROD_S', 'ADD_ATT_S',
                    'ZAHR_PROD_WORK', 'ZAHR_ATR_WORK', 'ZAHR_PROD_SERV', 'ZAHR_ATR_SERV')
MAX_TG_CYCLES = 10
DONOR_SOURCE = 'provenance/live01/DONOR_EFFECTIVE_CONFIG_FORENSIC_ONLY.json'


def _num(value, label, lo=None, hi=None, *, positive=False):
    require(isinstance(value, (int, float)) and not isinstance(value, bool), 'LIVE02_CONFIG_NUMBER:' + label)
    value = float(value)
    require(value == value and abs(value) != float('inf'), 'LIVE02_CONFIG_NUMBER:' + label)
    require(not positive or value > 0, 'LIVE02_CONFIG_POSITIVE:' + label)
    require(lo is None or value >= lo, 'LIVE02_CONFIG_RANGE:' + label)
    require(hi is None or value <= hi, 'LIVE02_CONFIG_RANGE:' + label)
    return value


def _int(value, label, lo, hi):
    require(type(value) is int and lo <= value <= hi, 'LIVE02_CONFIG_INT:' + label)
    return value


def donor_runtime_matches_source(cfg):
    """Every copied donor runtime value must equal the pinned donor config."""
    donor = read_json(ROOT / DONOR_SOURCE)
    rt = cfg['donor_runtime']
    mismatches = []
    def same(path, mine, theirs):
        if mine != theirs:
            mismatches.append(path)
    for key in ('expected_zones', 'require_solver_convergence_for_apply',
                'require_projection_convergence_for_apply', 'com_resilience'):
        same(key, rt[key], donor.get(key))
    for key in ('passenger_dsegs', 'freight_dsegs', 'component_matrix_nos', 'link_attributes',
                'excluded_link_keys', 'editable_link_types', 'assignment_operations', 'gap_readback'):
        same('supply.' + key, rt['supply'][key], donor['supply'].get(key))
    same('matrix_scope_by_block.GENERATION', rt['matrix_scope_by_block']['GENERATION'],
         donor['matrix_scope_by_block']['GENERATION'])
    same('min_changed_matrices_by_block.GENERATION', rt['min_changed_matrices_by_block']['GENERATION'],
         donor['min_changed_matrices_by_block']['GENERATION'])
    same('shared_objective.minimum_improvement', rt['shared_objective']['minimum_improvement'],
         donor['shared_objective']['minimum_improvement'])
    same('trial_calibration.require_reproducible_reapply', rt['trial_calibration']['require_reproducible_reapply'],
         donor['trial_calibration']['require_reproducible_reapply'])
    same('performance.bulk_link_read', rt['performance']['bulk_link_read'], donor['performance']['bulk_link_read'])
    mine = rt['performance']['v24915_perf1']['phase_specific_procseq']
    theirs = donor['performance']['v24915_perf1']['phase_specific_procseq']
    same('performance.v24915_perf1.phase_specific_procseq', mine, theirs)
    gs = cfg['generation_search']
    same('generation_search.backtracking_scales', gs['backtracking_scales'], donor['backtracking_scales'])
    same('generation_search.max_generation_pa_relative_gap', gs['max_generation_pa_relative_gap'],
         donor['max_generation_pa_relative_gap'])
    same('generation_search.max_generation_effect_log_error', gs['max_generation_effect_log_error'],
         donor['max_generation_effect_log_error'])
    same('generation_search.first_sufficient_min_relative_improvement',
         gs['first_sufficient_min_relative_improvement'],
         donor['performance']['first_sufficient']['generation_min_relative_improvement'])
    # Fewer trials is a conservative operational choice; more than the donor is drift.
    if gs['max_trials'] > donor['trial_calibration']['max_trials_per_block']['GENERATION']:
        mismatches.append('generation_search.max_trials')
    return mismatches


def validate_config(cfg, *, allow_donor_overrides=False):
    require(cfg.get('schema') == SCHEMA and cfg.get('live_stage') == STAGE, 'LIVE02_CONFIG_SCHEMA')
    require(cfg.get('execution_mode') == 'TECHNICAL_TRIAL', 'LIVE02_PRODUCTION_NOT_AUTHORIZED')
    path = ROOT / cfg['live01_contract_file']
    require(cfg['live01_contract_file'] == 'CORDON_LIVE01_CONFIG.json', 'LIVE02_LIVE01_CONTRACT_PATH')
    require(sha256(path) == cfg['live01_contract_sha256'], 'LIVE02_LIVE01_CONTRACT_CHANGED')
    _int(cfg.get('outer_cycle_start'), 'outer_cycle_start', 1, 100)
    _int(cfg.get('max_tg_cycles'), 'max_tg_cycles', 1, MAX_TG_CYCLES)
    ex = cfg.get('explicit_excluded_zone_nos')
    require(isinstance(ex, list) and all(type(z) is int and z > 0 for z in ex) and len(set(ex)) == len(ex),
            'LIVE02_INVALID_ZONE_EXCLUSIONS')
    wp = cfg['write_policy']
    require(wp.get('tg_zone_parameter_writes') is True, 'LIVE02_TG_WRITE_POLICY_REQUIRED')
    for key in ('td_parameter_writes', 'direct_od_matrix_writes', 'load_version', 'overwrite_source_version'):
        require(wp.get(key) is False, 'LIVE02_FORBIDDEN_WRITE_FLAG:' + key)
    require(isinstance(wp.get('save_accepted_version_new_file'), bool), 'LIVE02_SAVE_FLAG')
    guard = cfg['isolated_copy_guard']
    tokens = guard.get('required_version_name_tokens_any')
    require(isinstance(tokens, list) and tokens and all(isinstance(t, str) and t.strip() for t in tokens),
            'LIVE02_ISOLATED_COPY_GUARD_REQUIRED')
    require('2022' in guard.get('forbidden_version_name_tokens', []), 'LIVE02_2022_GUARD_REQUIRED')
    acc = cfg['acceptance']
    require(acc.get('method') in METHODS and acc.get('secondary_method') in METHODS + (None,)
            and acc.get('method') != acc.get('secondary_method'), 'LIVE02_ACCEPTANCE_METHOD')
    _num(acc['secondary_max_relative_degradation'], 'secondary_max_relative_degradation', 0.0, 1.0)
    _num(acc['min_relative_improvement'], 'min_relative_improvement', 0.0, 1.0)
    _num(acc['minimum_absolute_improvement'], 'minimum_absolute_improvement', 0.0)
    dec = acc.get('diagnostic_hash_decimals')
    require(dec is None or (type(dec) is int and 3 <= dec <= 12), 'LIVE02_DIAGNOSTIC_HASH_DECIMALS')
    require(acc.get('reproducibility') == 'EXACT_CORDON_DIAGNOSTIC_HASH', 'LIVE02_REPRODUCIBILITY_POLICY')
    require(acc.get('candidate_capture_failure_policy') in
            ('REJECT_CANDIDATE_AFTER_VERIFIED_ROLLBACK', 'FAIL_RUN_AFTER_VERIFIED_ROLLBACK'), 'LIVE02_CAPTURE_FAILURE_POLICY')
    gs = cfg['generation_search']
    scales = gs.get('backtracking_scales')
    require(isinstance(scales, list) and scales and all(0 < _num(s, 'scale') <= 1 for s in scales)
            and len(set(scales)) == len(scales), 'LIVE02_BACKTRACKING_SCALES')
    _int(gs.get('max_trials'), 'max_trials', 1, len(scales))
    for key in ('first_sufficient_enabled', 'pre_apply_gate_nonfatal', 'pre_apply_gate_shortcut'):
        require(isinstance(gs.get(key), bool), 'LIVE02_BOOL:' + key)
    _num(gs['first_sufficient_min_relative_improvement'], 'first_sufficient', 0.0, 1.0)
    _num(gs['max_generation_pa_relative_gap'], 'max_generation_pa_relative_gap', 0.0, 0.5, positive=True)
    _num(gs['max_generation_effect_log_error'], 'max_generation_effect_log_error', 0.0, 1.0, positive=True)
    ladder = gs.get('solver_tolerance_ladder')
    require(isinstance(ladder, list) and len(ladder) <= 6, 'LIVE02_SOLVER_LADDER')
    for step in ladder:
        require(isinstance(step, dict) and set(step) == {'solver_tolerance', 'solver_max_iter'}, 'LIVE02_SOLVER_LADDER')
        _num(step['solver_tolerance'], 'solver_tolerance', 0.0, 1e-6, positive=True)
        _int(step['solver_max_iter'], 'solver_max_iter', 1, 10000000)
    ev = cfg['evaluation']
    require(isinstance(ev.get('trial_full_geometry_check'), bool) and isinstance(ev.get('keep_trial_capture_db'), bool),
            'LIVE02_EVALUATION_FLAGS')
    require(ev.get('rollback_proof') in ('PATH_VOLUME_SIGNATURE_THEN_FULL_CAPTURE', 'FULL_CAPTURE'), 'LIVE02_ROLLBACK_PROOF')
    rt = cfg['donor_runtime']
    require(rt.get('source') == DONOR_SOURCE and rt.get('expected_zones') == 681, 'LIVE02_DONOR_RUNTIME_SOURCE')
    require(rt['supply']['gap_readback'].get('source') == 'PRT_ASS_QUALITY_LIST', 'LIVE02_GAP_READBACK_POLICY')
    require(rt['trial_calibration'].get('require_reproducible_reapply') is True, 'LIVE02_REPRODUCIBLE_REAPPLY_REQUIRED')
    mismatches = donor_runtime_matches_source(cfg)
    require(allow_donor_overrides or not mismatches, 'LIVE02_DONOR_RUNTIME_DRIFT:' + ','.join(mismatches))
    require(cfg.get('generation_mode') in GENERATION_MODES, 'LIVE02_GENERATION_MODE')
    if cfg['generation_mode'] == 'V24917_TARGETED_STEP1':
        validate_v24917(cfg, allow_donor_overrides)
    require(not set(cfg) - set(read_json(ROOT / 'CORDON_LIVE02_CONFIG.json')), 'LIVE02_UNKNOWN_CONFIG_FIELD')
    return cfg


GENERATION_MODES = ('V24917_TARGETED_STEP1', 'HOTFIX2_BACKTRACKING')
V24917_RUN_OPTIONS_PIN = 'provenance/v24917/R1_RUN_OPTIONS_V24917.json'
V24917_NOT_PORTED = {'fa_enabled': False}


def validate_v24917(cfg, allow_donor_overrides=False):
    v = cfg.get('v24917')
    require(isinstance(v, dict), 'LIVE02_V24917_SECTION')
    require(sha256(ROOT / V24917_RUN_OPTIONS_PIN) == v.get('run_options_source_sha256'), 'LIVE02_V24917_RUN_OPTIONS_PIN')
    require(v.get('run_options_environment_overrides') is False, 'LIVE02_V24917_ENV_OVERRIDES_FORBIDDEN')
    src = read_json(ROOT / V24917_RUN_OPTIONS_PIN)
    opts = v.get('run_options')
    require(isinstance(opts, dict) and opts, 'LIVE02_V24917_RUN_OPTIONS')
    for key, value in V24917_NOT_PORTED.items():
        require(opts.get(key) == value, 'LIVE02_V24917_NOT_PORTED_OPTION:' + key)
    drift = [k for k, val in opts.items() if k not in V24917_NOT_PORTED and src.get(k) != val]
    require(allow_donor_overrides or not drift, 'LIVE02_V24917_RUN_OPTION_DRIFT:' + ','.join(drift))
    from .common import parent_module
    parent_module('r1_15a2_demand_policy_v1').validate(dict(opts))
    r = v.get('catchup_until_model_obs_ratio')
    _num(r, 'catchup_until_model_obs_ratio', 0.0, 1.5, positive=True)
    require(v.get('boundary_zone_policy') == 'CONFIGURED_ZONES_POSITIVE_WS_PA_AND_NO_ADD_ZAHR_ACTUATOR', 'LIVE02_V24917_BD_POLICY')
    require(v.get('long_exposure') == 'CORDON_PAIR_NATIVE_CL_PATH_VOLUME', 'LIVE02_V24917_LONG_EXPOSURE')
    return v


def load_config(path=None, overrides=None):
    cfg = read_json(path or ROOT / 'CORDON_LIVE02_CONFIG.json')
    if overrides:
        cfg = merge(cfg, overrides)
    validate_config(cfg, allow_donor_overrides=bool(overrides and overrides.get('_allow_donor_overrides')))
    return cfg


def merge(base, overrides):
    out = deepcopy(base)
    for key, value in overrides.items():
        if key.startswith('_'):
            continue
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = merge(out[key], value)
        else:
            out[key] = deepcopy(value)
    return out


def live01_view(cfg, outer_cycle):
    """LIVE01-shaped, writes-disabled view used only for the existing math."""
    view = read_json(ROOT / cfg['live01_contract_file'])
    view['outer_cycle'] = int(outer_cycle)
    view['explicit_excluded_zone_nos'] = list(cfg['explicit_excluded_zone_nos'])
    validate_live01(view)
    return view


def adapter_config(cfg, outer_cycle, actuatable_zones=None):
    """Donor adapter cfg = exact LIVE01 donor design cfg + pinned donor runtime."""
    view = live01_view(cfg, outer_cycle)
    out = donor_config(view)
    if actuatable_zones is not None:
        out['actuatable_zones'] = list(actuatable_zones)
    rt = deepcopy(cfg['donor_runtime'])
    rt.pop('source')
    for key, value in rt.items():
        out[key] = value
    gs = cfg['generation_search']
    # Donor semantics: the planned scale list must be fully evaluated (otherwise
    # SEARCH_TRUNCATED_NOT_A_PLATEAU).  A smaller trial budget therefore keeps the
    # largest steps in donor order instead of truncating a planned search.
    out['backtracking_scales'] = list(gs['backtracking_scales'])[:gs['max_trials']]
    out['max_generation_pa_relative_gap'] = gs['max_generation_pa_relative_gap']
    out['max_generation_effect_log_error'] = gs['max_generation_effect_log_error']
    out.setdefault('trial_calibration', {})['max_trials_per_block'] = {'GENERATION': gs['max_trials']}
    out['performance']['first_sufficient'] = {
        'enabled': gs['first_sufficient_enabled'],
        'gate': 'EXISTING_ACCEPTANCE_MUST_PASS_BEFORE_EARLY_STOP',
        'generation_min_relative_improvement': gs['first_sufficient_min_relative_improvement']}
    out['live02'] = {'acceptance': deepcopy(cfg['acceptance']), 'outer_cycle': int(outer_cycle),
                     'evaluation': deepcopy(cfg['evaluation']), 'generation_mode': cfg.get('generation_mode')}
    if cfg.get('generation_mode') == 'V24917_TARGETED_STEP1':
        from .live02_v24917 import targeted_policy, run_options
        out['v24917_targeted_generation'] = targeted_policy(cfg)
        trials = min(int(run_options(cfg)['tg_max_trials']), int(gs['max_trials']))
        out['trial_calibration']['max_trials_per_block'] = {'GENERATION': trials}
        out['backtracking_scales'] = list(gs['backtracking_scales'])[:trials]
    # Explicit separate guard: the cordon math view keeps apply=False.  The donor
    # adapter checks only convergence flags for apply_generation, never 'apply'.
    require(out.get('apply') is False, 'LIVE02_MATH_VIEW_APPLY_FLAG')
    return out


def config_identity(cfg):
    return canonical_hash(cfg)
