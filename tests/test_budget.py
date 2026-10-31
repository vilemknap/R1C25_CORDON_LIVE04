import numpy as np
import pytest
from cordon2025.common import ROOT,ContractError
from cordon2025.budget import SharedBudget,from_audit_csv

def make(pairs=((1,2),(1,3),(2,1)),caps=(10.,8.,9.),policy='BOUNDED_SCENARIO'):
    return SharedBudget(list(pairs),[1,2,3],np.array(caps),sum(caps),policy,{'origin':'SYNTHETIC_TEST_FIXTURE'},policy=='BOUNDED_SCENARIO')

def test_actual_C17_not_double_counted():
    b=from_audit_csv(ROOT/'data/audited/C17_STATION_BUDGETS.csv',[(1,3),(3,1)])
    assert b.global_cap==48645
    assert not b.enabled and b.project([100,100]).tolist()==[0,0]
    assert b.ledger([0,0])['global_credits_consumed']==0

def test_station_shared_across_relations_and_reverse():
    b=make();u=b.project([20,20,20]);ledger=b.ledger(u)
    assert u.sum()<=10+1e-8
    assert ledger['global_credits_consumed']==pytest.approx(2*u.sum())
    assert all(r['consumed']<=r['available']+1e-8 for r in ledger['station_accounts'])
    with pytest.raises(ContractError,match='OVERDRAWN'):b.ledger([8,8,8])

def test_zero_budgets():
    b=make(caps=(0.,0.,0.));assert np.max(abs(b.project([4,5,6])))<1e-8

def test_high_c17_not_forced_to_be_used():
    b=make(caps=(1e9,1e9,1e9));assert np.allclose(b.project([0,0,0]),0)

def test_projection_independent_qp_oracle():
    from scipy.optimize import minimize,LinearConstraint,Bounds
    b=make();v=np.array([12.,3.,15.]);u=b.project(v)
    r=minimize(lambda x:0.5*np.sum((x-v)**2),np.zeros(3),jac=lambda x:x-v,method='SLSQP',
      constraints=[LinearConstraint(b.constraint_matrix,-np.inf,b.limits)],bounds=Bounds(0,np.inf),options={'ftol':1e-10})
    assert r.success and np.allclose(u,r.x,atol=1e-5)

def test_repeated_projection_idempotent():
    b=make();x=b.project([12,-10,15]);assert np.allclose(x,b.project(x),atol=1e-8)

def test_disabled_and_unapproved_no_relaxation():
    for policy in ('UNAPPROVED','DISABLED'):
        b=make(policy=policy);assert np.all(b.project([1,2,3])==0)
        with pytest.raises(ContractError,match='DISABLED'):b.ledger([1,2,3])

def test_scenario_requires_explicit_authorization():
    with pytest.raises(ContractError,match='OPT_IN'):
        SharedBudget([(1,2)],[1,2],np.ones(2),2,'BOUNDED_SCENARIO',{},False)

def test_global_tighter_than_station_caps():
    b=make();b=SharedBudget(b.pairs,b.station_ids,b.station_caps,2.,b.policy,b.provenance,True)
    x=b.project([10,10,10]);assert x.sum()<=1+1e-8

def test_missing_direction_rejected(tmp_path):
    from cordon2025.common import read_csv,write_csv
    rows=read_csv(ROOT/'data/audited/C17_STATION_BUDGETS.csv');rows[0]['D2_pre_C17_to_column']=''
    p=tmp_path/'missing.csv';write_csv(p,rows)
    with pytest.raises(ContractError,match='MISSING_OR_INVALID_NUMBER'):from_audit_csv(p,[(1,2)])

def test_empiric_asymmetry_retained_not_used_twice():
    from cordon2025.common import read_csv
    r=read_csv(ROOT/'data/audited/C17_STATION_BUDGETS.csv')[0]
    assert r['D2_pre_row_to_C17']!=r['D2_pre_C17_to_column']
    b=from_audit_csv(ROOT/'data/audited/C17_STATION_BUDGETS.csv',[(1,2)])
    assert b.station_caps[0]==float(r['D3_station_to_C17'])
