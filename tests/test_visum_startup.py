import copy
import json
import sqlite3
import sys
from pathlib import Path
import pytest
from cordon2025.common import ROOT,read_config,parent_module
from cordon2025.visum_startup import preflight,capture,run,settings,ReadControl,retry_policy
from fake_visum_startup import FakeVisum,BusyError,UnprintableBusy,UnprintableOther

@pytest.fixture
def setup(tmp_path):
    v=FakeVisum(tmp_path/'model');out=tmp_path/'out';out.mkdir()
    cfg=read_config(ROOT/'CORDON_2025_AGGRESSIVE_CONFIG.json')
    opt=settings({'page_size':2,'min_free_disk_gib':0,'com_retry_attempts':64,'com_retry_initial_delay_seconds':0.,'com_retry_max_delay_seconds':0.})
    return v,cfg,out,ReadControl(out),opt

def ready(t):return preflight(*t)

def test_full_preflight_reads_all_12_dsegs_without_writes(setup):
    v,c,o,ctl,opt=setup;p=ready(setup)
    assert p[0]['status']=='VISUM_READONLY_PREFLIGHT_PASS'
    assert len(p[0]['matrix_audit'])==12 and len(p[0]['path_list_probes'])==24
    assert v.writes==[] and not v.unbounded

@pytest.mark.parametrize('options,message',[
 ({'apply':True},'UNKNOWN_VISUM_STARTUP_OPTION'),({'page_size':0},'INVALID_STARTUP_SETTING'),
 ({'page_size':True},'INVALID_STARTUP_SETTING'),({'full_geometry_check':1},'INVALID_GEOMETRY'),
 ({'max_store_gib':-1},'INVALID_STARTUP_SETTING'),({'od_parity_rtol':float('nan')},'INVALID_STARTUP_SETTING')])
def test_bad_options(options,message):
    with pytest.raises(Exception,match=message):settings(options)

@pytest.mark.parametrize('damage,message',[
 ('bad_signature','UNVERIFIED'),('bad_width','SCHEMA_MISMATCH'),('parent_empty','NO_SAVED_PRT_PATHS')])
def test_preflight_bad_lists_fail_without_unbounded_fallback(setup,damage,message):
    setattr(setup[0],damage,True)
    with pytest.raises(Exception,match=message):ready(setup)
    assert not setup[0].writes and not setup[0].unbounded

def test_mapping_changed_fails_early(setup):
    rows=setup[0].Net.Links.rows
    rows[:]=[r for r in rows if r['NO']!=2004231]
    with pytest.raises(Exception,match='MAPPING_DOES_NOT_MATCH'):ready(setup)

def test_missing_segment_fails_early(setup):
    setup[0].Net.DemandSegments.rows.pop()
    with pytest.raises(Exception,match='SEGMENTS_MISSING'):ready(setup)

def test_mode_mismatch_fails_early(setup):
    setup[0].dsegs['NATIVE_CW'].mode='C_noT'
    with pytest.raises(Exception,match='MODE_MISMATCH'):ready(setup)

def test_2022_version_refused(setup):
    v=setup[0];p=v.source.with_name('R1_2022.ver');p.write_bytes(b'x');v.IO.CurrentVersionFile=str(p)
    with pytest.raises(Exception,match='MODEL_2022_SOURCE_REFUSED'):ready(setup)

def test_unsaved_version_refused(setup):
    setup[0].IO.CurrentVersionFile=''
    with pytest.raises(Exception):ready(setup)

@pytest.mark.parametrize('label',['GetValues','AddColumn','SetObjects','Invoke','Links.NO'])
def test_busy_retry_at_com_boundaries(setup,label):
    setup[0].failures[label]=(2,BusyError)
    ready(setup)
    assert setup[0].counters[label]>=3 and not setup[0].writes

@pytest.mark.parametrize('error',[UnprintableBusy,UnprintableOther])
def test_unprintable_com_failure_preserved(setup,error):
    v=setup[0];v.failures['Invoke']=(99,error)
    with pytest.raises(error):ready(setup)
    assert v.counters['Invoke']==(setup[4]['com_retry_attempts'] if error is UnprintableBusy else 1)

