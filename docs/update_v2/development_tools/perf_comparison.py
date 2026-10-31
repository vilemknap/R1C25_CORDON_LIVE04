from pathlib import Path
import subprocess,sys,os,json
R=Path('/mnt/data/R1_CORDON_UPDATE_20261022');work=R/'performance_scratch';work.mkdir(exist_ok=True)
env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1')
base=R/'baseline/cordon_v1/R1_2025_CORDON_OPTIMIZER_V1_OFFLINE_20261019';current=R/'release'
reports={}
for name,root,phase in [('create',base,'create'),('baseline_v1',base,'measure'),('updated_v2',current,'measure')]:
    cmd=[sys.executable,str(root/'tools/benchmark.py'),'--count','100000','--phase',phase,'--work-dir',str(work)]
    p=subprocess.run([sys.executable,str(R/'tools/run_test.py'),'PERF_'+name,str(root)]+cmd,env=env)
    if p.returncode:
        raise SystemExit(p.returncode)
    f=work/('CREATE.json' if phase=='create' else 'MEASURE.json')
    reports[name]=json.loads(f.read_text());(R/'audit'/('PERF_'+name+'.json')).write_text(f.read_text())
b=reports['baseline_v1'];v=reports['updated_v2']
for k in ['objective_before','objective_after','KKT_x','solver_status','source_cache_sha256','geometries','segment_volume_rows','mutable_OD_variables']:
    assert b[k]==v[k],(k,b[k],v[k])
reports['comparison']={'same_exact_input':True,'numerics_identical':True,
    'incidence_ratio_v2_over_v1':v['incidence_seconds']/b['incidence_seconds'],
    'solver_ratio_v2_over_v1':v['solver_seconds']/b['solver_seconds'],
    'note':'One run per implementation on same synthetic cache. Timing ratios are measurements, not statistical claims or real-Visum speedup.'}
(R/'audit/PERFORMANCE_COMPARISON.json').write_text(json.dumps(reports,indent=2))
