"""Deterministic end-to-end examples, all synthetic, including a real SQLite schema."""
from pathlib import Path
from dataclasses import replace
import copy
import numpy as np
from .common import read_config, write_json, write_csv, canonical_hash, parent_core
from .aggressive_policy import effective_config, META, DESIGN_KEYS
from .aggressive import propose, incidence_state_hash, td_trial_plan
from .optimizer import solve
from .demos import algebra_example, exact_synthetic_basis
from .budget import SharedBudget
from .fixtures import create_cache
from .incidence import build_from_snapshot, aggregate_observations
from .feasibility import ActuatorBasis, evaluate_realizability


def synthetic_basis(inc, matrix=None, *, step_type='TG_PARAMETER', upper=.30):
    if matrix is None:
        old=exact_synthetic_basis(inc)
        old.evidence['state_hash']=incidence_state_hash(inc)
        old.column_meta=[dict(m,step_kind='ADD_LOG') for m in old.column_meta]
        return old
    M=np.asarray(matrix,float);rr,cc=np.nonzero(M)
    return ActuatorBasis(parent_core().SparseOperator(rr,cc,M[rr,cc],*M.shape),
        [(m['dseg_code'],m['origin'],m['destination']) for m in inc.variables],
        [{'type':step_type,'step_kind':'ADD_LOG','family':'WORK','allowed':True,'parameter_id':f'SYNTHETIC_{j}'} for j in range(M.shape[1])],
        np.full(M.shape[1],-upper),np.full(M.shape[1],upper),
        {'basis_kind':'EXACT_SYNTHETIC_LINEAR','state_hash':incidence_state_hash(inc),
         'source_sha256':canonical_hash(M.tolist()),'origin':'SYNTHETIC_NOT_VISUM_TD'})


