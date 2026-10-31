"""Reproducible SYNTHETIC COM benchmark; use live harness for native claims."""
from pathlib import Path
import argparse,json,subprocess,sys,time,statistics,platform,os
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--worker',choices=['LEGACY','FAST_EXACT']);p.add_argument('--page',type=int,default=256)
    p.add_argument('--routes',type=int,default=3000);p.add_argument('--zones',type=int,default=681)
    p.add_argument('--repetitions',type=int,default=3);p.add_argument('--no-instrumentation',action='store_true')
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    if a.worker:
        from diagfast_scaled_visum import ScaledVisum
        from cordon2025.diagfast_runtime import run
        from cordon2025.io import write_json,read_json
        t=time.perf_counter();host=ScaledVisum(a.output/'model',a.routes,a.zones)
        fixture_s=time.perf_counter()-t;t=time.perf_counter()
        result=run(host,backend=a.worker,output_root=a.output/'runs',options={'min_free_disk_gib':0},
             fast_options={'fast_parent_page_size':a.page,'fast_geometry_page_size':a.page,'instrumentation':not a.no_instrumentation})
        seconds=time.perf_counter()-t
        timing=read_json(Path(result['output_directory'])/'DIAGFAST_TIMING.json')
        report={'transport':'SYNTHETIC_NO_NATIVE_COM','backend':a.worker,'page_size':a.page,'routes_per_mode':a.routes,
            'zones':a.zones,'fixture_creation_seconds':fixture_s,'wall_seconds':seconds,
            'provider_calls':len(host.calls),'getvalues':sum(d.ODMatrix.reads for d in host.dsegs.values()),
            'model_writes':host.writes,'output_directory':result['output_directory'],'timing':timing,
            'python':sys.version,'platform':platform.platform()}
        write_json(a.output/('worker_'+a.worker+'_'+str(a.page)+'_'+str(os.getpid())+'.json'),report)
        print(json.dumps(report));return
    configs=[('LEGACY',256),('FAST_EXACT',256),('FAST_EXACT',512),('FAST_EXACT',1024)]
    logs=[]
    for i in range(a.repetitions):
        order=configs if i%2==0 else configs[::-1]
        for backend,size in order:
            cmd=[sys.executable,__file__,'--worker',backend,'--page',str(size),'--routes',str(a.routes),
                 '--zones',str(a.zones),'--output',str(a.output)]
            if a.no_instrumentation:cmd.append('--no-instrumentation')
            r=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            if r.returncode:
                (a.output/'BENCHMARK_FAILED.txt').write_text(r.stderr);raise RuntimeError(r.stderr[-2000:])
            logs.append(json.loads(r.stdout))
            (a.output/'BENCHMARK_PROGRESS.json').write_text(json.dumps(logs,indent=2))
    from cordon2025.diagfast_parity import compare_runs
    reference=next(x for x in logs if x['backend']=='LEGACY')['output_directory']
    parity=[compare_runs(reference,x['output_directory'])['status'] for x in logs]
    import numpy as np
    summaries=[]
    for backend,size in configs:
        subset=[x for x in logs if x['backend']==backend and x['page_size']==size]
        ts=[x['wall_seconds'] for x in subset]
        summaries.append({'backend':backend,'page_size':size,'times':ts,'median_s':statistics.median(ts),
            'p95_s':float(np.percentile(ts,95)),'variance_s2':statistics.variance(ts) if len(ts)>1 else 0,
            'provider_calls':[x['provider_calls'] for x in subset],
            'peak_process_rss_mib':[x['timing']['peak_process_rss_mib'] for x in subset]})
    report={'status':'SYNTHETIC_BENCHMARK_PASS' if all(x=='PARITY_PASS' for x in parity) else 'PARITY_FAIL',
       'native_capture_speedup':'NOT_MEASURED_NO_PERFORMANCE_CLAIM','filesystem_cache':'OS_CACHE_UNCONTROLLED_FRESH_PROCESSES_ALTERNATING_ORDER',
       'summaries':summaries,'parity_statuses':parity,'runs':logs}
    (a.output/'PERFORMANCE_BENCHMARK.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({'status':report['status'],'summaries':summaries},indent=2))

if __name__=='__main__':main()
