"""Recovery regressions; small native simulation and controller mock, no PTV COM."""
from types import SimpleNamespace
from contextlib import nullcontext
import numpy as np
import pytest

from test_live04_utility_state import setup
from cordon2025.live04_adapter import CordonLive04Adapter
from cordon2025.live03_adapter import CordonLive03Adapter
from cordon2025.common import ContractError


def adapter_for(raw, a, utility):
    adapter=CordonLive04Adapter.__new__(CordonLive04Adapter)
    adapter.visum=a.visum
    adapter.live02=a.live02
    adapter.com_retry_policy=a.com_retry_policy
    adapter.td_utility_state=utility
    adapter.assignment_invalidated=False
    return adapter


def test_interrupted_full_assignment_is_dirty_even_when_matrix_snapshot_matches(setup,tmp_path,monkeypatch):
    raw,a,u,parent,audit,inv=setup
    utility=SimpleNamespace(enabled=False,input_scope=lambda p:nullcontext(),finish=lambda p,f:None)
    adapter=adapter_for(raw,a,utility)
    native_before=raw.native_snapshot()
    def interrupted(self,folder,block,plan):
        raw.execute({'selected_operation_positions':[30]})
        raise RuntimeError('ASSIGNMENT_INTERRUPTED_AFTER_RESET')
    monkeypatch.setattr(CordonLive03Adapter,'_execute_perf1_plan',interrupted)
    with pytest.raises(RuntimeError,match='ASSIGNMENT_INTERRUPTED_AFTER_RESET'):
        adapter._execute_perf1_plan(tmp_path,'GENERATION',{'selected_operation_positions':[30,36]})
    assert raw.native_snapshot()==native_before and not raw.saved_paths
    assert adapter.assignment_invalidated is True


@pytest.mark.parametrize('damage',['zero_skims','nan_utility','negative_utility'])
def test_exact_parent_restore_can_replace_invalid_current_numeric_values(setup,damage):
    raw,a,u,parent,audit,inv=setup
    if damage=='zero_skims':
        for no in u.time_specs:raw.matrix(no).data[:]=0.
    elif damage=='nan_utility':raw.matrix(9700).data[0,1]=np.nan
    else:raw.matrix(9700).data[0,1]=-1.
    with pytest.raises(ContractError):u.read()
    u.restore()
    assert u.augment_snapshot(raw.native_snapshot())==parent
    assert audit.td_utility_restore_expected is None and audit.td_time_restore_numbers is None
    assert audit.summary()['direct_od_matrix_writes']==0


def test_invalid_numeric_values_do_not_allow_restoring_another_matrix_identity(setup):
    raw,a,u,parent,audit,inv=setup
    raw.matrix(9700).data[0,1]=np.nan
    raw.matrix(9700).values['CODE']='FOREIGN_MATRIX'
    with pytest.raises(ContractError,match='CODE_COLLISION'):u.restore()
    assert not audit.events


def test_successful_full_assignment_clears_the_pending_recovery_flag(setup,tmp_path,monkeypatch):
    raw,a,u,parent,audit,inv=setup
    utility=SimpleNamespace(enabled=False,input_scope=lambda p:nullcontext(),finish=lambda p,f:None)
    adapter=adapter_for(raw,a,utility)
    def execute(self,folder,block,plan):
        assert self.assignment_invalidated is True
        raw.execute(plan)
        return .001
    def assign(self,folder,block):
        return self._execute_perf1_plan(folder,block,{'selected_operation_positions':[30,36]})
    monkeypatch.setattr(CordonLive03Adapter,'_execute_perf1_plan',execute)
    monkeypatch.setattr(CordonLive03Adapter,'assign_for_block',assign)
    assert adapter.assign_for_block(tmp_path,'GENERATION')==.001
    assert adapter.assignment_invalidated is False and raw.saved_paths


def test_preexecution_failure_does_not_invalidate_untouched_assignment(setup,tmp_path,monkeypatch):
    raw,a,u,parent,audit,inv=setup
    class BeforeExecute:
        enabled=True
        def prepare(self,*args):raise RuntimeError('PREFLIGHT_FAILED_BEFORE_EXECUTE')
    adapter=adapter_for(raw,a,BeforeExecute())
    monkeypatch.setattr(CordonLive03Adapter,'snapshot',lambda self:raw.native_snapshot())
    with pytest.raises(RuntimeError,match='PREFLIGHT_FAILED_BEFORE_EXECUTE'):
        adapter._execute_perf1_plan(tmp_path,'GENERATION',{'selected_operation_positions':[30,36]})
    assert adapter.assignment_invalidated is False and raw.saved_paths


