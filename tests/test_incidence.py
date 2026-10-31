from pathlib import Path
from types import SimpleNamespace
import importlib.util
import sqlite3
import numpy as np
import pytest
from cordon2025.common import ROOT,sha256,ContractError,parent_core
from cordon2025.fixtures import create_cache,config
from cordon2025.incidence import build_from_snapshot,aggregate_observations,check_epoch_support,validate_roles,station_pairs

A=(101,1,2);B=(102,2,3);C=(103,3,4)
RA=(101,2,1);RB=(102,3,2);RC=(103,4,3)

def fixture(tmp_path):
    paths=[('C',10,20,1,[A,B,C],{'NATIVE_CW':60,'EXOG_EE_CF':30}),
           ('C',10,20,2,[A,B],{'NATIVE_CW':40,'EXOG_EE_CF':10}),
           ('C_NOT',10,20,1,[B,C],{'NATIVE_CW_NOT':50}),
           ('C',20,10,1,[RC,RB,RA],{'NATIVE_CW':50,'EXOG_EE_CF':5}),
           ('C',30,40,1,[],{'NATIVE_CW':8,'EXOG_EE_CF':1}),
           ('C',50,60,1,[A,B,RB,RA,A],{'NATIVE_CW':7,'EXOG_EE_CF':2})]
    p=tmp_path/'snapshot.sqlite';m,e=create_cache(p,paths)
    return p,m,e,config(['NATIVE_CW','NATIVE_CW_NOT','EXOG_EE_CF'])

def test_decode_once_mode_scope_and_fixed(tmp_path):
    p,m,e,c=fixture(tmp_path);before=sha256(p);r=build_from_snapshot(p,m,c,e,hits_output=tmp_path/'hits.csv')
    allp=r['ALL_ORDERED_UNIQUE_PAIRS'];two=r['EXACT_TWO_HITS']
    ix={(x['origin_station'],x['destination_station']):i for i,x in enumerate(allp.rows)}
    assert allp.model[ix[1,3]]==90 and two.model[ix[1,3]]==0
    assert allp.model[ix[1,2]]==140 and two.model[ix[1,2]]==50
    assert allp.model[ix[2,3]]==140 and two.model[ix[2,3]]==50
    assert allp.fixed[ix[1,2]]==40
    assert all(v['dseg_code']!='EXOG_EE_CF' for v in allp.variables)
    assert allp.audit['metrics']['decoded_geometry']==6
    assert allp.audit['metrics']['segment_path_rows']==11
    assert allp.audit['metrics']['repeated_geometry']==1
    assert allp.audit['metrics']['zero_link_geometry']==1
    assert allp.audit['metrics']['excluded_segment_volume']==9
    assert allp.audit['per_od_external_parity']=='PASS'
    assert allp.audit['zero_link_interzonal_volume_by_dseg']['NATIVE_CW']==8
    assert np.allclose(allp.share_operator.forward(allp.q_current),allp.mutable)
    assert sha256(p)==before

