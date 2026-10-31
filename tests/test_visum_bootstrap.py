"""Host/entry isolation tests. All Visum objects are explicitly simulated."""
from pathlib import Path
from types import ModuleType,SimpleNamespace
import json
import sys
import runpy
import pytest
import cordon_visum_bootstrap as boot
from cordon2025.common import ROOT
from fake_visum_startup import FakeVisum

@pytest.fixture
def env(tmp_path,monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path/'local'))
    monkeypatch.setattr(sys,'argv',['Visum.exe','--an-option-not-for-argparse'])
    return tmp_path

def test_foreign_modules_and_sys_path_restored_on_exception(env,monkeypatch):
    mod=ModuleType('r1_15a2_other_release');mod.__file__='/old/2022/r1_15a2_other_release.py'
    monkeypatch.setitem(sys.modules,mod.__name__,mod)
    before=list(sys.path);saved=sys.modules.get('cordon2025')
    with pytest.raises(RuntimeError,match='sentinel'):
        with boot.isolated_imports(ROOT):
            assert mod.__name__ not in sys.modules
            import cordon2025
            assert cordon2025 is not saved
            raise RuntimeError('sentinel')
    assert sys.modules[mod.__name__] is mod and sys.path==before
    assert sys.modules.get('cordon2025') is saved
    assert not hasattr(sys,'_r1_cordon2025_busy')

@pytest.mark.parametrize('flag',boot.BUSY)
def test_busy_rejected_without_deleting_host_modules(env,monkeypatch,flag):
    monkeypatch.setattr(sys,flag,True,raising=False);before=dict(sys.modules)
    r=boot.launch({'Visum':FakeVisum(env/'model')},ROOT,output_root=env/'run')
    assert r['status']=='STARTUP_BLOCKED' and 'ACTIVE' in r['reason']
    assert all(sys.modules.get(k) is v for k,v in before.items())

@pytest.mark.parametrize('namespace',[{}, {'Visum':None}, {'Visum':object(),'COM':object()}])
def test_missing_or_ambiguous_instance_never_activates_COM(env,namespace):
    r=boot.launch(namespace,ROOT)
    assert r['status']=='STARTUP_BLOCKED'
    assert not r['apply_permitted']
    assert (Path(r['boot_log_directory'])/'00_BOOT_RESULT.json').is_file()

def test_no_native_model_write_from_complete_entry(env,monkeypatch):
    v=FakeVisum(env/'model');old=list(sys.path)
    r=boot.launch({'Visum':v},ROOT,output_root=env/'runs')
    assert r['status']=='VISUM_READONLY_PREFLIGHT_PASS',r
    assert not v.writes and not v.unbounded
    assert sys.path==old and not hasattr(sys,'_r1_cordon2025_busy')

def test_repeat_entry_does_not_reuse_old_module_or_run(env):
    v=FakeVisum(env/'model');old=sys.modules.get('cordon2025')
    a=boot.launch({'Visum':v},ROOT,output_root=env/'runs')
    b=boot.launch({'Visum':v},ROOT,output_root=env/'runs')
    assert a['status']==b['status']=='VISUM_READONLY_PREFLIGHT_PASS'
    assert a['output_directory']!=b['output_directory']
    assert sys.modules.get('cordon2025') is old

def test_missing_numpy_has_clear_diagnostic_no_install(env,monkeypatch):
    original=boot.importlib.import_module
    def intercepted(name,*a,**kw):
        if name=='numpy':raise ImportError('not installed')
        return original(name,*a,**kw)
    monkeypatch.setattr(boot.importlib,'import_module',intercepted)
    r=boot.launch({'Visum':FakeVisum(env/'model')},ROOT,output_root=env/'runs')
    assert r['status']=='STARTUP_BLOCKED' and 'NUMPY_UNAVAILABLE' in r['reason']

def test_missing_manifest_has_boot_diagnostics(env):
    folder=env/'missing';folder.mkdir()
    r=boot.launch({'Visum':object()},folder)
    assert r['status']=='STARTUP_BLOCKED' and Path(r['boot_log_directory'],'99_TRACEBACK.txt').exists()

def test_release_verifier_path_not_preimported_fake(env,monkeypatch):
    fake=ModuleType('verify_release');fake.verify=lambda *_:{'status':'RELEASE_INTEGRITY_PASS'}
    monkeypatch.setitem(sys.modules,'verify_release',fake)
    r=boot.launch({'Visum':object()},env/'missing')
    assert r['status']=='STARTUP_BLOCKED'
    assert sys.modules['verify_release'] is fake

def test_run_from_different_cwd_without_file_global(env,monkeypatch):
    v=FakeVisum(env/'model');monkeypatch.chdir(env)
    p=ROOT/'RUN_CORDON_2025_VISUM.py'
    namespace={'Visum':v,'__name__':'__main__'}
    exec(compile(p.read_text(),str(p),'exec'),namespace)
    assert namespace['RESULT']['status']=='VISUM_READONLY_PREFLIGHT_PASS'
    assert not v.writes

def test_capture_entry_no_system_exit_or_argument_parsing(env,monkeypatch):
    v=FakeVisum(env/'model');monkeypatch.chdir(env)
    # LOCALAPPDATA output selection on native Windows; Linux test default is sandboxed below.
    from cordon2025 import session
    p=ROOT/'RUN_CORDON_2025_CAPTURE.py';ns={'Visum':v,'__name__':'__main__'}
    exec(compile(p.read_text(),str(p),'exec'),ns)
    assert ns['RESULT']['status']=='VISUM_SAVED_PATH_DIAGNOSTICS_COMPLETE',ns['RESULT']
    assert not v.writes

def test_hub_or_external_context_without_injected_visum_is_blocked(env):
    p=ROOT/'RUN_CORDON_2025_VISUM.py';ns={'__name__':'__main__'}
    exec(compile(p.read_text(),str(p),'exec'),ns)
    assert ns['RESULT']['status']=='STARTUP_BLOCKED' and 'NO_INJECTED_VISUM' in ns['RESULT']['reason']

def test_visum_startup_does_not_require_offline_spreadsheet_or_oracle_packages(tmp_path):
    import subprocess,os
    code='''
import importlib.abc,sys
class Guard(importlib.abc.MetaPathFinder):
 def find_spec(self,name,path=None,target=None):
  if name.split('.')[0] in ('openpyxl','scipy','pandas'):raise ImportError('EXPLICITLY_ABSENT:'+name)
sys.meta_path.insert(0,Guard())
from cordon2025.visum_startup import preflight,capture
from cordon2025.__main__ import empirical_run
print('STARTUP_IMPORT_WITHOUT_OPENPYXL_SCIPY_PANDAS_PASS')
'''
    p=subprocess.run([sys.executable,'-c',code],cwd=ROOT,text=True,capture_output=True,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'))
    assert p.returncode==0,p.stderr
    assert 'PASS' in p.stdout
