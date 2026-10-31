"""Existing 15A2 P/A projection plus full-OD realization residual, without COM."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
from .common import require,parent_core,ROOT


def parent_projection(inc,solution,config,*,zone_rows=None):
    core=parent_core()
    zones=sorted({int(m[k]) for m in inc.projection_base_variables for k in ('origin','destination')})
    cfg=dict(config,guidance_mode='SIGNED',projection_method='MARGINALS')
    result=core.project_guidance_to_add(solution.problem,solution.guidance,zones,cfg,all_variable_meta=inc.projection_base_variables)
    out={'projection_rows':result.rows,'family_summaries':result.family_summaries,
         'marginal_projection_weighted_rmse':result.weighted_rmse,
         'status':'PROJECTION_AVAILABLE_REALIZATION_NOT_VERIFIED',
         'od_realization_error':None,'real_visum_verified':False,'apply_permitted':False}
    # Calling the production design routine is safe only with actual audited zone attributes.
    if zone_rows is not None:
        from r1_15a2_multiblock import design_generation_candidates
        out['existing_generation_design']=design_generation_candidates(result.rows,zone_rows,cfg)
    else:out['existing_generation_design']='ZONE_PARAMETER_AUTHORITY_NOT_SUPPLIED'
    return out


def finecdf_availability():
    parent_core()
    from r1_15a2_finecdf_bridge_v242 import load_reference
    module,path,digest=load_reference(ROOT/'parent')
    return {'status':'HASH_LOCKED_REFERENCE_IMPORT_PASS','reference_sha256':digest,
            'script_id':module.SCRIPT_ID,'native_td_run':False,'availability':'CODE_AVAILABLE_LIVE_PARAMETERS_NOT_SUPPLIED'}

@dataclass
class ActuatorBasis:
    operator: object
    row_keys: list
    column_meta: list
    lower: np.ndarray
    upper: np.ndarray
    evidence: dict


def evaluate_realizability(inc,solution,basis=None,tolerance=None):
    """A supplied full-OD response basis must include collateral and fixed rows.

    Feasibility without a basis is UNKNOWN. Small marginal residuals alone never
    certify an OD pattern. Linearized real-model infeasibility is NOT global
    nonlinear impossibility. Synthetic exact-linear bases can prove that case.
    """
    if basis is None:
        return {'status':'TG_TD_REALIZATION_NOT_VERIFIED','reason':'FULL_OD_ACTUATOR_RESPONSE_NOT_SUPPLIED',
                'residual':None,'apply_permitted':False,'live_verified':False}
    core=parent_core();op=basis.operator
    from .limits import numerical
    numeric=numerical(solution.report)
    tolerance=numeric['feasibility_atol'] if tolerance is None else tolerance
    require(np.isfinite(tolerance) and tolerance>0,'INVALID_FEASIBILITY_TOLERANCE')
    require(np.all(np.isfinite(op.values)),'INVALID_ACTUATOR_RESPONSE')
    require(len(basis.row_keys)==op.n_rows and len(set(basis.row_keys))==op.n_rows,'ACTUATOR_ROW_KEY_MISMATCH')
    require(len(basis.column_meta)==op.n_cols,'ACTUATOR_COLUMN_META_MISMATCH')
    require(basis.evidence.get('basis_kind') in ('EXACT_SYNTHETIC_LINEAR','AUDITED_LOCAL_JACOBIAN'), 'UNPROVEN_ACTUATOR_BASIS')
    require(basis.evidence.get('state_hash') and basis.evidence.get('source_sha256'),'ACTUATOR_BASIS_PROVENANCE_MISSING')
    require(all(m.get('type') in ('TG_PARAMETER','TD_PARAMETER') and m.get('family') in ('WORK','SERVICE') and m.get('allowed') is True for m in basis.column_meta),'ILLEGAL_ACTUATOR_BASIS')
    keys={k:i for i,k in enumerate(basis.row_keys)};desired=np.zeros(op.n_rows)
    for meta,delta in zip(inc.variables,solution.delta_q):
        k=(meta['dseg_code'],meta['origin'],meta['destination'])
        require(k in keys,'GUIDED_OD_MISSING_FROM_ACTUATOR_BASIS');desired[keys[k]]=delta
    # Entire exported OD universe must be covered, including frozen segments.
    universe={(r['dseg'],r['orig'],r['dest']) for r in inc.audit.get('all_od_totals',[])}
    require(universe.issubset(keys),'COLLATERAL_OD_SCOPE_MISSING')
    mutable={(m['dseg_code'],m['origin'],m['destination']) for m in inc.variables}
    forbidden={i for i,k in enumerate(basis.row_keys) if k not in mutable}
    require(all(int(r) not in forbidden or abs(v)<1e-12 for r,v in zip(op.row_idx,op.values)), 'ACTUATOR_BASIS_CHANGES_FROZEN_OD')
    lo=np.asarray(basis.lower,dtype=float);hi=np.asarray(basis.upper,dtype=float)
    require(lo.shape==hi.shape==(op.n_cols,) and np.all(np.isfinite(lo)) and np.all(np.isfinite(hi)) and np.all(lo<=0) and np.all(hi>=0),'ACTUATOR_BOUNDS_INVALID')
    prob=core.GuidanceProblem(op,desired,np.ones(op.n_rows),np.zeros(op.n_cols),np.zeros(op.n_cols),lo,hi,[],[],np.arange(op.n_rows),[],{})
    result=core.solve_guidance(prob,{'solver_max_iter':10000,'solver_tolerance':numeric['feasibility_solver_tolerance'],'power_iterations':60})
    achieved=op.forward(result.x);residual=desired-achieved
    maxerr=float(np.max(np.abs(residual),initial=0));rmse=float(np.sqrt(np.mean(residual**2))) if len(residual) else 0.
    exact=basis.evidence['basis_kind']=='EXACT_SYNTHETIC_LINEAR'
    from .optimizer import _kkt_x
    kkt=_kkt_x(prob,result.x) if op.n_cols else 0.
    allowed=tolerance+numeric['feasibility_rtol']*np.abs(desired)
    if np.all(np.abs(residual)<=allowed):status='SYNTHETIC_FEASIBLE_TG_TD' if exact else 'LINEARIZED_FEASIBLE_TG_TD_NOT_LIVE_VERIFIED'
    elif kkt>numeric['feasibility_kkt_tolerance']:status='TG_TD_FEASIBILITY_SOLVER_NOT_CONVERGED'
    else:status='INFEASIBLE_TG_TD' if exact else 'INFEASIBLE_LOCAL_TG_TD_LINEARIZATION'
    return {'status':status,'tolerance_abs':tolerance,
            'tolerance_relative':numeric['feasibility_rtol'],'numerical_limits':numeric,'basis_kind':basis.evidence['basis_kind'],'full_od_max_abs_residual':maxerr,
            'full_od_rmse':rmse,'kkt':kkt,'desired_delta':desired.tolist(),'realizable_delta':achieved.tolist(),
            'residual':residual.tolist(),'actuator_step':result.x.tolist(),'basis_provenance':basis.evidence,
            'global_nonlinear_infeasibility_claimed':False,'live_verified':False,'apply_permitted':False}
