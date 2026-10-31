"""Isolated, reversible DIAGFAST overlay. Parent files and legacy startup unchanged."""
from __future__ import annotations
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
import importlib
import threading
import time
from .common import ROOT, require, parent_module
from .io import write_json, sha256, exception_text, read_json
from . import visum_startup as legacy
from . import diagfast_pages
from .diagfast_telemetry import Telemetry

RELEASE='R1_2025_CORDON_COM_DIAGFAST_EXACT_V1_20261023'
_LOCK=threading.Lock()

@contextmanager
def overlay(backend, fast_options, telemetry):
    """Only used inside original injected-instance isolation; restore on all exits."""
    require(backend in ('LEGACY','FAST_EXACT'),'UNKNOWN_DIAGFAST_BACKEND')
    require(_LOCK.acquire(blocking=False),'DIAGFAST_RUNTIME_ALREADY_ACTIVE')
    originals=[];controls=[];state={'stage':'STARTUP'}
    def install(owner,name,value):
        originals.append((owner,name,getattr(owner,name)));setattr(owner,name,value)
    def wrapped(owner,name,label):
        old=getattr(owner,name)
        @wraps(old)
        def call(*a,**kw):
            with telemetry.span(label):return old(*a,**kw)
        install(owner,name,call)
    try:
        two=parent_module('r1_15a2_two_mode_v238')
        base_control=legacy.ReadControl
        class Control(base_control):
            def __init__(self,*a,**kw):
                super().__init__(*a,**kw);controls.append(self)
            def checkpoint(self,*a,**kw):
                event=kw.get('com_retry_event') or kw.get('com_read_retry')
                if event:
                    telemetry.count('com_retry_events')
                    telemetry.count('com_retry_requested_backoff_s',float(event.get('delay_seconds',0)))
                return super().checkpoint(*a,**kw)
        install(legacy,'ReadControl',Control)
        old_call=legacy._call
        def comcall(func,control,opt,label):
            def measured():
                group='MATRIX_GETVALUES' if label.startswith('OD_VALUES_') else 'COM_HELPER_TRANSACTION'
                if group=='MATRIX_GETVALUES':
                    telemetry.count('matrix_getvalues_attempts')
                    telemetry.count('matrix_getvalues.'+label[len('OD_VALUES_'):])
                if label.startswith('PREFLIGHT_CreatePrT'):
                    telemetry.count('preflight_provider_invoke_attempts')
                    telemetry.count('provider_invoke_attempts')
                with telemetry.span(state['stage']+'.'+group):return func()
            return old_call(measured,control,opt,label)
        install(legacy,'_call',comcall)
        def bounded(obj,columns,st,control,opt,phase,**details):
            return diagfast_pages.rows(obj,columns,st,control,opt,phase,
                telemetry=telemetry,fast_options=fast_options,backend=backend,**details)
        install(legacy,'_bounded_rows',bounded)
        for name,label in (('_network','NETWORK_IDENTITY'),('_segments','DSEG_INVENTORY'),
                ('_new_list','LIST_CREATE'),('_od_parity','CAPTURE_OD_PARITY'),
                ('_geometry_equal','CAPTURE_PROOF_EQUALITY')):
            wrapped(legacy,name,label)
        matrix_reads={}
        old_matrix=legacy._matrix
        def matrix(ds,*a,**kw):
            code=ds['norm_code'];matrix_reads[code]=matrix_reads.get(code,0)+1
            phase={1:'PREFLIGHT_MATRIX',2:'CAPTURE_INITIAL_MATRIX',3:'CAPTURE_FINAL_MATRIX_READBACK'}.get(matrix_reads[code],'EXTRA_MATRIX_READ')
            previous=state['stage'];state['stage']=phase
            try:
                with telemetry.span(phase):return old_matrix(ds,*a,**kw)
            finally:state['stage']=previous
        install(legacy,'_matrix',matrix)
        original_init=two.TwoModeRouteCollector.__init__
        def collector_init(self,*a,**kw):
            with telemetry.span('COLLECTOR_CREATE'):
                original_init(self,*a,**kw)
            if telemetry.enabled:
                from .diagfast_sql import MeasuredConnection
                self.db=MeasuredConnection(self.db,telemetry,Path(self.route_db_path).name.startswith('proof_'))
        install(two.TwoModeRouteCollector,'__init__',collector_init)
        old_npz=legacy.write_npz
        def npz(*a,**kw):
            with telemetry.span('CAPTURE_MATRIX_NPZ_WRITE'):return old_npz(*a,**kw)
        install(legacy,'write_npz',npz)
        old_pre=legacy.preflight
        def pre(*a,**kw):
            state['stage']='PREFLIGHT'
            with telemetry.span('PREFLIGHT_TOTAL'):return old_pre(*a,**kw)
        install(legacy,'preflight',pre)
        old_capture=legacy.capture
        def capture(*a,**kw):
            state['stage']='CAPTURE'
            with telemetry.span('CAPTURE_TOTAL'):
                if backend=='FAST_EXACT':
                    from .diagfast_capture import capture as fast_capture
                    return fast_capture(*a,**kw,telemetry=telemetry)
                return old_capture(*a,**kw)
        install(legacy,'capture',capture)
        for method in ('add_parents','add_geometry'):
            old=getattr(two.TwoModeRouteCollector,method)
            def measure(old=old,method=method):
                @wraps(old)
                def call(self,*a,**kw):
                    proof=Path(self.route_db_path).name.startswith('proof_')
                    label=('LEGACY_PROOF_' if proof else 'REPRESENTATIVE_')+method.upper()
                    if proof and method=='add_parents':telemetry.count('scratch_sqlite_stores')
                    with telemetry.span(label):return old(self,*a,**kw)
                return call
            install(two.TwoModeRouteCollector,method,measure())
        old_cleanup=legacy._cleanup_store
        def cleanup(store,path,control):
            if path is not None:
                try:
                    size=Path(path).stat().st_size
                    telemetry.count('legacy_proof_final_file_bytes_sum',size)
                    telemetry.counters['legacy_proof_file_peak_bytes']=max(telemetry.counters['legacy_proof_file_peak_bytes'],size)
                except OSError as exc:
                    telemetry.sample({'measurement':'scratch_file_size','unavailable':exception_text(exc)})
            with telemetry.span('CAPTURE_SCRATCH_CLEANUP'):return old_cleanup(store,path,control)
        install(legacy,'_cleanup_store',cleanup)
        empirical=importlib.import_module('cordon2025.__main__')
        wrapped(empirical,'empirical_run','CAPTURE_EMPIRICAL_INCIDENCE')
        old_write=legacy.write_json
        def result_write(path,value):
            if Path(path).name=='00_RESULT.json':
                value=dict(value,diagnostics_backend=backend,diagfast_release=RELEASE,
                    diagfast_native_acceptance='LIVE_PENDING',diagfast_effective_options=fast_options)
            with telemetry.span('CAPTURE_REPORT_IO'):return old_write(path,value)
        install(legacy,'write_json',result_write)
        session=importlib.import_module('cordon2025.session')
        wrapped(session.RunSession,'checkpoint','CHECKPOINT_TOTAL_INCLUDING_HASH_IO')
        # Count bytes explicitly read by the capture seal/checkpoint hash aliases.
        for module in (legacy,session):
            if not hasattr(module,'sha256'):continue
            old_sha=module.sha256
            def hash_wrap(old=old_sha):
                def call(path):
                    with telemetry.span('FILE_SHA256_IO'):
                        value=old(path)
                    try:telemetry.count('explicit_file_sha256_bytes',Path(path).stat().st_size)
                    except OSError as exc:
                        telemetry.sample({'measurement':'hash_bytes','unavailable':exception_text(exc)})
                    return value
                return call
            install(module,'sha256',hash_wrap())
        yield controls
    finally:
        for owner,name,old in reversed(originals):setattr(owner,name,old)
        _LOCK.release()


