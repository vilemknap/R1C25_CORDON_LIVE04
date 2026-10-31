"""Hash-pinned PROFILE488 aggressive policy adapted to CORDON, not its live launcher.

Only search controls are copied. No profile authority/GEH threshold, approval,
C17 budget, COM attachment, matrix write or automatic outer loop is enabled.
"""
from __future__ import annotations
import copy
from .common import ROOT, require, canonical_hash, sha256, read_json
from .state import validate_runtime_options

SOURCE_REL = 'provenance/aggressive_profile/R1_15A2_AGGRESSIVE_TUNING_V1.json'
SOURCE_SHA256 = 'c41e28c1ecbaa3bbdef43b259458f6407bfbef6af240d9312282e47e6b83e10f'
DESIGN_SOURCE_REL = 'provenance/aggressive_profile/TGTD_BASE_CONFIG_REFERENCE.json'
DESIGN_SOURCE_SHA256 = '6aad964325002c8d13c10412bce3f0242ee75fae3640214bc5ab8ec823edda56'
DESIGN_KEYS = ('generation_signed_refinement', 'generation_bound_constrained_projection',
               'generation_coefficient_authority', 'salary', 'zahr')
POLICY_ID = 'CORDON_AGGRESSIVE_V1_PROFILE_FIX1_SEARCH_ONLY'
MUTABLE = {'NATIVE_CW', 'NATIVE_CW_NOT', 'NATIVE_CS', 'NATIVE_CS_NOT'}
META = 'aggressive_effective'


def source_policy():
    path = ROOT / SOURCE_REL
    require(path.is_file() and sha256(path) == SOURCE_SHA256, 'AGGRESSIVE_SOURCE_POLICY_HASH_MISMATCH')
    result = read_json(path)
    require(result.get('schema') == 'R1_15A2_AGGRESSIVE_TGTD_TUNING_V1', 'AGGRESSIVE_SOURCE_SCHEMA')
    return result


def design_defaults():
    path = ROOT / DESIGN_SOURCE_REL
    require(path.is_file() and sha256(path) == DESIGN_SOURCE_SHA256, 'AGGRESSIVE_DESIGN_SOURCE_HASH_MISMATCH')
    source = read_json(path)
    # Explicit whitelist; all profile counts, matrix IDs, run roots and live flags
    # in the reference config are evidence only and are NEVER copied.
    defaults = {k: copy.deepcopy(source[k]) for k in DESIGN_KEYS}
    for value in defaults.values():
        if 'acceptance_authority' in value:
            value['acceptance_authority'] = 'OFFLINE_DESIGN_REQUIRES_CORDON_LIVE_VERIFICATION'
    defaults['generation_coefficient_authority']['current_value_source'] = 'EXPLICIT_ZONE_SNAPSHOT_NOT_LIVE_READ'
    defaults['generation_signed_refinement']['reference_source'] = 'EXPLICIT_RUN_START_PARAMETER_REFERENCE'
    return defaults


def enabled(cfg):
    return cfg.get('aggressive_policy', {}).get('enabled') is True


def science_hash(cfg):
    return canonical_hash({k: v for k, v in cfg.items() if k != META})


def assert_offline_contract(cfg):
    validate_runtime_options(cfg)
    require(cfg.get('mode') == 'OFFLINE_PROPOSAL' and cfg.get('apply') is False,
            'AGGRESSIVE_OFFLINE_ONLY')
    require(cfg.get('model_year') == 2025 and cfg.get('survey_year') == 2026, 'AGGRESSIVE_YEAR_CONTRACT')
    require(cfg.get('category') == 'OA' and cfg.get('basis') == 'RPDI', 'AGGRESSIVE_OA_RPDI_ONLY')
    for key in ('run_assignment', 'run_procseq', 'write_od', 'supply_enabled'):
        require(cfg.get(key) is False, 'AGGRESSIVE_FORBIDDEN_FLAG:' + key)
    norm = [str(v).upper() for v in cfg.get('mutable_dsegs', [])]
    require(len(norm) == len(set(norm)) and set(norm).issubset(MUTABLE), 'AGGRESSIVE_FROZEN_SCOPE_CHANGED')
    require(cfg.get('pair_role_policy') == 'PAIRED_HOLDOUT_NO_REVERSE_LEAKAGE', 'AGGRESSIVE_ROLE_POLICY_CHANGED')
    require(cfg.get('c17_allocation_policy') in ('UNAPPROVED', 'DISABLED', 'BOUNDED_SCENARIO'), 'AGGRESSIVE_C17_POLICY')
    # A table of profile counts must never become the cordon observation authority.
    for key in ('expected_12d_rows', 'current_countlocation_authority', 'geh20_transition_policy'):
        require(key not in cfg, 'PROFILE_SETTING_IN_CORDON:' + key)