def run_demo(folder, config):
    folder=Path(folder);standard=read_config();cfg=effective_config(config)
    # Same input, targets, CAL/VALID split, ridge and C17 policy for both policies.
    inc=algebra_example([[100,0],[0,100],[40,60]],[140,70,999],base=[120,110,115])
    inc.rows[2]['role']='VALIDATION'
    base=solve(inc,standard);agg=propose(inc,cfg)
    base.save(folder/'STANDARD',inc);agg.save(folder/'AGGRESSIVE',inc)
    comparison={'standard_objective':base.report['objective_final'],
        'aggressive_objective':agg.solution.report['objective_final'],
        'standard_relative_changes':base.x.tolist(),'aggressive_relative_changes':agg.solution.x.tolist(),
        'standard_prediction':base.prediction.tolist(),'aggressive_prediction':agg.solution.prediction.tolist(),
        'fixed_contribution':inc.fixed.tolist(),'validation_used_for_optimization':False,
        'stage':cfg[META]['stage']['name'],'origin':'SYNTHETIC_TEST_FIXTURE'}
    write_json(folder/'STANDARD_VS_AGGRESSIVE.json',comparison)
    # Actual cache reader and both historical incidence hypotheses, no own routing.
    links=[(101,1,2),(102,2,3),(103,3,4)]
    cvol={s:10.+i for i,s in enumerate(cfg['selected_dsegs']) if not s.endswith('_NOT')}
    nvol={s:7.+i for i,s in enumerate(cfg['selected_dsegs']) if s.endswith('_NOT')}
    paths=[('C',10,20,1,links[:2],cvol),('C',10,20,2,links,{s:v*.5 for s,v in cvol.items()}),
           ('C',20,10,1,[(l,t,f) for l,f,t in links[:2][::-1]],cvol),
           ('C_NOT',10,20,1,links[1:],nvol)]
    station_map,evidence=create_cache(folder/'SYNTHETIC_PATH_STORE.sqlite',paths,station_count=16)
    raw_cfg=copy.deepcopy(cfg);raw_cfg.pop(META)
    for key in DESIGN_KEYS:raw_cfg.pop(key,None)
    raw_cfg['actuatable_zones']=[10,20]
    cache_cfg=effective_config(raw_cfg)
    write_json(folder/'SYNTHETIC_CACHE_CONFIG.json',cache_cfg)
    write_json(folder/'SYNTHETIC_CACHE_EVIDENCE.json',evidence)
    variants=build_from_snapshot(folder/'SYNTHETIC_PATH_STORE.sqlite',station_map,cache_cfg,evidence,hits_output=folder/'STATION_HITS.csv')
    summaries=[]
    for method,directed in variants.items():
        target_values=directed.model+directed.operator.forward(np.full(len(directed.variables),.25))
        targets={(r['origin_station'],r['destination_station']):float(v) for r,v in zip(directed.rows,target_values)}
        holdout={tuple(sorted(p)) for p in cfg['validation_unordered_pairs']}
        roles={(a,b):('VALIDATION' if (a,b) in holdout else 'CALIBRATION') for a in range(1,17) for b in range(a+1,17)}
        aggregated=aggregate_observations(directed,targets,roles=roles)
        result=propose(aggregated,cache_cfg);aggregated.save(folder/'CACHE'/method);result.save(folder/'CACHE'/method,aggregated)
        summaries.append({'method':method,'status':result.report['status'],'selected_scale':result.report['selected_scale'],
            'objective_before':result.report['profiled_baseline_objective'],'objective_after':result.report['selected_objective']})
    # Counterexamples: marginal equality must not masquerade as full OD feasibility.
    cases=[]
    for label,d in [('POSITIVE_CYCLE',[20.,-20.,-20.,20.]),('NEGATIVE_CYCLE',[-20.,20.,20.,-20.]),('FEASIBLE_CONTROL',[8.,8.,-4.,-4.])]:
        example=algebra_example(np.eye(4)*100,100+np.array(d))
        basis=synthetic_basis(example);result=propose(example,cfg,basis=basis)
        result.save(folder/'REALIZABILITY'/label,example)
        feasibility=evaluate_realizability(example,result.raw_solution,basis)
        cases.append({'case':label,'status':result.report['status'],'selected_scale':result.report['selected_scale'],
                      'undamped_full_od_status':feasibility['status'],'undamped_full_od_rmse':feasibility['full_od_rmse']})
    # Limited actuator: full OD proposal rejected; smaller positive step permitted.
    small=algebra_example([[100]],[130]);limited=synthetic_basis(small,[[100]],upper=.05)
    damped=propose(small,cfg,basis=limited);damped.save(folder/'BOUNDED_BACKTRACK',small)
    # C17 cannot create a fake improvement when no mutable demand exists.
    fixed=algebra_example(np.zeros((2,0)),[100,100],base=[140,150])
    budget=SharedBudget([(1,2),(1,3)],[1,2,3],np.full(3,10.),30.,'BOUNDED_SCENARIO',{'origin':'SYNTHETIC'},True)
    credit=propose(fixed,cfg,budget);credit.save(folder/'NO_OP_C17',fixed)
    tdinc=algebra_example(np.eye(2)*100,[130,130]);tdbasis=synthetic_basis(tdinc,[[100],[100]],step_type='TD_PARAMETER')
    tdplan=td_trial_plan(tdinc,cfg,tdbasis,[.2]);write_json(folder/'TD_PARAMETER_BACKTRACK_PLAN.json',tdplan)
    expected_scale=max(s for s in cfg['generation_backtracking_scales'] if abs(damped.raw_solution.x[0]*s)<=.05+1e-9)
    ok=(agg.report['guidance_solver_converged'] and all(s['status']!='OFFLINE_AGGRESSIVE_SOLVER_NOT_CONVERGED' for s in summaries)
        and all(c['selected_scale']==0 for c in cases[:2]) and cases[2]['selected_scale']>0
        and damped.report['selected_scale']==expected_scale and credit.report['selected_scale']==0 and len(tdplan['trials'])==7)
    report={'status':'SYNTHETIC_AGGRESSIVE_DEMO_PASS' if ok else 'SYNTHETIC_AGGRESSIVE_DEMO_NOT_CONVERGED',
            'scope':'SYNTHETIC_ONLY','comparison':comparison,'cache_variants':summaries,
            'realizability_cases':cases,'bounded_backtrack_selected_scale':damped.report['selected_scale'],
            'c17_no_op_status':credit.report['status'],'td_parameter_trial_count':len(tdplan['trials']),
            'apply_permitted':False,'production_ready':False,'live_visum_tested':False}
    write_json(folder/'AGGRESSIVE_DEMO_SUMMARY.json',report)
    return report
