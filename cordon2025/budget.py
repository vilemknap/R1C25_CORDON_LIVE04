"""C17 accounting and a deliberately non-production bounded relaxation.

C17 does not identify a second physical endpoint. The optional polytope below
spends TOLERANCE CREDITS, not attributed vehicles. An increment draws one credit
from each endpoint's single pooled account; row/column copies are never counted
as independent accounts. No claim of a physical imputation follows.
"""
from dataclasses import dataclass
from pathlib import Path
import numpy as np
from .common import require,finite,read_csv,sha256

@dataclass
class SharedBudget:
    pairs: list
    station_ids: list
    station_caps: np.ndarray
    global_cap: float
    policy: str
    provenance: dict
    scenario_authorized: bool = False

    def __post_init__(self):
        require(self.policy in ('UNAPPROVED','DISABLED','BOUNDED_SCENARIO'),'INVALID_C17_POLICY')
        require(len(set(self.station_ids))==len(self.station_ids),'DUPLICATE_C17_STATION')
        self.station_caps=np.asarray(self.station_caps,dtype=float)
        require(self.station_caps.shape==(len(self.station_ids),),'C17_CAP_SHAPE')
        require(np.all(np.isfinite(self.station_caps)) and np.all(self.station_caps>=0),'INVALID_C17_CAPS')
        require(np.isfinite(self.global_cap) and 0<=self.global_cap<=self.station_caps.sum()+1e-8,'INVALID_GLOBAL_C17_CAP')
        require(len(set(self.pairs))==len(self.pairs),'DUPLICATE_C17_PAIR')
        sid={v:i for i,v in enumerate(self.station_ids)}
        matrix=np.zeros((len(sid)+1,len(self.pairs)))
        for j,(a,b) in enumerate(self.pairs):
            require(a in sid and b in sid and a!=b,'C17_PAIR_ENDPOINT_INVALID')
            matrix[sid[a],j]=1;matrix[sid[b],j]=1
            matrix[-1,j]=2   # SAME station credits, not an independent extra budget.
        self.constraint_matrix=matrix
        self.limits=np.r_[self.station_caps,self.global_cap]
        require(self.policy!='BOUNDED_SCENARIO' or self.scenario_authorized is True,'C17_SCENARIO_OPT_IN_REQUIRED')

    @property
    def enabled(self):
        return self.policy=='BOUNDED_SCENARIO' and self.scenario_authorized

    def project(self, vector, tolerance=1e-10, max_cycles=20000):
        """Euclidean projection by Dykstra onto nonnegative shared-cap polytope."""
        require(np.isfinite(tolerance) and tolerance>0 and max_cycles>=1,'INVALID_PROJECTION_TOLERANCE')
        x=np.array(vector,dtype=float,copy=True)
        require(x.shape==(len(self.pairs),) and np.all(np.isfinite(x)),'C17_VECTOR_INVALID')
        if not self.enabled:return np.zeros_like(x)
        # Each set carries its correction; sequential clipping without corrections
        # is NOT a Euclidean projection and is intentionally not used here.
        correction=np.zeros((len(self.limits)+1,len(x)))
        norms=np.sum(self.constraint_matrix**2,axis=1)
        for _ in range(max_cycles):
            old=x.copy(); old_correction=correction.copy()
            y=x+correction[0];x=np.maximum(y,0);correction[0]=y-x
            for i,(a,b,norm) in enumerate(zip(self.constraint_matrix,self.limits,norms),1):
                y=x+correction[i]
                x=y-(max(0.,float(a@y-b))/norm)*a if norm>0 else y
                correction[i]=y-x
            violation=max(0.,float(np.max(self.constraint_matrix@x-self.limits,initial=0)),float(np.max(-x,initial=0)))
            if (np.max(np.abs(x-old),initial=0)<=tolerance and violation<=tolerance
                    and np.max(np.abs(correction-old_correction),initial=0)<=tolerance):
                x=np.maximum(x,0)
                used=self.constraint_matrix@x
                require(np.max(used-self.limits,initial=0)<=10*tolerance,'C17_PROJECTION_NOT_FEASIBLE')
                # Remove only the bounded numerical overdraw at termination.
                # Unlike relaxing the ledger, this cannot create extra C17 credit.
                if np.any(used>self.limits):
                    ratio=np.min(self.limits[used>0]/used[used>0],initial=1.)
                    x*=max(0.,float(ratio)*(1.-4.*np.finfo(float).eps))
                return x
        raise ValueError('C17_PROJECTION_DID_NOT_CONVERGE')

    def ledger(self, allocated):
        u=np.asarray(allocated,dtype=float)
        require(u.shape==(len(self.pairs),) and np.all(np.isfinite(u)) and np.min(u,initial=0)>=-1e-8,'INVALID_C17_ALLOCATION')
        require(self.enabled or np.max(np.abs(u),initial=0)<=1e-10,'C17_ALLOCATION_WHEN_DISABLED')
        used=self.constraint_matrix@u
        require(np.max(used-self.limits,initial=0)<=1e-7,'C17_BUDGET_OVERDRAWN')
        return {'policy':self.policy,'physical_pair_allocation':'PRODUCTION_DISABLED',
            'accounting_unit':'POOLED_STATION_RPDI_TOLERANCE_CREDITS_NOT_IMPUTED_VEHICLES',
            'pair_relaxation_sum':float(u.sum()),'global_credits_available':float(self.global_cap),
            'global_credits_consumed':float(used[-1]),'global_credits_remaining':max(0.,float(self.global_cap-used[-1])),
            'station_accounts':[{'station_id':s,'available':float(b),'consumed':float(v),'remaining':max(0.,float(b-v))} for s,b,v in zip(self.station_ids,self.station_caps,used[:-1])],
            'source':self.provenance,'apply_permitted':False}

    def subset(self, indices):
        return SharedBudget([self.pairs[i] for i in indices],self.station_ids,self.station_caps.copy(),self.global_cap,self.policy,self.provenance,self.scenario_authorized)

