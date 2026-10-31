import copy
from dataclasses import replace
import numpy as np
import pytest
from cordon2025.common import ROOT, read_config, ContractError, canonical_hash
from cordon2025.aggressive import propose, bounded_actuator_basis, incidence_state_hash, td_trial_plan
from cordon2025.aggressive_demo import synthetic_basis
from cordon2025.aggressive_policy import META
from cordon2025.optimizer import solve
from cordon2025.demos import algebra_example
from cordon2025.budget import SharedBudget


def config(cycle=1):
    return read_config(ROOT/'CORDON_2025_AGGRESSIVE_CONFIG.json',outer_cycle=cycle)


def test_more_aggressive_than_standard_same_loss():
    inc=algebra_example(np.eye(2)*100,[140,70],base=[120,110]);base=solve(inc,read_config());agg=propose(inc,config())
    assert agg.solution.report['objective_final']<base.report['objective_final']
    assert np.max(abs(base.x))==pytest.approx(.15)
    assert np.max(abs(agg.solution.x))==pytest.approx(.2)
    assert agg.report['selected_scale']==1
    assert len(agg.report['trials'])==6 and not agg.report['apply_permitted']
    assert agg.solution.problem.operator is not None


def test_projection_consumes_larger_limits():
    inc=algebra_example([[100]],[140]);out=propose(inc,config())
    assert all(abs(r['log_step'])<=.12+1e-12 for r in out.projection['projection_rows'])
    assert any(abs(r['log_step'])>.04 for r in out.projection['projection_rows'])
    assert out.projection['status']=='PROJECTION_AVAILABLE_REALIZATION_NOT_VERIFIED'


@pytest.mark.parametrize('cycle,bound',[(1,.2),(6,.2),(7,.14),(18,.14),(19,.08),(100,.08)])
def test_solver_consumes_each_stage(cycle,bound):
    out=propose(algebra_example([[100]],[200]),config(cycle))
    assert out.solution.x[0]==pytest.approx(bound)


def test_validation_has_no_influence_on_candidate_ranking_or_credit():
    inc=algebra_example([[100],[100]],[125,10]);inc.rows[1]['role']='VALIDATION'
    a=propose(inc,config())
    inc.rows[1].update(observed=1e12,weight=1e15)
    b=propose(inc,config())
    assert np.array_equal(a.solution.x,b.solution.x)
    assert a.report['selected_scale']==b.report['selected_scale']
    assert a.report['selected_objective']==b.report['selected_objective']
    assert b.solution.uncertainty[1]==0


def test_fixed_contribution_preserved():
    inc=algebra_example([[100]],[170],base=[150]);out=propose(inc,config())
    assert out.solution.prediction[0]-inc.operator.forward(out.solution.x)[0]==50+100
    assert out.solution.report['relations'][0]['fixed_contribution']==50
    assert out.report['realization_status']=='TG_TD_REALIZATION_NOT_VERIFIED'


def test_backtracking_respects_actuator_hard_cap():
    inc=algebra_example([[100]],[130]);basis=synthetic_basis(inc,[[100]],upper=.05)
    out=propose(inc,config(),basis=basis)
    assert out.report['selected_scale']==.25
    assert out.solution.x[0]==pytest.approx(.05)
    assert out.raw_solution.x[0]==pytest.approx(.2)
    assert out.feasibility['full_od_max_abs_residual']<1e-5
    assert out.solution.guidance.x[0]==pytest.approx(.05)
    assert out.solution.report['candidate_is_full_solver_optimum'] is False
    assert not out.report['trials'][0]['eligible_shadow_proposal']


@pytest.mark.parametrize('delta',[[20,-20,-20,20],[-20,20,20,-20]])
def test_unrealizable_patterns_not_accepted(delta):
    inc=algebra_example(np.eye(4)*100,100+np.array(delta));out=propose(inc,config(),basis=synthetic_basis(inc))
    assert out.report['status']=='OFFLINE_AGGRESSIVE_NO_IMPROVING_CANDIDATE'
    assert out.report['selected_scale']==0
    assert np.all(out.solution.x==0)
    assert any('INFEASIBLE_TG_TD' in x['reason'] for x in out.report['trials'])


def test_joint_budget_unchanged_and_default_not_enabled():
    inc=algebra_example(np.eye(2)*100,[100,100],base=[140,150])
    budget=SharedBudget([(1,2),(1,3)],[1,2,3],np.full(3,10.),30.,'BOUNDED_SCENARIO',{'kind':'SYNTHETIC'},True)
    caps=budget.station_caps.copy();out=propose(inc,config(),budget)
    assert np.array_equal(caps,budget.station_caps)
    assert out.report['selected_c17']['global_credits_consumed']<=30+1e-7
    assert all(r['c17_global_credits']<=30+1e-7 for r in out.report['trials'])
    assert propose(inc,config()).report['selected_c17']['policy']=='DISABLED'


def test_no_od_change_no_false_C17_improvement():
    inc=algebra_example(np.zeros((2,0)),[100,100],base=[140,150])
    budget=SharedBudget([(1,2),(1,3)],[1,2,3],np.full(3,100.),300.,'BOUNDED_SCENARIO',{},True)
    out=propose(inc,config(),budget)
    assert out.report['selected_scale']==0
    assert all(abs(r['relative_improvement'])<1e-12 for r in out.report['trials'])
    assert out.report['profiled_baseline_c17']['global_credits_consumed']>0


