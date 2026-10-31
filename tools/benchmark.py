"""Synthetic V24915-schema scaling benchmark; no real model or COM.

Creation and measurement run in separate processes so peak RSS does not mix
fixture generation with the measured incidence/solver phase. Exact geometric
chains are declared test data, not reconstructed Visum paths.
"""
from __future__ import annotations
import argparse,json,os,subprocess,sys,time,platform
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from cordon2025.common import write_json,sha256,read_config,require
from cordon2025.fixtures import create_cache,config
from cordon2025.incidence import build_from_snapshot,aggregate_observations
from cordon2025.optimizer import solve


def geometry_definition():
    mapping={};segments={};extra=[]
    for station in range(1,17):
        key=(100+station,24*station,24*station+1)
        mapping[key]=station;mapping[(key[0],key[2],key[1])]=station
        tail=[(10000+24*station+j,24*station+j,24*station+j+1) for j in range(1,24)]
        segments[station]=[key]+tail
        extra+=tail+[(ln,b,a) for ln,a,b in tail]
    return mapping,segments,extra


def path_generator(n,segments):
    cvol={'NATIVE_CW':1.,'NATIVE_CS':.7,'NATIVE_CL':.4,'NATIVE_CF':.3,
          'EXOG_EE_CW':.2,'EXOG_EE_CS':.15,'EXOG_EE_CL':.1,'EXOG_EE_CF':.08}
    nvol={'NATIVE_CW_NOT':.8,'NATIVE_CS_NOT':.5,'EXOG_EE_CW_NOT':.2,'EXOG_EE_CS_NOT':.1}
    for i in range(n):
        start=1+(i//2)%12;length=2+(i//24)%3
        route=[]
        for s in range(start,start+length-1):route+=segments[s]
        route.append(segments[start+length-1][0])
        if (i//72)%2:route=[(ln,b,a) for ln,a,b in reversed(route)]
        mode='C' if i%2==0 else 'C_NOT';base=cvol if mode=='C' else nvol
        weight=1+((i*17)%19)/20.
        od=i//2
        yield mode,1+od//500,1001+od%500,1,route,{c:v*weight for c,v in base.items()}


def peak_rss():
    try:
        import resource
        v=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return v/(1024**2 if sys.platform=='darwin' else 1024)
    except ImportError:return None


def phase_create(args):
    m,s,e=geometry_definition();t=time.perf_counter()
    _,ev=create_cache(args.work_dir/'BENCH_SYNTHETIC.sqlite',path_generator(args.count,s),station_count=16,station_map=m,extra_edges=e)
    report={'phase':'create','geometry_count':args.count,'creation_seconds':time.perf_counter()-t,'cache_bytes':(args.work_dir/'BENCH_SYNTHETIC.sqlite').stat().st_size,'fixture_generation_peak_RSS_MiB':peak_rss()}
    write_json(args.work_dir/'CREATE.json',report);print(json.dumps(report))


def phase_measure(args):
    import faulthandler
    faulthandler.dump_traceback_later(40,repeat=True)
    print('MEASURE_START',flush=True)
    m,_,_=geometry_definition();e=json.loads((args.work_dir/'BENCH_SYNTHETIC.evidence.json').read_text())
    print('EVIDENCE_LOADED',flush=True)
    cfg=config(list(e['dseg_totals']));t=time.perf_counter()
    variants=build_from_snapshot(args.work_dir/'BENCH_SYNTHETIC.sqlite',m,cfg,e)
    elapsed=time.perf_counter()-t;raw=variants['ALL_ORDERED_UNIQUE_PAIRS']
    print('INCIDENCE_DONE',elapsed,flush=True)
    require(raw.audit['metrics']['decoded_geometry']==args.count,'GEOMETRY_DECODE_COUNT')
    # A target generated on the declared support. This measures guidance only.
    xtruth=np.full(len(raw.variables),.02)
    yt=raw.model+raw.operator.forward(xtruth)
    targets={(r['origin_station'],r['destination_station']):float(v) for r,v in zip(raw.rows,yt)}
    roles={(a,b):'CALIBRATION' for a in range(1,17) for b in range(a+1,17)}
    t=time.perf_counter();inc=aggregate_observations(raw,targets,roles=roles);aggregate_time=time.perf_counter()-t
    print('AGGREGATION_DONE',aggregate_time,flush=True)
    cfg.update(relative_od_lower=-.15,relative_od_upper=.15,ridge=.1,l1=.001,solver_max_iter=800,solver_tolerance=1e-14,kkt_tolerance=1e-5)
    t=time.perf_counter();solution=solve(inc,cfg);solve_time=time.perf_counter()-t
    rr=raw.audit['metrics']['segment_path_rows'];links=raw.audit['metrics']['geometry_edge_count']
    report={'scope':'SYNTHETIC_COUNT_SCALING_NOT_REAL_R1_SPEED_CLAIM','python':platform.python_version(),
       'platform':platform.platform(),'geometries':args.count,'segment_volume_rows':rr,'ordered_link_occurrences':links,
       'mean_links_per_geometry':links/args.count,'incidence_seconds':elapsed,'geometries_per_second':args.count/elapsed,
       'segment_volume_rows_per_second':rr/elapsed,'geometry_decodes':raw.audit['metrics']['decoded_geometry'],
       'mutable_OD_variables':len(raw.variables),'nnz_all_ordered':len(raw.operator.values),'nnz_exact_two':len(variants['EXACT_TWO_HITS'].operator.values),
       'aggregation_seconds':aggregate_time,'solver_seconds':solve_time,'solver_status':solution.report['status'],
       'objective_before':solution.report['objective_initial'],'objective_after':solution.report['objective_final'],
       'KKT_x':solution.report['kkt_x'],'solver_iterations':solution.report['history'][-1]['parent_solver_iterations'],
       'measure_process_peak_RSS_MiB':peak_rss(),'source_cache_sha256':sha256(args.work_dir/'BENCH_SYNTHETIC.sqlite'),
       'geometry_decode_once':True,'DSEG_volume_parity':'PASS','external_OD_parity':'PASS','live_visum_tested':False,
       'apply_permitted':False,'C17_policy':'DISABLED_FOR_SPARSE_SCALING_BENCHMARK'}
    faulthandler.cancel_dump_traceback_later()
    write_json(args.work_dir/'MEASURE.json',report);print(json.dumps(report))


def main():
    p=argparse.ArgumentParser();p.add_argument('--count',type=int,default=100000)
    p.add_argument('--phase',choices=['all','create','measure'],default='all')
    p.add_argument('--work-dir',type=Path,required=True);p.add_argument('--report',type=Path)
    args=p.parse_args();require(args.count>0,'POSITIVE_COUNT_REQUIRED');args.work_dir.mkdir(parents=True,exist_ok=True)
    if args.phase=='create':phase_create(args)
    elif args.phase=='measure':phase_measure(args)
    else:
        env=dict(os.environ,OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',PYTHONHASHSEED='0')
        for phase in ('create','measure'):
            result=subprocess.run([sys.executable,__file__,'--phase',phase,'--count',str(args.count),'--work-dir',str(args.work_dir)],env=env,capture_output=True,text=True,timeout=180)
            (args.work_dir/(phase+'.log')).write_text(result.stdout+'\n'+result.stderr)
            require(result.returncode==0,'BENCHMARK_PHASE_FAILED:'+phase+':'+result.stderr[-1200:])
        combined={'creation':json.loads((args.work_dir/'CREATE.json').read_text()),'measurement':json.loads((args.work_dir/'MEASURE.json').read_text())}
        if args.report:write_json(args.report,combined)
        print(json.dumps(combined,indent=2))

if __name__=='__main__':main()
