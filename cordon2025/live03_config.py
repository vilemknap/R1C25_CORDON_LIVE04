"""LIVE03 contract = the validated LIVE02 contract + TD_CORDON, survey observations,
native frozen-path prediction and the IDP guard (CORDON_LIVE03_CONFIG.json).

Everything inherited from LIVE02 is validated by the unchanged LIVE02 validator
on a LIVE02-shaped view (same donor-drift checks); the LIVE03 additions are
validated here.  TD writes are the only new write permission.
"""
from copy import deepcopy
from .common import ROOT, require, read_json
from . import live02_config as l2
from .live03_observations import validate as validate_observations

SCHEMA = 'R1_CORDON_LIVE03_CONFIG_V1'
STAGE = 'LIVE03_TG_TD_CYCLE'
CONFIG_FILE = 'CORDON_LIVE03_CONFIG.json'
BLOCKS = ('GENERATION', 'TD_CORDON')
MAX_CYCLES = 10
LIVE03_KEYS = ('max_cycles', 'blocks_per_cycle', 'stop_after_cycle_without_change', 'observations',
               'native_prediction', 'td_cordon', 'idp_guard')


def live02_view(cfg):
    """LIVE02-shaped copy for the inherited validator (no LIVE03 permission leaks in)."""
    v = {k: deepcopy(val) for k, val in cfg.items() if k not in LIVE03_KEYS}
    v['schema'] = l2.SCHEMA; v['live_stage'] = l2.STAGE
    v['max_tg_cycles'] = 1
    v['write_policy']['td_parameter_writes'] = False
    v['acceptance']['method'] = 'ALL_ORDERED_UNIQUE_PAIRS'
    v['acceptance']['secondary_method'] = 'EXACT_TWO_HITS'
    rt = v['donor_runtime']
    rt['matrix_scope_by_block'] = {'GENERATION': rt['matrix_scope_by_block']['GENERATION']}
    rt['min_changed_matrices_by_block'] = {'GENERATION': rt['min_changed_matrices_by_block']['GENERATION']}
    return v


def _num(d, key, lo, hi, *, positive=False):
    return l2._num(d.get(key), key, lo, hi, positive=positive)


def validate_config(cfg, *, allow_donor_overrides=False):
    require(cfg.get('schema') == SCHEMA and cfg.get('live_stage') == STAGE, 'LIVE03_CONFIG_SCHEMA')
    l2.validate_config(live02_view(cfg), allow_donor_overrides=allow_donor_overrides)
    require(set(cfg) == set(read_json(ROOT / CONFIG_FILE)), 'LIVE03_UNKNOWN_OR_MISSING_CONFIG_FIELD')
    require(cfg['generation_mode'] == 'V24917_TARGETED_STEP1', 'LIVE03_REQUIRES_V24917_TARGETED_STEP1')
    return validate_sections(cfg)