def run(visum,*,backend='FAST_EXACT',action='CAPTURE_DIAGNOSTICS',output_root=None,
        options=None,fast_options=None):
    require(backend in ('LEGACY','FAST_EXACT'),'UNKNOWN_DIAGFAST_BACKEND')
    require(action in legacy.ACTIONS,'UNSUPPORTED_VISUM_ACTION_APPLY_NOT_IMPLEMENTED')
    fast_options=diagfast_pages.settings(fast_options)
    opt=legacy.settings(options)
    if backend=='FAST_EXACT':require(opt['full_geometry_check'],'FAST_REQUIRES_FULL_GEOMETRY_CHECK')
    telemetry=Telemetry(fast_options['instrumentation']);controls=[];result=None
    try:
        with telemetry.span('CAPTURE_DIAGNOSTICS_TOTAL'):
            with overlay(backend,fast_options,telemetry) as controls:
                result=legacy.run(visum,action=action,output_root=output_root,options=options)
        result=dict(result,diagnostics_backend=backend,diagfast_release=RELEASE,
                    diagfast_native_acceptance='LIVE_PENDING',diagfast_effective_options=fast_options)
        return result
    finally:
        # A separately sealed post-checkpoint telemetry sidecar. Never edits the
        # original completed RUN_CHECKPOINT or any already-hashed result file.
        if controls:
            folder=controls[-1].folder
            try:
                timing=telemetry.report()
                timing.update(backend=backend,effective_options=fast_options,
                    status='MEASURED_COMPLETE' if result is not None else 'MEASURED_FAILED',
                    native_measurement_claim=False,origin='RUNTIME_COUNTERS_TRANSPORT_NOT_CERTIFIED',
                    failure_context=controls[-1].state.get('diagfast_failure'))
                write_json(folder/'DIAGFAST_TIMING.json',timing)
                seal={'schema':'CORDON_DIAGFAST_POST_CHECKPOINT_AUDIT_V1',
                    'timing_sha256':sha256(folder/'DIAGFAST_TIMING.json'),
                    'original_checkpoint_sha256':sha256(folder/'RUN_CHECKPOINT.json') if (folder/'RUN_CHECKPOINT.json').exists() else None,
                    'capture_completed':result is not None,'apply_permitted':False}
                write_json(folder/'DIAGFAST_AUDIT_SEAL.json',seal)
            except Exception as exc:
                # Telemetry cannot replace a primary model/COM/contract failure.
                controls[-1].telemetry_failures.append('DIAGFAST_TIMING:'+exception_text(exc))
                if result is not None:
                    result['diagfast_telemetry_errors']=list(controls[-1].telemetry_failures)
