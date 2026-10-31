"""Explicit synthetic COM fixture. No installed PTV Visum is used by these tests."""
from types import SimpleNamespace
from collections import Counter
import copy
import numpy as np
from cordon2025.common import ROOT,parent_module,parent_core
from cordon2025.authority import mapping

class BusyError(Exception):
    hresult=-2147418111
class UnprintableBusy(BusyError):
    def __str__(self):raise ValueError('broken str')
    def __repr__(self):raise ValueError('broken repr')
class UnprintableOther(Exception):
    def __str__(self):raise ValueError('broken str')
    def __repr__(self):raise ValueError('broken repr')

class Guarded:
    def __init__(self,host):self.host=host
    def __getattr__(self,key):
        if key.startswith(('Set','Save','Load','AddUser','Execute','Remove','Delete','Run')):
            def forbidden(*a,**kw):
                self.host.writes.append(key)
                raise AssertionError('FORBIDDEN_MODEL_WRITE:'+key)
            return forbidden
        raise AttributeError(key)

class Collection(Guarded):
    def __init__(self,host,rows,kind):super().__init__(host);self.rows=rows;self.kind=kind
    def GetMultiAttValues(self,name,*args):
        assert args==(False,), 'ALL_NETWORK_OBJECTS_REQUIRED_NOT_ACTIVE_FILTER'
        self.host.touch(self.kind+'.'+name)
        out=[(i+1,r[name]) for i,r in enumerate(self.rows)]
        # Deliberate different provider enumeration order: keys are authoritative.
        if self.kind=='Links' and name=='TONODENO':out.reverse()
        return out
    def ItemByKey(self,key):return self.host.dsegs[key]

class Matrix(Guarded):
    def __init__(self,host,no,values):super().__init__(host);self.no=no;self.values=np.asarray(values,dtype=float);self.reads=0
    def AttValue(self,name):
        if name.upper()=='NO':return self.no
        if name.upper()=='SUM':return float(self.values.sum())
        raise AttributeError(name)
    def GetValues(self):
        self.host.touch('GetValues');self.reads+=1
        value=self.values.copy()
        if self.host.matrix_drift and self.reads>=3:value[0,1]+=1;self.values=value.copy()
        return value.tolist()

class DSeg(Guarded):
    def __init__(self,host,code,mode,index):
        super().__init__(host);self.code=code;self.mode=mode
        self.ODMatrix=Matrix(host,8000+index,[[0,10+index,0],[0,0,20+index],[0,0,0]])
    def AttValue(self,name):
        if name.upper()=='MODE':return self.mode
        if name.upper()=='CODE':return self.code
        raise AttributeError(name)

class TypeInfo:
    def __init__(self,host):self.host=host
    def GetTypeAttr(self):return SimpleNamespace(cFuncs=1)
    def GetFuncDesc(self,i):return SimpleNamespace(memid=11,invkind=1)
    def GetNames(self,mid):
        if self.host.bad_signature:return ('SaveToArray','NotFirstObject','LastObject')
        return ('SaveToArray','FirstObject','LastObject')

class OLE:
    def __init__(self,owner):self.owner=owner
    def GetTypeInfo(self):return TypeInfo(self.owner.host)
    def Invoke(self,mid,lcid,kind,method,first,last):
        assert (mid,lcid,kind,method)==(11,0,1,True)
        assert first>=1 and last>=first
        h=self.owner.host;h.touch('Invoke');h.calls.append((self.owner.kind,self.owner.code,first,last))
        rows=self.owner.rows
        if h.repeat_pages and first>1: first,last=1,last-first+1
        out=copy.deepcopy(rows[first-1:last])
        if h.bad_width and out:out[0]=out[0][:-1]
        return out

