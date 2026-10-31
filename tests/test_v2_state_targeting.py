import copy,json,sqlite3
import numpy as np
import pytest
from cordon2025.common import ROOT,ContractError,read_config,sha256,parent_module
from cordon2025.state import (SEMANTIC_FIELDS, snapshot_semantics, observation_roster,
                             diagnostic_reference_hash, readback_manager)
from cordon2025.targeting import path_targeting_report,seal_distance_context,td_component_context
from cordon2025.incidence import build_from_snapshot,aggregate_observations
from test_incidence import fixture
from test_optimizer import example


def hashes():return {key:('%064x'%(i+1)) for i,key in enumerate(SEMANTIC_FIELDS)}


def evidence():return {'semantic_hashes':hashes(),'origin':'VISUM_SAVED_PATHS',
                       'network_sha256':'a'*64,'demand_sha256':'b'*64}


@pytest.mark.parametrize('key',SEMANTIC_FIELDS)
def test_semreload_every_domain_matters_not_just_filename(key):
    e=evidence();cfg={'expected_snapshot_semantics':hashes()};e['semantic_hashes'][key]='f'*64
    with pytest.raises(ContractError,match='CACHE_SEMANTIC_STATE_MISMATCH:'+key):snapshot_semantics(e,cfg)


def test_semreload_has_no_automatic_loadversion():
    e=evidence();r=snapshot_semantics(e,{'expected_snapshot_semantics':hashes()}, {'parent_hash':hashes()['state_hash']})
    assert r['expected_compared'] and not r['live_verified'] and not r['automatic_reload_performed']


def test_cache_parent_hash_mismatch_rejected():
    with pytest.raises(ContractError,match='CACHE_PARENT'):snapshot_semantics(evidence(),{}, {'parent_hash':'0'*64})


def test_missing_semantics_is_declared_not_live_pass():
    r=snapshot_semantics({'origin':'VISUM_SAVED_PATHS'}, {})
    assert r['status']=='SEMANTIC_SNAPSHOT_NOT_SUPPLIED' and not r['complete']
    with pytest.raises(ContractError):snapshot_semantics({}, {'expected_snapshot_semantics':hashes()})


@pytest.mark.parametrize('key', ['network_sha256','demand_sha256'])
def test_actual_source_identity_must_match(key):
    cfg={('actual_network_sha256' if key=='network_sha256' else 'actual_demand_sha256'):'c'*64}
    with pytest.raises(ContractError,match='SOURCE_IDENTITY_MISMATCH'):snapshot_semantics(evidence(),cfg)


def test_invalid_hash_not_accepted_as_length_only():
    e=evidence();e['semantic_hashes']['matrix_hash']='g'*64
    with pytest.raises(ContractError,match='SEMANTIC_HASH'):snapshot_semantics(e,{})


@pytest.mark.parametrize('key,value',[
    ('persistent_path_cache_enabled',True),('automatic_cache_discovery',True),
    ('automatic_live_reload',True),('flowbundle_count_authority',True),
    ('wallclock_limit_seconds',36000),('authority_family','CSD2022')])
def test_production_donor_runtime_options_rejected(tmp_path,key,value):
    c=json.loads((ROOT/'CORDON_2025_CONFIG.json').read_text());c[key]=value
    p=tmp_path/'cfg.json';p.write_text(json.dumps(c))
    with pytest.raises(ContractError):read_config(p)


def test_semantic_state_bound_in_snapshot_reader(tmp_path):
    p,m,e,c=fixture(tmp_path)
    db=sqlite3.connect(p);db.execute("UPDATE metadata SET value=? WHERE key='parent_hash'",(hashes()['state_hash'],));db.commit();db.close()
    e['cache_sha256']=sha256(p);e['semantic_hashes']=hashes();c['expected_snapshot_semantics']=hashes()
    inc=build_from_snapshot(p,m,c,e)['ALL_ORDERED_UNIQUE_PAIRS']
    assert inc.audit['semantic_snapshot']['expected_compared']
    c['expected_snapshot_semantics']['operations_hash']='f'*64
    with pytest.raises(ContractError,match='operations_hash'):build_from_snapshot(p,m,c,e)


