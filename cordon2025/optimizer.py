"""Use the actual 15A2 FISTA solver; extend only the observation and C17 blocks."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import numpy as np
from .common import write_npz
from .io import mkdir
from .common import parent_core,require,write_json,write_csv
from .incidence import validate_roles


def deadzone(x,eps):
    return np.sign(x)*np.maximum(0.,np.abs(x)-eps)

def _subset_operator(op, selected):
    core=parent_core();lookup={int(x):i for i,x in enumerate(selected)}
    mask=np.array([int(x) in lookup for x in op.row_idx],dtype=bool)
    rows=np.array([lookup[int(x)] for x in op.row_idx[mask]],dtype=np.int64)
    return core.SparseOperator(rows,op.col_idx[mask],op.values[mask],len(selected),op.n_cols)

@dataclass
class CordonSolution:
    x: np.ndarray
    delta_q: np.ndarray
    uncertainty: np.ndarray
    prediction: np.ndarray
    report: dict
    problem: object
    guidance: object

    def save(self, folder, inc):
        folder=Path(folder);mkdir(folder)
        write_npz(folder/'SOLUTION.npz',relative_change=self.x,delta_q=self.delta_q,
                            c17_relaxation=self.uncertainty,linearized_prediction=self.prediction)
        write_json(folder/'SOLVER_REPORT.json',self.report)
        write_csv(folder/'RELATION_BEFORE_AFTER.csv',self.report['relations'])
        write_csv(folder/'OD_GUIDANCE.csv',[dict(m,relative_change=float(x),delta_q=float(d),q_guided=float(m['q_current']+d),
            result_kind='SHADOW_OD_GUIDANCE_NOT_VISUM_RESULT') for m,x,d in zip(inc.variables,self.x,self.delta_q)])


def validate_solver_inputs(inc, cfg):
    """Validate external/forged inputs before invoking the unchanged parent FISTA."""
    for name, default in (('solver_max_iter',6000),('solver_check_every',10),
                          ('power_iterations',50),('block_max_iter',100)):
        value = cfg.get(name, default)
        try:
            valid = not isinstance(value, (bool, np.bool_)) and np.isfinite(float(value)) and float(value).is_integer() and 1 <= float(value) <= 10000000
        except (TypeError, ValueError, OverflowError):
            valid = False
        require(valid, 'INVALID_SOLVER_SETTING:' + name)
    value = cfg.get('solver_tolerance',1e-13)
    try:
        valid = not isinstance(value, (bool, np.bool_)) and np.isfinite(float(value)) and float(value) > 0
    except (TypeError, ValueError, OverflowError):
        valid = False
    require(valid, 'INVALID_SOLVER_SETTING:solver_tolerance')
    from .limits import numerical
    numeric=numerical(cfg)
    nr, nc = len(inc.rows), len(inc.variables)
    for name, size in (('model',nr),('mutable',nr),('fixed',nr),('q_current',nc)):
        values = np.asarray(getattr(inc, name))
        require(values.shape == (size,) and np.all(np.isfinite(values)) and np.all(values >= -1e-8), 'INVALID_INCIDENCE:' + name)
    require(np.all(inc.q_current > 0), 'INVALID_INCIDENCE:positive_OD_required')
    op = inc.operator
    require(op.n_rows == nr and op.n_cols == nc, 'INVALID_INCIDENCE:operator_shape')
    require(op.row_idx.ndim == op.col_idx.ndim == op.values.ndim == 1 and len(op.row_idx) == len(op.col_idx) == len(op.values), 'INVALID_INCIDENCE:sparse_shape')
    require(np.all(np.isfinite(op.values)) and np.all(op.values >= 0), 'INVALID_INCIDENCE:operator_values')
    for idx, size in ((op.row_idx,nr),(op.col_idx,nc)):
        require(np.issubdtype(idx.dtype, np.integer) and np.all(idx >= 0) and np.all(idx < size), 'INVALID_INCIDENCE:sparse_index')
    require(np.allclose(inc.fixed + inc.mutable, inc.model, atol=numeric['internal_sum_atol'],rtol=numeric['internal_sum_rtol']), 'INVALID_INCIDENCE:fixed_mutable_parity')
    require(np.allclose(op.forward(np.ones(nc)), inc.mutable, atol=numeric['internal_sum_atol'],rtol=numeric['internal_sum_rtol']), 'INVALID_INCIDENCE:operator_parity')


def build_problem(inc,cfg):
    core=parent_core();require(cfg.get('apply') is False,'V1_APPLY_FORBIDDEN')
    validate_solver_inputs(inc,cfg)
    validate_roles(inc.rows)
    selected=np.array([i for i,r in enumerate(inc.rows) if r['role']=='CALIBRATION'],dtype=int)
    require(selected.size>0,'NO_CALIBRATION_OBSERVATIONS')
    op=_subset_operator(inc.operator,selected)
    y=np.array([inc.rows[i]['observed'] for i in selected],dtype=float)
    require(np.all(np.isfinite(y)) and np.all(y>=0),'INVALID_CAL_TARGET')
    base=inc.model[selected]
    # Reference scales remain fixed during all candidate/block updates.
    weights=np.array([float(inc.rows[i].get('weight',1.0)) for i in selected])/np.sqrt(np.maximum(1.,y))
    require(np.all(np.isfinite(weights)) and np.all(weights>0),'INVALID_OBJECTIVE_WEIGHT')
    eps=np.array([float(inc.rows[i].get('epsilon_abs',cfg.get('epsilon_abs',0.))) for i in selected])
    require(np.all(np.isfinite(eps)) and np.all(eps>=0),'INVALID_DEADBAND')
    n=op.n_cols;lo=float(cfg.get('relative_od_lower',-0.15));hi=float(cfg.get('relative_od_upper',0.15))
    ridge=float(cfg.get('ridge',0.1));l1=float(cfg.get('l1',0.001))
    require(np.isfinite(lo) and np.isfinite(hi) and -1<lo<=0<=hi,'INVALID_RELATIVE_OD_BOUNDS')
    require(np.isfinite(ridge) and np.isfinite(l1) and ridge>=0 and l1>=0,'INVALID_REGULARIZATION')
    problem=core.GuidanceProblem(op,y-base,weights,np.full(n,ridge),np.full(n,l1),np.full(n,lo),np.full(n,hi),
        inc.variables,[inc.rows[i] for i in selected],selected,[],{'source':'KORDON_PAIR','mode':'SIGNED','origin':inc.audit['origin']},deadband=eps)
    return problem,selected,y,base,eps


def _kkt_x(problem,x):
    core=parent_core();grad,_=core._smooth_gradient(problem,x)
    L=core.estimate_lipschitz(problem,40)
    z=x-grad/L
    z=np.sign(z)*np.maximum(0.,np.abs(z)-problem.l1_diag/L)
    z=np.clip(z,problem.lower,problem.upper)
    # Scale by L: this is a gradient mapping, not merely a tiny step size.
    return float(np.max(np.abs((x-z)*L),initial=0))


def _optimize_u(residual,weights,eps,budget,start,ridge,tol=1e-9,max_iter=5000,projection_tolerance=1e-11):
    if budget is None or not budget.enabled:return np.zeros_like(residual),0,0.
    L=max(1e-12,float(np.max(weights**2,initial=0))+ridge);u=np.array(start,copy=True)
    for it in range(1,max_iter+1):
        grad=-(weights**2)*deadzone(residual-u,eps)+ridge*u
        nxt=budget.project(u-grad/L,tolerance=projection_tolerance)
        gap=float(np.max(np.abs(nxt-u)*L,initial=0));u=nxt
        if gap<tol:return u,it,gap
    return u,max_iter,gap


def solve(inc,cfg,budget=None,*,allow_unapproved_scenario=False):
    core=parent_core()
    from .limits import numerical
    numeric=numerical(cfg)
    require(allow_unapproved_scenario or inc.audit['origin']=='SYNTHETIC_TEST_FIXTURE',
            'UNAPPROVED_OBSERVATION_SEMANTICS_EXPLICIT_SCENARIO_REQUIRED')
    problem,selected,y,base,eps=build_problem(inc,cfg)
    if budget:
        require(budget.pairs==[(r['origin_station'],r['destination_station']) for r in inc.rows], 'C17_OBSERVATION_ORDER_MISMATCH')
        bcal=budget.subset(selected.tolist())
    else:bcal=None
    ridgeu=float(cfg.get('c17_ridge',0.02));require(np.isfinite(ridgeu) and ridgeu>0,'C17_CONSUMPTION_PENALTY_REQUIRED')
    tol=float(cfg.get('kkt_tolerance',1e-6));require(np.isfinite(tol) and tol>0,'INVALID_KKT_TOLERANCE')
    x=np.zeros(problem.operator.n_cols);u=np.zeros(len(selected));history=[]
    inner_cfg={k:cfg[k] for k in ('solver_max_iter','solver_tolerance','solver_check_every','power_iterations') if k in cfg}
    inner_cfg.setdefault('solver_max_iter',6000);inner_cfg.setdefault('solver_tolerance',1e-13)
    def cost(xx,uu):
        residual=base+problem.operator.forward(xx)-y-uu
        return {'cordon_data_loss':0.5*float(np.sum((problem.row_weight*deadzone(residual,eps))**2)),
          'od_ridge_loss':0.5*float(np.sum(problem.ridge_diag*xx**2)),
          'od_l1_loss':float(np.sum(problem.l1_diag*np.abs(xx))),
          'c17_credit_loss':0.5*ridgeu*float(uu@uu)}
    initial=cost(x,u);previous=sum(initial.values());converged=False;g=None
    maximum=int(cfg.get('block_max_iter',100)) if bcal is not None and bcal.enabled else 1
    require(maximum>=1,'INVALID_BLOCK_MAX_ITER')
    for step in range(1,maximum+1):
        problem.target=y+u-base
        if len(x):
            g=core.solve_guidance(problem,inner_cfg);candidate=np.asarray(g.x)
        else:
            g=core.GuidanceResult(x,np.zeros(len(selected)),base-y-u,previous,previous,0,True,1.,[]);candidate=x
        raw=base+problem.operator.forward(candidate)-y
        unew,uit,ugap=_optimize_u(raw,problem.row_weight,eps,bcal,u,ridgeu,
            tol=numeric['c17_solver_tolerance'],projection_tolerance=numeric['c17_projection_tolerance'])
        objective=cost(candidate,unew);total=sum(objective.values())
        require(np.isfinite(total) and total<=previous+1e-7*max(1.,abs(previous)),'NONMONOTONE_SOLVER_BLOCK')
        x,u=candidate,unew
        problem.target=y+u-base
        gapx=_kkt_x(problem,x) if len(x) else 0.
        # Check BOTH blocks against the same final state, not an old iterate.
        gapu=ugap
        history.append({'block':step,'objective':total,'kkt_x':gapx,'kkt_u':gapu,'u_iterations':uit,'parent_solver_iterations':int(g.iterations)})
        if max(gapx,gapu)<tol:converged=True;break
        previous=total
    fullu=np.zeros(len(inc.rows));fullu[selected]=u
    prediction=inc.model+inc.operator.forward(x)
    require(np.all(np.isfinite(x)) and np.all(x>=problem.lower-1e-10) and np.all(x<=problem.upper+1e-10),'SOLVER_BOUNDS_FAIL')
    breakdown=cost(x,u);rows=[]
    for i,row in enumerate(inc.rows):
        target=row.get('observed');after=float(prediction[i]);unc=float(fullu[i]);before=float(inc.model[i])
        epsilon=float(row.get('epsilon_abs',cfg.get('epsilon_abs',0.)))
        residual=(after-float(target)-unc) if target is not None else None
        flags=[]
        if target is None:flags.append('NO_MEASUREMENT')
        if before>0 and inc.fixed[i]/before>0.8:flags.append('LARGE_FIXED_SHARE')
        if inc.mutable[i]<=0:flags.append('NO_MUTABLE_PATH_SUPPORT')
        if residual is not None and abs(residual)>epsilon+1e-7:flags.append('UNMET_TARGET_OUTSIDE_RELAXATION')
        rows.append({k:row.get(k) for k in ('origin_station','destination_station','observed','role','method','aggregation')} |
           {'before_saved_path_prediction':before,'after_LINEARIZED':after,'fixed_contribution':float(inc.fixed[i]),
            'mutable_before':float(inc.mutable[i]),'c17_scenario_relaxation':unc,'epsilon_abs':epsilon,
            'raw_difference_after':(after-float(target)) if target is not None else None,
            'residual_after_relaxation':residual,'flags':','.join(flags),'actual_assignment_verified':False})
    report={'limit_profile':cfg.get('limit_profile','LEGACY_STRICT'),'numerical_limits':numeric,
        'status':'OFFLINE_SOLVER_PASS' if converged else 'OFFLINE_SOLVER_NOT_CONVERGED',
        'numeric_converged':converged,'origin':inc.audit['origin'],
        'hypothesis':inc.audit.get('method'),'objective_initial':sum(initial.values()),
        'objective_final':sum(breakdown.values()),'initial_breakdown':initial,'final_breakdown':breakdown,
        'history':history,'kkt_x':gapx,'kkt_u':gapu,'relative_bounds':[float(problem.lower.min(initial=0)),float(problem.upper.max(initial=0))],
        'c17':bcal.ledger(u) if bcal else {'policy':'DISABLED','global_credits_consumed':0,'physical_pair_allocation':'PRODUCTION_DISABLED'},
        'relations':rows,'solver_backend':'PARENT_15A2_SOLVE_GUIDANCE_FISTA_PLUS_C17_BLOCK',
        'validation_used_for_optimization':False,'epsilon_is_statistical_interval':False,
        'prediction_kind':'LINEARIZED_SHADOW_OD_NOT_VISUM_RESULT','apply_permitted':False,'production_ready':False,
        'live_visum_tested':False,'uses_supply_actuator':False}
    # Keep the original parent GuidanceResult type for the existing projection API.
    projected=core.GuidanceResult(x,problem.operator.forward(x),base+problem.operator.forward(x)-y-u,
        sum(initial.values()),sum(breakdown.values()),sum(h['parent_solver_iterations'] for h in history),converged,
        float(g.lipschitz),history)
    return CordonSolution(x,x*inc.q_current,fullu,prediction,report,problem,projected)