def test_full_capture_hierarchy_across_page_boundaries_and_geometry_proof(setup):
    v,c,out,ctl,opt=setup;p=ready(setup)
    cache,evidence=capture(v,c,out,ctl,opt,p);ev=json.loads(evidence.read_text())
    assert ev['completed'] and ev['geometry_full_identity_proven']
    assert len(ev['full_geometry_checks'])==12
    with sqlite3.connect(cache) as db:
        assert db.execute('SELECT COUNT(*) FROM volumes').fetchone()[0]==24
        assert db.execute('SELECT COUNT(*) FROM geometry').fetchone()[0]==4
        assert db.execute('SELECT COUNT(*) FROM profile_hits').fetchone()[0]==0
    assert not v.writes and not v.unbounded
    assert len(json.loads((out/'OD_PARITY.json').read_text()))==12

@pytest.mark.parametrize('damage,message',[
 ('matrix_drift','MATRIX_CHANGED_DURING_CAPTURE'),
 ('path_drift','PATH_VOLUMES_CHANGED_DURING_CAPTURE'),
 ('path_distribution_wrong','PER_OD_PATH_MATRIX_PARITY_FAIL'),
 ('same_mode_geometry_mismatch','FULL_SAME_MODE_GEOMETRY_DIFFERS'),
 ('sequence_gap','CONTIGUOUS')])
def test_capture_corruption_does_not_publish_success(setup,damage,message):
    v,c,out,ctl,opt=setup;setattr(v,damage,True);p=ready(setup)
    with pytest.raises(Exception,match=message):capture(v,c,out,ctl,opt,p)
    assert not (out/'SNAPSHOT_EVIDENCE.json').exists()
    assert not v.writes and not v.unbounded

def test_geometry_only_mode_preserves_nonempty_profile_requirement(tmp_path):
    two=parent_module('r1_15a2_two_mode_v238');sup=parent_module('r1_15a2_supply')
    with pytest.raises(Exception,match='EMPTY_OBSERVATION_AUTHORITY'):
        two.TwoModeRouteCollector([],sup.SupplyPolicy(),'x',{},tmp_path/'bad.sqlite')
    c=two.TwoModeRouteCollector([],sup.SupplyPolicy(),'x',{},tmp_path/'good.sqlite',geometry_only=True)
    try:
        for method in (c.prepare_incidence_evidence,c.prepare_sequence_evidence,c.finish):
            with pytest.raises(Exception,match='GEOMETRY_ONLY_HAS_NO_PROFILE_OBJECTIVE'):method()
    finally:c.close()

def test_stop_request_and_com_thread_identity(setup):
    v,c,o,ctl,opt=setup;(o/'STOP_REQUESTED').touch()
    with pytest.raises(Exception,match='USER_STOP_REQUESTED'):ready(setup)
    (o/'STOP_REQUESTED').unlink();ctl.thread=-1
    with pytest.raises(Exception,match='COM_THREAD_CHANGED'):ready(setup)

def test_end_to_end_real_bridge_using_synthetic_com_fixture(tmp_path):
    v=FakeVisum(tmp_path/'model')
    import os,faulthandler
    trace=os.environ.get('R1_TEST_STACK_LOG')
    handle=open(trace,'w') if trace else None
    if handle:faulthandler.dump_traceback_later(5,repeat=True,file=handle)
    try:
        r=run(v,action='CAPTURE_DIAGNOSTICS',output_root=tmp_path/'runs',options={'page_size':2,'min_free_disk_gib':0})
    finally:
        if handle:faulthandler.cancel_dump_traceback_later();handle.close()
    assert r['status']=='VISUM_SAVED_PATH_DIAGNOSTICS_COMPLETE'
    assert not r['apply_permitted'] and not r['calibration_ready']
    assert len(r['variants'])==2
    assert not v.writes and not v.unbounded
    # Test transport is synthetic even when exercising actual production callbacks.
    assert v.origin=='SYNTHETIC_TEST_FIXTURE_NOT_NATIVE_VISUM'