def test_dynamic_roster_not_488_and_reverse_roles():
    inc=example();r=observation_roster(inc.rows)
    assert r['rows']==2 and r['calibration']==2 and not r['uses_2022_profile_count']
    assert observation_roster(inc.rows,r)==r
    r['rows']=488
    with pytest.raises(ContractError,match='ROSTER_GATE_MISMATCH'):observation_roster(inc.rows,r)


def test_roster_same_count_different_station_is_mismatch():
    inc=example();expected=observation_roster(inc.rows);inc.rows[0]['destination_station']=16
    with pytest.raises(ContractError,match='identity_sha256'):observation_roster(inc.rows,expected)


def test_duplicate_roster_row_rejected():
    rows=example().rows
    with pytest.raises(ContractError,match='DUPLICATE'):observation_roster(rows+rows[:1])


def test_nonfinite_diagnostic_hash_kept_out_of_numeric_objective():
    a={'rmse':float('inf'),'empty_stat':float('nan')};b=copy.deepcopy(a)
    value=diagnostic_reference_hash(a)
    assert len(value)==64 and np.isnan(a['empty_stat'])
    assert value==diagnostic_reference_hash(b)
    assert value!=diagnostic_reference_hash({'rmse':float('-inf'),'empty_stat':float('nan')})


def test_bundle_factory_starts_unready_no_fake_assignment():
    manager=readback_manager({'performance':{'v24915_perf2_candidate_readback_bundle':{'enabled':True}}},run_token='C25',session_token='OFFLINE_TEST')
    assert not manager.can_capture() and not manager.assignment_completed


def test_targeting_uses_cal_only_with_signed_pressure():
    inc=example(matrix=np.array([[100.,0.],[0.,100.]]),targets=[120.,80.])
    r=path_targeting_report(inc)
    assert sum(x['upward_pressure'] for x in r['zone_rankings'])>0
    assert sum(x['downward_pressure'] for x in r['zone_rankings'])>0
    assert not r['changes_candidate_order'] and not r['changes_objective']
    inc.rows[1]['role']='VALIDATION';a=path_targeting_report(inc)
    inc.rows[1]['observed']=1e12;b=path_targeting_report(inc)
    assert a==b


def test_skim_identity_seal_and_no_oracle_activation():
    seal=seal_distance_context(values=np.array([[0.,1.],[1.,0.]]),zone_nos=[10,20],matrix_no=7,matrix_code='DIST_KM')
    assert seal.unit=='km' and seal.role=='READ_ONLY_TARGETING_CONTEXT_NOT_ACCEPTANCE_AUTHORITY'
    with pytest.raises(ValueError):seal_distance_context(values=np.eye(2),zone_nos=[1,2],matrix_no=7,matrix_code='DIST_KM',unit='minutes')
    with pytest.raises(ValueError):seal_distance_context(values=np.eye(2),zone_nos=[1,1],matrix_no=7,matrix_code='DIST_KM')


def test_td_context_does_not_unlock_frozen_components():
    r=td_component_context({'WORK':2.,'LONG':200.},{'w':1.,'long':100.},{'w':'WORK','long':'LONG'})
    assert [x[0] for x in r.pressure_by_component]==['w']


def test_expected_demand_cannot_be_bypassed_with_absent_semantics():
    import pytest
    from cordon2025.state import snapshot_semantics
    with pytest.raises(ValueError,match='CACHE_SOURCE_IDENTITY_MISMATCH:demand'):
        snapshot_semantics({'origin':'VISUM_SAVED_PATHS'}, {'actual_demand_sha256':'a'*64})


def test_snapshot_output_cannot_replace_cache(tmp_path):
    import pytest
    from cordon2025.incidence import build_from_snapshot
    p=tmp_path/'original.sqlite';p.write_bytes(b'unchanged')
    with pytest.raises(ValueError,match='OUTPUT_INPUT_COLLISION'):
        build_from_snapshot(p,{}, {}, {}, hits_output=p)
    assert p.read_bytes()==b'unchanged'
