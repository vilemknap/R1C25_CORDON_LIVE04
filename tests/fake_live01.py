"""681-zone, 12+2-DSeg synthetic COM host. Never native PTV evidence."""
from types import SimpleNamespace
import numpy as np
from fake_visum_startup import FakeVisum,Guarded,Collection,Matrix,ListObj,Lists,DSeg
from cordon2025.common import ROOT,read_json,parent_module,parent_core
from cordon2025.authority import mapping

class Attr(Guarded):
    def __init__(self,h,values):super().__init__(h);self.values=values
    def AttValue(self,name):
        self.host.touch('AttValue:'+name)
        if name in self.values:return self.values[name]
        raise AttributeError(name)
class All(Guarded):
    def __init__(self,h,items):super().__init__(h);self.items=items
    @property
    def GetAll(self):return self.items
    @property
    def Count(self):return len(self.items)
class MatrixCollection(All):
    def ItemByKey(self,no):return next(x for x in self.items if x.no==no)
class GenParams(Attr):
    def TripGenerationDStratParameters(self,code):return self.strata[code]
class TDParams(Attr):
    def TripDistributionDStratParameters(self,code):return self.strata[code]
class FullList(ListObj):
    def SetObjects(self,origin,code,routefilter):
        assert (origin,routefilter)==(0,0)
        self.code=code;h=self.host;h.touch('SetObjects');h.list_counts[(self.kind,code)]+=1
        ds=h.dsegs[code]
        if self.kind=='parent':
            self.rows=[[o,d,1,float(ds.ODMatrix.values[h.axis[o],h.axis[d]])] for o,d in h.path_keys]
            if h.path_drift and h.list_counts[(self.kind,code)]>=3:self.rows[0][3]+=1;self.rows[1][3]-=1
        else:self.rows=h.geometry_rows[parent_core().norm_code(ds.mode)]
class FullLists(Lists):
    def CreatePrTPathList(self):return FullList(self.host,'parent')
    def CreatePrTPathLinkList(self):return FullList(self.host,'geometry')