def effective_config(cfg, outer_cycle=None):
    """Resolve a stage for ONE offline proposal. Never advances a real cycle.

    A new science lineage is required. A resolved config is immutable: callers
    cannot edit stage bounds after sealing its effective fingerprint.
    """
    assert_offline_contract(cfg)
    require(enabled(cfg), 'AGGRESSIVE_POLICY_NOT_ENABLED')
    policy = cfg['aggressive_policy']
    require(policy.get('policy_id') == POLICY_ID and policy.get('source_sha256') == SOURCE_SHA256,
            'AGGRESSIVE_POLICY_IDENTITY_MISMATCH')
    require(policy.get('lineage') == 'NEW_OFFLINE_LINEAGE_FROM_EXPLICIT_SNAPSHOT', 'AGGRESSIVE_NEW_LINEAGE_REQUIRED')
    if META in cfg:
        require(cfg[META].get('effective_science_sha256') == science_hash(cfg), 'AGGRESSIVE_EFFECTIVE_CONFIG_CHANGED')
        require(outer_cycle is None or outer_cycle == cfg[META]['outer_cycle'], 'AGGRESSIVE_STAGE_REBASE_REQUIRES_BASE_CONFIG')
        source = source_policy(); design_defaults()  # integrity matters on repeat use
        cycle = policy.get('outer_cycle')
        require(type(cycle) is int and 1 <= cycle and (cycle <= 100 or cfg.get('limit_profile')=='PRACTICAL_V1'), 'AGGRESSIVE_OUTER_CYCLE_OUT_OF_RANGE')
        expected_stage = next((s for s in source['generation_stages'] if cycle <= s['through_outer_cycle']),source['generation_stages'][-1])
        meta = cfg[META]
        require(meta.get('stage') == expected_stage and meta.get('outer_cycle') == cycle
                and meta.get('policy_id') == POLICY_ID
                and meta.get('source_policy_sha256') == SOURCE_SHA256
                and meta.get('design_source_sha256') == DESIGN_SOURCE_SHA256
                and meta.get('apply_permitted') is False
                and meta.get('live_visum_tested') is False,
                'AGGRESSIVE_EFFECTIVE_METADATA_CHANGED')
        return copy.deepcopy(cfg)
    cycle = policy.get('outer_cycle', 1) if outer_cycle is None else outer_cycle
    require(type(cycle) is int and 1 <= cycle and (cycle <= 100 or cfg.get('limit_profile')=='PRACTICAL_V1'), 'AGGRESSIVE_OUTER_CYCLE_OUT_OF_RANGE')
    source = source_policy()
    stage = next((s for s in source['generation_stages'] if cycle <= s['through_outer_cycle']),source['generation_stages'][-1])
    out = copy.deepcopy(cfg)
    for key, value in design_defaults().items():
        require(key not in out or out[key] == value, 'AGGRESSIVE_BASE_DESIGN_OVERRIDE_REQUIRES_NEW_POLICY:' + key)
        out[key] = value
    out['aggressive_policy']['outer_cycle'] = cycle
    out['relative_od_lower'] = -stage['max_od_relative_down']
    out['relative_od_upper'] = stage['max_od_relative_up']
    for key in ('max_od_relative_up', 'max_od_relative_down', 'max_add_log_up', 'max_add_log_down'):
        out[key] = stage[key]
    out['guidance_mode'] = 'SIGNED'
    out.setdefault('salary', {})['max_abs_delta_per_block'] = stage['salary_max_abs_delta_per_block']
    signed = out.setdefault('generation_signed_refinement', {})
    signed['max_family_global_log_up'] = stage['signed_max_family_global_log_up']
    signed['max_family_global_log_down'] = stage['signed_max_family_global_log_down']
    signed['soft_outward_step_factor'] = stage['signed_soft_outward_step_factor']
    out['generation_backtracking_scales'] = source['generation_backtracking_scales']
    out['td_realization_backtracking_scales'] = source['td_realization_backtracking_scales']
    out['generation_min_cal_relative_improvement'] = source['generation_min_cal_relative_improvement']
    out['generation_max_cal_relative_degradation'] = source['generation_max_cal_relative_degradation_in_early_exploration']
    out['td_soft_reference_policy'] = {
        'aggregate_selected_min_relative_improvement': source['td_min_aggregate_selected_relative_improvement'],
        'selected_component_max_relative_degradation': source['td_max_selected_component_relative_degradation'],
        'nonselected_component_max_relative_degradation': source['td_max_nonselected_component_relative_degradation'],
        'native_ipf_tolerance_relaxed': False,
    }
    # Native TD acceptance keys are supplied, not only an advisory mirror.
    out['td'] = {
        'min_selected_component_relative_improvement': source['td_min_aggregate_selected_relative_improvement'],
        'max_selected_component_relative_degradation': source['td_max_selected_component_relative_degradation'],
        'max_nonselected_component_objective_degradation': source['td_max_nonselected_component_relative_degradation'],
    }
    from .limits import numerical
    numeric=numerical(out)
    out['generation_min_cal_relative_improvement']=numeric['generation_min_relative_improvement']
    out['td']['min_selected_component_relative_improvement']=numeric['td_min_relative_improvement']
    out['td_soft_reference_policy']['aggregate_selected_min_relative_improvement']=numeric['td_min_relative_improvement']
    out['native_ipf_tolerance_policy'] = 'UNCHANGED_NEVER_RELAXED_BY_CALIBRATOR'
    out[META] = {
        'policy_id': POLICY_ID, 'stage': copy.deepcopy(stage), 'outer_cycle': cycle,
        'cycle_kind': 'EXPLICIT_OFFLINE_STAGE_SELECTOR_NOT_LIVE_ITERATION',
        'source_policy_sha256': SOURCE_SHA256, 'design_source_sha256': DESIGN_SOURCE_SHA256, 'base_config_sha256': canonical_hash(cfg),
        'effective_science_sha256': science_hash(out),
        'limit_profile':out.get('limit_profile','LEGACY_STRICT'),
        'last_stage_continuation':cycle>source['generation_stages'][-1]['through_outer_cycle'],
        'new_science_lineage': True, 'no_2022_resume': True,
        'c17_budgets_unchanged': True, 'regularization_unchanged': True,
        'profile_GEH_relaxations_imported': False, 'validation_split_unchanged': True,
        'apply_permitted': False, 'live_visum_tested': False,
    }
    return out


