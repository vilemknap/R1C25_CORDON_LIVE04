"""Reproducible synthetic demonstrations. They are never evidence of a real run."""
from pathlib import Path
import numpy as np
from .common import parent_core,write_json,canonical_hash
from .fixtures import create_cache,config as fixture_config
from .incidence import Incidence,build_from_snapshot,aggregate_observations
from .optimizer import solve
from .budget import SharedBudget
from .feasibility import ActuatorBasis,evaluate_realizability,parent_projection,finecdf_availability


def algebra_example(matrix,targets,*,base=None):
    core=parent_core();M=np.asarray(matrix,dtype=float);nr,nc=M.shape
    rr,cc=np.nonzero(M);op=core.SparseOperator(rr,cc,M[rr,cc],nr,nc)
    sh=core.SparseOperator(rr,cc,M[rr,cc]/100.,nr,nc)
    variables=[{'variable_index':i,'dseg_code':'NATIVE_CW','family':'WORK','origin':1+i//2,
       'destination':3+i%2,'q_current':100.,'path_count':1} for i in range(nc)]
    pairs=[(1,2),(1,3),(1,4),(2,3),(2,4),(3,4)]
    rows=[{'origin_station':pairs[i][0],'destination_station':pairs[i][1],
       'observed':float(targets[i]),'role':'CALIBRATION','category':'OA','method':'SYNTHETIC_ALGEBRA',
       'aggregation':'BIDIRECTIONAL_SUM','weight':1.0} for i in range(nr)]
    model=np.asarray(base if base is not None else M.sum(axis=1),dtype=float)
    audit={'origin':'SYNTHETIC_TEST_FIXTURE','method':'SYNTHETIC_ALGEBRA',
       'all_od_totals':[{'dseg':m['dseg_code'],'orig':m['origin'],'dest':m['destination'],'volume':100.} for m in variables]}
    return Incidence(rows,variables,variables,np.full(nc,100.),op,sh,model,M.sum(axis=1),model-M.sum(axis=1),audit)


def exact_synthetic_basis(inc):
    M=100*np.array([[1,0,1,0],[1,0,0,1],[0,1,1,0],[0,1,0,1]],float)
    rr,cc=np.nonzero(M);core=parent_core()
    definition={'matrix':M.tolist(),'law':'EXACT_SYNTHETIC_MARGINAL_PARAMETER_MODEL_NOT_VISUM_TD'}
    return ActuatorBasis(core.SparseOperator(rr,cc,M[rr,cc],4,4),
        [(m['dseg_code'],m['origin'],m['destination']) for m in inc.variables],
        [{'type':'TG_PARAMETER','family':'WORK','allowed':True,'parameter_id':'SYNTHETIC_'+str(i)} for i in range(4)],
        np.full(4,-.3),np.full(4,.3),{'basis_kind':'EXACT_SYNTHETIC_LINEAR',
        'state_hash':canonical_hash(inc.variables),'source_sha256':canonical_hash(definition),
        'definition':definition})


def counterexamples(folder,config):
    results=[]
    for name,delta in [('CYCLE_POSITIVE',np.array([20.,-20.,-20.,20.])),
                       ('CYCLE_NEGATIVE',np.array([-20.,20.,20.,-20.])),
                       ('FEASIBLE_CONTROL',np.array([10.,10.,-5.,-5.]))]:
        inc=algebra_example(np.eye(4)*100,100+delta)
        cfg=dict(config,relative_od_lower=-.4,relative_od_upper=.4,ridge=0.,l1=0.,solver_tolerance=1e-15)
        result=solve(inc,cfg);projection=parent_projection(inc,result,cfg)
        feasibility=evaluate_realizability(inc,result,exact_synthetic_basis(inc))
        out=Path(folder)/name;result.save(out,inc)
        write_json(out/'TG_TD_PROJECTION.json',projection)
        write_json(out/'FULL_OD_FEASIBILITY.json',feasibility)
        results.append({'case':name,'shadow_objective_before':result.report['objective_initial'],
          'shadow_objective_after':result.report['objective_final'],
          'marginal_projection_weighted_rmse':projection['marginal_projection_weighted_rmse'],
          'full_od_realization_status':feasibility['status'],'full_od_rmse':feasibility['full_od_rmse'],
          'live_result':False})
    write_json(Path(folder)/'COUNTEREXAMPLE_SUMMARY.json',results)
    return results