class Live01Visum(FakeVisum):
    def __init__(self,folder):
        super().__init__(folder);self.origin='MOCK_LIVE01_681_ZONES_NOT_NATIVE'
        zones=[10*i+5 for i in range(681)];self.axis={z:i for i,z in enumerate(zones)}
        cfg=read_json(ROOT/'provenance/live01/TG_DEPENDENCY_CONTRACT_FROM_DONOR.json')
        zr=[]
        for i,z in enumerate(zones):
            r={k:1. for k in cfg['required_zone_attributes']};r.update(NO=z,NOT_ZAHR=1. if i<600 else 0.,ZAHR_SUSED=1. if i<650 else 0.,POP_ZP=1000.,AV_INCOME=2700.,NUM_PM_SMEAR=100.,ADD_SALARY=.5)
            zr.append(r)
        self.Net.Zones=Collection(self,zr,'Zones')
        self.Net.Zones.Attributes=All(self,[SimpleNamespace(ID=k,ValueType=int(v)) for k,v in cfg['expected_zone_attribute_types'].items()])
        stations,_=mapping(ROOT/'data/audited/STATION_MAPPING.csv');by={}
        for key,s in stations.items():by.setdefault(s,[]).append(key)
        edge_rows={k:{'NO':k[0],'FROMNODENO':k[1],'TONODENO':k[2],'TSYSSET':'C,LNV,NV' if s in (1,3,15,16) else 'C,C_noT,LNV,NV'} for k,s in stations.items()}
        self.path_keys=[(zones[a-1],zones[b-1]) for a in range(1,17) for b in range(1,17) if a!=b]
        self.geometry_rows={}
        pairs=[(a,b) for a in range(1,17) for b in range(1,17) if a!=b]
        for mi,mode in enumerate(('C','C_NOT')):
            data=[]
            for n,((o,d),(a,b)) in enumerate(zip(self.path_keys,pairs)):
                data.append([o,d,1,'','','',''])
                if mode=='C_NOT' and (a in (1,3,15,16) or b in (1,3,15,16)):continue
                x=sorted(by[a])[mi];y=sorted(by[b])[mi]
                bridge=(800000+mi*1000+n,x[2],y[1])
                edge_rows[bridge]={'NO':bridge[0],'FROMNODENO':bridge[1],'TONODENO':bridge[2],'TSYSSET':'C,C_noT,LNV,NV'}
                for j,k in enumerate((x,bridge,y),1):data.append(['','','',j,*k])
            self.geometry_rows[mode]=data
        self.Net.Links=Collection(self,list(edge_rows.values()),'Links')
        bindings=read_json(ROOT/'provenance/live01/CORDON_LIVE_DONOR_CONTRACT.json')['matrices']['assignment_od_by_normalized_dseg']
        for ix,(code,ds) in enumerate(self.dsegs.items()):
            arr=np.zeros((681,681))
            for n,(o,d) in enumerate(self.path_keys):arr[self.axis[o],self.axis[d]]=2.+ix*.1+(n%5)*.01
            ds.ODMatrix=Matrix(self,bindings[parent_core().norm_code(code)],arr)
        for n,code in enumerate(('LNV','NV')):
            ds=DSeg(self,code,code,n);ds.ODMatrix=Matrix(self,9501+n,np.zeros((681,681)));self.dsegs[code]=ds
        self.Net.DemandSegments=Collection(self,[{'CODE':c} for c in self.dsegs],'DSegs')
        mats=[ds.ODMatrix for ds in self.dsegs.values()]
        mats += [Matrix(self,no,np.zeros((681,681))) for no in list(range(9101,9118))+[9001,9697]]
        self.Net.Matrices=MatrixCollection(self,mats)
        gen=GenParams(self,{'DSTRATSET':','.join(cfg['required_dstrata'])});gen.strata={}
        for code,spec in cfg['dstrata'].items():
            v={}
            for prefix,field in [('production','PRODUCTIONFUNCTION'),('attraction','ATTRACTIONFUNCTION')]:
                text='['+spec[prefix+'_outer_attribute']+']'
                if spec.get(prefix+'_additive_attribute'):text+='+['+spec[prefix+'_additive_attribute']+']'
                v[field]=text
            gen.strata[code]=Attr(self,v)
        regs=read_json(ROOT/'provenance/live01/TD_COMPONENT_REGISTRY_FROM_DONOR.json')
        td=TDParams(self,{'DSTRATSET':','.join(v['dstrat_code'] for v in regs.values())});td.strata={}
        for code in [v['dstrat_code'] for v in regs.values()]+['4_FOREIGN']:
            td.strata[code]=Attr(self,{})
            td.strata[code].GravitationParameters=Attr(self,{'PARA_A':1.,'PARA_B':.2,'PARA_C':-.1})
        ops=[Attr(self,{'OPERATIONTYPE':0,'ACTIVE':True,'NAME':'','COMMENT':''}) for _ in range(20)]
        ops[4].values['OPERATIONTYPE']=45;ops[4].TripGenerationParameters=gen
        ops[5].values['OPERATIONTYPE']=46;ops[5].TripDistributionParameters=td
        script=folder/'20B_synthetic.py';script.write_text('# Synthetic script reference, never executed\n')
        ops[10].values.update(OPERATIONTYPE=1000,COMMENT='20B',SCRIPTFILE=str(script))
        scope=parent_module('r1_15a2_assignment_authority_v239').EXPECTED
        for pos,codes in scope.items():
            ops[pos-1].values['OPERATIONTYPE']=101
            ops[pos-1].PrTAssignmentParameters=Attr(self,{'DSEGSET':','.join(sorted(codes)),'MAXGAP':.005})
        self.Procedures=SimpleNamespace(Operations=All(self,ops))
        self.Workbench.Lists=FullLists(self)