def test_oracle_and_legacy_core_numerical_parity(tmp_path):
    p,m,e,c=fixture(tmp_path);r=build_from_snapshot(p,m,c,e)
    oraclepath=ROOT/'docs/readonly_reference/R1_2025_CORDON_READONLY_V1/r1_cordon_2025.py'
    spec=importlib.util.spec_from_file_location('oracle_2025',oraclepath);oracle=importlib.util.module_from_spec(spec);spec.loader.exec_module(oracle)
    ref=oracle.route_diagnostic(p,m,selected_dsegs=c['selected_dsegs'])
    for method,inc in r.items():
        for i,row in enumerate(inc.rows):
            key='%d>%d'%(row['origin_station'],row['destination_station'])
            assert inc.model[i]==ref['counts'][method].get(key,0)
    # Independent existing core oracle with actual path records (not our own formula).
    import struct
    db=sqlite3.connect(p);ed={r[0]:tuple(r[1:]) for r in db.execute('SELECT * FROM edges')};paths=[];links=[]
    for mode,o,d,pi,blob,code,v in db.execute('SELECT g.mode,g.orig,g.dest,g.path_index,g.edge_ids,v.dseg,v.volume FROM geometry g JOIN volumes v USING(gid)'):
        paths.append(dict(dseg_code=code,OrigZoneNo=o,DestZoneNo=d,Index=pi,**{'Vol(AP)':v}))
        for seq,eid in enumerate(struct.unpack('<%dI'%(len(blob)//4),blob),1):
            ln,fr,to=ed[eid];links.append(dict(dseg_code=code,OrigZoneNo=o,DestZoneNo=d,PathIndex=pi,Index=seq,LinkNo=ln,FromNodeNo=fr,ToNodeNo=to))
    db.close()
    pair_auth=[dict(origin_label=str(row['origin_station']),destination_label=str(row['destination_station']),observed=1) for row in r['ALL_ORDERED_UNIQUE_PAIRS'].rows]
    old=parent_core().build_actual_path_incidence(paths,links,[],mutable_dsegs=c['mutable_dsegs'],mutable_relation_policy='ALL_MUTABLE_RELATIONS',station_link_to_labels={k:[str(v)] for k,v in m.items()},pair_authority=pair_auth)
    assert np.array_equal(old['pair_observations']['full_model'],r['ALL_ORDERED_UNIQUE_PAIRS'].model)

def test_hook_uses_existing_parent(tmp_path):
    p,m,e,c=fixture(tmp_path);parent_core()
    from r1_15a2_two_mode_v238 import TwoModeRouteCollector
    obj=SimpleNamespace(incidence_ready=True,route_db_path=str(p))
    result=TwoModeRouteCollector.cordon_incidence_offline(obj,m,c,e)
    assert len(result)==2

def test_mode_identity_not_inferred(tmp_path):
    p,m,e,c=fixture(tmp_path);e['geometry_full_identity_proven']=False
    r=build_from_snapshot(p,m,c,e)
    assert 'GEOMETRY_IDENTITY_UNAPPROVED' in r['ALL_ORDERED_UNIQUE_PAIRS'].audit['blocked']

def test_same_linkno_opposite_direction(tmp_path):
    p,m,e,c=fixture(tmp_path);r=build_from_snapshot(p,m,c,e)['ALL_ORDERED_UNIQUE_PAIRS']
    q={(x['origin_station'],x['destination_station']):r.model[i] for i,x in enumerate(r.rows)}
    assert q[1,2]==140 and q[2,1]==55

def test_missing_segment(tmp_path):
    p,m,e,c=fixture(tmp_path);c['selected_dsegs'].append('NATIVE_CS')
    with pytest.raises(ContractError,match='REQUIRED_DSEG'):build_from_snapshot(p,m,c,e)

def test_omitting_fixed_is_rejected(tmp_path):
    p,m,e,c=fixture(tmp_path);c['selected_dsegs'].remove('EXOG_EE_CF')
    with pytest.raises(ContractError,match='OMITTED'):build_from_snapshot(p,m,c,e)

def test_bad_parity(tmp_path):
    p,m,e,c=fixture(tmp_path);e['dseg_totals']['NATIVE_CW']+=1
    with pytest.raises(ContractError,match='PARITY_FAIL'):build_from_snapshot(p,m,c,e)

def test_wal_and_source_hash(tmp_path):
    p,m,e,c=fixture(tmp_path);side=Path(str(p)+'-wal');side.touch()
    with pytest.raises(ContractError,match='SIDECAR'):build_from_snapshot(p,m,c,e)
    side.unlink();e['cache_sha256']='0'*64
    with pytest.raises(ContractError,match='SHA256'):build_from_snapshot(p,m,c,e)

def test_corrupt_geometry(tmp_path):
    p,m,e,c=fixture(tmp_path);db=sqlite3.connect(p);db.execute('UPDATE geometry SET edge_ids=NULL WHERE gid=1');db.commit();db.close();e['cache_sha256']=sha256(p)
    with pytest.raises(ContractError,match='NULL_GEOMETRY'):build_from_snapshot(p,m,c,e)

def test_frozen_actuator_rejected(tmp_path):
    p,m,e,c=fixture(tmp_path);c['mutable_dsegs'].append('EXOG_EE_CF')
    with pytest.raises(ContractError,match='FROZEN_DSEG'):build_from_snapshot(p,m,c,e)

def test_role_split_and_aggregation(tmp_path):
    p,m,e,c=fixture(tmp_path);r=build_from_snapshot(p,m,c,e)['ALL_ORDERED_UNIQUE_PAIRS']
    a=aggregate_observations(r,{(1,2):100,(2,1):80},roles={(1,2):'CALIBRATION'})
    assert a.rows[0]['observed']==180 and a.model[0]==195
    assert a.rows[0]['role']=='CALIBRATION'
    with pytest.raises(ContractError,match='LEAKAGE'):
        aggregate_observations(r,{(1,2):100,(2,1):80},bidirectional=False,roles={(1,2):'CALIBRATION',(2,1):'VALIDATION'})

def test_epoch_support_and_zero(tmp_path):
    p,m,e,c=fixture(tmp_path);r=build_from_snapshot(p,m,c,e)['ALL_ORDERED_UNIQUE_PAIRS']
    with pytest.raises(ContractError,match='NEW_POSITIVE'):
        check_epoch_support(r,[{'dseg':'NATIVE_CW','orig':555,'dest':777,'volume':1}])
    assert check_epoch_support(r,[{'dseg':'NATIVE_CW','orig':10,'dest':20,'volume':101}])['new_assignment_verified'] is False

def test_repeat_policies_and_three_stations():
    p,repeat=station_pairs([1,2,3]);assert len(p['ALL_ORDERED_UNIQUE_PAIRS'])==3 and not p['EXACT_TWO_HITS']
    p,repeat=station_pairs([1,2,1]);assert repeat and not p['ALL_ORDERED_UNIQUE_PAIRS']
    p,repeat=station_pairs([1,2,1],'FIRST_OCCURRENCE_DIAGNOSTIC');assert p['ALL_ORDERED_UNIQUE_PAIRS']==((1,2),)

def test_no_cache(tmp_path):
    with pytest.raises(ContractError,match='NO_2025_PATH_CACHE'):
        build_from_snapshot(tmp_path/'absent.sqlite',{},config(['NATIVE_CW']),{})
