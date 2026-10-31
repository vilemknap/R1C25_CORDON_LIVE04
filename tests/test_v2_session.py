from pathlib import Path
import json, subprocess, sys
import pytest
from cordon2025.common import ROOT,read_config
from cordon2025.io import write_json
from cordon2025 import session as mod
from cordon2025.session import RunSession,verify_run,capture_context,ROOT_MARKER,LOCK,CHECKPOINT


def test_new_root_owned_and_no_overwrite(tmp_path):
    root=tmp_path/'out'
    with RunSession('A',root) as s:
        assert s.folder==root/'A'
        assert (root/LOCK).is_file()
        s.start(read_config());write_json(s.folder/'X.json',{'x':1});s.checkpoint('DONE',completed=True)
    assert not (root/LOCK).exists()
    assert verify_run(root/'A')['completed']
    with pytest.raises(FileExistsError):
        with RunSession('A',root):pass
    assert not (root/LOCK).exists()


def test_parallel_writer_rejected_without_stealing(tmp_path):
    root=tmp_path/'out'
    with RunSession('A',root):
        before=(root/LOCK).read_bytes()
        with pytest.raises(ValueError,match='LOCKED'):
            with RunSession('B',root):pass
        assert (root/LOCK).read_bytes()==before
        assert not (root/'B').exists()


def test_stale_lock_is_not_automatically_deleted(tmp_path):
    root=tmp_path/'out';root.mkdir();write_json(root/ROOT_MARKER,{'model_year':2025,'authority_family':'CORDON_SDP'})
    (root/LOCK).write_text('other-session')
    with pytest.raises(ValueError,match='NO_AUTOMATIC_STEAL'):
        with RunSession('B',root):pass
    assert (root/LOCK).read_text()=='other-session'


def test_arbitrary_existing_root_not_adopted(tmp_path):
    (tmp_path/'2022.log').write_bytes(b'untouched')
    with pytest.raises(ValueError,match='UNOWNED'):
        with RunSession('B',tmp_path):pass
    assert not (tmp_path/ROOT_MARKER).exists()
    assert (tmp_path/'2022.log').read_bytes()==b'untouched'


def test_explicit_2022_directory_forbidden_even_empty(tmp_path):
    with pytest.raises(ValueError,match='2022_OUTPUT'):
        with RunSession('A',tmp_path/'2022'/'new'):pass
    assert not (tmp_path/'2022').exists()


@pytest.mark.parametrize('name',['../A','A/B','',str(Path('/tmp/test'))])
def test_invalid_run_names(name,tmp_path):
    with pytest.raises(ValueError,match='UNSAFE'):
        with RunSession(name,tmp_path/'out'):pass


def test_long_run_name_shortened_but_recorded(tmp_path):
    name='A'*250
    with RunSession(name,tmp_path/'out') as s:
        assert len(s.folder.name)<64
        assert json.loads((s.folder/'PATH_PREFLIGHT.json').read_text())['requested_name']==name


def test_bad_owner_marker_preserved(tmp_path):
    root=tmp_path/'out';root.mkdir();write_json(root/ROOT_MARKER,{'model_year':2022})
    before=(root/ROOT_MARKER).read_bytes()
    with pytest.raises(ValueError,match='OWNER_MISMATCH'):
        with RunSession('A',root):pass
    assert (root/ROOT_MARKER).read_bytes()==before and not (root/LOCK).exists()


def test_symlink_output_root_rejected(tmp_path):
    other=tmp_path/'other';other.mkdir();root=tmp_path/'out';root.symlink_to(other,target_is_directory=True)
    with pytest.raises(ValueError,match='SYMLINK'):
        with RunSession('A',root):pass
    assert list(other.iterdir())==[]


def test_input_changed_during_run_cannot_be_sealed(tmp_path):
    source=tmp_path/'input';source.write_bytes(b'first')
    with RunSession('A',tmp_path/'out') as s:
        s.start(read_config(),{'source':source})
        source.write_bytes(b'second')
        with pytest.raises(ValueError,match='INPUT_CHANGED'):s.checkpoint('DONE',completed=True)
        assert json.loads((s.folder/CHECKPOINT).read_text())['stage']=='STARTED'