@pytest.mark.parametrize('repair_result',['FAILED_DIRTY','FAILED_PROOF','VERIFIED'])
def test_failed_assignment_repair_cannot_be_saved_or_reported_as_verified(tmp_path,monkeypatch,repair_result):
    from pathlib import Path
    from fake_live04 import Live04Visum
    from cordon2025 import live04_cycle as cycle
    from cordon2025.common import read_json
    model=Live04Visum(tmp_path/'model')
    model.paths_gone=False
    def generation(*args):
        def block(adapter,cfg,folder,control,state,diag,*extra,**kw):
            Path(folder).mkdir(parents=True,exist_ok=True)
            # Stub an already accepted block; this test covers orchestration
            # after acceptance, not the numerical optimizer's acceptance gate.
            adapter.long_support_last_trial=adapter.long_support(folder,'ACCEPTED')
            return True,state,diag,{'total':1.},{'status':'ACCEPTED'}
        return block
    def td(*args):
        def block(adapter,*args,**kw):
            adapter.assignment_invalidated=True
            model.paths_gone=True
            raise RuntimeError('NATIVE_ASSIGNMENT_ABORTED')
        return block
    def repair(adapter,*args):
        adapter.assignment_invalidated=repair_result=='FAILED_DIRTY'
        model.paths_gone=repair_result=='FAILED_DIRTY'
        return {'status':'REPAIRED_VERIFIED' if repair_result=='VERIFIED' else 'REPAIR_FAILED'}
    monkeypatch.setattr(cycle,'make_generation_block',generation)
    monkeypatch.setattr(cycle,'make_td_block',td)
    monkeypatch.setattr(cycle,'_repair',repair)
    with pytest.raises(RuntimeError,match='NATIVE_ASSIGNMENT_ABORTED'):
        cycle.run(model,output_root=tmp_path/'runs',
                  options={'min_free_disk_gib':0,'com_retry_initial_delay_seconds':0.,'com_retry_max_delay_seconds':0.},
                  config_overrides={'max_cycles':1,'checkpoint':{'enabled':False}})
    folder=next((tmp_path/'runs').glob('LIVE04_TGTD_*'))
    result=read_json(folder/'00_RESULT.json')
    proof=read_json(folder/'FAILURE_STATE_READBACK.json')
    assert proof['snapshot_matches_last_accepted_or_baseline'] is True
    if repair_result=='VERIFIED':
        assert result['model_state_verified'] is True
        assert result['saved_version_at_stop'] and len(model.saved_versions)==1
        assert not model.paths_gone
    else:
        assert result['model_state_verified'] is False
        assert result['status']=='LIVE04_STOPPED_MODEL_STATE_NOT_VERIFIED_REOPEN_SOURCE_OR_SAVED_VERSION'
        assert proof['assignment_verified'] is False
        assert result['saved_version_at_stop'] is None and not model.saved_versions


@pytest.mark.parametrize('failure',['unprintable_exception','report_write'])
def test_td_trial_rolls_back_even_when_error_reporting_itself_fails(tmp_path,monkeypatch,failure):
    from fake_live04 import Live04Visum
    from cordon2025 import live03_td as td
    from cordon2025 import live02_adapter as adapter_module
    from cordon2025.live04_cycle import run
    from cordon2025.common import read_json
    model=Live04Visum(tmp_path/'model')
    from cordon2025.common import parent_module
    cb=parent_module('r1_15a2_combusy2_v24917')
    original_classifier=cb._manual_recovery_required
    original_gap=adapter_module.CordonTrialAdapter.gap
    calls=[]
    class Unprintable(RuntimeError):
        def __str__(self):raise ValueError('EXCEPTION_TEXT_CONVERSION_FAILED')
    def gap(adapter):
        calls.append(True)
        if len(calls)==1:
            if failure=='unprintable_exception':raise Unprintable('TRIAL_ASSIGNMENT_FAILED')
            raise RuntimeError('TRIAL_ASSIGNMENT_FAILED')
        return original_gap(adapter)
    writer=td.write_json
    def report(path,data):
        if failure=='report_write' and str(path).endswith('TD_BLOCK_RESULT.json') and data.get('status')=='TRIAL_FAILED':
            raise OSError('REPORT_FILE_LOCKED')
        return writer(path,data)
    monkeypatch.setattr(adapter_module.CordonTrialAdapter,'gap',gap)
    monkeypatch.setattr(td,'write_json',report)
    with pytest.raises(Exception):
        run(model,output_root=tmp_path/'runs',
            options={'min_free_disk_gib':0,'com_retry_initial_delay_seconds':0.,'com_retry_max_delay_seconds':0.},
            config_overrides={'max_cycles':1,'blocks_per_cycle':['TD_CORDON'],
                              'idp_guard':{'enabled':False},
                              'td_cordon':{'grouping':'FAMILY','max_inner_evaluations':1,
                                           'idp_constrained_step':False,'idp_objective_weight':0.}})
    folder=next((tmp_path/'runs').glob('LIVE04_TGTD_*'))
    assert cb._manual_recovery_required is original_classifier
    assert calls
    proof=folder/'C01_TD_CORDON/TRIAL/ROLLBACK/ROLLBACK_VERIFICATION.json'
    assert proof.exists() and read_json(proof)['passes']
    result=read_json(folder/'00_RESULT.json')
    assert result['model_state_verified'] is True and not model.saved_versions
    if failure=='unprintable_exception':assert 'LIVE03_TD_TRIAL_ERROR_NOT_A_PLATEAU' in result['reason']


