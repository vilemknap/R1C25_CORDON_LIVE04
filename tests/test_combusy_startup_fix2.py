"""Recovered STARTUP_FIX1 regressions + 24915 HOTFIX1 port. MOCK COM ONLY."""
from pathlib import Path
from types import SimpleNamespace
from collections import Counter
import hashlib
import json
import copy
import sqlite3
import pytest
from cordon2025.common import ROOT, parent_module, read_config
from cordon2025 import com_busy as busy
from cordon2025.visum_startup import settings, preflight, capture, ReadControl, run, retry_policy
from fake_visum_startup import FakeVisum, BusyError, UnprintableBusy, UnprintableOther

class Later(BusyError): hresult = -2147417846
class UnsignedBusy(BusyError): hresult = 0x80010001
class Permanent(Exception): hresult = -2147024809

class OnceMember:
    """Fail at property/method retrieval, BEFORE invoking the bound method."""
    def __init__(self, obj, key, times=2, error=BusyError):
        self.obj, self.key, self.times, self.error = obj, key, times, error
        self.calls = 0
    def __getattr__(self, key):
        if key == self.key:
            self.calls += 1
            if self.calls <= self.times: raise self.error('provider unavailable')
        return getattr(self.obj, key)

@pytest.fixture
def setup(tmp_path):
    v = FakeVisum(tmp_path/'model'); out=tmp_path/'out';out.mkdir()
    cfg=read_config(ROOT/'CORDON_2025_AGGRESSIVE_CONFIG.json')
    opt=settings({'page_size':2,'min_free_disk_gib':0.,'com_retry_attempts':4,
                  'com_retry_initial_delay_seconds':0.,'com_retry_max_delay_seconds':0.})
    return v,cfg,out,ReadControl(out),opt

def damage(v,point,error=BusyError,times=2):
    if point in ('Net','Procedures','IO','Workbench'):
        return OnceMember(v,point,times,error)
    if point in ('Zones','Links','DemandSegments'):
        v.Net=OnceMember(v.Net,point,times,error)
    elif point=='GetMultiAttValues':
        v.Net.Links=OnceMember(v.Net.Links,point,times,error)
    elif point=='CurrentVersionFile':
        v.IO=OnceMember(v.IO,point,times,error)
    elif point=='Lists':v.Workbench=OnceMember(v.Workbench,point,times,error)
    elif point=='ItemByKey':v.Net.DemandSegments=OnceMember(v.Net.DemandSegments,point,times,error)
    elif point=='ODMatrix':
        code=next(iter(v.dsegs));v.dsegs[code]=OnceMember(v.dsegs[code],point,times,error)
    elif point in ('GetValues','AttValue'):
        code=next(iter(v.dsegs));v.dsegs[code].ODMatrix=OnceMember(v.dsegs[code].ODMatrix,point,times,error)
    elif point in ('GetTypeInfo','GetTypeAttr','GetFuncDesc','GetNames'):
        old=v.Workbench.Lists.CreatePrTPathList
        def factory():
            obj=old()
            if point=='GetTypeInfo':obj._oleobj_=OnceMember(obj._oleobj_,point,times,error)
            else:
                ole=obj._oleobj_;fn=ole.GetTypeInfo
                ole.GetTypeInfo=lambda:OnceMember(fn(),point,times,error)
            return obj
        v.Workbench.Lists.CreatePrTPathList=factory
    else:raise AssertionError(point)
    return v

@pytest.mark.parametrize('point',['Net','Procedures','IO','Workbench','Zones','Links','DemandSegments',
    'GetMultiAttValues','CurrentVersionFile','Lists','ItemByKey','ODMatrix','GetValues','AttValue',
    'GetTypeInfo','GetTypeAttr','GetFuncDesc','GetNames'])
@pytest.mark.parametrize('error',[BusyError,Later])
def test_property_and_typeinfo_reads_recover(setup,point,error):
    v,c,o,ctl,opt=setup;injected=damage(v,point,error)
    report=preflight(injected,c,o,ctl,opt)[0]
    assert report['status']=='VISUM_READONLY_PREFLIGHT_PASS'
    assert busy.telemetry(ctl,opt)['event_counts']['RETRY'] >= 2
    assert not v.writes and not v.unbounded

