from pathlib import Path
import subprocess,sys,json,os,time
R=Path('/mnt/data/R1_CORDON_UPDATE_20261022');rel=R/'release'
tasks=[('CP04_PARENT_RAW',rel/'parent',[sys.executable,'-m','pytest','tests','-q','--disable-warnings']),
       ('CP04_PARENT_COMPATIBILITY',rel,[sys.executable,'tools/parent_compatibility.py']),
       ('CP04_AUTHORITY_REAUDIT',rel,[sys.executable,'-m','cordon2025','audit-inputs','--output-root',str(R/'validation_runs'),'--run-name','AUTHORITY_REAUDIT'])]
for name,cwd,args in tasks:
    p=subprocess.run([sys.executable,str(R/'tools/run_test.py'),name,str(cwd)]+args)
    print(name,p.returncode,flush=True)