@pytest.mark.parametrize('manual',[False,True])
def test_manual_recovery_verdict_survives_an_unprintable_exception_chain(manual):
    from cordon2025.live04_v7 import manual_recovery_required
    class Unprintable(RuntimeError):
        def __str__(self):raise ValueError('BAD_EXCEPTION_TEXT')
    inner=RuntimeError('MANUAL_REOPEN' if manual else 'OTHER_FAILURE')
    outer=Unprintable('OUTER_FAILURE')
    outer.__cause__=inner
    inner.__cause__=outer
    assert manual_recovery_required(outer) is manual


@pytest.mark.parametrize('report_failure',[False,True])
def test_supply_partial_setter_error_restores_parent_before_error_report(tmp_path,monkeypatch,report_failure):
    from copy import deepcopy
    from cordon2025 import live04_supply as supply
    from cordon2025.common import parent_module
    sm=parent_module('r1_15a2_supply_mix_v24917')
    state={'state_hash':'PARENT','value':0.}
    live=deepcopy(state);events=[]
    class Unprintable(RuntimeError):
        def __str__(self):raise ValueError('BAD_EXCEPTION_FORMAT')
    def apply(*args):
        live['value']=1.
        raise Unprintable('SETTER_MUTATED_THEN_FAILED')
    def rollback(*args):
        events.append('ROLLBACK');live.update(state)
        return {'passes':True},{'diagnostic_hash':'D'}
    adapter=SimpleNamespace(snapshot=lambda:deepcopy(live),read_links=lambda:{},v24917_status={},
                            baseline_addval={},supply_path_proof=None,apply_supply=apply)
    base={'ledger':lambda *a:{'total':1.},'diagnostic_hash':lambda d:'D',
          '_candidate_signature':lambda *a:'C','_rollback_candidate':rollback,
          'recovery_scope':lambda *a:nullcontext(),'UserStopRequested':KeyboardInterrupt,
          'TimeBudgetReached':TimeoutError}
    tx=SimpleNamespace(ctrl_ns=base,coupled_ns={'_generation_counts_cfg':lambda c:c})
    cand={'candidate_id':'C','changes':[{'key':(1,2,3),'new':1.}],
          'positive_edges':1,'negative_edges':0,'members':[]}
    design={'design_step_units':[16],'design_policy_override':{},'drivers':[],
            'candidates':[cand],'skipped':[]}
    monkeypatch.setattr(supply,'design',lambda *a:(design,None,{'profiles':[]}))
    monkeypatch.setattr(sm,'profile_table',lambda *a:{})
    monkeypatch.setattr(sm,'driver_mode',lambda *a:'M')
    monkeypatch.setattr(sm,'select_groups',lambda *a:[{'keys':[],'ladder':[]}])
    monkeypatch.setattr(sm,'addval_integer',lambda *a:{'integer':True})
    monkeypatch.setattr(sm,'cost_safe_merged_candidate',lambda *a,**k:(cand,{}))
    writer=supply.write_json
    def report(path,data):
        if str(path).endswith('SUPPLYMIX_BLOCK_RESULT.json') and data.get('error'):
            events.append('ERROR_REPORT')
            if report_failure:raise OSError('REPORT_LOCKED')
        return writer(path,data)
    monkeypatch.setattr(supply,'write_json',report)
    result=supply.supply_block(tx,adapter,{},tmp_path,SimpleNamespace(checkpoint=lambda *a,**k:None),
                              state,{'diagnostic_hash':'D'},{},None,None,outer_cycle=1,
                              opts={'step_units':[16],'max_trials':1})
    assert live==state and events==['ROLLBACK','ERROR_REPORT']
    assert result[0] is False and result[-1]['status']=='TRIAL_FAILED_ROLLBACK_VERIFIED'