@pytest.mark.parametrize('point',['Net','Links','GetMultiAttValues','GetTypeInfo','ODMatrix','GetValues'])
def test_permanent_properties_are_not_retried(setup,point):
    v,c,o,ctl,opt=setup;injected=damage(v,point,Permanent,99)
    with pytest.raises(Permanent):preflight(injected,c,o,ctl,opt)
    assert not busy.telemetry(ctl,opt)['event_counts']
    assert not v.writes

@pytest.mark.parametrize('error',[BusyError,Later,UnsignedBusy,UnprintableBusy])
def test_exhaustion_preserves_exact_exception_instance_and_bound(setup,error):
    v,c,o,ctl,opt=setup
    exc=error();calls=[]
    def reject():calls.append(1);raise exc
    with pytest.raises(error) as raised:busy.read_call(reject,ctl,opt,'bounded')
    assert raised.value is exc and len(calls)==4
    assert busy.telemetry(ctl,opt)['event_counts']=={'RETRY':3,'EXHAUSTED':1}
    assert ctl._cordon_combusy_depth==0

@pytest.mark.parametrize('enabled',[False,True])
def test_optout_respected_with_no_silent_activation(setup,enabled):
    v,c,o,ctl,opt=setup;opt['com_retry_enabled']=enabled
    calls=[]
    def reject():calls.append(1);raise BusyError()
    with pytest.raises(BusyError):busy.read_call(reject,ctl,opt,'optout')
    assert len(calls)==(4 if enabled else 1)


def test_nested_reads_do_not_multiply_attempts(setup):
    v,c,o,ctl,opt=setup;calls=[]
    def inner():calls.append(1);raise Later()
    with pytest.raises(Later):
        busy.read_call(lambda:busy.read_call(inner,ctl,opt,'inner'),ctl,opt,'outer')
    assert len(calls)==4
    assert all(e['label'].endswith('outer') for e in ctl.com_retry_events)

class CounterControl:
    def __init__(self):self.points=[]
    def checkpoint(self,*args,**kwargs):self.points.append((args,kwargs))


def test_elapsed_lease_and_backoff_use_parent_algorithm(monkeypatch):
    ctl=CounterControl();opt=settings({'com_retry_max_elapsed_seconds':.4})
    now=[0.];delays=[];calls=[]
    monkeypatch.setattr(busy.time,'monotonic',lambda:now[0])
    def sleep(dt):delays.append(dt);now[0]+=dt
    monkeypatch.setattr(busy.time,'sleep',sleep)
    def reject():calls.append(1);raise Later()
    with pytest.raises(Later):busy.read_call(reject,ctl,opt,'lease')
    assert len(calls)==3 and delays==pytest.approx([.15,.225])
    assert ctl.com_retry_events[-1]['exhausted_by_elapsed'] is True
    assert now[0] <= .4


def test_original_hotfix_defaults_preserved_with_explicit_practical_budget():
    mod=parent_module('r1_15a2_com_busy_snapshot_hotfix_v1')
    p=retry_policy(settings())
    assert all(p[k]==v for k,v in mod.DEFAULTS.items() if k not in ('max_attempts','max_elapsed_seconds'))
    assert mod.DEFAULTS['max_attempts']==64 and mod.DEFAULTS['max_elapsed_seconds']==75.
    assert p['max_attempts']==128 and p['max_elapsed_seconds']==180.
    assert p['enabled'] is True
    assert hashlib.sha256((ROOT/'parent'/busy.SOURCE).read_bytes()).hexdigest()==busy.SOURCE_SHA256

@pytest.mark.parametrize('changes',[
    {'com_retry_enabled':1},{'com_retry_max_elapsed_seconds':None},
    {'com_retry_max_elapsed_seconds':float('inf')},{'com_retry_max_elapsed_seconds':-1},
    {'com_retry_max_elapsed_seconds':True},{'com_retry_backoff_factor':.5},
    {'com_retry_max_delay_seconds':.01},{'com_retry_attempts':0},
    {'com_retry_max_delay_seconds':'one'}])
