import copy
import json
import numpy as np
import pytest
from cordon2025.common import ROOT, read_config, ContractError, canonical_hash
from cordon2025.aggressive_policy import effective_config, source_policy, science_hash, META, SOURCE_SHA256, td_soft_fit_check


def raw_config():
    return json.loads((ROOT/'CORDON_2025_AGGRESSIVE_CONFIG.json').read_text())


@pytest.mark.parametrize('cycle,name,od,add,glob,salary', [
    (1,'SIGNED_EXPLORE',.2,.12,.1,.1),(6,'SIGNED_EXPLORE',.2,.12,.1,.1),
    (7,'SIGNED_REFINE',.14,.08,.06,.08),(18,'SIGNED_REFINE',.14,.08,.06,.08),
    (19,'DISTRIBUTION_FOCUS',.08,.05,.03,.05),(100,'DISTRIBUTION_FOCUS',.08,.05,.03,.05)])
def test_stage_is_effective_not_metadata(cycle,name,od,add,glob,salary):
    base=raw_config();original=copy.deepcopy(base);c=effective_config(base,cycle)
    assert base==original
    assert c[META]['stage']['name']==name
    assert c['relative_od_lower']==-od and c['relative_od_upper']==od
    assert c['max_add_log_up']==c['max_add_log_down']==add
    assert c['generation_signed_refinement']['max_family_global_log_up']==glob
    assert c['salary']['max_abs_delta_per_block']==salary
    assert c[META]['effective_science_sha256']==science_hash(c)
    assert effective_config(c)==c


@pytest.mark.parametrize('cycle',[0,-1,101,True,1.5,'1',None])
def test_invalid_cycle_rejected(cycle):
    c=raw_config();c['limit_profile']='LEGACY_STRICT';c['aggressive_policy']['outer_cycle']=cycle
    with pytest.raises(ContractError,match='OUTER_CYCLE'):effective_config(c)


def test_exact_source_policy_and_default_config_remains_standard():
    source=source_policy();base=read_config();ag=read_config(ROOT/'CORDON_2025_AGGRESSIVE_CONFIG.json')
    assert base['relative_od_upper']==.15
    assert ag['generation_backtracking_scales']==source['generation_backtracking_scales']
    assert ag['td_realization_backtracking_scales']==source['td_realization_backtracking_scales']
    assert ag['td']['min_selected_component_relative_improvement']==.00005
    assert ag['generation_min_cal_relative_improvement']==.000001
    for key in ('mutable_dsegs','selected_dsegs','validation_unordered_pairs','ridge','l1','epsilon_abs',
                'c17_ridge','c17_allocation_policy','repeat_policy','approvals','observation_methods',
                'solver_tolerance','kkt_tolerance'):
        assert ag[key]==base[key]
    assert len(ag['validation_unordered_pairs'])==12


@pytest.mark.parametrize('flag',['apply','run_assignment','run_procseq','write_od','supply_enabled',
                                'automatic_live_reload','automatic_cache_discovery','persistent_path_cache_enabled'])
def test_no_live_switch(flag):
    c=raw_config();c[flag]=True
    with pytest.raises(ContractError):effective_config(c)


@pytest.mark.parametrize('seg',['NATIVE_CL','NATIVE_CF','EXOG_EE_CW','NATIVE_SCHOOL'])
def test_no_scope_expansion(seg):
    c=raw_config();c['mutable_dsegs'].append(seg)
    with pytest.raises(ContractError,match='FROZEN_SCOPE'):effective_config(c)


@pytest.mark.parametrize('key,value',[('relative_od_upper',.9),('epsilon_abs',1000),('c17_ridge',0),('ridge',0)])
def test_effective_config_tamper_fails(key,value):
    c=effective_config(raw_config());c[key]=value
    with pytest.raises(ContractError,match='EFFECTIVE_CONFIG_CHANGED'):effective_config(c)


def test_tuning_source_hash_pinned(monkeypatch):
    import cordon2025.aggressive_policy as p
    monkeypatch.setattr(p,'SOURCE_SHA256','f'*64)
    with pytest.raises(ContractError,match='HASH_MISMATCH'):p.source_policy()


def test_cycle_rebase_is_explicit_not_same_checkpoint():
    c=effective_config(raw_config(),1)
    with pytest.raises(ContractError,match='STAGE_REBASE'):effective_config(c,7)
    assert c[META]['effective_science_sha256']!=effective_config(raw_config(),7)[META]['effective_science_sha256']


def test_td_component_gates_no_ipf_relaxation():
    c=effective_config(raw_config())
    result=td_soft_fit_check({'a':100.,'b':100.,'c':20.},{'a':85.,'b':109.,'c':21.},['a','b'],c)
    assert result['passes_soft_fit_only'] and not result['native_ipf_verified']
    bad=td_soft_fit_check({'a':100.,'b':100.},{'a':50.,'b':111.},['a','b'],c)
    assert not bad['passes_soft_fit_only']
    zero=td_soft_fit_check({'a':10.,'b':0.},{'a':5.,'b':.0001},['a'],c)
    assert not zero['passes_soft_fit_only']


@pytest.mark.parametrize('value',[float('inf'),float('nan'),-1,True])
def test_bad_td_loss_rejected(value):
    with pytest.raises(ContractError,match='INVALID_COMPONENT'):
        td_soft_fit_check({'a':100.},{'a':value},['a'],effective_config(raw_config()))


def test_profile_counts_and_resume_not_imported():
    c=raw_config();c['expected_12d_rows']=488
    with pytest.raises(ContractError,match='PROFILE_SETTING'):effective_config(c)
    c=raw_config();c['aggressive_policy']['lineage']='RESUME_2022_A0004'
    with pytest.raises(ContractError,match='NEW_LINEAGE'):effective_config(c)


@pytest.mark.parametrize('key,value', [('outer_cycle',7),('apply_permitted',True),
                                      ('source_policy_sha256','0'*64),('stage',{'name':'FORGED'})])
def test_resolved_metadata_cannot_change_stage_or_approval(key,value):
    c=effective_config(raw_config());c[META][key]=value
    with pytest.raises(ContractError,match='METADATA_CHANGED'):
        effective_config(c)
