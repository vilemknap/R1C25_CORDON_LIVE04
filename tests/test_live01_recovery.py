"""Additional recovery-time faults. All COM providers here are synthetic."""
from pathlib import Path
import json
import pytest
from fake_live01 import Live01Visum
from cordon2025.common import ROOT
from cordon2025.live01_config import load_config
from cordon2025.live01_visum import model_preflight, verify_end_state
from cordon2025.visum_startup import ReadControl,settings

@pytest.fixture
def case(tmp_path):
    v=Live01Visum(tmp_path/'model');folder=tmp_path/'out';folder.mkdir()
    return v,load_config(),folder,ReadControl(folder),settings({'min_free_disk_gib':0,'com_retry_initial_delay_seconds':0.,'com_retry_max_delay_seconds':0.,'com_retry_attempts':3})

@pytest.mark.parametrize('mutation',['oa_same_sum','oa_binding','network','source_pointer'])
def test_final_readback_covers_current_oa_network_and_source(case,mutation):
    v,cfg,folder,ctl,opt=case;pre,state=model_preflight(*case)
    if mutation=='oa_same_sum':
        m=v.dsegs['NATIVE_CW'].ODMatrix.values;m[0,1]+=.01;m[0,2]-=.01
    elif mutation=='oa_binding':v.dsegs['EXOG_EE_CW'].ODMatrix.no=9999
    elif mutation=='network':v.Net.Links.rows[-1]['TSYSSET']='C,LNV,NV'
    else:
        new=v.source.with_name('other_2025.ver');new.write_bytes(v.source.read_bytes());v.IO.CurrentVersionFile=str(new)
    with pytest.raises(Exception,match='CHANGED|STALE|MISMATCH'):
        verify_end_state(v,cfg,folder,ctl,opt,pre,state)
    assert not v.writes


def test_state_readback_still_passes_unchanged(case):
    v,cfg,folder,ctl,opt=case;pre,state=model_preflight(*case)
    report=verify_end_state(v,cfg,folder,ctl,opt,pre,state)
    assert report['status']=='DONOR_AND_OA_CURRENT_STATE_UNCHANGED'
    assert not report['new_assignment_verified'] and not v.writes


@pytest.mark.parametrize('mutation',['oa','zone','td','network'])
def test_change_after_solve_prevents_successful_publication(tmp_path,monkeypatch,mutation):
    from cordon2025 import live01_baseline as baseline
    v=Live01Visum(tmp_path/'model');original=baseline.propose_generation;called=[]
    def changed(*a,**kw):
        result=original(*a,**kw);called.append(True)
        if len(called)==1:
            if mutation=='oa':
                m=v.dsegs['NATIVE_CS'].ODMatrix.values;m[0,1]+=.1;m[0,2]-=.1
            elif mutation=='zone':v.Net.Zones.rows[0]['ADD_PROD_W']+=.01
            elif mutation=='td':next(iter(v.Procedures.Operations.items[5].TripDistributionParameters.strata.values())).GravitationParameters.values['PARA_B']+=.01
            else:v.Net.Links.rows[-1]['TSYSSET']='C'
        return result
    monkeypatch.setattr(baseline,'propose_generation',changed)
    with pytest.raises(Exception,match='CHANGED'):
        baseline.run(v,output_root=tmp_path/'runs',options={'min_free_disk_gib':0})
    folder=next((tmp_path/'runs').glob('LIVE01_*'))
    assert json.loads((folder/'RUN_CHECKPOINT.json').read_text())['completed'] is False
    assert json.loads((folder/'00_RESULT.json').read_text())['status']=='LIVE01_BLOCKED'
    assert (folder/'99_TRACEBACK.txt').is_file() and not v.writes


def test_completed_checkpoint_revoked_on_lock_cleanup_failure(tmp_path,monkeypatch):
    from cordon2025 import live01_baseline as baseline
    from cordon2025.session import RunSession
    original=RunSession._release
    def failure(self,preserve_primary=False):
        original(self,preserve_primary=preserve_primary)
        if not preserve_primary:raise OSError('INJECTED_RELEASE_FAILURE')
    monkeypatch.setattr(RunSession,'_release',failure)
    v=Live01Visum(tmp_path/'model')
    with pytest.raises(OSError,match='INJECTED_RELEASE_FAILURE'):
        baseline.run(v,output_root=tmp_path/'runs',options={'min_free_disk_gib':0})
    folder=next((tmp_path/'runs').glob('LIVE01_*'))
    assert json.loads((folder/'RUN_CHECKPOINT.json').read_text())['completed'] is False
    assert json.loads((folder/'00_RESULT.json').read_text())['status']=='LIVE01_BLOCKED'
    assert not v.writes


def test_primary_unprintable_failure_preserved(tmp_path,monkeypatch):
    from cordon2025 import live01_baseline as baseline
    from fake_visum_startup import UnprintableOther
    error=UnprintableOther()
    def fail(*a,**kw):raise error
    monkeypatch.setattr(baseline,'model_preflight',fail)
    v=Live01Visum(tmp_path/'model')
    with pytest.raises(UnprintableOther) as caught:
        baseline.run(v,output_root=tmp_path/'runs',options={'min_free_disk_gib':0})
    assert caught.value is error and not v.writes
    folder=next((tmp_path/'runs').glob('LIVE01_*'))
    assert 'unprintable' in json.loads((folder/'00_RESULT.json').read_text())['reason']
    assert json.loads((folder/'RUN_CHECKPOINT.json').read_text())['completed'] is False


def test_full_handoff_verifier_and_tampering(tmp_path):
    from cordon2025.live01_baseline import run
    from cordon2025.live01_provenance import verify_handoff_directory
    v=Live01Visum(tmp_path/'model')
    result=run(v,output_root=tmp_path/'runs',options={'min_free_disk_gib':0})
    folder=Path(result['output_directory'])
    handoff=json.loads((folder/'BASELINE_AND_PROPOSAL_CONTRACT.json').read_text())
    proof=verify_handoff_directory(folder,handoff['current_model_fingerprint'])
    assert len(proof['candidate_counts'])==2 and all(n>0 for n in proof['candidate_counts'].values())
    assert proof['apply_permitted'] is False
    with pytest.raises(ValueError,match='STALE'):
        verify_handoff_directory(folder,'wrong_current_model')
    path=folder/'ALL_ORDERED_UNIQUE_PAIRS/PROPOSED_TG_CANDIDATES.json'
    path.write_text(path.read_text()+' ')
    with pytest.raises(ValueError,match='ARTIFACT_CHANGED'):
        verify_handoff_directory(folder,handoff['current_model_fingerprint'])


def test_static_new_source_has_no_model_mutators():
    import ast
    forbidden={'SetAttValue','SetMultiAttValues','SetValues','Execute','ExecuteProcedures',
               'SaveVersion','LoadVersion','Dispatch','GetActiveObject','GetObject'}
    for path in sorted((ROOT/'cordon2025').glob('live01_*.py')):
        tree=ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute):
                assert node.func.attr not in forbidden,(path.name,node.lineno,node.func.attr)