def from_audit_csv(path, pairs, *, category='OA', policy='UNAPPROVED', scenario_authorized=False, eligible_fraction=1.):
    require(category=='OA','V1_C17_OA_ONLY')
    require(np.isfinite(eligible_fraction) and 0<=eligible_fraction<=1,'C17_ELIGIBLE_FRACTION_INVALID')
    accounts={}
    for r in read_csv(path):
        if r['category']!=category:continue
        s=int(r['station_id']);require(s not in accounts,'DUPLICATE_C17_STATION')
        require(r.get('basis')=='RPDI' and int(r.get('survey_year',0))==2026,'C17_TIME_BASIS_INVALID')
        a=finite(r.get('D3_station_to_C17'),'D3_row');b=finite(r.get('D3_C17_to_station'),'D3_column')
        require(abs(a-b)<1e-8,'C17_SYMMETRY_SOURCE_MISMATCH')
        pre_a=finite(r.get('D2_pre_row_to_C17'),'D2_pre_row');pre_b=finite(r.get('D2_pre_C17_to_column'),'D2_pre_col')
        require(r.get('D2_sha256') and r.get('D3_sha256'),'C17_PROVENANCE_MISSING')
        accounts[s]=a*eligible_fraction
    require(set(accounts)==set(range(1,17)),'C17_STATION_COVERAGE_INCOMPLETE')
    ids=sorted(accounts);caps=np.array([accounts[i] for i in ids])
    return SharedBudget(list(pairs),ids,caps,float(caps.sum()),policy,
        {'audit_sha256':sha256(path),'category':category,'basis':'RPDI_2026','canonicalization':'ONE_SYMMETRIC_MARGIN_ONLY','eligible_fraction':eligible_fraction,'physical_eligibility_proven':False},scenario_authorized)