def validate_sections(cfg):
    """LIVE03 additions (also reused unchanged by LIVE04)."""
    l2._int(cfg.get('max_cycles'), 'max_cycles', 1, MAX_CYCLES)
    blocks = cfg.get('blocks_per_cycle')
    require(isinstance(blocks, list) and blocks and set(blocks) <= set(BLOCKS) and len(set(blocks)) == len(blocks),
            'LIVE03_BLOCKS_PER_CYCLE')
    require(isinstance(cfg.get('stop_after_cycle_without_change'), bool), 'LIVE03_STOP_FLAG')
    wp = cfg['write_policy']
    require(wp.get('td_parameter_writes') is ('TD_CORDON' in blocks), 'LIVE03_TD_WRITE_POLICY_MUST_MATCH_BLOCKS')
    obs = validate_observations(cfg['observations'])
    acc = cfg['acceptance']
    roles = obs['methods']
    require(acc['method'] == next(m for m, r in roles.items() if r == 'PRIMARY'), 'LIVE03_ACCEPTANCE_PRIMARY')
    sec = next((m for m, r in roles.items() if r == 'SECONDARY'), None)
    require(acc.get('secondary_method') == sec, 'LIVE03_ACCEPTANCE_SECONDARY')
    npred = cfg['native_prediction']
    require(isinstance(npred.get('enabled'), bool) and isinstance(npred.get('tg_step1'), bool), 'LIVE03_NATIVE_FLAGS')
    fr = npred.get('tg_node_fractions')
    require(isinstance(fr, list) and 1 <= len(fr) <= 4 and all(0 < l2._num(f, 'tg_node_fraction', 0, 1.5) for f in fr)
            and len(set(fr)) == len(fr), 'LIVE03_TG_NODE_FRACTIONS')
    _num(npred, 'base_parity_tolerance', 0.0, 1e-3, positive=True)
    td = cfg['td_cordon']
    require(isinstance(td.get('enabled'), bool) and td.get('grouping') == 'FAMILY'
            and td.get('objective') == 'CORDON_PRIMARY_METHOD_ONLY', 'LIVE03_TD_POLICY')
    from .common import parent_module
    registry = parent_module('r1_15a2_multiblock').COMPONENT_REGISTRY
    groups = td.get('groups')
    require(isinstance(groups, dict) and groups, 'LIVE03_TD_GROUPS')
    seen = []
    for name, comps in groups.items():
        require(isinstance(comps, list) and comps and all(c in registry for c in comps), 'LIVE03_TD_GROUP_COMPONENT:' + name)
        require(all(registry[c]['family'] != 'LONG' for c in comps), 'LIVE03_TD_LONG_NOT_IN_CORDON_TD_SCOPE')
        seen += comps
    require(len(seen) == len(set(seen)), 'LIVE03_TD_COMPONENT_IN_TWO_GROUPS')
    for key, lo, hi in (('probe_b', 1e-4, 1.0), ('probe_logc', 1e-4, 1.0), ('trust_b', 1e-3, 4.0),
                        ('trust_logc', 1e-3, 2.0), ('damping', 0.0, 10.0), ('trust_growth', 1.0, 3.0),
                        ('trust_shrink', 0.05, 0.95), ('trust_radius_max', 0.1, 10.0), ('trust_radius_min', 1e-4, 1.0),
                        ('min_predicted_relative_improvement', 0.0, 0.5), ('base_parity_tolerance', 1e-12, 1e-3),
                        ('min_relative_column_norm', 0.0, 0.1)):
        _num(td, key, lo, hi)
    l2._int(td.get('max_inner_evaluations'), 'max_inner_evaluations', 1, 20)
    scope = cfg['donor_runtime']['matrix_scope_by_block'].get('TD_CORDON')
    require(scope and set(scope) == {'dseg_codes', 'matrix_nos'}, 'LIVE03_TD_MATRIX_SCOPE')
    require(cfg['donor_runtime']['min_changed_matrices_by_block'].get('TD_CORDON') == 1, 'LIVE03_TD_MIN_CHANGED')
    idp = cfg['idp_guard']
    require(isinstance(idp.get('enabled'), bool) and idp.get('role') == 'DEGRADATION_GUARD_ONLY'
            and idp.get('reference') == 'FINECDF_V1_9', 'LIVE03_IDP_POLICY')
    require(idp.get('components') is None or (isinstance(idp['components'], list) and idp['components']), 'LIVE03_IDP_COMPONENTS')
    require(isinstance(idp.get('blocks'), list) and set(idp['blocks']) <= set(BLOCKS), 'LIVE03_IDP_BLOCKS')
    for key in ('max_fine_cdf_rmse_degradation', 'mean_error_floor', 'max_mean_error_degradation'):
        _num(idp, key, 0.0, 1.0)
    return cfg


def load_config(path=None, overrides=None):
    cfg = read_json(path or ROOT / CONFIG_FILE)
    if overrides:
        cfg = l2.merge(cfg, overrides)
    validate_config(cfg, allow_donor_overrides=bool(overrides and overrides.get('_allow_donor_overrides')))
    return cfg


def adapter_config(cfg, outer_cycle, actuatable_zones=None):
    view = live02_view(cfg)
    out = l2.adapter_config(view, outer_cycle, actuatable_zones)
    out['matrix_scope_by_block'] = deepcopy(cfg['donor_runtime']['matrix_scope_by_block'])
    out['min_changed_matrices_by_block'] = deepcopy(cfg['donor_runtime']['min_changed_matrices_by_block'])
    out['live02']['acceptance'] = deepcopy(cfg['acceptance'])
    out['live03'] = {'blocks_per_cycle': list(cfg['blocks_per_cycle']), 'native_prediction': deepcopy(cfg['native_prediction']),
                     'td_cordon': deepcopy(cfg['td_cordon']), 'idp_guard': deepcopy(cfg['idp_guard'])}
    return out


live01_view = l2.live01_view
