from pathlib import Path
import hashlib,json,shutil,csv,ast
R=Path('/mnt/data/R1_CORDON_UPDATE_20261022');P=R/'release/parent';F=R/'upstream/donor_fresh';D=R/'upstream/donor_resume'
changes=json.loads((R/'audit/COMPARISON.json').read_text()); rows=[]
def h(p):return hashlib.sha256(p.read_bytes()).hexdigest()
# Keep original V1 parent code+two offline extension hooks. Only additive library modules.
files=set(changes['base__fresh']['added'])|set(changes['base__resume']['added'])
for rel in sorted(files):
 src=(F/rel) if (F/rel).is_file() else (D/rel)
 rec={'path':rel,'source':'fresh' if src.is_relative_to(F) else 'resume','sha256':h(src)}
 if '/' not in rel and rel.startswith('r1_') and rel.endswith('.py'):
  assert not (P/rel).exists(),rel
  shutil.copy2(src,P/rel)
  rec['decision']='PORTED_LIBRARY_INACTIVE_UNTIL_EXPLICIT_OFFLINE_BRIDGE'
 elif rel.startswith('tests/'):
  rec['decision']='DONOR_REGRESSION_EXECUTED_IN_ORIGINAL_TREE'
 elif rel.endswith('.py'):
  rec['decision']='NOT_PORTED_2022_LAUNCHER_OR_PROFILE_HELPER'
 elif rel.endswith('.json'):
  rec['decision']='NOT_PORTED_2022_CONFIG_STATE_OR_DEPLOYMENT_AUTHORITY'
 else:rec['decision']='HISTORICAL_EVIDENCE_ONLY'
 rows.append(rec)
out=R/'release/docs/update_v2';out.mkdir(parents=True,exist_ok=True)
(out/'PORT_DECISIONS.json').write_text(json.dumps(rows,indent=2))
with (out/'PORT_DECISIONS.csv').open('w',newline='') as f:
 w=csv.DictWriter(f,fieldnames=['path','source','sha256','decision']);w.writeheader();w.writerows(rows)
manifest={r['path']:{'sha256':r['sha256'],'source':r['source']} for r in rows if r['decision'].startswith('PORTED')}
(out/'DONOR_LIBRARY_MANIFEST.json').write_text(json.dumps(manifest,indent=2))
shutil.copy2(R/'audit/INPUT_ARCHIVES.json',out/'INPUT_ARCHIVES.json');shutil.copy2(R/'audit/IMPLEMENTATION_PLAN_CZ.md',out/'IMPLEMENTATION_PLAN_CZ.md')
print('additive libraries',len(manifest),'all decisions',len(rows))
# Visible import-time call audit (review only; imports are not executed here).
unsafe=[]
for rel in manifest:
 t=ast.parse((P/rel).read_text(encoding='utf-8-sig'))
 for n in t.body:
  if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call):unsafe.append((rel,n.lineno,ast.unparse(n)[:200]))
print('module-level call expressions',unsafe)
