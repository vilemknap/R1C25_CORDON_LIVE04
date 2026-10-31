"""Separate read-only live contract; never weakens the historic offline guards."""
from copy import deepcopy
from .common import ROOT, require, read_json, sha256, canonical_hash
from .aggressive_policy import source_policy, design_defaults

SCHEMA='R1_CORDON_LIVE01_CONFIG_V1'
STAGE='LIVE01_BASELINE_READ_ONLY'
MUTABLE=('NATIVE_CW','NATIVE_CW_NOT','NATIVE_CS','NATIVE_CS_NOT')


def load_config(path=None):
    cfg=read_json(path or ROOT/'CORDON_LIVE01_CONFIG.json')
    validate_config(cfg)
    return cfg


def validate_config(cfg):
    require(cfg.get('schema')==SCHEMA and cfg.get('live_stage')==STAGE,'LIVE01_CONFIG_SCHEMA')
    require(cfg.get('execution_mode')=='TECHNICAL_TRIAL','LIVE01_PRODUCTION_NOT_AUTHORIZED')
    for k in ('writes_enabled','assignment_enabled','apply_permitted','native_candidate_accepted'):
        require(cfg.get(k) is False,'LIVE01_FORBIDDEN_FLAG:'+k)
    require(cfg.get('model_year')==2025 and cfg.get('survey_year')==2026 and cfg.get('expected_zone_count')==681,'LIVE01_MODEL_CONTRACT')
    require(cfg.get('observation_policy')=='WHOLE_FINAL_SYMMETRIC_RPDI_MATRIX','LIVE01_OBSERVATION_POLICY')
    require(cfg.get('capture_backend')=='LEGACY' and cfg.get('snapshot_policy')=='FRESH_CAPTURE_THIS_INVOCATION','LIVE01_UNPROVEN_SOURCE_REUSE')
    require(cfg.get('calibration_rows')==120 and cfg.get('validation_rows')==0,'LIVE01_NO_HOLDOUT')
    require(cfg.get('c17_allocation_policy')=='UNAPPROVED','LIVE01_C17_POLICY_CHANGE_REQUIRES_NEW_CONTRACT')
    require(cfg.get('primary_aggregation')=='BIDIRECTIONAL_SUM','LIVE01_AGGREGATION_CHANGED')
    require(cfg.get('repeat_policy')=='EXCLUDE_FLAGGED','LIVE01_REPEAT_POLICY_CHANGED')
    require(type(cfg.get('outer_cycle')) is int and cfg['outer_cycle']>=1,'LIVE01_CYCLE_INVALID')
    exclusions=cfg.get('explicit_excluded_zone_nos')
    require(isinstance(exclusions,list) and all(type(z) is int and z>0 for z in exclusions) and len(set(exclusions))==len(exclusions),'LIVE01_INVALID_ZONE_EXCLUSIONS')
    require(cfg.get('mutable_dsegs')==list(MUTABLE),'LIVE01_FROZEN_SCOPE_CHANGED')
    require(cfg.get('authority_family')=='CORDON_SDP' and cfg.get('category')=='OA' and cfg.get('basis')=='RPDI','LIVE01_AUTHORITY_FAMILY')
    for name,rel in [('physical_targets','data/audited/PHYSICAL_TARGETS.csv'),('station_mapping','data/audited/STATION_MAPPING.csv'),('c17','data/audited/C17_STATION_BUDGETS.csv')]:
        require(sha256(ROOT/rel)==cfg['authority_pins'][name],'LIVE01_AUTHORITY_HASH_CHANGED:'+name)
    require(not set(cfg)-set(read_json(ROOT/'CORDON_LIVE01_CONFIG.json')),'LIVE01_UNKNOWN_CONFIG_FIELD')
    return cfg


def calculation_config(live,actuatable_zones=None):
    """Narrow math view, not a fake offline config sent to aggressive.propose()."""
    validate_config(live)
    base=read_json(ROOT/'CORDON_2025_CONFIG.json')
    out={k:deepcopy(v) for k,v in base.items() if k not in ('validation_unordered_pairs','aggressive_policy','role_split_status')}
    out.update(mode=STAGE,apply=False,pair_role_policy='WHOLE_MATRIX_NO_HOLDOUT',
               validation_unordered_pairs=[],role_split_status='ALL_120_CALIBRATION',
               actuatable_zones=actuatable_zones,mutable_dsegs=list(MUTABLE),
               c17_allocation_policy=live['c17_allocation_policy'])
    out.update(design_defaults())
    stage=next((s for s in source_policy()['generation_stages'] if live['outer_cycle']<=s['through_outer_cycle']),source_policy()['generation_stages'][-1])
    out.update(relative_od_lower=-stage['max_od_relative_down'],relative_od_upper=stage['max_od_relative_up'],guidance_mode='SIGNED')
    for k in ('max_od_relative_down','max_od_relative_up','max_add_log_down','max_add_log_up'):out[k]=stage[k]
    out['salary']['max_abs_delta_per_block']=stage['salary_max_abs_delta_per_block']
    for k in ('up','down'):out['generation_signed_refinement']['max_family_global_log_'+k]=stage['signed_max_family_global_log_'+k]
    out['generation_signed_refinement']['soft_outward_step_factor']=stage['signed_soft_outward_step_factor']
    out['generation_coefficient_authority']['current_value_source']='LIVE01_CURRENT_2025_READBACK'
    out['generation_signed_refinement']['reference_source']='LIVE01_CURRENT_RUN_START'
    out['live01_search_stage']=stage
    return out


def donor_config(live):
    cfg=calculation_config(live)
    path=ROOT/'provenance/live01/TG_DEPENDENCY_CONTRACT_FROM_DONOR.json'
    cfg['tg_dependency_contract']=read_json(path)
    cfg['explicit_excluded_zone_nos']=list(live['explicit_excluded_zone_nos'])
    return cfg
