"""Synthetic 12-segment benchmark host. Never represents a native PTV measurement."""
from collections import Counter
import numpy as np
from fake_visum_startup import FakeVisum,Collection,Matrix,ListObj,Lists
from cordon2025.common import parent_core

class ScaledList(ListObj):
    def SetObjects(self,origin,code,routefilter):
        assert (origin,routefilter)==(0,0)
        self.code=code;h=self.host;h.touch('SetObjects');h.list_counts[(self.kind,code)]+=1
        if self.kind=='parent':
            self.rows=h.parent_rows[code]
        else:
            self.rows=h.geometry_rows[parent_core().norm_code(h.dsegs[code].mode)]

class ScaledLists(Lists):
    def CreatePrTPathList(self):return ScaledList(self.host,'parent')
    def CreatePrTPathLinkList(self):return ScaledList(self.host,'geometry')

class ScaledVisum(FakeVisum):
    def __init__(self,folder,route_count=3000,zone_count=681,tail_length=20):
        super().__init__(folder)
        assert route_count<=zone_count*(zone_count-1)
        self.origin='SYNTHETIC_SCALED_COM_NO_PTV_TIME_CLAIM'
        self.geometry_rows={};self.parent_rows={}
        keys=[]
        for i in range(route_count):
            o=i//(zone_count-1)+1;d=i%(zone_count-1)+1
            if d>=o:d+=1
            keys.append((o,d,1))
        rows=self.Net.Links.rows
        for mi,mode in enumerate(('C','C_NOT')):
            variants=[]
            for vi in (0,1):
                path=list(self.routes[mode][0])
                if vi:path+=self.routes[mode][1][1:]
                last=path[-1][2]
                for j in range(tail_length):
                    end=800000+mi*1000+vi*100+j
                    edge=(900000+mi*1000+vi*100+j,last,end);last=end;path.append(edge)
                    rows.append({'NO':edge[0],'FROMNODENO':edge[1],'TONODENO':edge[2],'TSYSSET':'C,C_noT,LNV,NV'})
                variants.append(path)
            out=[]
            for i,key in enumerate(keys):
                out.append([*key,'','','',''])
                path=[] if i%37==0 else variants[int(i%3==0)]
                for j,edge in enumerate(path,1):out.append(['','','',j,*edge])
            self.geometry_rows[mode]=out
        self.Net.Zones=Collection(self,[{'NO':i+1} for i in range(zone_count)],'Zones')
        for index,(code,ds) in enumerate(self.dsegs.items()):
            m=np.zeros((zone_count,zone_count),dtype=float);parents=[]
            for i,(o,d,p) in enumerate(keys):
                value=0. if i%11==0 else round(.1*(index+1)+.001*(i%7),3)
                m[o-1,d-1]=value;parents.append([o,d,p,value])
            ds.ODMatrix=Matrix(self,8000+index,m);self.parent_rows[code]=parents
        self.Workbench.Lists=ScaledLists(self)