def test_invalid_policy_fails_before_reads(changes):
    with pytest.raises(Exception,match='INVALID_STARTUP'):settings(changes)

@pytest.mark.parametrize('point',['Invoke','SetObjects','AddColumn'])
def test_existing_page_and_list_retries_still_work(setup,point):
    v,c,o,ctl,opt=setup;v.failures[point]=(2,Later)
    pre=preflight(v,c,o,ctl,opt)
    cache,ep=capture(v,c,o,ctl,opt,pre)
    assert json.loads(ep.read_text())['completed'] is True
    assert not v.writes and not v.unbounded


def test_retry_never_changes_or_skips_a_bounded_range(setup):
    from fake_visum_startup import ListObj
    from cordon2025.visum_startup import _bounded_rows
    v,c,o,ctl,opt=setup;obj=ListObj(v,'parent');obj.SetObjects(0,'NATIVE_CW',0)
    ole=obj._oleobj_;original=ole.Invoke;calls=[];remaining=[2]
    def invoke(*args):
        calls.append(args[-2:])
        if remaining[0]:remaining[0]-=1;raise BusyError()
        return original(*args)
    ole.Invoke=invoke
    two=parent_module('r1_15a2_two_mode_v238')
    st=dict(two.DEFAULT_SETTINGS,page_size=2,com_retry_policy=retry_policy(opt))
    rows=list(_bounded_rows(obj,two.PARENT_COLUMNS,st,ctl,opt,'TEST_PAGE'))
    assert calls==[(1,2),(1,2),(1,2),(3,4)]
    assert rows==obj.rows


def test_STOP_created_during_backoff_stops_before_next_COM_call(setup,monkeypatch):
    v,c,o,ctl,opt=setup;opt.update(com_retry_initial_delay_seconds=.1,com_retry_max_delay_seconds=.1)
    calls=[]
    def reject():calls.append(1);raise BusyError()
    monkeypatch.setattr(busy.time,'sleep',lambda dt:(o/'STOP_REQUESTED').touch())
    with pytest.raises(Exception,match='USER_STOP_REQUESTED'):busy.read_call(reject,ctl,opt,'cancel')
    assert len(calls)==1 and ctl._cordon_combusy_depth==0


def test_retry_progress_failure_does_not_mask_original_error(setup,monkeypatch):
    import cordon2025.visum_startup as runtime
    v,c,o,ctl,opt=setup;exc=UnprintableBusy()
    monkeypatch.setattr(runtime,'write_json',lambda *a,**kw:(_ for _ in ()).throw(ValueError('telemetry serialization failed')))
    def reject():raise exc
    with pytest.raises(UnprintableBusy) as raised:busy.read_call(reject,ctl,opt,'telemetry')
    assert raised.value is exc and ctl.telemetry_failures


def test_parent_hotfix_scoped_success_and_failure_restore_aliases():
    supply=parent_module('r1_15a2_supply_visum');opt=parent_module('r1_15a2_single_pass_snapshot_v24915p2c')
    adapt=parent_module('r1_15a2_trial_adapter_v24915p2c');hot=parent_module('r1_15a2_com_busy_snapshot_hotfix_v1')
    before=(supply.VisumAdapter.read_links,supply.VisumAdapter.snapshot,opt.single_pass_exact_snapshot,adapt.single_pass_exact_snapshot)
    for fail in (False,True):
        try:
            with busy.parent_hotfix_scope() as proof:
                assert proof['active'] and hot._ACTIVE
                assert adapt.single_pass_exact_snapshot is opt.single_pass_exact_snapshot
                assert supply.VisumAdapter.read_links is not before[0]
                if fail:raise LookupError('sentinel')
        except LookupError:pass
        assert not hot._ACTIVE
        assert before==(supply.VisumAdapter.read_links,supply.VisumAdapter.snapshot,opt.single_pass_exact_snapshot,adapt.single_pass_exact_snapshot)