def test_assignment_unrelated_OD_not_masked_by_equal_total(setup):
    v,c,o,ctl,opt=setup;v.path_distribution_wrong=True
    p=ready(setup)
    with pytest.raises(Exception,match='PER_OD_PATH_MATRIX_PARITY_FAIL'):capture(v,c,o,ctl,opt,p)
    rows=json.loads((o/'OD_PARITY.json').read_text())
    assert rows[0]['missing_or_inconsistent_od_count']==2
    assert len(rows[0]['sample_errors'])==2

@pytest.mark.parametrize('bad',[float('nan'),float('inf'),-1.])
def test_invalid_matrix_values(setup,bad):
    setup[0].dsegs['NATIVE_CW'].ODMatrix.values[0,1]=bad
    with pytest.raises(Exception,match='INVALID_DSEG_MATRIX_AUTHORITY'):ready(setup)

def test_same_LinkNo_reverse_direction_must_exist(setup):
    rows=setup[0].Net.Links.rows
    # Remove exactly one direction, while retaining the link number in the other.
    choices=[r for r in rows if r['NO']==2004231];assert len(choices)==2
    rows.remove(choices[0])
    with pytest.raises(Exception,match='STATION_LINK_MAPPING'):ready(setup)

def test_duplicate_COM_indices_rejected(setup):
    coll=setup[0].Net.Links;old=coll.GetMultiAttValues
    coll.GetMultiAttValues=lambda name,*args:old(name,*args)+old(name,*args)[:1]
    with pytest.raises(Exception,match='DUPLICATE_COM_ROW_INDEX'):ready(setup)

def test_wrong_column_row_coverage_rejected(setup):
    coll=setup[0].Net.Links;old=coll.GetMultiAttValues
    coll.GetMultiAttValues=lambda name,*args:old(name,*args)[:-1] if name=='TONODENO' else old(name,*args)
    with pytest.raises(Exception,match='ROW_COVERAGE_MISMATCH'):ready(setup)

def test_zero_new_geometry_budget_fails_closed(setup):
    v,c,o,ctl,opt=setup;p=ready(setup);opt['max_store_gib']=1e-10
    with pytest.raises(Exception,match='INVALID_TWO_MODE_SETTING'):capture(v,c,o,ctl,opt,p)
    assert not (o/'SNAPSHOT_EVIDENCE.json').exists()

def test_insufficient_free_disk_rejected(setup,monkeypatch):
    from types import SimpleNamespace
    v,c,o,ctl,opt=setup;p=ready(setup);opt['min_free_disk_gib']=1.
    monkeypatch.setattr(parent_module('r1_15a2_two_mode_v238').shutil,'disk_usage',lambda *_:SimpleNamespace(free=0))
    with pytest.raises(Exception,match='LOW_FREE_DISK_SPACE'):capture(v,c,o,ctl,opt,p)
    assert not (o/'SNAPSHOT_EVIDENCE.json').exists()

def test_no_forced_shared_geometry_on_unproved_provisional_capture(setup):
    v,c,o,ctl,opt=setup;p=ready(setup);opt['full_geometry_check']=False
    _,evpath=capture(v,c,o,ctl,opt,p);ev=json.loads(evpath.read_text())
    assert ev['geometry_full_identity_proven'] is False and ev['apply_permitted'] is False

def test_partial_capture_error_is_closed_and_never_sealed(setup):
    v,c,o,ctl,opt=setup;p=ready(setup)
    v.failures['Invoke']=(99,BusyError)
    with pytest.raises(BusyError):capture(v,c,o,ctl,opt,p)
    assert not (o/'SNAPSHOT_EVIDENCE.json').exists()
    # The SQLite handle has been closed; failed capture cannot be treated as completed.
    with sqlite3.connect(o/'p.sqlite') as db:
        assert db.execute("SELECT value FROM metadata WHERE key='capture_complete'").fetchone() is None

