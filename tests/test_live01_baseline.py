from pathlib import Path
import json,sys
import pytest
from fake_live01 import Live01Visum
from cordon2025.live01_baseline import run
from cordon2025.live01_provenance import verify_handoff
from cordon2025.session import verify_run


def test_end_to_end_baseline_681_zones_all120_and_nonzero_tg(tmp_path):
    v=Live01Visum(tmp_path/'model')
    result=run(v,output_root=tmp_path/'runs',options={'min_free_disk_gib':0,'com_retry_initial_delay_seconds':0.,'com_retry_max_delay_seconds':0.})
    assert result['status']=='MOCK_READONLY_BASELINE_PASS' and result['objective_rows_per_method']==120
    assert all(r['candidate_count']>0 for r in result['variants'].values())
    assert not v.writes and result['real_visum_verified'] is False
    folder=Path(result['output_directory'])
    h=json.loads((folder/'BASELINE_AND_PROPOSAL_CONTRACT.json').read_text())
    assert verify_handoff(h,h['current_model_fingerprint'])
    with pytest.raises(ValueError,match='STALE'):verify_handoff(h,'another_state')
    proof=json.loads((folder/'WHOLE_MATRIX_ROLE_AND_OBJECTIVE_PROOF.json').read_text())
    for p in proof.values():
        assert p['objective_rows']==120 and p['roles']['validation']==0 and p['operator_nonzeros']>0
        assert p['selected_row_indices']==list(range(120))
    assert verify_run(folder)['completed']


def test_mid_read_failure_no_complete_seal(tmp_path):
    v=Live01Visum(tmp_path/'model');v.path_drift=True
    with pytest.raises(Exception,match='PATH_VOLUMES_CHANGED'):run(v,output_root=tmp_path/'runs',options={'min_free_disk_gib':0})
    folders=list((tmp_path/'runs').glob('LIVE01_*'));assert len(folders)==1
    cp=json.loads((folders[0]/'RUN_CHECKPOINT.json').read_text())
    assert not cp['completed'] and not v.writes
    assert json.loads((folders[0]/'00_RESULT.json').read_text())['status']=='LIVE01_BLOCKED'


def test_launcher_import_does_not_touch_com():
    import RUN_R1_2025_CORDON_LIVE_BASELINE as entry
    assert callable(entry.main)
    result=entry.main({})
    assert result['reason']=='VISUM_NOT_INJECTED'


def test_full_public_bootstrap_mock_and_import_restoration(tmp_path):
    import cordon_live01_bootstrap as bootstrap
    import cordon_visum_bootstrap as original
    v=Live01Visum(tmp_path/'model')
    path_before=list(sys.path)
    mods={k:m for k,m in sys.modules.items() if original._owned(k)}
    result=bootstrap.launch({'Visum':v},output_root=tmp_path/'runs',options={'min_free_disk_gib':0})
    assert result['status']=='MOCK_READONLY_BASELINE_PASS',result
    assert list(sys.path)==path_before
    assert {k:m for k,m in sys.modules.items() if original._owned(k)}==mods
    assert not hasattr(sys,'_r1_cordon2025_busy') and not v.writes


def test_full_public_bootstrap_read_failure_restores_imports(tmp_path):
    import cordon_live01_bootstrap as bootstrap
    import cordon_visum_bootstrap as original
    v=Live01Visum(tmp_path/'model');del v.Net.Zones.rows[0]['ADD_PROD_W']
    path_before=list(sys.path);mods={k:m for k,m in sys.modules.items() if original._owned(k)}
    result=bootstrap.launch({'Visum':v},output_root=tmp_path/'runs',options={'min_free_disk_gib':0})
    assert result['status']=='LIVE01_STARTUP_BLOCKED' and 'TG_CONTRACT_MISSING' in result['reason']
    assert list(sys.path)==path_before and {k:m for k,m in sys.modules.items() if original._owned(k)}==mods
    assert not hasattr(sys,'_r1_cordon2025_busy') and not v.writes