def test_budget_not_a_lower_side_tolerance():
    inc=algebra_example([[100]],[150]);b=SharedBudget([(1,2)],[1,2],np.full(2,1000.),2000.,'BOUNDED_SCENARIO',{},True)
    out=propose(inc,config(),b)
    assert out.solution.uncertainty[0]==0 and out.solution.x[0]>.19


def test_actuator_limits_intersect_not_replace():
    inc=algebra_example([[100]],[130]);basis=synthetic_basis(inc,[[100]],upper=.05)
    new=bounded_actuator_basis(inc,basis,config())
    assert new.upper[0]==.05 and basis.upper[0]==.05
    wide=synthetic_basis(inc,[[100]],upper=2)
    assert bounded_actuator_basis(inc,wide,config()).upper[0]==.12


@pytest.mark.parametrize('bad_kind',['DIRECT_OD','LINK_MULTIPLIER','UNKNOWN'])
def test_unapproved_actuator_kinds_rejected(bad_kind):
    inc=algebra_example([[100]],[130]);b=synthetic_basis(inc,[[100]]);b.column_meta[0]['step_kind']=bad_kind
    with pytest.raises(ContractError,match='STEP_KIND'):propose(inc,config(),basis=b)


def test_actuator_state_hash_cannot_be_reused():
    inc=algebra_example([[100]],[130]);b=synthetic_basis(inc,[[100]])
    b.evidence['state_hash']='wrong'
    with pytest.raises(ContractError,match='STATE_MISMATCH'):propose(inc,config(),basis=b)


def test_false_mutable_scope_rejected():
    inc=algebra_example([[100]],[130]);inc.variables[0]['dseg_code']='EXOG_EE_CF'
    with pytest.raises(ContractError,match='SCOPE_MISMATCH'):propose(inc,config())


def test_empirical_still_requires_explicit_scenario():
    inc=algebra_example([[100]],[130]);inc.audit['origin']='VISUM_SAVED_PATHS'
    with pytest.raises(ContractError,match='EXPLICIT_SCENARIO'):propose(inc,config())
    out=propose(inc,config(),allow_unapproved_scenario=True)
    assert not out.report['production_ready']


def test_td_seven_parameter_scales_no_native_claim():
    inc=algebra_example(np.eye(2)*100,[130,130]);b=synthetic_basis(inc,[[100],[100]],step_type='TD_PARAMETER')
    plan=td_trial_plan(inc,config(),b,[.2])
    assert [r['scale'] for r in plan['trials']]==[1.,.5,.25,.125,.0625,.03125,.015625]
    assert all(not r['native_ipf_verified'] for r in plan['trials'])
    assert all(not r['native_accept_permitted'] for r in plan['trials'])
    assert all(r['component_gate']['status']=='NATIVE_TD_COMPONENT_LOSSES_NOT_SUPPLIED' for r in plan['trials'])


def test_td_soft_component_evidence_is_used():
    inc=algebra_example(np.eye(2)*100,[130,130]);b=synthetic_basis(inc,[[100],[100]],step_type='TD_PARAMETER');cfg=config()
    metrics={s:{'before':{'A':100.},'after':{'A':50.},'selected':['A']} for s in cfg['td_realization_backtracking_scales']}
    plan=td_trial_plan(inc,cfg,b,[.2],component_losses=metrics)
    assert plan['trials'][0]['component_gate']['passes_soft_fit_only']
    assert not plan['trials'][0]['native_accept_permitted']


def test_no_c17_authority_change_from_aggressive_policy():
    inc=algebra_example([[100]],[110]);out=propose(inc,config())
    assert out.report['effective_policy']['c17_budgets_unchanged']
    assert out.report['effective_policy']['validation_split_unchanged']


@pytest.mark.parametrize('cycle,global_log',[(1,.1),(7,.06),(19,.03)])
def test_existing_signed_generation_design_is_active(cycle,global_log):
    inc=algebra_example([[100]],[150])
    zones=[{'zone_no':i,'NOT_ZAHR':1.,'ADD_PROD_W':1.,'ADD_ATT_W':1.,
            'ADD_PROD_S':1.,'ADD_ATT_S':1.,'ADD_SALARY':1.,'AV_INCOME':1500.} for i in (1,3)]
    out=propose(inc,config(cycle),zone_rows=zones)
    design=out.projection['existing_generation_design']
    assert design['summary']['signed_generation_refinement']['enabled']
    assert design['summary']['bound_constrained_projection']['enabled']
    assert len(design['candidate_rows'])==2
    for row in design['candidate_rows']:
        assert np.log(row['proposed']/row['current'])==pytest.approx(global_log)
        assert .5<=row['proposed']<=2
    assert design['summary']['estimated_pa_delta_by_family']['WORK']['estimated_abs_gap']<1e-9
    assert not out.projection['native_generation_executed']
    assert not out.projection['real_visum_verified']


def test_signed_design_preserves_zero_parameters():
    inc=algebra_example([[100]],[150])
    zones=[{'zone_no':i,'NOT_ZAHR':1.,'ADD_PROD_W':0.,'ADD_ATT_W':0.,
            'ADD_PROD_S':0.,'ADD_ATT_S':0.,'ADD_SALARY':1.,'AV_INCOME':1500.} for i in (1,3)]
    out=propose(inc,config(),zone_rows=zones)
    assert not out.projection['existing_generation_design']['candidate_rows']
    assert out.report['realization_status']=='TG_TD_REALIZATION_NOT_VERIFIED'
