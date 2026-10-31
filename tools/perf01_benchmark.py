"""Reproducible OFFLINE benchmark. Separate process for each measured operation."""
import argparse,json,sys,time,os,platform,statistics,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def prepare(root,n):
    from cordon2025.fixtures import create_cache,config
    from cordon2025.common import write_json
    from cordon2025.incidence import METHODS
    root.mkdir(parents=True,exist_ok=True)
    edges=[(10000+i,i,i+1) for i in range(1,81)]
    reverse=[(ln,b,a) for ln,a,b in edges]
    mapping={}
    for k in range(16):
        mapping[edges[5*k]]=k+1;mapping[reverse[5*k]]=k+1
    c=['NATIVE_CW','NATIVE_CS','NATIVE_CF','NATIVE_CL','EXOG_EE_CF','EXOG_EE_CL','EXOG_EE_CS','EXOG_EE_CW']
    nt=['NATIVE_CW_NOT','NATIVE_CS_NOT','EXOG_EE_CS_NOT','EXOG_EE_CW_NOT']
    def paths():
        for i in range(n):
            mode='C' if i%2==0 else 'C_NOT';codes=c if mode=='C' else nt
            # Varied forward/reverse, no-hit, >2 hits, two-hit, repeated, empty.
            length=[4,8,16,32,48,64,80][i%7]
            seq=edges[:length]
            if i%11==0:seq=list(reversed(reverse[:length]))
            if i%37==0:seq=edges[:10]+list(reversed(reverse[:10]))
            if i%43==0:seq=[]
            o=1000+i//400;d=2000+i%400
            yield(mode,o,d,1,seq,{ds:round((1+i%700)*(j+1)/1000,3) for j,ds in enumerate(codes)})
    m,e=create_cache(root/'source.sqlite',paths(),station_count=16,station_map=mapping,extra_edges=edges+reverse)
    cfg=dict(config(c+nt),model_year=2025,survey_year=2026,basis='RPDI',mode='OFFLINE_PROPOSAL',limit_profile='PRACTICAL_V1',observation_methods=list(METHODS))
    write_json(root/'cfg.json',cfg);write_json(root/'mapping.json',[[*k,v] for k,v in m.items()])
    write_json(root/'dataset.json',{'origin':'SYNTHETIC_TEST_FIXTURE','geometries':n,'segments':12,'modes':2,'stations':16,
                    'ordered_path_edge_lengths':'varied 0..80','volume_rows':n//2*12,'note':'NOT real R1 snapshot'})


def operation(root,kind,out):
    from cordon2025.common import write_json,sha256,canonical_hash
    from cordon2025.perf01_cache import get_or_build,peak_rss
    from cordon2025.incidence import build_from_snapshot,aggregate_observations
    cfg=json.loads((root/'cfg.json').read_text());mapping={tuple(r[:3]):r[3] for r in json.loads((root/'mapping.json').read_text())}
    ep=root/'source.evidence.json';p=root/'source.sqlite'
    targets={(a,b):float(a+b) for a in range(1,17) for b in range(1,17) if a!=b}
    roles={(a,b):'VALIDATION' if (a+b)%10==0 else 'CALIBRATION' for a in range(1,17) for b in range(a+1,17)}
    def process_io():
        try:return {line.split(':')[0]:int(line.split(':')[1]) for line in Path('/proc/self/io').read_text().splitlines()}
        except (OSError,ValueError):return None
    io_before=process_io()
    t=time.perf_counter();cpu=time.process_time();start_out_bytes=0
    if kind=='reference':
        e=json.loads(ep.read_text())
        variants=build_from_snapshot(p,mapping,cfg,e,hits_output=out/'STATION_HITS.csv');cache=None
        stats={'cache_action':'COLD_REFERENCE','geometry_redecode_count':next(iter(variants.values())).audit['metrics']['decoded_geometry'],'sqlite_geometry_scans':1,'native_com_read_count':0}
    else:
        cache=get_or_build(p,mapping,cfg,ep,cache_dir=root/'derived',policy='build-offline' if kind=='build' else 'require-verified-hit',status_path=out/'PERF01_CACHE_STATUS.json')
        variants=cache.variants;stats=dict(cache.status)
    signatures={}
    import numpy as np,hashlib
    for method,raw in variants.items():
        inc=aggregate_observations(raw,targets,roles=roles)
        if cache:
            cache.save_incidence(raw,out/method/'DIRECTED_DIAGNOSTICS');cache.save_incidence(inc,out/method)
        else:
            raw.save(out/method/'DIRECTED_DIAGNOSTICS');inc.save(out/method)
        h=hashlib.sha256()
        for a in (inc.model,inc.mutable,inc.fixed,inc.q_current,inc.operator.row_idx,inc.operator.col_idx,inc.operator.values,inc.share_operator.values):h.update(np.asarray(a).tobytes())
        # Hashes of per-DSeg rows and all audit fields independently test more than totals.
        signatures[method]={'arrays_sha256':h.hexdigest(),'rows_sha256':canonical_hash(inc.rows),
                            'directed_rows_sha256':canonical_hash(raw.rows),'model_sum':float(inc.model.sum()),
                            'variables':len(inc.variables),'nnz':len(inc.operator.values)}
    elapsed=time.perf_counter()-t
    io_after=process_io()
    io_delta={k:io_after[k]-io_before[k] for k in io_before} if io_before and io_after else None
    record={'operation':kind,'wall_s':elapsed,'cpu_s':time.process_time()-cpu,'peak_rss_mib':peak_rss(),
            'process_io_delta':io_delta,'output_bytes':sum(f.stat().st_size for f in out.rglob('*') if f.is_file()),'status':stats,'signatures':signatures,
            'source_sqlite_bytes':p.stat().st_size,'apply_permitted':False,'native_visum_tested':False}
    write_json(out/'MEASUREMENT.json',record)
    return record


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--dataset',type=Path,required=True);ap.add_argument('--paths',type=int,default=100000)
    ap.add_argument('--operation',choices=['prepare','reference','build','warm','all'],default='all');ap.add_argument('--output',type=Path)
    args=ap.parse_args();root=args.dataset.resolve()
    if args.operation=='prepare':prepare(root,args.paths);return
    if args.operation!='all':
        args.output.mkdir(parents=True,exist_ok=False);operation(root,args.operation,args.output);return
    if not (root/'source.sqlite').exists():prepare(root,args.paths)
    runs=[]
    for i,kind in enumerate(['reference','build','warm','warm','warm','warm']):
        out=root/('run_%02d_%s'%(i,kind))
        cp=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--dataset',str(root),'--operation',kind,'--output',str(out)],cwd=ROOT,text=True,capture_output=True)
        (root/('PROCESS_%02d.log'%i)).write_text(cp.stdout+'\n'+cp.stderr)
        if cp.returncode:raise RuntimeError('BENCHMARK_PROCESS_FAILED:'+str(out)+':rc='+str(cp.returncode)+':'+cp.stderr)
        runs.append(json.loads((out/'MEASUREMENT.json').read_text()))
    ref=runs[0]['signatures'];same=all(r['signatures']==ref for r in runs)
    median=statistics.median(r['wall_s'] for r in runs if r['operation']=='warm')
    report={'schema':'PERF01_BENCHMARK_V1','dataset':json.loads((root/'dataset.json').read_text()),
            'environment':{'platform':platform.platform(),'python':sys.version,'cpu_count':os.cpu_count()},
            'runs':runs,'warm_runs_separate_processes':4,'numerical_signature_match':same,
            'median_warm_s':median,'speedup':runs[0]['wall_s']/median,
            'derived_cache_bytes':sum(p.stat().st_size for p in (root/'derived').rglob('*') if p.is_file()),
            'full_source_sha_validation':True,'native_real_acceptance':'NOT_RUN_MISSING_FINAL_CACHE'}
    (root/'BENCHMARK.json').write_text(json.dumps(report,indent=2));print(json.dumps({k:report[k] for k in ('speedup','median_warm_s','numerical_signature_match')}))
    if not same:raise RuntimeError('NUMERIC_BENCHMARK_MISMATCH')

if __name__=='__main__':main()
