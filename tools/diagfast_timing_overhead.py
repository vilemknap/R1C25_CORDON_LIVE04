"""Paired same-fixture LEGACY instrumentation overhead, not native timing."""
from pathlib import Path
import argparse,json,subprocess,sys,time,statistics,platform
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--worker',choices=['RAW_LEGACY','TIMED_LEGACY'])
    p.add_argument('--routes',type=int,default=3000);p.add_argument('--zones',type=int,default=681)
    p.add_argument('--repetitions',type=int,default=3);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=True)
    if a.worker:
        from diagfast_scaled_visum import ScaledVisum
        from cordon2025 import visum_startup
        from cordon2025.diagfast_runtime import run
        host=ScaledVisum(a.output/'model',a.routes,a.zones)
        t=time.perf_counter()
        if a.worker=='RAW_LEGACY':
            result=visum_startup.run(host,action='CAPTURE_DIAGNOSTICS',output_root=a.output/'runs',options={'min_free_disk_gib':0})
        else:
            result=run(host,backend='LEGACY',output_root=a.output/'runs',options={'min_free_disk_gib':0})
        print(json.dumps({'worker':a.worker,'wall_seconds':time.perf_counter()-t,
            'provider_calls':len(host.calls),'output_directory':result['output_directory']}));return
    runs=[]
    for i in range(a.repetitions):
        modes=['RAW_LEGACY','TIMED_LEGACY'] if i%2==0 else ['TIMED_LEGACY','RAW_LEGACY']
        for mode in modes:
            cmd=[sys.executable,__file__,'--worker',mode,'--output',str(a.output),
                 '--routes',str(a.routes),'--zones',str(a.zones)]
            r=subprocess.run(cmd,text=True,capture_output=True)
            if r.returncode:raise RuntimeError(r.stderr[-3000:])
            runs.append(json.loads(r.stdout))
    from cordon2025.diagfast_parity import compare_runs
    parity=[compare_runs(runs[0]['output_directory'],r['output_directory'])['status'] for r in runs]
    med={m:statistics.median(x['wall_seconds'] for x in runs if x['worker']==m) for m in modes}
    report={'origin':'SYNTHETIC_NO_NATIVE_COM','status':'PASS' if all(x=='PARITY_PASS' for x in parity) else 'FAIL',
        'routes_per_mode':a.routes,'zones':a.zones,'repetitions':a.repetitions,'medians_s':med,
        'instrumented_minus_raw_s':med['TIMED_LEGACY']-med['RAW_LEGACY'],
        'relative_overhead':med['TIMED_LEGACY']/med['RAW_LEGACY']-1,
        'order':'ALTERNATING_FRESH_PROCESSES_OS_CACHE_UNCONTROLLED','runs':runs,'parity':parity,
        'native_overhead':'NOT_MEASURED','python':sys.version,'platform':platform.platform()}
    (a.output/'TIMING_OVERHEAD.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k not in ('runs','parity')},indent=2))
    if report['status']!='PASS':raise SystemExit(1)

if __name__=='__main__':main()
