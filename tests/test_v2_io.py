from pathlib import Path
import errno,io as stdio,json,os,subprocess,sys
import numpy as np
import pytest
from cordon2025 import io
from cordon2025.common import ROOT,write_json,write_csv,write_npz,parent_module,ContractError


def no_delay(monkeypatch):
    monkeypatch.setattr(io,'ATTEMPTS',3)
    monkeypatch.setattr(io.donor().time,'sleep',lambda *_:None)


@pytest.mark.parametrize('kind',['json','csv','npz'])
def test_existing_output_not_corrupted_on_replace_exhaustion(tmp_path,monkeypatch,kind):
    target=tmp_path/('result.'+kind);target.write_bytes(b'last-good')
    def fail(*args):raise PermissionError(errno.EACCES,'locked')
    no_delay(monkeypatch);monkeypatch.setattr(io.donor(),'_REAL_REPLACE',fail)
    with pytest.raises(PermissionError):
        if kind=='json':write_json(target,{'ok':True})
        elif kind=='csv':write_csv(target,[{'x':1}])
        else:write_npz(target,x=np.arange(10))
    assert target.read_bytes()==b'last-good'
    assert not list(tmp_path.glob('.r1*.tmp'))


def test_retry_transient_then_success(tmp_path,monkeypatch):
    original=io.donor()._REAL_REPLACE;calls=[]
    def transient(a,b):
        calls.append((a,b))
        if len(calls)<3:raise PermissionError(errno.EACCES,'sharing lock')
        return original(a,b)
    no_delay(monkeypatch);monkeypatch.setattr(io.donor(),'_REAL_REPLACE',transient)
    write_json(tmp_path/'a.json',{'value':4})
    assert len(calls)==3 and io.read_json(tmp_path/'a.json')=={'value':4}


def test_nontransient_disk_full_not_retried(tmp_path,monkeypatch):
    calls=[]
    def fail(*a):calls.append(a);raise OSError(errno.ENOSPC,'disk full')
    monkeypatch.setattr(io.donor(),'_REAL_REPLACE',fail)
    with pytest.raises(OSError):write_json(tmp_path/'a.json',{})
    assert len(calls)==1


def test_nan_json_not_silently_stringified_or_null(tmp_path):
    p=tmp_path/'a.json';p.write_text('old')
    with pytest.raises(ValueError):write_json(p,{'bad':float('nan')})
    assert p.read_text()=='old'
    p.write_text('{"x":NaN}')
    with pytest.raises(ValueError,match='NONFINITE'):io.read_json(p)


def test_csv_schema_error_preserves_old(tmp_path):
    p=tmp_path/'a.csv';p.write_text('old')
    with pytest.raises(ValueError):write_csv(p,[{'extra':2}],fields=['required'])
    assert p.read_text()=='old'


@pytest.mark.parametrize('data',[np.array([float('inf')]),np.array([{'a':1}],dtype=object)])
def test_npz_unsafe_array_rejected(tmp_path,data):
    with pytest.raises(ValueError):write_npz(tmp_path/'a.npz',x=data)
    assert not (tmp_path/'a.npz').exists()


def test_npz_atomic_readback(tmp_path):
    p=tmp_path/'a.npz';write_npz(p,x=np.arange(7))
    with np.load(p,allow_pickle=False) as d:assert np.array_equal(d['x'],np.arange(7))


def test_postpublish_corruption_fails_closed(tmp_path,monkeypatch):
    original=io.donor()._REAL_REPLACE
    def corrupt(a,b):original(a,b);Path(b).write_text('corrupt')
    monkeypatch.setattr(io.donor(),'_REAL_REPLACE',corrupt)
    with pytest.raises(OSError,match='READBACK_HASH_MISMATCH'):write_json(tmp_path/'a.json',{'ok':1})


def test_short_siblings_and_long_local_path(tmp_path):
    deep=tmp_path
    while len(str(deep))<300:deep/='abcdef123456'
    target=deep/('long_evidence_filename_'*4+'result.json')
    write_json(target,{'ok':True})
    assert io.read_json(target)['ok']
    assert len(io.donor()._short_temp_path(target).name)<30
    assert not list(deep.glob('.r1*.tmp'))


