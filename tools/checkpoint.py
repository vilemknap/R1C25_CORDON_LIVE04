from pathlib import Path
import json,hashlib,sys,datetime,zipfile
root=Path(__file__).resolve().parents[1]; rel=root
cp=sys.argv[1]; detail=json.loads(sys.argv[2])
out=rel/'CHECKPOINTS'/cp;out.mkdir(exist_ok=False)
files={str(p.relative_to(rel)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(rel.rglob('*')) if p.is_file() and not any(x in p.parts for x in ('CHECKPOINTS','__pycache__','.pytest_cache'))}
prev=sorted((rel/'CHECKPOINTS').glob('CP*/status.json'))
status={'checkpoint':cp,'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'details':detail,'source_files':len(files),'manifest_sha256':hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest(),'predecessor_status_sha256':hashlib.sha256(prev[-1].read_bytes()).hexdigest() if prev else None,'apply':False,'live_visum_tested':False,'resume':'Read status.json and file_manifest.json. Restore this checkpoint source ZIP on top of the full immutable parent only. Continue with the next unmet gate.'}
(out/'status.json').write_text(json.dumps(status,indent=2))
(out/'file_manifest.json').write_text(json.dumps(files,indent=2))
(out/'RESUME.txt').write_text(status['resume']+'\n'+json.dumps(detail,indent=2))
# Store source/authority conversion state and evidence, not repeated copies of the large input workbooks.
with zipfile.ZipFile(out/'code_snapshot.zip','w',zipfile.ZIP_DEFLATED) as z:
 for path in files:
  p=rel/path
  if (not path.startswith('parent/') and p.suffix in ('.py','.json','.md','.csv','.txt')) or path in ('parent/r1_15a2_core.py','parent/r1_15a2_two_mode_v238.py'):z.write(p,path)
(out/'code_snapshot.zip.sha256').write_text(hashlib.sha256((out/'code_snapshot.zip').read_bytes()).hexdigest()+'  code_snapshot.zip\n')
print(json.dumps(status,indent=2))