def test_unknown_live_action_does_not_write_or_run(setup):
    with pytest.raises(Exception,match='APPLY_NOT_IMPLEMENTED'):run(setup[0],action='APPLY')
    assert not setup[0].writes


def test_official_COM_list_property_not_called_as_factory(setup):
    from fake_visum_startup import ListObj
    v=setup[0]
    class PropertyLists:
        @property
        def CreatePrTPathList(self):return ListObj(v,'parent')
        @property
        def CreatePrTPathLinkList(self):return ListObj(v,'geometry')
    v.Workbench.Lists=PropertyLists()
    assert ready(setup)[0]['status']=='VISUM_READONLY_PREFLIGHT_PASS'

def test_matrix_size_budget_prevents_getvalues_allocation(setup):
    from cordon2025.visum_startup import _matrix
    v,c,o,ctl,opt=setup;opt['max_dense_matrix_cells']=100
    ds={'code':'NATIVE_CW','object':v.dsegs['NATIVE_CW']}
    with pytest.raises(Exception,match='DENSE_MATRIX_MEMORY_BUDGET'):_matrix(ds,1000,ctl,opt)
    assert v.counters['GetValues']==0

def test_cleanup_failure_does_not_replace_primary(setup):
    from cordon2025.visum_startup import _cleanup_store
    class Broken:
        def close(self):raise OSError('cleanup')
    with pytest.raises(ValueError,match='primary'):
        try:raise ValueError('primary')
        finally:_cleanup_store(Broken(),None,setup[3])
    assert setup[3].state['cleanup_errors']

def test_critical_cleanup_failure_reported_without_primary(setup):
    from cordon2025.visum_startup import _cleanup_store
    class Broken:
        def close(self):raise OSError('cleanup')
    with pytest.raises(OSError,match='cleanup'):_cleanup_store(Broken(),None,setup[3])

def test_progress_IO_failure_cannot_mask_com_busy_failure(setup,monkeypatch):
    import cordon2025.visum_startup as runtime
    real=runtime.write_json
    def writer(path,value):
        if Path(path).name=='00_PROGRESS.json':raise PermissionError('locked telemetry')
        return real(path,value)
    monkeypatch.setattr(runtime,'write_json',writer)
    setup[0].failures['GetValues']=(99,UnprintableBusy)
    with pytest.raises(UnprintableBusy):ready(setup)
    assert setup[3].telemetry_failures

@pytest.mark.parametrize('damage,reason',[(None,None),('matrix','SHA_MISMATCH'),('balance','PER_OD_PARITY_FAIL'),('traversal','PATH_INVALID'),('scope','SCOPE_MISMATCH')])
def test_sealed_matrix_parity_rechecked_by_incidence_reader(setup,damage,reason):
    import numpy as np
    from cordon2025.common import sha256
    from cordon2025.io import write_npz
    from cordon2025.incidence import build_from_snapshot
    from cordon2025.authority import mapping
    v,c,o,ctl,opt=setup;p=ready(setup);cache,ep=capture(v,c,o,ctl,opt,p)
    ev=json.loads(ep.read_text());cfg=copy.deepcopy(c);cfg['mutable_dsegs']=[]
    m,_=mapping(ROOT/'data/audited/STATION_MAPPING.csv')
    rec=ev['od_matrix_authorities'][0];path=o/rec['path']
    if damage in ('matrix','balance'):
        with np.load(path) as data:val=data['values'].copy();zones=data['zone_nos'].copy()
        val[0,1]+=1;val[1,2]-=1;write_npz(path,values=val,zone_nos=zones)
        if damage=='balance':rec['sha256']=sha256(path)
    if damage=='traversal':rec['path']='../escape.npz'
    if damage=='scope':ev['od_matrix_authorities'].pop()
    if reason:
        with pytest.raises(Exception,match=reason):build_from_snapshot(cache,m,cfg,ev)
    else:
        r=build_from_snapshot(cache,m,cfg,ev)
        assert all(inc.audit['per_od_external_parity']=='PASS' for inc in r.values())
