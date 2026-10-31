"""Run unchanged numerical parent tests, with one explicit identity exclusion.

The excluded test requires byte-identical original V24915 deployment. It was run
and failed exactly on the two deliberate fork patches. Do not change/relax that
2022 deployment guard. A new test proves that rejection remains in effect.
"""
from pathlib import Path
import os,sys,subprocess,datetime
ROOT=Path(__file__).resolve().parents[1]
EXCLUDED='tests/test_v24915_release.py::test_v24915_config_runtime_bundle_and_lineage_are_hash_locked'
if __name__=='__main__':
    evidence=ROOT/'OFFLINE_RESULTS'/('PARENT_REGRESSION_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f'));evidence.mkdir(parents=True,exist_ok=False)
    env=dict(os.environ,OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',PYTHONHASHSEED='0')
    args=[sys.executable,'-m','pytest','tests','-q','--disable-warnings','--deselect='+EXCLUDED,
          '--junitxml='+str(evidence/'CP05_parent_compatibility.xml')]
    with (evidence/'CP05_parent_compatibility.log').open('w') as log:
        p=subprocess.run(args,cwd=ROOT/'parent',env=env,stdout=log,stderr=subprocess.STDOUT,timeout=120)
    print((evidence/'CP05_parent_compatibility.log').read_text())
    raise SystemExit(p.returncode)
