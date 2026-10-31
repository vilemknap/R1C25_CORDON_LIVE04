from pathlib import Path
import sqlite3,json,sys,importlib.util
import numpy as np
import pytest
from fake_visum_startup import FakeVisum
from diagfast_scaled_visum import ScaledVisum
from cordon2025.diagfast_runtime import run
from cordon2025.diagfast_parity import compare_runs
from cordon2025.common import ROOT

@pytest.mark.parametrize('size',[256,512,1024])
def test_scaled_12segment_multiple_pages(tmp_path,size):
    left=run(ScaledVisum(tmp_path/'model',route_count=513,zone_count=32,tail_length=3),backend='LEGACY',
             output_root=tmp_path/'runs',options={'min_free_disk_gib':0})
    host=ScaledVisum(tmp_path/'model',route_count=513,zone_count=32,tail_length=3)
    right=run(host,output_root=tmp_path/'runs',options={'min_free_disk_gib':0},
              fast_options={'fast_parent_page_size':size,'fast_geometry_page_size':size})
    diff=compare_runs(left['output_directory'],right['output_directory'])
    assert diff['status']=='PARITY_PASS'
    assert not host.writes and sum(d.ODMatrix.reads for d in host.dsegs.values())==36

@pytest.mark.parametrize('backend',['LEGACY','FAST_EXACT'])
def test_sum_preserving_matrix_drift(tmp_path,backend):
    host=FakeVisum(tmp_path/'model');m=host.dsegs['NATIVE_CW'].ODMatrix;original=m.GetValues
    def get():
        if m.reads>=2:m.values[0,1]+=1;m.values[1,2]-=1
        return original()
    m.GetValues=get
    with pytest.raises(Exception,match='MATRIX_CHANGED_DURING_CAPTURE'):
        run(host,backend=backend,output_root=tmp_path/'runs',options={'min_free_disk_gib':0})
    assert not list((tmp_path/'runs').rglob('SNAPSHOT_EVIDENCE.json'))

@pytest.mark.parametrize('backend',['LEGACY','FAST_EXACT'])
def test_network_change_in_final_readback(tmp_path,backend):
    host=FakeVisum(tmp_path/'model');original=host.touch
    def touch(label):
        if label=='Links.TSYSSET' and host.counters[label]>=1:host.Net.Links.rows[0]['TSYSSET']='C'
        return original(label)
    host.touch=touch
    with pytest.raises(Exception,match='NETWORK_CHANGED_DURING_CAPTURE'):
        run(host,backend=backend,output_root=tmp_path/'runs',options={'min_free_disk_gib':0})

@pytest.mark.parametrize('file',['RUN_CORDON_2025_CAPTURE_DIAGFAST.py','RUN_CORDON_2025_PARITY_AUDIT.py','LIVE_VISUM_ACCEPTANCE.py','RUN_CORDON_2025_CAPTURE_LEGACY_TIMED.py'])
def test_entries_no_import_time_execution(file):
    spec=importlib.util.spec_from_file_location('_test_entry',ROOT/file)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    assert not hasattr(module,'RESULT') and callable(module.main)


def test_paired_harness_fake_transport(tmp_path):
    from cordon2025.diagfast_harness import paired
    host=FakeVisum(tmp_path/'model')
    r=paired(host,output_root=tmp_path/'harness',options={'min_free_disk_gib':0})
    assert r['status']=='PARITY_PASS'
    assert len(r['pairs'])==1 and not host.writes


def test_same_output_root_locked(tmp_path):
    from cordon2025.session import RunSession
    with RunSession('first',tmp_path/'runs'):
        with pytest.raises(Exception,match='LOCKED'):
            run(FakeVisum(tmp_path/'model'),output_root=tmp_path/'runs',options={'min_free_disk_gib':0})


def test_sqlite_failure_closes_partial_store(tmp_path,monkeypatch):
    from cordon2025.common import parent_module
    two=parent_module('r1_15a2_two_mode_v238')
    def fail(*a,**kw):raise sqlite3.OperationalError('database or disk is full')
    monkeypatch.setattr(two.TwoModeRouteCollector,'add_geometry',fail)
    with pytest.raises(sqlite3.OperationalError,match='disk is full'):
        run(FakeVisum(tmp_path/'model'),output_root=tmp_path/'runs',options={'min_free_disk_gib':0})
    assert not list((tmp_path/'runs').rglob('SNAPSHOT_EVIDENCE.json'))
    for p in (tmp_path/'runs').rglob('p.sqlite'):
        with sqlite3.connect(p) as db:assert not db.execute("SELECT 1 FROM metadata WHERE key='capture_complete'").fetchone()