def td_soft_fit_check(before, after, selected, cfg):
    """Pure diagnostic gate for supplied component losses; does not run TD/IPF.

    Mirrors the source aggregate + per-component limits. Missing components,
    zero baselines with positive deterioration and nonfinite values fail closed.
    No claim of native-IPF convergence is made by this check.
    """
    import math
    require(META in cfg and cfg[META]['effective_science_sha256'] == science_hash(cfg), 'AGGRESSIVE_EFFECTIVE_CONFIG_REQUIRED')
    require(set(before) == set(after) and bool(before), 'TD_COMPONENT_SCOPE_MISMATCH')
    require(bool(selected) and set(selected).issubset(before), 'TD_SELECTED_SCOPE_INVALID')
    require(len(selected) == len(set(selected)), 'TD_DUPLICATE_SELECTED_COMPONENT')
    require(all(not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v) and v >= 0
                for v in list(before.values()) + list(after.values())), 'TD_INVALID_COMPONENT_LOSS')
    gates = cfg['td']; failures = []; ratios = {}
    b = sum(before[k] for k in selected); a = sum(after[k] for k in selected)
    improve = (b - a) / b if b > 0 else 0.0
    if improve < gates['min_selected_component_relative_improvement']:
        failures.append('TD_AGGREGATE_IMPROVEMENT_TOO_SMALL')
    for key in before:
        ratio = (after[key] - before[key]) / before[key] if before[key] > 0 else (0.0 if after[key] == 0 else None)
        ratios[key] = ratio
        cap = gates['max_selected_component_relative_degradation'] if key in selected else gates['max_nonselected_component_objective_degradation']
        if ratio is None or ratio > cap + 1e-12:
            failures.append('TD_COMPONENT_DEGRADATION:' + str(key))
    return {'passes_soft_fit_only': not failures, 'failures': failures, 'relative_aggregate_improvement': improve,
            'component_relative_degradation': ratios, 'native_ipf_verified': False,
            'native_ipf_tolerance_relaxed': False, 'apply_permitted': False}
