from pathlib import Path
import hashlib,json,zipfile,sys,time
R=Path('/mnt/data/R1_CORDON_UPDATE_20261022');N=sys.argv[1];folder=R/'checkpoints';folder.mkdir(exist_ok=True)
p=folder/(N+'.zip');assert not p.exists(),p
with zipfile.ZipFile(p,'w',zipfile.ZIP_DEFLATED,compresslevel=5) as z:
 for sub in ('audit','tools'):
  for f in sorted((R/sub).rglob('*')):
   if f.is_file() and '__pycache__' not in f.parts and not f.name.endswith(('.pyc','.tmp')): z.write(f,str(f.relative_to(R)))
 if N.startswith('CP00'):
  inputs=json.loads((R/'audit/INPUT_ARCHIVES.json').read_text())
  for entry in inputs.values():
   f=Path('/mnt/data')/entry['file'];z.write(f,'inputs/'+f.name,compress_type=zipfile.ZIP_STORED)
 else:
  # Full code state; original data/history is supplied by CP00 (no large duplication).
  for f in sorted((R/'release').rglob('*')):
   rel=f.relative_to(R/'release');parts=rel.parts
   if not f.is_file() or '__pycache__' in parts or '.pytest_cache' in parts: continue
   if (parts[0] in ('data','OFFLINE_RESULTS','CHECKPOINTS','docs') and (len(parts)<2 or parts[1]!='update_v2')):continue
   if f.suffix in ('.pyc',):continue
   z.write(f,'release/'+str(rel))
 with_content={'checkpoint':N,'status':'AUDIT_SNAPSHOT' if N.startswith('CP00') else 'INCREMENTAL_CODE_SNAPSHOT','restore':'CP00 inputs contains original sources and data; later checkpoint release overlays code; do not run parent launchers.','timestamp_epoch':time.time(),'apply':False,'live_visum_tested':False}
 z.writestr('CHECKPOINT_STATE.json',json.dumps(with_content,indent=2))
with zipfile.ZipFile(p) as z:assert z.testzip() is None
sha=hashlib.sha256(p.read_bytes()).hexdigest(); md5=hashlib.md5(p.read_bytes()).hexdigest()
Path(str(p)+'.sha256').write_text(sha+'  '+p.name+'\n')
receipt={'checkpoint':N,'file':str(p),'bytes':p.stat().st_size,'sha256':sha,'md5':md5,'zip_integrity':'PASS','drive_verified':False}
Path(str(p)+'.receipt.json').write_text(json.dumps(receipt,indent=2));print(json.dumps(receipt))
