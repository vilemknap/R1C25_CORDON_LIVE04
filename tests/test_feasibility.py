import numpy as np
import pytest
from cordon2025.common import parent_core,ContractError
from cordon2025.feasibility import ActuatorBasis,evaluate_realizability,parent_projection,finecdf_availability
from cordon2025.optimizer import solve
from test_optimizer import example,cfg


def basis_for(inc):
    # Exact synthetic first-order marginal actuator map, not an assumed Visum TD law.
    M=100*np.array([[1,0,1,0],[1,0,0,1],[0,1,1,0],[0,1,0,1]],float)
    rr,cc=np.nonzero(M);c=parent_core()
    return ActuatorBasis(c.SparseOperator(rr,cc,M[rr,cc],4,4),
        [(m['dseg_code'],m['origin'],m['destination']) for m in inc.variables],
        [{'type':'TG_PARAMETER','family':'WORK','allowed':True,'parameter_id':str(i)} for i in range(4)],
        np.full(4,-.3),np.full(4,.3),{'basis_kind':'EXACT_SYNTHETIC_LINEAR','state_hash':'synthetic','source_sha256':'synthetic_definition'})

@pytest.mark.parametrize('sign',[1,-1])
def test_opposing_cycle_has_zero_marginal_error_but_cannot_be_realized(sign):
    cycle=sign*np.array([20,-20,-20,20.])
    inc=example(matrix=np.eye(4)*100,targets=100+cycle)
    s=solve(inc,cfg(ridge=0,l1=0));assert s.report['objective_final']<1e-12
    p=parent_projection(inc,s,cfg());assert p['marginal_projection_weighted_rmse']<1e-8
    assert len(p['projection_rows'])==0
    r=evaluate_realizability(inc,s,basis_for(inc))
    assert r['status']=='INFEASIBLE_TG_TD'
    assert r['full_od_rmse']==pytest.approx(20,abs=1e-5)
    assert r['apply_permitted'] is False

def test_synthetic_feasible_basis():
    inc=example(matrix=np.eye(4)*100,targets=[110,110,95,95])
    s=solve(inc,cfg(ridge=0,l1=0));r=evaluate_realizability(inc,s,basis_for(inc))
    assert r['status']=='SYNTHETIC_FEASIBLE_TG_TD' and r['full_od_rmse']<1e-5

def test_missing_basis_is_unknown_not_feasible():
    inc=example();s=solve(inc,cfg());r=evaluate_realizability(inc,s)
    assert r['status']=='TG_TD_REALIZATION_NOT_VERIFIED' and r['residual'] is None

def test_real_linearized_failure_not_claimed_global():
    inc=example(matrix=np.eye(4)*100,targets=[120,80,80,120]);s=solve(inc,cfg(ridge=0,l1=0))
    b=basis_for(inc);b.evidence['basis_kind']='AUDITED_LOCAL_JACOBIAN'
    r=evaluate_realizability(inc,s,b)
    assert r['status']=='INFEASIBLE_LOCAL_TG_TD_LINEARIZATION' and not r['global_nonlinear_infeasibility_claimed']

def test_illegal_actuator_rejected():
    inc=example(matrix=np.eye(4)*100,targets=[120,80,80,120]);s=solve(inc,cfg())
    b=basis_for(inc);b.column_meta[0]['family']='FOREIGN'
    with pytest.raises(ContractError,match='ILLEGAL_ACTUATOR'):evaluate_realizability(inc,s,b)

def test_finecdf_reference_loaded_without_execution():
    r=finecdf_availability();assert r['status']=='HASH_LOCKED_REFERENCE_IMPORT_PASS'
    assert r['native_td_run'] is False
