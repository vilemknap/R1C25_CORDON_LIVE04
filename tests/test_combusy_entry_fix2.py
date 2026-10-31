"""Mock-host integration at the actual Execute Script entry, not a native PTV test."""
from pathlib import Path
from types import ModuleType
import json
import sys
import pytest
import cordon_visum_bootstrap as boot
from cordon2025.common import ROOT, parent_module
from cordon2025.visum_startup import preflight, capture, _bounded_rows, retry_policy
from test_combusy_startup_fix2 import setup, OnceMember, Later, damage
from fake_visum_startup import FakeVisum, ListObj, BusyError, UnprintableBusy


def test_stop_during_native_message_pump_prevents_next_page_RPC(setup, monkeypatch):
    v,c,o,ctl,opt=setup
    obj=ListObj(v,'parent');obj.SetObjects(0,'NATIVE_CW',0)
    v.failures['Invoke']=(2,BusyError)
    com=parent_module('r1_15a2_com_compat')
    monkeypatch.setattr(com,'_pump_waiting_messages',lambda:(o/'STOP_REQUESTED').touch())
    two=parent_module('r1_15a2_two_mode_v238')
    st=dict(two.DEFAULT_SETTINGS,page_size=2,com_retry_policy=retry_policy(opt))
    with pytest.raises(RuntimeError,match='USER_STOP_REQUESTED'):
        list(_bounded_rows(obj,two.PARENT_COLUMNS,st,ctl,opt,'CANCEL_PAGE'))
    # The next rejected attempt must not reach COM after STOP exists.
    assert v.counters['Invoke']==1
    assert not v.writes and not v.unbounded


@pytest.mark.parametrize('point',['GetTypeInfo','GetTypeAttr','GetFuncDesc','GetNames'])
def test_capture_geometry_metadata_busy_recovers_after_preflight(setup,point):
    v,c,o,ctl,opt=setup;pre=preflight(v,c,o,ctl,opt)
    old=v.Workbench.Lists.CreatePrTPathLinkList
    def factory():
        obj=old()
        if point=='GetTypeInfo':obj._oleobj_=OnceMember(obj._oleobj_,point,2,Later)
        else:
            get_type=obj._oleobj_.GetTypeInfo
            obj._oleobj_.GetTypeInfo=lambda:OnceMember(get_type(),point,2,Later)
        return obj
    v.Workbench.Lists.CreatePrTPathLinkList=factory
    cache,ep=capture(v,c,o,ctl,opt,pre)
    assert cache.is_file() and json.loads(ep.read_text())['geometry_full_identity_proven']
    assert ctl.com_retry_event_counts['RETRY'] >= 2
    assert not v.writes and not v.unbounded


@pytest.mark.parametrize('drift,reason',[('matrix_drift','MATRIX_CHANGED'),('path_drift','PATH_VOLUMES_CHANGED'),('path_distribution_wrong','PER_OD_PATH_MATRIX_PARITY_FAIL')])
def test_recovered_COM_cannot_mask_assignment_state_corruption(setup,drift,reason):
    v,c,o,ctl,opt=setup;setattr(v,drift,True)
    v=damage(v,'GetTypeInfo',Later)
    pre=preflight(v,c,o,ctl,opt)
    with pytest.raises(Exception,match=reason):capture(v,c,o,ctl,opt,pre)
    assert not (o/'SNAPSHOT_EVIDENCE.json').exists()


