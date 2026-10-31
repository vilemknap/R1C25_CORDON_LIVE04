from pathlib import Path
import copy,hashlib,json,sqlite3
import numpy as np
import pytest
from fake_visum_startup import FakeVisum,BusyError
from cordon2025.common import ROOT,read_config,parent_module
from cordon2025.diagfast_runtime import run,overlay
from cordon2025.diagfast_parity import compare_runs,compare_sql
from cordon2025.diagfast_telemetry import Telemetry
from cordon2025 import visum_startup as legacy
from cordon2025 import diagfast_pages

OPT={'min_free_disk_gib':0,'com_retry_attempts':3,'com_retry_initial_delay_seconds':0.,'com_retry_max_delay_seconds':0.}

def invoke(tmp_path,backend,size=256,v=None):
    v=v or FakeVisum(tmp_path/'model')
    r=run(v,backend=backend,output_root=tmp_path/'runs',options=OPT,
        fast_options={'fast_parent_page_size':size,'fast_geometry_page_size':size})
    return v,Path(r['output_directory']),r

@pytest.mark.parametrize('size',[256,512,1024])
def test_full_12dseg_exact_diagnostics_parity(tmp_path,size):
    v=FakeVisum(tmp_path/'model');_,left,_=invoke(tmp_path,'LEGACY',v=v)
    v2=FakeVisum(tmp_path/'model');_,right,r=invoke(tmp_path,'FAST_EXACT',size,v2)
    diff=compare_runs(left,right)
    assert diff['status']=='PARITY_PASS', [x for x in diff['artifacts'] if not x['equal']]
    t=json.loads((right/'DIAGFAST_TIMING.json').read_text())
    assert t['counters']['matrix_getvalues_attempts']==36
    assert t['counters']['full_stream_proofs']==10
    assert t['counters'].get('scratch_sqlite_stores',0)==0
    assert not list(right.glob('proof_*.sqlite'))
    assert r['geometry_full_identity_proven'] and not r['apply_permitted'] and not v2.writes and not v2.unbounded
    for method in ('ALL_ORDERED_UNIQUE_PAIRS','EXACT_TWO_HITS'):
        roster=json.loads((right/method/'OBSERVATION_ROSTER.json').read_text())
        assert (roster['rows'],roster['calibration'],roster['validation'])==(120,108,12)

@pytest.mark.parametrize('backend',['LEGACY','FAST_EXACT'])
@pytest.mark.parametrize('damage,message',[
 ('matrix_drift','MATRIX_CHANGED_DURING_CAPTURE'),('path_drift','PATH_VOLUMES_CHANGED_DURING_CAPTURE'),
 ('same_mode_geometry_mismatch','FULL_SAME_MODE_GEOMETRY_DIFFERS'),('sequence_gap','CONTIGUOUS'),
 ('path_distribution_wrong','PER_OD_PATH_MATRIX_PARITY_FAIL'),('bad_width','SCHEMA_MISMATCH'),
 ('bad_signature','UNVERIFIED'),('parent_empty','NO_SAVED_PRT_PATHS')])
def test_errors_fail_closed_both_backends(tmp_path,backend,damage,message):
    v=FakeVisum(tmp_path/'model');setattr(v,damage,True)
    original=legacy.capture
    with pytest.raises(Exception,match=message):invoke(tmp_path,backend,v=v)
    assert legacy.capture is original and not v.writes
    assert not list((tmp_path/'runs').rglob('SNAPSHOT_EVIDENCE.json'))
    assert not list((tmp_path/'runs').rglob('00_RESULT.json'))

@pytest.mark.parametrize('backend',['LEGACY','FAST_EXACT'])
def test_busy_capture_and_restore(tmp_path,backend):
    v=FakeVisum(tmp_path/'model');v.failures['Invoke']=(2,BusyError)
    _,out,r=invoke(tmp_path,backend,v=v)
    assert r['status']=='VISUM_SAVED_PATH_DIAGNOSTICS_COMPLETE'
    assert len(json.loads((out/'COM_READ_RETRY.json').read_text())['events'])==2
    assert not v.writes