class ListObj:
    def __init__(self,host,kind):
        self.host=host;self.kind=kind;self.code=None;self.rows=[];self.columns=[];self._oleobj_=OLE(self)
    def AddColumn(self,c):self.host.touch('AddColumn');self.columns.append(c)
    def SetObjects(self,origin,code,routefilter):
        assert (origin,routefilter)==(0,0)
        self.code=code;self.host.touch('SetObjects')
        h=self.host;h.list_counts[(self.kind,code)]+=1
        ds=h.dsegs[code];norm=parent_core().norm_code(code)
        vals=[float(ds.ODMatrix.values[0,1]),float(ds.ODMatrix.values[1,2])]
        if h.parent_empty:self.rows=[];return
        if self.kind=='parent':
            self.rows=[[10,20,1,vals[0]],[20,30,1,vals[1]]]
            if h.path_drift and h.list_counts[('parent',code)]>=3:
                self.rows[0][3]+=1;self.rows[1][3]-=1
            if h.path_distribution_wrong:self.rows[0][3]+=1;self.rows[1][3]-=1
        else:
            mode=parent_core().norm_code(ds.mode)
            paths=h.routes[mode]
            if h.same_mode_geometry_mismatch and norm=='EXOG_EE_CF':paths=paths[::-1]
            self.rows=[]
            for (o,d),edges in zip([(10,20),(20,30)],paths):
                self.rows.append([o,d,1,'','','',''])
                for idx,key in enumerate(edges,1):self.rows.append(['','','',idx,*key])
            if h.sequence_gap and len(self.rows)>2:self.rows[2][3]=5
    @property
    def SaveToArray(self):
        self.host.unbounded+=1;raise AssertionError('UNBOUNDED_EXPORT_FORBIDDEN')

class Lists:
    def __init__(self,host):self.host=host
    def CreatePrTPathList(self):return ListObj(self.host,'parent')
    def CreatePrTPathLinkList(self):return ListObj(self.host,'geometry')

class FakeVisum(Guarded):
    def __init__(self,folder):
        super().__init__(self);folder.mkdir(parents=True,exist_ok=True)
        self.origin='SYNTHETIC_TEST_FIXTURE_NOT_NATIVE_VISUM'
        self.writes=[];self.calls=[];self.unbounded=0;self.counters=Counter();self.list_counts=Counter();self.failures={}
        self.bad_signature=False;self.bad_width=False;self.parent_empty=False;self.repeat_pages=False
        self.matrix_drift=False;self.path_drift=False;self.path_distribution_wrong=False
        self.same_mode_geometry_mismatch=False;self.sequence_gap=False
        self.source=folder/'R1_2025_SYNTHETIC.ver';self.source.write_bytes(b'SYNTHETIC_NOT_A_VISUM_VERSION')
        self.IO=SimpleNamespace(CurrentVersionFile=str(self.source))
        self.Procedures=Guarded(self)
        idx,_=mapping(ROOT/'data/audited/STATION_MAPPING.csv')
        by={}
        for key,station in idx.items():by.setdefault(station,[]).append(key)
        edges=set(idx);self.routes={}
        # Bridges below create a controlled test fixture ONLY, not production routing.
        for m,sign in [('C',0),('C_NOT',1)]:
            s1=sorted(by[2])[sign];s2=sorted(by[4])[sign];s3=sorted(by[7])[sign]
            b12=(70001+sign*10,s1[2],s2[1]);b23=(70002+sign*10,s2[2],s3[1])
            edges.update((b12,b23))
            self.routes[m]=[[s1,b12,s2],[s2,b23,s3]]
        rows=[{'NO':key[0],'FROMNODENO':key[1],'TONODENO':key[2],'TSYSSET':'C,C_noT,LNV,NV'} for key in sorted(edges)]
        expected=parent_module('r1_15a2_two_mode_v238').EXPECTED_MODE_DSEGS
        self.dsegs={};order=0
        for mode,codes in sorted(expected.items()):
            for normalized in sorted(codes):
                code=normalized.replace('_NOT','_noT')
                self.dsegs[code]=DSeg(self,code,'C_noT' if mode=='C_NOT' else 'C',order);order+=1
        self.Net=SimpleNamespace(Zones=Collection(self,[{'NO':10},{'NO':20},{'NO':30}],'Zones'),
            Links=Collection(self,rows,'Links'),DemandSegments=Collection(self,[{'CODE':c} for c in self.dsegs],'DSegs'))
        self.Workbench=SimpleNamespace(Lists=Lists(self))
    def touch(self,label):
        self.counters[label]+=1
        if label in self.failures:
            remaining,kind=self.failures[label]
            if remaining>0:
                self.failures[label]=(remaining-1,kind)
                raise kind()