def test_partial_parent_activation_failure_restores_everything(monkeypatch):
    hot=parent_module('r1_15a2_com_busy_snapshot_hotfix_v1');supply=parent_module('r1_15a2_supply_visum')
    before=supply.VisumAdapter.read_links
    def broken():
        supply.VisumAdapter.read_links=lambda *_:None
        hot._ACTIVE=True
        raise RuntimeError('activation failed')
    monkeypatch.setattr(hot,'activate',broken)
    with pytest.raises(RuntimeError,match='activation failed'):
        with busy.parent_hotfix_scope():pass
    assert not hot._ACTIVE and supply.VisumAdapter.read_links is before


def test_final_version_read_is_also_retried(setup):
    v,c,o,ctl,opt=setup;pre=preflight(v,c,o,ctl,opt)
    v.IO=OnceMember(v.IO,'CurrentVersionFile',2,Later)
    cache,ep=capture(v,c,o,ctl,opt,pre)
    assert json.loads(ep.read_text())['completed']
    assert any(e['label'].endswith('FINAL_CURRENT_VERSION') for e in ctl.com_retry_events)


def test_workbench_busy_never_uses_legacy_alternate_list_api(setup):
    v,c,o,ctl,opt=setup
    class Forbidden:
        def __getattr__(self,name):raise AssertionError('LEGACY_LIST_API_WAS_USED')
    v.Lists=Forbidden();v.Workbench=OnceMember(v.Workbench,'Lists',2,BusyError)
    assert preflight(v,c,o,ctl,opt)[0]['status']=='VISUM_READONLY_PREFLIGHT_PASS'


def test_capture_after_recovery_has_identical_SQL_values(setup,tmp_path):
    v,c,o,ctl,opt=setup;pre=preflight(v,c,o,ctl,opt);p,_=capture(v,c,o,ctl,opt,pre)
    other=tmp_path/'other';other.mkdir();v2=FakeVisum(tmp_path/'model2')
    v2.Net=OnceMember(v2.Net,'Links',2,Later)
    ctl2=ReadControl(other);pre2=preflight(v2,c,other,ctl2,opt);p2,_=capture(v2,c,other,ctl2,opt,pre2)
    with sqlite3.connect(p) as a,sqlite3.connect(p2) as b:
        for table,cols in [('edges','eid,link_no,from_no,to_no'),('geometry','gid,mode,orig,dest,path_index,edge_ids,edge_count,sequence_sha256'),('volumes','gid,dseg,volume')]:
            assert list(a.execute('SELECT '+cols+' FROM '+table+' ORDER BY 1,2'))==list(b.execute('SELECT '+cols+' FROM '+table+' ORDER BY 1,2'))
    assert not v.writes and not v2.writes


def test_failure_has_retry_evidence_and_restores_original_parent(tmp_path):
    v=FakeVisum(tmp_path/'model');v.Net=OnceMember(v.Net,'Links',100,Later)
    supply=parent_module('r1_15a2_supply_visum');before=supply.VisumAdapter.read_links
    with pytest.raises(Later):run(v,output_root=tmp_path/'runs',options={'com_retry_attempts':3,'com_retry_initial_delay_seconds':0.,'com_retry_max_delay_seconds':0.})
    files=list((tmp_path/'runs').rglob('COM_READ_RETRY.json'));assert len(files)==1
    evidence=json.loads(files[0].read_text())
    assert evidence['event_counts']=={'RETRY':2,'EXHAUSTED':1}
    assert supply.VisumAdapter.read_links is before
    assert not list((tmp_path/'runs').rglob('SNAPSHOT_EVIDENCE.json'))


def test_telemetry_has_bounded_memory():
    ctl=CounterControl()
    for i in range(1300):busy.record_event(ctl,{'label':'same','attempt':i,'exhausted':False})
    assert len(ctl.com_retry_events)==1000 and ctl.com_retry_event_counts['RETRY']==1300