def test_windows_local_and_unc_native_boundary():
    assert io.native_path(r'C:\model\a.json',os_name='nt').startswith('\\\\?\\C:')
    assert io.native_path(r'\\server\share\a.json',os_name='nt').startswith('\\\\?\\UNC\\server\\share')


def test_telemetry_cannot_abort_but_critical_must(tmp_path,monkeypatch):
    def fail(*a,**k):raise PermissionError('permanent')
    monkeypatch.setattr(io,'write_json',fail)
    assert io.telemetry_json(tmp_path/'perf.json',{})['published'] is False
    with pytest.raises(PermissionError):write_json(tmp_path/'critical.json',{})


def test_failure_finalizer_preserves_primary_when_both_outputs_fail(tmp_path,monkeypatch):
    def fail(*a,**k):raise OSError('secondary io')
    monkeypatch.setattr(io,'write_json',fail);monkeypatch.setattr(io,'write_text',fail)
    stderr=stdio.StringIO();r=io.safe_failure_report(tmp_path,ValueError('PRIMARY'),traceback_text='trace',emergency_stream=stderr)
    assert r['reason']=='PRIMARY' and len(r['reporting_errors'])==2
    assert json.loads(stderr.getvalue())['exception']=='ValueError'


def test_missing_copy_is_critical_error(tmp_path):
    with pytest.raises(FileNotFoundError):io.copy_verified(tmp_path/'absent',tmp_path/'dst')


def test_copy_exact_and_existing_destination(tmp_path):
    src=tmp_path/'src';src.write_bytes(b'updated')
    dst=tmp_path/'dst';dst.write_bytes(b'old');io.copy_verified(src,dst)
    assert dst.read_bytes()==src.read_bytes()


def test_no_parent_global_patch_after_cordon_io(tmp_path):
    parent_module('r1_15a2_core')
    rt=parent_module('r1_15a2_runtime_v1');original=rt.write_json
    write_json(tmp_path/'a.json',{'x':1})
    assert rt.write_json is original and rt.write_json is not io.donor().critical_runtime_write_json


def test_other_parent_dependency_collision_rejected_clean_process():
    code="""
import sys,types
from cordon2025.common import parent_module,ContractError
m=types.ModuleType('r1_15a2_runtime_v1');m.__file__='/tmp/another_2022/r1_15a2_runtime_v1.py'
sys.modules[m.__name__]=m
try:parent_module('r1_15a2_core')
except ContractError as e:assert 'PARENT_MODULE_COLLISION' in str(e)
else:raise AssertionError('collision not rejected')
"""
    p=subprocess.run([sys.executable,'-c',code],cwd=ROOT,capture_output=True,text=True)
    assert p.returncode==0,p.stderr


def test_failed_incidence_does_not_publish_partial_hits(tmp_path):
    from test_incidence import fixture
    from cordon2025.incidence import build_from_snapshot
    p,m,e,c=fixture(tmp_path);e['dseg_totals']['NATIVE_CW']+=1
    target=tmp_path/'hits.csv';target.write_text('previous-valid')
    with pytest.raises(ContractError):build_from_snapshot(p,m,c,e,hits_output=target)
    assert target.read_text()=='previous-valid'


class UnprintableError(Exception):
    def __str__(self):raise ValueError('str failed')
    def __repr__(self):raise ValueError('repr failed')


def test_failure_report_survives_unprintable_primary(tmp_path):
    from cordon2025.io import safe_failure_report
    result=safe_failure_report(tmp_path,UnprintableError())
    assert result['exception']=='UnprintableError'
    assert result['reason']=='<unprintable UnprintableError>'
    assert not result['reporting_errors']


def test_telemetry_survives_unprintable_secondary(monkeypatch,tmp_path):
    import cordon2025.io as io
    def fail(*args,**kwargs):raise UnprintableError()
    monkeypatch.setattr(io,'write_json',fail)
    result=io.telemetry_json(tmp_path/'log.json',{})
    assert result['published'] is False
    assert result['error']=='<unprintable UnprintableError>'