@pytest.mark.parametrize('mode',['PREFLIGHT','CAPTURE_DIAGNOSTICS'])
def test_complete_boot_retries_and_restores_existing_2022_modules(tmp_path,monkeypatch,mode):
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path/'local'))
    # Deliberately insert a conflicting loaded parent snapshot module.
    # The test proves it is not used and remains unmodified after return.
    v=FakeVisum(tmp_path/'model');v.Net=OnceMember(v.Net,'Links',2,Later)
    name='r1_15a2_supply_visum'
    old=ModuleType(name);old.__file__='/old/2022/'+name+'.py';old.identity=object()
    old.data={'immutable':True};token=old.identity
    monkeypatch.setitem(sys.modules,name,old)
    before_path=list(sys.path);before_cordon=sys.modules.get('cordon2025')
    result=boot.launch({'Visum':v},ROOT,action=mode,output_root=tmp_path/'runs',options={
        'min_free_disk_gib':0.,'com_retry_initial_delay_seconds':0.,'com_retry_max_delay_seconds':0.})
    expected='VISUM_READONLY_PREFLIGHT_PASS' if mode=='PREFLIGHT' else 'VISUM_SAVED_PATH_DIAGNOSTICS_COMPLETE'
    assert result['status']==expected,result
    assert result['com_busy_retry']['event_counts']['RETRY']==2
    assert sys.modules[name] is old and old.identity is token and old.data=={'immutable':True}
    assert sys.path==before_path and sys.modules.get('cordon2025') is before_cordon
    assert not getattr(sys,'_r1_cordon2025_busy',False)
    assert not v.writes and not v.unbounded and result['apply_permitted'] is False


def test_actual_entry_reports_exhausted_unprintable_failure_and_boot_log(tmp_path,monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path/'local'))
    before=sys.modules.get('cordon2025');path_before=list(sys.path)
    v=FakeVisum(tmp_path/'model');v.Net=OnceMember(v.Net,'Links',100,UnprintableBusy)
    r=boot.launch({'Visum':v},ROOT,output_root=tmp_path/'runs',options={
        'com_retry_attempts':3,'com_retry_initial_delay_seconds':0.,'com_retry_max_delay_seconds':0.})
    assert r['status']=='STARTUP_BLOCKED',r
    assert r['error_type']=='UnprintableBusy' and 'unprintable' in r['reason']
    assert v.Net.calls==3 and sys.path==path_before
    assert sys.modules.get('cordon2025') is before
    assert Path(r['boot_log_directory'],'00_BOOT_RESULT.json').is_file()
    files=list((tmp_path/'runs').rglob('COM_READ_RETRY.json'));assert len(files)==1
    proof=json.loads(files[0].read_text());assert proof['event_counts']=={'RETRY':2,'EXHAUSTED':1}
    assert not list((tmp_path/'runs').rglob('SNAPSHOT_EVIDENCE.json'))


def test_new_retry_does_not_import_profile_launchers(tmp_path,monkeypatch):
    import importlib.abc
    class Guard(importlib.abc.MetaPathFinder):
        def find_spec(self,name,path=None,target=None):
            if 'launcher' in name.lower() or name.startswith('R1_15A2_'):
                raise AssertionError('PROFILE_LAUNCHER_IS_FORBIDDEN:'+name)
    monkeypatch.setattr(sys,'meta_path',[Guard()]+list(sys.meta_path))
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path/'local'))
    r=boot.launch({'Visum':FakeVisum(tmp_path/'model')},ROOT,output_root=tmp_path/'runs')
    assert r['status']=='VISUM_READONLY_PREFLIGHT_PASS',r


def test_default_retry_does_not_change_active_scope_and_science():
    cfg=json.loads((ROOT/'CORDON_2025_AGGRESSIVE_CONFIG.json').read_text())
    assert cfg['apply'] is False and cfg['model_year']==2025 and cfg['survey_year']==2026
    base=ROOT/'provenance/startup_fix2/STARTUP_FIX1_SOURCE_MANIFEST.json'
    records=json.loads(base.read_text())['files']
    import hashlib
    protected=[r for r in records if r['path'].startswith(('data/','parent/')) or r['path'] in ('CORDON_2025_CONFIG.json','CORDON_2025_AGGRESSIVE_CONFIG.json')]
    assert len(protected)>800
    for rec in protected:
        digest=rec['sha256']
        review=json.loads((ROOT/'docs/fix3/REVIEWED_CHANGES.json').read_text())['files']
        if rec['path'] in review:
            assert review[rec['path']]['before_sha256']==digest
            digest=review[rec['path']]['after_sha256']
        assert hashlib.sha256((ROOT/rec['path']).read_bytes()).hexdigest()==digest,rec['path']
