"""Independent, read-only release verifier; never imports the calibrated engine."""
from pathlib import Path, PurePosixPath
import argparse,hashlib,json,sys,re
ROOT=Path(__file__).resolve().parent
RUNTIME_DIRS={'OFFLINE_RESULTS','__pycache__','.pytest_cache','.venv','venv'}


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def load(path):
    def bad(value):raise ValueError('NONFINITE_JSON:'+value)
    return json.loads(path.read_text(encoding='utf-8'),parse_constant=bad)


def verify(root=ROOT):
    root=Path(root)
    manifest=load(root/'SOURCE_MANIFEST.json')
    failures=[];seen=set()
    for rec in manifest['files']:
        name=rec['path'];rel=PurePosixPath(name)
        if rel.is_absolute() or '..' in rel.parts or '\\' in name or name in seen:
            failures.append({'path':name,'reason':'INVALID_OR_DUPLICATE_RELATIVE_PATH'});continue
        seen.add(name);p=root/rel
        if any((root/Path(*rel.parts[:i])).is_symlink() for i in range(1,len(rel.parts)+1)):
            failures.append({'path':name,'reason':'SYMLINK_FORBIDDEN'});continue
        if not re.fullmatch('[0-9a-f]{64}',str(rec.get('sha256',''))):
            failures.append({'path':name,'reason':'INVALID_MANIFEST_HASH'});continue
        if not p.is_file():failures.append({'path':name,'reason':'MISSING'})
        elif p.stat().st_size!=rec['size'] or digest(p)!=rec['sha256']:
            failures.append({'path':name,'reason':'HASH_OR_SIZE_MISMATCH'})
    # Detect accidental old/extra code left when overlaying into an old release.
    for p in root.rglob('*.py'):
        rel=p.relative_to(root)
        if not any(part in RUNTIME_DIRS for part in rel.parts) and rel.as_posix() not in seen:
            failures.append({'path':rel.as_posix(),'reason':'UNMANIFESTED_PYTHON_SOURCE'})
    config=load(root/'CORDON_2025_CONFIG.json')
    if config.get('apply') is not False:failures.append({'path':'CORDON_2025_CONFIG.json','reason':'APPLY_MUST_BE_FALSE'})
    if config.get('model_year')!=2025 or config.get('survey_year')!=2026:
        failures.append({'path':'CORDON_2025_CONFIG.json','reason':'WRONG_MODEL_OR_SURVEY_YEAR'})
    if config.get('mode')!='OFFLINE_PROPOSAL':failures.append({'path':'CORDON_2025_CONFIG.json','reason':'OFFLINE_MODE_REQUIRED'})
    for key in ('run_assignment','run_procseq','write_od','supply_enabled','automatic_live_reload','automatic_cache_discovery','persistent_path_cache_enabled','flowbundle_count_authority'):
        if config.get(key,False) is not False:
            failures.append({'path':'CORDON_2025_CONFIG.json','reason':'FORBIDDEN_LIVE_OR_REUSE_FLAG:'+key})
    aggressive_path=root/'CORDON_2025_AGGRESSIVE_CONFIG.json'
    if aggressive_path.is_file():
        aggressive=load(aggressive_path)
        if aggressive.get('apply') is not False or aggressive.get('mode')!='OFFLINE_PROPOSAL':
            failures.append({'path':aggressive_path.name,'reason':'AGGRESSIVE_MUST_BE_OFFLINE'})
        for key in ('run_assignment','run_procseq','write_od','supply_enabled','automatic_live_reload','automatic_cache_discovery','persistent_path_cache_enabled','flowbundle_count_authority'):
            if aggressive.get(key,False) is not False:
                failures.append({'path':aggressive_path.name,'reason':'AGGRESSIVE_FORBIDDEN_FLAG:'+key})
        if aggressive.get('model_year')!=2025 or aggressive.get('survey_year')!=2026:
            failures.append({'path':aggressive_path.name,'reason':'AGGRESSIVE_WRONG_YEAR'})
        source=root/'provenance/aggressive_profile/R1_15A2_AGGRESSIVE_TUNING_V1.json'
        if not source.is_file() or digest(source)!='c41e28c1ecbaa3bbdef43b259458f6407bfbef6af240d9312282e47e6b83e10f':
            failures.append({'path':str(source.relative_to(root)),'reason':'AGGRESSIVE_POLICY_HASH_MISMATCH'})
        design=root/'provenance/aggressive_profile/TGTD_BASE_CONFIG_REFERENCE.json'
        if not design.is_file() or digest(design)!='6aad964325002c8d13c10412bce3f0242ee75fae3640214bc5ab8ec823edda56':
            failures.append({'path':str(design.relative_to(root)),'reason':'AGGRESSIVE_DESIGN_SOURCE_HASH_MISMATCH'})
    return {'status':'RELEASE_INTEGRITY_PASS' if not failures else 'RELEASE_INTEGRITY_FAIL',
            'release':manifest['release'],'checked_files':len(manifest['files']),'failures':failures,
            'apply_permitted':False,'live_visum_tested':False,'production_ready':False}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path);a=p.parse_args()
    try:r=verify()
    except Exception as e:r={'status':'RELEASE_INTEGRITY_FAIL','reason':repr(e),'apply_permitted':False}
    text=json.dumps(r,indent=2);print(text)
    if a.output:a.output.write_text(text,encoding='utf-8')
    raise SystemExit(0 if r['status']=='RELEASE_INTEGRITY_PASS' else 1)
