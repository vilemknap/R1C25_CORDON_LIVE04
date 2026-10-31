"""Full real R1 acceptance, offline only. Never discovers/opens a Visum instance."""
from pathlib import Path
import sys,argparse,json,time,gc,hashlib
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cordon2025.common import ROOT,read_config,canonical_hash,require,write_json,sha256
from cordon2025.authority import mapping
from cordon2025.incidence import build_from_snapshot,aggregate_observations
from cordon2025.perf01_cache import get_or_build
from cordon2025.__main__ import targets_from_audit

EXPECTED='7e35a96ac1bc4fb306049d410379e349fde5aa8a07b15bf11301ed858253fa9a'
EXPECTED_BYTES=664272896


def signature(inc):
    h=hashlib.sha256()
    for a in (inc.model,inc.mutable,inc.fixed,inc.q_current,inc.operator.row_idx,inc.operator.col_idx,inc.operator.values,inc.share_operator.values):
        h.update(str(a.dtype).encode());h.update(str(a.shape).encode());h.update(a.tobytes())
    audit={k:v for k,v in inc.audit.items() if k!='all_od_totals'}
    od=hashlib.sha256()
    for row in inc.audit['all_od_totals']:
        od.update(json.dumps(row,sort_keys=True,separators=(',',':'),allow_nan=False).encode());od.update(b'\n')
    return {'arrays':h.hexdigest(),'rows':canonical_hash(inc.rows),'variables':canonical_hash(inc.variables),
            'projection_base':canonical_hash(inc.projection_base_variables),'audit':canonical_hash(audit),
            'all_od_totals_stream':od.hexdigest(),'model_sum':float(inc.model.sum())}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--snapshot-dir',type=Path,required=True)
    p.add_argument('--derived-dir',type=Path,required=True)
    p.add_argument('--output-dir',type=Path,required=True)
    args=p.parse_args();args.output_dir.mkdir(parents=True,exist_ok=False)
    status={'status':'NOT_RUN','apply_permitted':False,'live_calibration_verified':False}
    try:
        cache=args.snapshot_dir/'p.sqlite';ep=args.snapshot_dir/'SNAPSHOT_EVIDENCE.json';cp=args.snapshot_dir/'RUN_CHECKPOINT.json'
        require(cache.is_file() and cache.stat().st_size==EXPECTED_BYTES and sha256(cache)==EXPECTED,'WAITING_FOR_REAL_FINAL_CACHE')
        e=json.loads(ep.read_text(encoding='utf-8'));cfg=read_config();cfg['mutable_dsegs']=[]
        m,_=mapping(ROOT/'data/audited/STATION_MAPPING.csv')
        before=sha256(cache);t=time.perf_counter()
        reference=build_from_snapshot(cache,m,cfg,e);ref={k:signature(v) for k,v in reference.items()};del reference;gc.collect()
        cold_seconds=time.perf_counter()-t
        built=get_or_build(cache,m,cfg,ep,cache_dir=args.derived_dir,policy='build-offline',source_checkpoint=cp,
                           status_path=args.output_dir/'PERF01_BUILD_STATUS.json')
        built_sig={k:signature(v) for k,v in built.variants.items()}
        require(built_sig==ref,'REAL_COLD_BUILD_SIGNATURE_MISMATCH');del built;gc.collect()
        warm=get_or_build(cache,m,cfg,ep,cache_dir=args.derived_dir,policy='require-verified-hit',source_checkpoint=cp,
                          status_path=args.output_dir/'PERF01_WARM_STATUS.json')
        got={k:signature(v) for k,v in warm.variants.items()}
        require(got==ref,'REAL_WARM_SIGNATURE_MISMATCH')
        targets=targets_from_audit();holdout={tuple(x) for x in cfg['validation_unordered_pairs']}
        roles={(a,b):'VALIDATION' if (a,b) in holdout else 'CALIBRATION' for a in range(1,17) for b in range(a+1,17)}
        from cordon2025.state import observation_roster
        aggregates={}
        expected={'ALL_ORDERED_UNIQUE_PAIRS':188009.68000000517,'EXACT_TWO_HITS':62500.212999999494}
        for method,inc in warm.variants.items():
            ag=aggregate_observations(inc,targets,roles=roles)
            require(abs(ag.model.sum()-expected[method])<1e-6,'REAL_REFERENCE_TOTAL_DIFFERS')
            aggregates[method]={'model_sum':float(ag.model.sum()),'roster':observation_roster(ag.rows)}
            warm.save_incidence(ag,args.output_dir/method)
        require(sha256(cache)==before,'REAL_SOURCE_CHANGED')
        status.update(status='REAL_REFERENCE_COLD_WARM_PASS',source_sha256=before,signatures=ref,
                      aggregated=aggregates,reference_plus_signature_seconds=cold_seconds,warm_runtime=warm.status,
                      native_assignment_executed=False)
    except Exception as exc:
        status.update(status='NOT_RUN' if 'WAITING_FOR_REAL' in str(exc) or isinstance(exc,FileNotFoundError) else 'FAIL',reason=str(exc))
        write_json(args.output_dir/'PERF01_REAL_ACCEPTANCE.json',status)
        raise
    write_json(args.output_dir/'PERF01_REAL_ACCEPTANCE.json',status)
    print(json.dumps({'status':status['status'],'output':str(args.output_dir)}))

if __name__=='__main__':main()