def synthetic_demo(folder,config):
    folder=Path(folder)
    forward=[(100+i,i,i+1) for i in range(1,5)]
    reverse=[(ln,b,a) for ln,a,b in reversed(forward)]
    cvol={'NATIVE_CW':60.,'NATIVE_CS':20.,'NATIVE_CL':10.,'NATIVE_CF':5.,
          'EXOG_EE_CW':4.,'EXOG_EE_CS':3.,'EXOG_EE_CL':2.,'EXOG_EE_CF':1.}
    nvol={'NATIVE_CW_NOT':40.,'NATIVE_CS_NOT':15.,'EXOG_EE_CW_NOT':5.,'EXOG_EE_CS_NOT':2.}
    paths=[('C',10,20,1,forward[:3],cvol),
           ('C',10,20,2,forward,{c:v*.5 for c,v in cvol.items()}),
           ('C',20,10,1,reverse,{c:v*.8 for c,v in cvol.items()}),
           ('C_NOT',10,20,1,forward[1:3],nvol),
           ('C',11,21,1,forward[2:],{c:v*.6 for c,v in cvol.items()})]
    mapping,evidence=create_cache(folder/'SYNTHETIC_PATH_STORE.sqlite',paths,station_count=16)
    cfg=dict(config,**fixture_config(list(evidence['dseg_totals'])))
    cfg.update(relative_od_lower=-.4,relative_od_upper=.4,solver_tolerance=1e-15,solver_max_iter=20000)
    write_json(folder/'DEMO_CONFIG.json',cfg)
    variants=build_from_snapshot(folder/'SYNTHETIC_PATH_STORE.sqlite',mapping,cfg,evidence,hits_output=folder/'STATION_HITS.csv')
    summaries=[]
    for method,directed in variants.items():
        # Generate targets by a declared synthetic correction on this exact support.
        xtruth=np.array([.10 if i%2==0 else -.08 for i in range(len(directed.variables))])
        synthetic_targets=directed.model+directed.operator.forward(xtruth)
        targets={(r['origin_station'],r['destination_station']):float(v) for r,v in zip(directed.rows,synthetic_targets)}
        roles={(a,b):('VALIDATION' if (a,b)==(1,3) else 'CALIBRATION') for a in range(1,17) for b in range(a+1,17)}
        inc=aggregate_observations(directed,targets,roles=roles)
        solution=solve(inc,cfg);out=folder/method;inc.save(out);solution.save(out,inc)
        projection=parent_projection(inc,solution,cfg)
        write_json(out/'TG_TD_PROJECTION.json',projection)
        write_json(out/'FULL_OD_FEASIBILITY.json',evaluate_realizability(inc,solution))
        write_json(out/'SYNTHETIC_TARGET_ORIGIN.json',{'kind':'GENERATED_FROM_DECLARED_SYNTHETIC_OD_CHANGE','relative_truth':xtruth.tolist(),
            'is_survey_target':False,'used_real_2025_model':False})
        summaries.append({'method':method,'status':solution.report['status'],
            'objective_before':solution.report['objective_initial'],'objective_after':solution.report['objective_final'],
            'kkt_x':solution.report['kkt_x'],'geometry_decoded':inc.audit['metrics']['decoded_geometry'],
            'mutable_od_variables':len(inc.variables),'fixed_volume_sum_over_observations':float(inc.fixed.sum()),
            'realizability':'TG_TD_REALIZATION_NOT_VERIFIED','c17_policy':'DISABLED'})
    # Separate bounded-credit scenario: values and budgets here are synthetic too.
    inc=algebra_example(np.eye(2)*100,[100,100],base=[140,150])
    budget=SharedBudget([(1,2),(1,3)],[1,2,3],np.full(3,10.),30.,'BOUNDED_SCENARIO',{'origin':'SYNTHETIC'},True)
    joint=solve(inc,dict(cfg,relative_od_lower=-.2,relative_od_upper=.2,block_max_iter=200),budget)
    joint.save(folder/'SYNTHETIC_C17_SHARED',inc)
    cases=counterexamples(folder/'REALIZABILITY_CASES',cfg)
    report={'status':'SYNTHETIC_DEMO_PASS' if all(r['status']=='OFFLINE_SOLVER_PASS' for r in summaries) and joint.report['numeric_converged'] else 'SYNTHETIC_DEMO_NOT_CONVERGED',
      'scope':'SYNTHETIC_ONLY','variants':summaries,'c17_objective_before':joint.report['objective_initial'],
      'c17_objective_after':joint.report['objective_final'],'c17_ledger':joint.report['c17'],
      'counterexamples':cases,'finecdf_reference':finecdf_availability(),
      'live_visum_tested':False,'production_ready':False,'apply_permitted':False}
    write_json(folder/'DEMO_SUMMARY.json',report)
    return report
