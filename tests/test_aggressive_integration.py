import hashlib
import json
from pathlib import Path
import subprocess
import sys
import numpy as np
import pytest
from cordon2025.common import ROOT, read_config
from cordon2025.aggressive_policy import META
from cordon2025.aggressive import propose
from cordon2025.demos import algebra_example
from cordon2025.budget import SharedBudget
from cordon2025.session import verify_run


def test_v2_bytes_preserved_except_explicit_reviewed_startup_patches():
    records=json.loads((ROOT/'docs/aggressive/PRESERVED_V2_FILES.json').read_text())
    assert len(records)>700
    changes=json.loads((ROOT/'docs/startup_fix1/REVIEWED_PARENT_CHANGES.json').read_text())
    assert set(changes)=={'parent/R1_15A2_VISUM_COM_PREFLIGHT_V2_3_6_INLINE.py','parent/r1_15a2_com_compat.py','parent/r1_15a2_supply.py','parent/r1_15a2_two_mode_v238.py'}
    for name,digest in records.items():
        if name in changes:
            assert changes[name]['before_sha256']==digest
            digest=changes[name]['after_sha256']
        fix3=json.loads((ROOT/'docs/fix3/REVIEWED_CHANGES.json').read_text())['files']
        if name in fix3:
            assert fix3[name]['before_sha256']==digest
            digest=fix3[name]['after_sha256']
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest,name


@pytest.mark.parametrize('cycle',[1,7,19])
def test_cli_aggressive_demo_sealed_checkpoint(tmp_path,cycle):
    from cordon2025.__main__ import main
    args=['demo','--config',str(ROOT/'CORDON_2025_AGGRESSIVE_CONFIG.json'),'--outer-cycle',str(cycle),
          '--output-root',str(tmp_path/'runs'),'--run-name','demo']
    assert main(args)==0
    folder=tmp_path/'runs/demo'
    effective=json.loads((folder/'AGGRESSIVE_EFFECTIVE_CONFIG.json').read_text())
    assert effective[META]['outer_cycle']==cycle
    summary=json.loads((folder/'AGGRESSIVE_DEMO_SUMMARY.json').read_text())
    assert summary['status']=='SYNTHETIC_AGGRESSIVE_DEMO_PASS'
    assert summary['comparison']['stage']==effective[META]['stage']['name']
    report=verify_run(folder)
    assert report['completed'] and not report['apply_permitted']
    ctx=json.loads((folder/'RUN_CHECKPOINT.json').read_text())['context']
    assert 'aggressive_source_policy' in ctx['inputs'] and 'aggressive_design_source' in ctx['inputs']


def test_no_automatic_live_data_or_scenario(tmp_path):
    from cordon2025.__main__ import main
    rc=main(['propose','--config',str(ROOT/'CORDON_2025_AGGRESSIVE_CONFIG.json'),
             '--output-root',str(tmp_path/'runs'),'--run-name','missing'])
    assert rc==2
    assert not (tmp_path/'runs/missing/AGGRESSIVE_REPORT.json').exists()


def test_preflight_does_not_claim_live(tmp_path):
    from cordon2025.__main__ import main
    rc=main(['preflight','--config',str(ROOT/'CORDON_2025_AGGRESSIVE_CONFIG.json'),
             '--output-root',str(tmp_path/'runs'),'--run-name','preflight'])
    assert rc==2
    report=json.loads((tmp_path/'runs/preflight/PREFLIGHT.json').read_text())
    assert report['status']=='NO_2025_PATH_CACHE'
    assert 'AGGRESSIVE_OFFLINE_ONLY' in report['gate']['blockers']


def test_standard_cli_does_not_silently_become_aggressive(tmp_path):
    from cordon2025.__main__ import main
    assert main(['preflight','--output-root',str(tmp_path/'runs'),'--run-name','std'])==2
    assert not (tmp_path/'runs/std/AGGRESSIVE_EFFECTIVE_CONFIG.json').exists()


def test_launcher_blocks_injected_visum(monkeypatch):
    import RUN_CORDON_AGGRESSIVE_OFFLINE as launcher
    monkeypatch.setattr(launcher,'Visum',object(),raising=False)
    with pytest.raises(RuntimeError,match='OFFLINE_ONLY'):launcher.main(['demo'])


def test_no_active_2022_process_reuse(monkeypatch):
    import RUN_CORDON_AGGRESSIVE_OFFLINE as launcher
    monkeypatch.setattr(sys,'_r1_15a2_calibration_busy',True,raising=False)
    with pytest.raises(RuntimeError,match='OFFLINE_ONLY'):launcher.main(['demo'])


def test_runtime_scenario_identity_includes_c17():
    inc=algebra_example([[100]],[100],base=[130]);c=read_config(ROOT/'CORDON_2025_AGGRESSIVE_CONFIG.json')
    a=propose(inc,c)
    budget=SharedBudget([(1,2)],[1,2],np.ones(2)*10,20,'BOUNDED_SCENARIO',{},True)
    b=propose(inc,c,budget)
    assert a.report['objective_scenario_sha256']!=b.report['objective_scenario_sha256']


def test_own_parent_import_not_other_running_release(monkeypatch):
    # Existing collision guard is not disabled by the aggressive launcher/policy.
    import types
    from cordon2025.common import parent_module,ContractError
    fake=types.ModuleType('r1_15a2_other_engine');fake.__file__='/other/2022/r1_15a2_other_engine.py'
    monkeypatch.setitem(sys.modules,'r1_15a2_other_engine',fake)
    with pytest.raises(ContractError,match='PARENT_MODULE_COLLISION'):parent_module('r1_15a2_core')
