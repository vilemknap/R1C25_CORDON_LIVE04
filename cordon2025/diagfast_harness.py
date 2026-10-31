"""Read-only paired LEGACY/FAST harness; injectable host, no model discovery."""
from __future__ import annotations
from pathlib import Path
import json,platform,statistics,sys,time,uuid
from .common import require,parent_module
from .io import write_json,read_json,sha256,mkdir
from .session import default_root,RunSession
from .diagfast_runtime import run
from .diagfast_parity import compare_runs


def paired(visum,*,output_root=None,page_sizes=(256,),repetitions=1,options=None):
    require(type(repetitions) is int and 1<=repetitions<=10,'INVALID_PARITY_REPETITIONS')
    require(page_sizes and all(type(n) is int and n in (256,512,1024) for n in page_sizes),
            'INVALID_PARITY_PAGE_SIZES')
    # Parent RunSession owns the harness root, serializes all pairs and retains
    # no stale objects/matrices across an intervening capture.
    from .common import ROOT,read_config
    cfg=read_config(ROOT/'CORDON_2025_AGGRESSIVE_CONFIG.json')
    with RunSession('DIAGFAST_PARITY_'+uuid.uuid4().hex[:10],output_root) as session:
        session.start(cfg,{'config':ROOT/'CORDON_2025_AGGRESSIVE_CONFIG.json'})
        root=session.folder
        api=parent_module('r1_15a2_live_api_audit')
        source=Path(api.current_version_file(visum))
        require(source.is_file(),'PARITY_REQUIRES_SAVED_REFERENCE_VERSION_COPY')
        source_hash=sha256(source)
        pairs=[]
        try:
            for size in page_sizes:
                for rep in range(repetitions):
                    if (root/'STOP_REQUESTED').exists():raise RuntimeError('USER_STOP_REQUESTED')
                    order=('LEGACY','FAST_EXACT') if rep%2==0 else ('FAST_EXACT','LEGACY')
                    results={}
                    for backend in order:
                        require(Path(api.current_version_file(visum))==source and sha256(source)==source_hash,
                                'PARITY_VERSION_FILE_CHANGED')
                        r=run(visum,backend=backend,options=options,output_root=root/'captures',
                              fast_options={'fast_parent_page_size':size,'fast_geometry_page_size':size})
                        results[backend]=Path(r['output_directory'])
                        require(Path(api.current_version_file(visum))==source and sha256(source)==source_hash,
                                'PARITY_VERSION_FILE_CHANGED')
                    diff=compare_runs(results['LEGACY'],results['FAST_EXACT'],
                         output=root/('PARITY_'+str(size)+'_'+str(rep+1)+'.json'))
                    timings={k:read_json(v/'DIAGFAST_TIMING.json') for k,v in results.items()}
                    pairs.append({'page_size':size,'repetition':rep+1,'order':list(order),
                        'status':diff['status'],'directories':{k:str(v) for k,v in results.items()},
                        'timing':timings})
                    write_json(root/'PAIRED_PROGRESS.json',{'pairs':pairs,'apply_permitted':False})
                    require(diff['status']=='PARITY_PASS','DIAGFAST_PAIRED_PARITY_FAIL')
            summary=[]
            for size in page_sizes:
                selected=[p for p in pairs if p['page_size']==size]
                a=[p['timing']['LEGACY']['stages']['CAPTURE_DIAGNOSTICS_TOTAL']['wall_inclusive_s'] for p in selected]
                b=[p['timing']['FAST_EXACT']['stages']['CAPTURE_DIAGNOSTICS_TOTAL']['wall_inclusive_s'] for p in selected]
                summary.append({'page_size':size,'pairs':len(a),'legacy_times_s':a,'fast_times_s':b,
                    'legacy_median_s':statistics.median(a),'fast_median_s':statistics.median(b),
                    'median_speedup':statistics.median(a)/statistics.median(b)})
            report={'status':'PARITY_PASS','schema':'CORDON_DIAGFAST_LIVE_HARNESS_V1',
                'source_version':str(source),'source_file_sha256':source_hash,
                'platform':platform.platform(),'python_executable':sys.executable,
                'transport_origin':getattr(visum,'__class__',type(visum)).__module__,
                'pairs':pairs,'summary':summary,'apply_permitted':False,'assignment_executed':False,
                'native_acceptance':'REQUIRES_REVIEW_OF_INJECTED_HOST_AND_ALL_NATIVE_GATES',
                'output_directory':str(root)}
            write_json(root/'PARITY_REPORT.json',report)
            session.checkpoint('PAIRED_READONLY_AUDIT_COMPLETE',completed=True)
            return report
        except BaseException as exc:
            from .io import safe_failure_report
            import traceback
            safe_failure_report(root,exc,traceback_text=traceback.format_exc())
            raise
