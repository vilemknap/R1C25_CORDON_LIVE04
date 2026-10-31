"""Existing cordon FISTA -> parent P/A -> exact donor TG design, no live apply."""
from .common import ROOT,require,canonical_hash
from .optimizer import solve,build_problem
from .feasibility import parent_projection,evaluate_realizability
from .budget import from_audit_csv
from .targeting import path_targeting_report
from .live01_config import calculation_config
import numpy as np


def propose_generation(inc,live,state,solver_ladder=None):
    cfg=calculation_config(live,state['actuatable_zones'])
    cfg['actual_network_sha256']=state.get('network_sha256')
    pairs=[(r['origin_station'],r['destination_station']) for r in inc.rows]
    require(len(pairs)==120 and all(r['role']=='CALIBRATION' for r in inc.rows),'LIVE01_OBJECTIVE_MUST_USE_ALL_120')
    budget=from_audit_csv(ROOT/'data/audited/C17_STATION_BUDGETS.csv',pairs,policy=cfg['c17_allocation_policy'])
    solution=solve(inc,cfg,budget,allow_unapproved_scenario=True)
    # LIVE02: optional tolerance ladder. The KKT acceptance criterion itself is
    # unchanged; only more parent FISTA iterations are allowed until it holds.
    ladder=[]
    for step in (solver_ladder or []):
        if solution.report.get('numeric_converged'):break
        trial=dict(cfg,solver_tolerance=float(step['solver_tolerance']),solver_max_iter=int(step['solver_max_iter']))
        solution=solve(inc,trial,budget,allow_unapproved_scenario=True)
        ladder.append({'solver_tolerance':trial['solver_tolerance'],'solver_max_iter':trial['solver_max_iter'],
                       'numeric_converged':solution.report['numeric_converged'],'kkt_x':solution.report['kkt_x']})
    solution.report['solver_tolerance_ladder']=ladder
    require(solution.problem.operator.n_rows==120 and len(solution.problem.objective_rows)==120,
            'LIVE01_INTERNAL_OBJECTIVE_OMISSION')
    projection=parent_projection(inc,solution,cfg,zone_rows=state['zone_rows'])
    design=projection['existing_generation_design'];candidates=design['candidate_rows']
    byzone={r['zone_no']:r for r in state['zone_rows']}
    allowed=set(state['actuatable_zones'])
    attrs=set(('ADD_PROD_W','ADD_ATT_W','ADD_SALARY','ADD_PROD_S','ADD_ATT_S',
               'ZAHR_PROD_WORK','ZAHR_ATR_WORK','ZAHR_PROD_SERV','ZAHR_ATR_SERV'))
    identities=set()
    for r in candidates:
        z,attr=r['zone_no'],r['attr']
        require(z in allowed and attr in attrs,'LIVE01_CANDIDATE_OUTSIDE_ACTUATOR_SCOPE')
        require((z,attr) not in identities,'LIVE01_DUPLICATE_ACTUATOR_CANDIDATE');identities.add((z,attr))
        require(r['current']==byzone[z][attr],'LIVE01_CANDIDATE_NOT_CURRENT_VALUE')
        require(np.isfinite(r['proposed']) and np.isfinite(r['current']),'LIVE01_CANDIDATE_NONFINITE')
        require(r['family'] in ('WORK','SERVICE'),'LIVE01_FROZEN_FAMILY_CHANGE')
    if candidates:status='NONZERO_DONOR_TG_PROPOSAL_NATIVE_EFFECT_NOT_VERIFIED'
    elif not inc.operator.n_cols or not len(inc.operator.values):status='NO_EFFECTIVE_MUTABLE_CORDON_SUPPORT'
    elif np.max(np.abs(solution.x),initial=0)<=1e-12:
        status='NO_OD_STEP_OPTIMAL_WITHIN_CONFIGURED_OBJECTIVE' if solution.report.get('numeric_converged') else 'NO_OD_STEP_REVIEW_SOLVER_STATUS'
    else:status='NO_ACTUATOR_STEP_REVIEW_DONOR_SKIPPED_ROWS'
    report={'schema':'LIVE01_TG_PROPOSAL_V1','status':status,'method':inc.audit['method'],
        'objective_rows':len(solution.problem.objective_rows),'mutable_variables':len(inc.variables),
        'operator_nonzeros':len(inc.operator.values),'candidate_count':len(candidates),
        'candidate_rows':candidates,'projection':projection,'solver_report':solution.report,
        'c17_ledger':budget.ledger(solution.uncertainty),'targeting':path_targeting_report(inc),
        'realizability':evaluate_realizability(inc,solution),'real_visum_verified':False,
        'native_candidate_accepted':False,'apply_permitted':False,
        'current_model_fingerprint':state.get('current_model_fingerprint'),
        'search_stage':cfg['live01_search_stage'],'frozen_segments':sorted(set(cfg['selected_dsegs'])-set(cfg['mutable_dsegs']))}
    report['proposal_sha256']=canonical_hash(report)
    return solution,report
