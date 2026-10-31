from types import SimpleNamespace
from pathlib import Path
import math
import threading
import pytest
from cordon2025 import diagfast_pages as fast
from cordon2025.diagfast_telemetry import Telemetry
from cordon2025.visum_startup import ReadControl,settings
from cordon2025.common import parent_module
from fake_visum_startup import TypeInfo, BusyError

class Provider:
    def __init__(self, data):
        self.data=data;self.calls=[];self.bad_signature=False;self.max_size=1024
        self.busy=0;self.bad_width=False;self.repeat=False;self.error=None;self.stop=None
    def GetTypeInfo(self):return TypeInfo(self)
    def Invoke(self,mid,lcid,kind,method,first,last):
        self.calls.append((first,last))
        if self.stop:self.stop.touch()
        if self.busy:
            self.busy-=1
            raise BusyError()
        if self.error:raise self.error
        if last-first+1>self.max_size:raise MemoryError('page too large')
        if self.repeat and first>1:first,last=1,last-first+1
        page=self.data[first-1:last]
        if self.bad_width and page:page=[r[:-1] for r in page]
        return page

@pytest.fixture
def setup(tmp_path):
    out=tmp_path/'out';out.mkdir()
    opt=settings({'min_free_disk_gib':0,'com_retry_attempts':3,
                  'com_retry_initial_delay_seconds':0.,'com_retry_max_delay_seconds':0.})
    return out,ReadControl(out),opt,Telemetry()

def read(p,size,t,columns=None,backend='FAST_EXACT'):
    two=parent_module('r1_15a2_two_mode_v238')
    out,ctl,opt,tele=t
    return list(fast.rows(SimpleNamespace(_oleobj_=p),columns or two.PARENT_COLUMNS,
              dict(two.DEFAULT_SETTINGS,com_retry_policy={'enabled':True,'max_attempts':3,'initial_delay_seconds':0.,'max_delay_seconds':0.}),
              ctl,opt,'TEST',telemetry=tele,backend=backend,
              fast_options=fast.settings({'fast_parent_page_size':size,'fast_geometry_page_size':size})))

@pytest.mark.parametrize('n',[0,1,255,256,257,511,512,513,1023,1024,1025,3073])
@pytest.mark.parametrize('size',[256,512,1024])
def test_pages_complete_exact_and_counts(setup,n,size):
    data=[[i+1,i+2,1,float(i)] for i in range(n)];p=Provider(data)
    assert read(p,size,setup)==data
    assert len(p.calls)==n//size+1
    assert setup[3].counters['provider_invoke_attempts']==len(p.calls)

@pytest.mark.parametrize('size',[256,512,1024])
def test_geometry_hierarchy_page_boundary_exact(setup,size):
    two=parent_module('r1_15a2_two_mode_v238')
    data=[]
    for i in range(355):
        data+=[[i+1,i+2,1,'','','',''],['','','',1,4,10,20],['','','',2,5,20,30]]
    assert read(Provider(data),size,setup,two.GEOMETRY_COLUMNS)==data

def test_bounded_downshift_same_first_no_skip(setup):
    data=[[i+1,i+2,1,0.] for i in range(2033)];p=Provider(data);p.max_size=256
    assert read(p,1024,setup)==data
    assert p.calls[:3]==[(1,1024),(1,512),(1,256)]
    assert p.calls[3][0]==257

def test_busy_retries_exact_same_range(setup):
    p=Provider([[1,2,1,10.]]);p.busy=2
    assert read(p,512,setup)==p.data
    assert p.calls==[(1,512)]*3
    assert setup[3].counters['TEST.provider_invoke_errors']==2

def test_busy_exhaustion_never_downshifts(setup):
    p=Provider([]);p.busy=100
    with pytest.raises(BusyError):read(p,512,setup)
    assert p.calls==[(1,512)]*3

@pytest.mark.parametrize('kind,code',[('width','BOUNDED_ROW_SCHEMA_MISMATCH'),('signature','UNVERIFIED'),('repeat','NO_PROGRESS')])
def test_invalid_provider(setup,kind,code):
    p=Provider([[i+1,i+2,1,0.] for i in range(1024)])
    if kind=='width':p.bad_width=True
    if kind=='signature':p.bad_signature=True
    if kind=='repeat':p.repeat=True
    with pytest.raises(Exception,match=code):read(p,256,setup)

def test_data_error_not_retried_or_fallback(setup):
    p=Provider([]);p.error=ValueError('INVALID_PROVIDER_DATA')
    with pytest.raises(ValueError,match='INVALID_PROVIDER_DATA'):read(p,512,setup)
    assert len(p.calls)==1

def test_stop_before_retry(setup):
    p=Provider([]);p.stop=setup[0]/'STOP_REQUESTED';p.busy=2
    with pytest.raises(RuntimeError,match='USER_STOP_REQUESTED'):read(p,512,setup)
    assert len(p.calls)==1

def test_wrong_thread(setup):
    setup[1].thread=-1;p=Provider([])
    with pytest.raises(Exception,match='COM_THREAD_CHANGED'):read(p,256,setup)
    assert not p.calls

def test_legacy_uses_original_page_size(setup):
    p=Provider([[i+1,i+2,1,0.] for i in range(1200)])
    read(p,1024,setup,backend='LEGACY')
    assert p.calls[0]==(1,256)

@pytest.mark.parametrize('options',[{'fast_geometry_page_size':2048},{'fast_parent_page_size':True},{'auto_tune':True},{'typo':2}])
def test_settings_reject_untested(options):
    with pytest.raises(Exception):fast.settings(options)


def test_downshift_after_successful_page_same_cursor(setup):
    class MidCapacity(Provider):
        def Invoke(self,mid,lcid,kind,method,first,last):
            if first>=1025:self.max_size=256
            return super().Invoke(mid,lcid,kind,method,first,last)
    data=[[i+1,i+2,1,0.] for i in range(3073)];p=MidCapacity(data)
    assert read(p,1024,setup)==data
    assert p.calls[:4]==[(1,1024),(1025,2048),(1025,1536),(1025,1280)]
