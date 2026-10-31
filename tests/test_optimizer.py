import copy
import numpy as np
import pytest
from cordon2025.common import parent_core,ContractError
from cordon2025.incidence import Incidence
from cordon2025.optimizer import solve,deadzone
from cordon2025.budget import SharedBudget


def example(matrix=None,base=None,targets=None,roles=None):
    c=parent_core();M=np.asarray(matrix if matrix is not None else [[100,0],[0,100]],dtype=float)
    nr,nc=M.shape;rr,cc=np.nonzero(M)
    op=c.SparseOperator(rr.astype(np.int64),cc.astype(np.int64),M[rr,cc],nr,nc)
    sh=c.SparseOperator(rr.astype(np.int64),cc.astype(np.int64),M[rr,cc]/100,nr,nc)
    meta=[{'variable_index':i,'dseg_code':'NATIVE_CW','family':'WORK','origin':1+i//2,'destination':3+i%2,'q_current':100.,'path_count':1} for i in range(nc)]
    pairs=[(1,2),(1,3),(1,4),(2,3),(2,4),(3,4)]
    base=np.asarray(base if base is not None else M.sum(axis=1),dtype=float)
    targets=targets if targets is not None else [130,80]
    rows=[{'origin_station':pairs[i][0],'destination_station':pairs[i][1],'observed':float(targets[i]),'role':(roles[i] if roles else 'CALIBRATION'),'category':'OA','method':'SYNTHETIC_ALGEBRA','weight':1.0} for i in range(nr)]
    return Incidence(rows,meta,meta,np.full(nc,100.),op,sh,base,M.sum(axis=1),base-M.sum(axis=1),
        {'origin':'SYNTHETIC_TEST_FIXTURE','method':'SYNTHETIC_ALGEBRA','all_od_totals':[{'dseg':m['dseg_code'],'orig':m['origin'],'dest':m['destination'],'volume':m['q_current']} for m in meta]})

def cfg(**kw):
    return {'apply':False,'relative_od_lower':-.4,'relative_od_upper':.4,'ridge':.1,'l1':.001,'epsilon_abs':0.,
            'solver_max_iter':10000,'solver_tolerance':1e-15,'block_max_iter':200,'kkt_tolerance':1e-6,'c17_ridge':.02,**kw}

def test_parent_solver_signed_cordon_loss():
    inc=example();s=solve(inc,cfg())
    assert s.report['numeric_converged']
    # Ridge/L1 have a nonzero optimum even with an exactly solvable target.
    assert s.report['objective_final']<s.report['objective_initial']*.01
    target=np.array([130.,80.]);diff=target-100
    analytic=(100*diff/target-.001*np.sign(diff))/(10000/target+.1)
    assert np.allclose(s.x,analytic,atol=1e-7)
    assert s.x[0]>0 and s.x[1]<0
    assert np.all(s.x>=-.4) and np.all(s.x<=.4)
    assert s.report['apply_permitted'] is False

def test_deadband_no_unnecessary_change():
    inc=example(targets=[103,97]);s=solve(inc,cfg(epsilon_abs=5))
    assert np.allclose(s.x,0) and s.report['objective_final']==0

def test_zero_targets_not_dropped():
    inc=example(targets=[0,80]);s=solve(inc,cfg())
    assert s.x[0]==pytest.approx(-.4)

def test_validation_never_used():
    inc=example(matrix=[[100],[100]],targets=[120,1],roles=['CALIBRATION','VALIDATION'])
    a=solve(inc,cfg());inc.rows[1]['observed']=1e9;inc.rows[1]['weight']=1e15
    b=solve(inc,cfg());assert np.array_equal(a.x,b.x)
    assert b.report['validation_used_for_optimization'] is False

def test_shared_C17_joint_solver_and_independent_oracle():
    from scipy.optimize import minimize,Bounds,LinearConstraint
    inc=example(base=[140,150],targets=[100,100])
    budget=SharedBudget([(1,2),(1,3)],[1,2,3],np.array([10.,10.,10.]),30.,'BOUNDED_SCENARIO',{'origin':'SYNTHETIC'},True)
    config=cfg(relative_od_lower=-.2,relative_od_upper=.2)
    s=solve(inc,config,budget)
    assert s.report['numeric_converged'] and s.report['c17']['global_credits_consumed']<=30+1e-7
    y=np.array([100.,100.]);M=np.diag([100.,100.]);base=inc.model
    def fun(z):
        x,u=z[:2],z[2:];res=base+M@x-y-u
        return .5*np.sum(res**2/y)+.05*x@x+.001*abs(x).sum()+.01*u@u
    C=np.c_[np.zeros((4,2)),budget.constraint_matrix]
    oracle=minimize(fun,np.r_[s.x,s.uncertainty],method='SLSQP',bounds=Bounds([-.2,-.2,0,0],[.2,.2,np.inf,np.inf]),
       constraints=[LinearConstraint(C,-np.inf,budget.limits)],options={'ftol':1e-10,'maxiter':500})
    assert oracle.success
    assert abs(fun(oracle.x)-s.report['objective_final'])<1e-6
    assert s.report['c17']['physical_pair_allocation']=='PRODUCTION_DISABLED'

def test_C17_does_not_explain_deficit_or_touch_validation():
    inc=example(targets=[130,150],roles=['CALIBRATION','VALIDATION'])
    b=SharedBudget([(1,2),(1,3)],[1,2,3],np.full(3,1e6),3e6,'BOUNDED_SCENARIO',{},True)
    s=solve(inc,cfg(),b)
    assert np.allclose(s.uncertainty,0) and s.x[0]>0

def test_no_mutable_support_does_not_fabricate_variables():
    inc=example(matrix=np.zeros((2,0)),base=[100,80],targets=[130,100])
    s=solve(inc,cfg());assert s.x.size==0 and np.array_equal(s.prediction,inc.model)
    assert all('NO_MUTABLE_PATH_SUPPORT' in r['flags'] for r in s.report['relations'])

def test_real_unapproved_requires_explicit_scenario():
    inc=example();inc.audit['origin']='VISUM_SAVED_PATHS'
    with pytest.raises(ContractError,match='UNAPPROVED_OBSERVATION'):solve(inc,cfg())
    s=solve(inc,cfg(),allow_unapproved_scenario=True)
    assert not s.report['production_ready']

def test_apply_forbidden():
    with pytest.raises(ContractError,match='FORBIDDEN'):solve(example(),cfg(apply=True))

def test_budget_order_mismatch():
    b=SharedBudget([(1,3),(1,2)],[1,2,3],np.ones(3),3,'DISABLED',{})
    with pytest.raises(ContractError,match='ORDER_MISMATCH'):solve(example(),cfg(),b)

def test_parent_default_loss_equivalence():
    c=parent_core();inc=example();s=solve(inc,cfg());p=s.problem
    x=np.array([.1,-.15]);p.deadband=None
    exact=.5*np.sum((p.row_weight*(p.operator.forward(x)-p.target))**2)+.5*np.sum(p.ridge_diag*x*x)+np.sum(p.l1_diag*abs(x))
    assert c.guidance_objective(p,x)==pytest.approx(exact)
