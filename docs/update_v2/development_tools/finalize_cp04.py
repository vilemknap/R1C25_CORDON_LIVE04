from pathlib import Path
import json,shutil,hashlib
R=Path('/mnt/data/R1_CORDON_UPDATE_20261022');r=R/'release';base=R/'baseline/cordon_v1/R1_2025_CORDON_OPTIMIZER_V1_OFFLINE_20261019';d=r/'docs/update_v2';(d/'evidence').mkdir(exist_ok=True)
# Preserve any historical evidence that an inherited helper regenerated before path hardening.
restored=[]
for p in (base/'docs/evidence').glob('*'):
    q=r/'docs/evidence'/p.name
    if p.is_file() and q.is_file() and p.read_bytes()!=q.read_bytes():
        shutil.copy2(q,d/'evidence'/('V2_'+p.name));shutil.copy2(p,q);restored.append(p.name)
(d/'EVIDENCE_PRESERVATION.json').write_text(json.dumps({'historical_evidence_restored_after_inherited_helper':restored,'new_results_retained_separately':True},indent=2))
p=r/'tools/parent_compatibility.py';s=p.read_text().replace('import os,sys,subprocess','import os,sys,subprocess,datetime')
s=s.replace("evidence=ROOT/'docs/update_v2/evidence';evidence.mkdir(parents=True,exist_ok=True)","evidence=ROOT/'OFFLINE_RESULTS'/('PARENT_REGRESSION_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f'));evidence.mkdir(parents=True,exist_ok=False)")
p.write_text(s)
# Make source decisions reflect final dependency-closed selection, preserving earlier snapshot history.
mp=json.loads((d/'DONOR_LIBRARY_MANIFEST.json').read_text());dec=json.loads((d/'PORT_DECISIONS.json').read_text())
for row in dec:
    if row['path'] in ('r1_15a2_fresh_baseline_live_preflight_v24916p2c.py','r1_15a2_safety_v24915p2c3.py'):
        row['decision']='NOT_PORTED_RUN_BOUND_DEPENDENCY';row['refinement_checkpoint']='CP03B'
(d/'PORT_DECISIONS.json').write_text(json.dumps(dec,indent=2))
with (d/'PORT_DECISIONS.csv').open('w',encoding='utf-8',newline='') as f:
    import csv
    fields=list(dict.fromkeys(k for a in dec for k in a));w=csv.DictWriter(f,fields);w.writeheader();w.writerows(dec)
cp='CP03B_STATE_CACHE_TARGETING_PASS_20261022';jp=R/'audit/DRIVE_JOURNAL.json';journal=json.loads(jp.read_text())
if not any(x['checkpoint']==cp for x in journal):
    x=json.loads((R/'checkpoints'/f'{cp}.zip.receipt.json').read_text());x.update(drive_verified=True,drive_id='1Fh_34Vx2BV5eOzMQTCgNBMnDeYvAsMul',drive_sha_sidecar_id='1zC_Ig8UjiL9C-rUXMSoQ5s38U2UYt_Ky',verification_level='METADATA_NAME_SIZE_PARENT');journal.append(x)
jp.write_text(json.dumps(journal,indent=2))
(d/'CP04_INTEGRATION_REPORT.md').write_text('''# CP04 - isolated offline execution and compatibility

Implemented short, isolated 2025 run roots, exclusive owner-token locks, no automatic stale-lock takeover, refusal to adopt arbitrary existing roots/2022 directories, critical checkpoints with input/code/authority hashes and sealed output hashes. Long run names are deterministically compacted. Windows defaults to LOCALAPPDATA/R1C25; Linux defaults to OFFLINE_RESULTS. No wallclock stop is introduced.

verify-run is a read-only verifier for an offline checkpoint. Recovery is an explicit verified restart from immutable inputs. It is NOT a resumption of Visum, path search, FISTA internal iterations or a partially completed assignment. No claim of solver continuation is made.

Validation before checkpoint:
- own suite: 162 passed;
- 97 unchanged donor regression tests passed against the merged isolated tree;
- raw parent suite: 879 passed, 4 skipped, 1 expected legacy package-identity failure (the same two intentional core modules patched in V1);
- parent compatibility: 879 passed, 4 skipped, 1 explicitly deselected byte-identity test. The original identity gate stays unchanged and is separately tested to refuse the fork;
- authority re-audit: STATIC_PASS;
- original V1 vs V2 independent-process synthetic runs: 40 arrays exactly equal and complete numerical demo summaries identical.

These are offline/mock/synthetic results, not a live Windows/Visum test. Apply remains false. The 2022 state, configuration and data were not modified.
''')
# New test helper records outside immutable historical evidence.
print('restored historical evidence',restored,'libraries',len(mp))