def test_unsealed_and_modified_artifacts_rejected(tmp_path):
    with RunSession('A',tmp_path/'out') as s:
        s.start(read_config());write_json(s.folder/'X.json',{'x':1});s.checkpoint('DONE',completed=True)
    x=s.folder/'X.json';before=x.read_bytes();x.write_bytes(b'bad')
    with pytest.raises(ValueError,match='ARTIFACT_CHANGED'):verify_run(s.folder)
    x.write_bytes(before);(s.folder/'UNSEALED').write_bytes(b'x')
    with pytest.raises(ValueError,match='UNSEALED_ARTIFACTS'):verify_run(s.folder)


def test_code_change_is_not_filename_only_resume(tmp_path,monkeypatch):
    with RunSession('A',tmp_path/'out') as s:
        s.start(read_config());s.checkpoint('DONE',completed=True)
    monkeypatch.setattr(mod,'code_identity',lambda:'0'*64)
    with pytest.raises(ValueError,match='CODE_CHANGED'):verify_run(s.folder)


def test_failed_checkpoint_write_does_not_destroy_previous(tmp_path,monkeypatch):
    with RunSession('A',tmp_path/'out') as s:
        s.start(read_config());before=(s.folder/CHECKPOINT).read_bytes()
        def fail(*a,**k):raise OSError('locked')
        monkeypatch.setattr(mod,'write_json',fail)
        with pytest.raises(OSError,match='locked'):s.checkpoint('DONE',completed=True)
        assert (s.folder/CHECKPOINT).read_bytes()==before


def test_primary_error_not_masked_by_bad_lock_owner(tmp_path):
    root=tmp_path/'out'
    with pytest.raises(RuntimeError,match='original'):
        with RunSession('A',root):
            (root/LOCK).write_text('replaced-by-other')
            raise RuntimeError('original')
    assert (root/LOCK).read_text()=='replaced-by-other'


def test_unsafe_checkpoint_relative_path_rejected(tmp_path):
    with RunSession('A',tmp_path/'out') as s:
        s.start(read_config());s.checkpoint('DONE',completed=True)
    p=s.folder/CHECKPOINT;v=json.loads(p.read_text());v['artifacts'][0]['path']='../outside';write_json(p,v)
    with pytest.raises(ValueError,match='INVALID_CHECKPOINT_ARTIFACT_PATH'):verify_run(s.folder)


def test_cli_demo_and_verified_restart_are_not_solver_resume(tmp_path):
    root=tmp_path/'out'
    cmd=[sys.executable,'-m','cordon2025','demo','--run-name','DEMO','--output-root',str(root)]
    p=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=45)
    assert p.returncode==0,p.stderr
    result=verify_run(root/'DEMO')
    assert result['completed'] and not result['live_visum_tested']
    assert 'NOT_SOLVER_CONTINUATION' in result['restart_mode']
    v=subprocess.run([sys.executable,'-m','cordon2025','verify-run','--run-directory',str(root/'DEMO')],cwd=ROOT,capture_output=True,text=True,timeout=20)
    assert v.returncode==0,v.stderr
    assert 'OFFLINE_RUN_CHECKPOINT_VERIFIED' in v.stdout


def test_cli_missing_cache_fails_cleanly_and_unlocks(tmp_path):
    root=tmp_path/'out'
    p=subprocess.run([sys.executable,'-m','cordon2025','inspect-cache','--run-name','MISSING','--output-root',str(root)],cwd=ROOT,capture_output=True,text=True,timeout=20)
    assert p.returncode==2 and not (root/LOCK).exists()
    status=json.loads((root/'MISSING/COMMAND_STATUS.json').read_text())
    assert status['status']=='BLOCKED' and status['reason']=='NO_2025_PATH_CACHE'


def test_cli_preflight_is_not_false_pass(tmp_path):
    p=subprocess.run([sys.executable,'-m','cordon2025','preflight','--run-name','PREFLIGHT','--output-root',str(tmp_path/'out')],cwd=ROOT,capture_output=True,text=True,timeout=20)
    assert p.returncode==2
    assert json.loads(p.stdout)['status']=='NO_2025_PATH_CACHE'