def test_no_provisional_fast():
    with pytest.raises(Exception,match='FULL_GEOMETRY'):run(None,options={'full_geometry_check':False})

def test_scoped_runtime_restore_on_fault(tmp_path):
    two=parent_module('r1_15a2_two_mode_v238')
    originals=(legacy.capture,legacy._call,two.TwoModeRouteCollector.add_geometry)
    with pytest.raises(RuntimeError,match='INJECTED_CRASH'):
        with overlay('FAST_EXACT',diagfast_pages.settings(),Telemetry()):raise RuntimeError('INJECTED_CRASH')
    assert originals==(legacy.capture,legacy._call,two.TwoModeRouteCollector.add_geometry)

def test_no_nested_overlay():
    with overlay('LEGACY',diagfast_pages.settings(),Telemetry()):
        with pytest.raises(Exception,match='ALREADY_ACTIVE'):
            with overlay('FAST_EXACT',diagfast_pages.settings(),Telemetry()):pass

def test_sql_diff_catches_redistribution(tmp_path):
    v,left,_=invoke(tmp_path,'LEGACY');v2,right,_=invoke(tmp_path,'FAST_EXACT')
    with sqlite3.connect(right/'p.sqlite') as db:
        db.execute("UPDATE volumes SET volume=volume+1 WHERE gid=1")
    assert compare_sql(left/'p.sqlite',right/'p.sqlite')['status']=='PARITY_FAIL'


def test_perf01_build_hit_with_new_proof(tmp_path):
    from cordon2025.perf01_cache import get_or_build
    from cordon2025.authority import mapping
    _,out,r=invoke(tmp_path,'FAST_EXACT')
    cfg=read_config(ROOT/'CORDON_2025_CONFIG.json');cfg['mutable_dsegs']=[]
    m,_=mapping(ROOT/'data/audited/STATION_MAPPING.csv')
    kw={'cache_dir':tmp_path/'cache','context':'same-sealed-snapshot'}
    a=get_or_build(out/'p.sqlite',m,cfg,out/'SNAPSHOT_EVIDENCE.json',policy='build-offline',**kw)
    b=get_or_build(out/'p.sqlite',m,cfg,out/'SNAPSHOT_EVIDENCE.json',policy='require-verified-hit',**kw)
    assert b.status['geometry_redecode_count']==0
    for k in a.variants:assert np.array_equal(a.variants[k].model,b.variants[k].model)


def test_nonzero_mutable_incidence_unchanged_across_backends(tmp_path):
    from cordon2025.incidence import build_from_snapshot
    from cordon2025.authority import mapping
    from cordon2025.io import read_json
    _,a,_=invoke(tmp_path,'LEGACY');_,b,_=invoke(tmp_path,'FAST_EXACT')
    cfg=read_config(ROOT/'CORDON_2025_CONFIG.json')
    cfg['mutable_dsegs']=['NATIVE_CW','NATIVE_CS'];cfg['mutable_relation_policy']='ALL_MUTABLE_RELATIONS'
    m,_=mapping(ROOT/'data/audited/STATION_MAPPING.csv')
    left=build_from_snapshot(a/'p.sqlite',m,cfg,read_json(a/'SNAPSHOT_EVIDENCE.json'))
    right=build_from_snapshot(b/'p.sqlite',m,cfg,read_json(b/'SNAPSHOT_EVIDENCE.json'))
    for method in left:
        x,y=left[method],right[method]
        assert len(x.operator.values)>0
        for field in ('row_idx','col_idx','values'):
            assert np.array_equal(getattr(x.operator,field),getattr(y.operator,field))
        assert x.variables==y.variables and np.array_equal(x.q_current,y.q_current)
