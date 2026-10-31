"""Reproducible synthetic comparison, identical targets and no Visum execution.

Run `python tools/benchmark.py --phase create --count 10000 --work-dir DIR`
then `python tools/benchmark_aggressive.py --work-dir DIR` in a new process.
No external libraries beyond the release's existing dependencies are introduced.
"""
from __future__ import annotations
import argparse, copy, json, platform, sys, time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from benchmark import geometry_definition, peak_rss
from cordon2025.common import ROOT, require, write_json
from cordon2025.fixtures import config
from cordon2025.incidence import build_from_snapshot, aggregate_observations
from cordon2025.optimizer import solve
from cordon2025.aggressive_policy import effective_config
from cordon2025.aggressive import propose


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--work-dir',required=True,type=Path)
    args=parser.parse_args();folder=args.work_dir
    evidence=json.loads((folder/'BENCH_SYNTHETIC.evidence.json').read_text())
    cfg=json.loads((ROOT/'CORDON_2025_CONFIG.json').read_text())
    cfg.update(config(list(evidence['dseg_totals'])))
    cfg.update(relative_od_lower=-.15,relative_od_upper=.15,ridge=.1,l1=.001,
               solver_max_iter=6000,solver_tolerance=1e-12,kkt_tolerance=1e-6)
    aggressive=copy.deepcopy(cfg)
    aggressive['aggressive_policy']=json.loads((ROOT/'CORDON_2025_AGGRESSIVE_CONFIG.json').read_text())['aggressive_policy']
    aggressive=effective_config(aggressive,1)
    mapping,_,_=geometry_definition()
    start=time.perf_counter();variants=build_from_snapshot(folder/'BENCH_SYNTHETIC.sqlite',mapping,cfg,evidence)
    incidence_time=time.perf_counter()-start
    raw=variants['ALL_ORDERED_UNIQUE_PAIRS']
    truth=raw.model+raw.operator.forward(np.full(len(raw.variables),.25))
    targets={(r['origin_station'],r['destination_station']):float(v) for r,v in zip(raw.rows,truth)}
    roles={(a,b):'CALIBRATION' for a in range(1,17) for b in range(a+1,17)}
    inc=aggregate_observations(raw,targets,roles=roles)
    start=time.perf_counter();standard=solve(inc,cfg);standard_time=time.perf_counter()-start
    start=time.perf_counter();extended=propose(inc,aggressive);aggressive_time=time.perf_counter()-start
    require(standard.report['numeric_converged'],'STANDARD_BENCHMARK_NOT_CONVERGED')
    require(extended.report['guidance_solver_converged'],'AGGRESSIVE_BENCHMARK_NOT_CONVERGED')
    require(extended.report['selected_scale']>0,'AGGRESSIVE_BENCHMARK_NO_PROPOSAL')
    report={'scope':'SYNTHETIC_NOT_R1_LIVE_CALIBRATION','python':platform.python_version(),
        'platform':platform.platform(),'geometry_count':raw.audit['metrics']['decoded_geometry'],
        'segment_volume_rows':raw.audit['metrics']['segment_path_rows'],
        'ordered_link_occurrences':raw.audit['metrics']['geometry_edge_count'],
        'variables':len(raw.variables),'observation_rows':len(inc.rows),
        'incidence_seconds':incidence_time,'standard_solver_seconds':standard_time,
        'aggressive_with_six_trials_seconds':aggressive_time,'process_peak_RSS_MiB':peak_rss(),
        'standard_objective':standard.report['objective_final'],
        'aggressive_objective':extended.solution.report['objective_final'],
        'standard_max_relative_step':float(np.max(abs(standard.x))),
        'aggressive_max_relative_step':float(np.max(abs(extended.solution.x))),
        'selected_scale':extended.report['selected_scale'],
        'standard_converged':standard.report['numeric_converged'],
        'aggressive_converged':extended.report['guidance_solver_converged'],
        'C17_policy':'DISABLED_IN_SCALING_BENCHMARK','actuator_basis':'NOT_SUPPLIED',
        'source_cache_sha256':raw.audit['cache_sha256'],
        'actual_assignment_verified':False,'apply_permitted':False}
    write_json(folder/'AGGRESSIVE_MEASURE.json',report)
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
