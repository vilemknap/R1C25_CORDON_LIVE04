from pathlib import Path
import subprocess,sys,os,json,numpy as np
R=Path('/mnt/data/R1_CORDON_UPDATE_20261022');env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1')
roots={'v1':R/'baseline/cordon_v1/R1_2025_CORDON_OPTIMIZER_V1_OFFLINE_20261019','v2':R/'release'}
for name,root in roots.items():
    out=R/'parity_runs'/name;out.mkdir(parents=True,exist_ok=True)
    script="from pathlib import Path;from cordon2025.demos import synthetic_demo;from cordon2025.common import read_config;synthetic_demo(Path("+repr(str(out))+"),read_config())"
    p=subprocess.run([sys.executable,'-c',script],cwd=root,env=env,capture_output=True,text=True,timeout=45)
    (R/'audit/logs'/('PARITY_'+name+'.log')).write_text(p.stdout+'\n'+p.stderr)
    assert p.returncode==0,p.stderr
v1=R/'parity_runs/v1';v2=R/'parity_runs/v2';a=json.loads((v1/'DEMO_SUMMARY.json').read_text());b=json.loads((v2/'DEMO_SUMMARY.json').read_text())
# Summary includes all solver objectives, KKT and feasibility, all independent of filesystem location.
assert a==b,(a,b)
arrays=[]
for p in sorted(v1.rglob('*.npz')):
    other=v2/p.relative_to(v1);aa=np.load(p,allow_pickle=False);bb=np.load(other,allow_pickle=False)
    assert aa.files==bb.files
    for key in aa.files:
        assert np.array_equal(aa[key],bb[key]),(p,key)
        arrays.append({'file':p.relative_to(v1).as_posix(),'array':key,'shape':list(aa[key].shape),'bitwise_equal':True})
report={'status':'NUMERICAL_PARITY_PASS','summary_identical':True,'arrays_checked':len(arrays),'arrays':arrays,'method':'Independent processes; original V1 and modified V2; identical synthetic paths and targets; exact array equality; no live Visum'}
(R/'audit/NUMERICAL_PARITY.json').write_text(json.dumps(report,indent=2));print(json.dumps({k:v for k,v in report.items() if k!='arrays'}))
