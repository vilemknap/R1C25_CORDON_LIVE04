"""Guarded PATCH-ONLY installer. Creates a NEW release; never edits the base."""
from pathlib import Path,PurePosixPath
import argparse,hashlib,json,os,shutil,stat,subprocess,sys,tempfile,zipfile,uuid
BASE_ZIP_SHA='4f09428132925cda73994e5b7fb46613a4e21dee3287df1e83986fc49e5aaead'
BASE_MANIFEST_SHA='1695276e4cce407e6bf482ec1c9bd1c1844ee00cc249dacfcac9b271d9f328cc'

def digest(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()

def check_path(p):
    for q in [p,*p.parents]:
        if q.is_symlink():raise ValueError('PATCH_SYMLINK_FORBIDDEN')
        if q.exists() and getattr(q.lstat(),'st_file_attributes',0)&0x400:
            raise ValueError('PATCH_REPARSE_POINT_FORBIDDEN')

def safe_member(name):
    p=PurePosixPath(name)
    if p.is_absolute() or '..' in p.parts or '\\' in name or ':' in name:
        raise ValueError('PATCH_UNSAFE_MEMBER')
    return p

def verify_base(p):
    if digest(p/'SOURCE_MANIFEST.json')!=BASE_MANIFEST_SHA:raise ValueError('PATCH_BASE_MANIFEST_MISMATCH')
    m=json.loads((p/'SOURCE_MANIFEST.json').read_text());allowed={'SOURCE_MANIFEST.json','SHA256SUMS.txt'}
    for rec in m['files']:
        name=safe_member(rec['path']);file=p/name;check_path(file)
        if not file.is_file() or file.stat().st_size!=rec['size'] or digest(file)!=rec['sha256']:
            raise ValueError('PATCH_BASE_FILE_MISMATCH:'+rec['path'])
        allowed.add(rec['path'])
    for file in p.rglob('*'):
        if file.is_file() and not any(t in ('__pycache__','.pytest_cache','OFFLINE_RESULTS') for t in file.relative_to(p).parts) and file.relative_to(p).as_posix() not in allowed:
            raise ValueError('PATCH_UNMANIFESTED_BASE_FILE')

def _install(base_zip,base_tree,output,patch_root):
    output=Path(output).absolute();patch_root=Path(patch_root).absolute()
    check_path(output);check_path(patch_root)
    if output.exists():raise ValueError('PATCH_OUTPUT_MUST_BE_NEW')
    if '2022' in output.parts:raise ValueError('PATCH_2022_OUTPUT_FORBIDDEN')
    output.parent.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((patch_root/'PATCH_MANIFEST.json').read_text())
    if manifest.get('base_zip_sha256')!=BASE_ZIP_SHA:raise ValueError('PATCH_WRONG_BASE_AUTHORITY')
    if len({r['path'] for r in manifest['files']})!=len(manifest['files']):raise ValueError('PATCH_DUPLICATE_PATH')
    with tempfile.TemporaryDirectory(prefix='r1df_',dir=output.parent) as temp:
        temp=Path(temp)
        if base_zip:
            p=Path(base_zip);check_path(p)
            if digest(p)!=BASE_ZIP_SHA:raise ValueError('PATCH_BASE_ZIP_SHA_MISMATCH')
            with zipfile.ZipFile(p) as z:
                for rec in z.infolist():
                    name=safe_member(rec.filename)
                    if stat.S_ISLNK(rec.external_attr>>16):raise ValueError('PATCH_ZIP_SYMLINK_FORBIDDEN')
                    z.extract(rec,temp/'base')
            base=temp/'base'/'R1C25_PERF01'
        else:
            base=Path(base_tree).absolute();check_path(base)
            if base==output or base in output.parents:raise ValueError('PATCH_OUTPUT_INSIDE_BASE')
        verify_base(base)
        staged=temp/'release'
        shutil.copytree(base,staged,ignore=shutil.ignore_patterns('__pycache__','.pytest_cache','OFFLINE_RESULTS'))
        for rec in manifest['files']:
            name=safe_member(rec['path']);src=patch_root/'payload'/name;check_path(src)
            if not src.is_file() or digest(src)!=rec['sha256']:raise ValueError('PATCH_PAYLOAD_HASH_MISMATCH:'+str(name))
            dest=staged/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dest)
        proof=subprocess.run([sys.executable,str(staged/'verify_release.py')],cwd=staged,capture_output=True,text=True)
        if proof.returncode:raise ValueError('PATCH_RESULT_INTEGRITY_FAIL:'+proof.stdout[-1000:])
        if output.exists():raise ValueError('PATCH_OUTPUT_RACE')
        # Output is a newly staged sibling on the same filesystem; source is never overwritten.
        os.rename(staged,output)
    return {'status':'PATCH_INSTALLED_TO_NEW_RELEASE','output':str(output),'base_modified':False}

def install(base_zip,base_tree,output,patch_root):
    output=Path(output).absolute();check_path(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    lock=output.parent/('.r1df_'+hashlib.sha256(str(output).encode()).hexdigest()[:16]+'.lock')
    token=uuid.uuid4().hex
    try:
        with lock.open('x',encoding='ascii') as f:f.write(token);f.flush();os.fsync(f.fileno())
    except FileExistsError as exc:raise ValueError('PATCH_OUTPUT_LOCKED_NO_STEAL') from exc
    try:return _install(base_zip,base_tree,output,patch_root)
    finally:
        if lock.read_text()==token:lock.unlink()

def main():
    p=argparse.ArgumentParser();g=p.add_mutually_exclusive_group(required=True)
    g.add_argument('--base-zip',type=Path);g.add_argument('--base-tree',type=Path)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--patch-root',type=Path,default=Path(__file__).resolve().parent)
    a=p.parse_args();print(json.dumps(install(a.base_zip,a.base_tree,a.output,a.patch_root),indent=2))
if __name__=='__main__':main()
