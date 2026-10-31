from pathlib import Path
import sys,types
import pytest
from fake_visum_startup import FakeVisum
from cordon2025 import diagfast_runtime as runtime
from cordon2025 import diagfast_telemetry as metrics
from cordon2025 import visum_startup as legacy
from cordon2025.common import parent_module


def test_optional_psutil_access_error_is_not_capture_error(monkeypatch):
    class Denied(Exception):pass
    def bad():raise Denied('permission denied')
    monkeypatch.setitem(sys.modules,'psutil',types.SimpleNamespace(Process=bad))
    assert metrics._io_counters() is None
    assert metrics.Telemetry().report()['process_io_delta'] is None


def test_optional_resource_error_is_not_capture_error(monkeypatch):
    def bad(*a):raise OSError('not available')
    monkeypatch.setitem(sys.modules,'resource',types.SimpleNamespace(getrusage=bad,RUSAGE_SELF=0))
    assert metrics.Telemetry().report()['peak_process_rss_mib'] is None

@pytest.mark.parametrize('backend',['LEGACY','FAST_EXACT'])
def test_failed_final_timing_preserves_success(tmp_path,monkeypatch,backend):
    def bad(*a):raise OSError('timing report unavailable')
    monkeypatch.setattr(metrics.Telemetry,'report',bad)
    host=FakeVisum(tmp_path/'model')
    result=runtime.run(host,backend=backend,output_root=tmp_path/'runs',options={'min_free_disk_gib':0})
    assert result['status']=='VISUM_SAVED_PATH_DIAGNOSTICS_COMPLETE'
    assert 'timing report unavailable' in result['diagfast_telemetry_errors'][0]
    assert not host.writes

@pytest.mark.parametrize('backend',['LEGACY','FAST_EXACT'])
def test_failed_final_timing_preserves_primary_error(tmp_path,monkeypatch,backend):
    def bad(*a):raise OSError('secondary telemetry error')
    monkeypatch.setattr(metrics.Telemetry,'report',bad)
    host=FakeVisum(tmp_path/'model');two=parent_module('r1_15a2_two_mode_v238')
    def corrupt(*a,**kw):raise ValueError('PRIMARY_CAPTURE_FAILURE')
    monkeypatch.setattr(two.TwoModeRouteCollector,'add_geometry',corrupt)
    with pytest.raises(ValueError,match='PRIMARY_CAPTURE_FAILURE'):
        runtime.run(host,backend=backend,output_root=tmp_path/'runs',options={'min_free_disk_gib':0})
    assert not list((tmp_path/'runs').rglob('SNAPSHOT_EVIDENCE.json'))


def test_scratch_stat_failure_still_runs_original_cleanup(tmp_path,monkeypatch):
    target=tmp_path/'proof.sqlite';target.write_bytes(b'a')
    original=Path.stat;seen=[]
    def bad(self,*a,**kw):
        if self==target:raise OSError('measurement inaccessible')
        return original(self,*a,**kw)
    def cleanup(*a):seen.append(a)
    monkeypatch.setattr(legacy,'_cleanup_store',cleanup)
    with runtime.overlay('LEGACY',{'fast_parent_page_size':256,'fast_geometry_page_size':256,'instrumentation':True},metrics.Telemetry()):
        monkeypatch.setattr(Path,'stat',bad)
        try:raise ValueError('primary')
        except ValueError:
            legacy._cleanup_store(None,target,types.SimpleNamespace(state={}))
    assert len(seen)==1
