from pathlib import Path
import json,shutil,hashlib,subprocess,sys
R=Path('/mnt/data/R1_CORDON_UPDATE_20261022');r=R/'release';donor=R/'upstream/donor_fresh'
names=['test_v24915_perf1_exact_safe_acceleration.py','test_v24915p2_candidate_readback_bundle.py','test_v24915p2_fault_injection.py','test_v24915p2_invalidation.py','test_v24915p2_snapshot_parity.py','test_v24915p2_r6_nonfinite_diagnostic_reference.py','test_v24915p2c_single_pass_snapshot.py','test_v24916_demand_evidence.py','test_v24916_flowbundle_targeting.py','test_v24916_active_evidence_builder.py']
manifest={}
for n in names:
    f=donor/'tests'/n;assert f.exists(),f
    dest=r/'parent/tests'/n;assert not dest.exists(),dest
    shutil.copy2(f,dest);manifest[n]=hashlib.sha256(f.read_bytes()).hexdigest()
(r/'docs/update_v2/PORTED_TEST_MANIFEST.json').write_text(json.dumps(manifest,indent=2))
cmd=[sys.executable,str(R/'tools/run_test.py'),'CP04_DONOR_REGRESSIONS',str(r/'parent'),sys.executable,'-m','pytest','-q','--disable-warnings']+['tests/'+n for n in names]
p=subprocess.Popen(cmd,stdout=open(R/'audit/logs/regression_launcher.log','w'),stderr=subprocess.STDOUT);print('pid',p.pid)
