import sys,subprocess,os,time,json
from pathlib import Path
root=Path('/mnt/data/R1_CORDON_UPDATE_20261022');name=sys.argv[1];cwd=sys.argv[2];cmd=sys.argv[3:];log=root/'audit/logs'/f'{name}.log';start=time.time()
env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
with log.open('w') as f:
 try:
  rc=subprocess.call(cmd,cwd=cwd,env=env,stdout=f,stderr=subprocess.STDOUT)
 except Exception as e:f.write(repr(e));rc=255
(root/'audit/logs'/f'{name}.result.json').write_text(json.dumps({'command':cmd,'cwd':cwd,'returncode':rc,'elapsed_seconds':time.time()-start},indent=2))

raise SystemExit(rc)
