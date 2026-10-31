import hashlib,json
import pytest
from verify_release import verify


def root(tmp_path):
    (tmp_path/'one.py').write_text('x=1\n')
    config={'model_year':2025,'survey_year':2026,'mode':'OFFLINE_PROPOSAL','apply':False}
    (tmp_path/'CORDON_2025_CONFIG.json').write_text(json.dumps(config))
    files=[{'path':p.name,'size':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in tmp_path.iterdir()]
    (tmp_path/'SOURCE_MANIFEST.json').write_text(json.dumps({'release':'TEST','files':files}))
    return tmp_path


def test_verifier_accepts_exact_manifest_and_ignores_runtime(tmp_path):
    r=root(tmp_path);(r/'OFFLINE_RESULTS').mkdir();(r/'OFFLINE_RESULTS/demo.py').write_text('runtime')
    assert verify(r)['status']=='RELEASE_INTEGRITY_PASS'


def test_verifier_rejects_unmanifested_old_code(tmp_path):
    r=root(tmp_path);(r/'old_oneclick.py').write_text('do_not_run')
    assert any(x['reason']=='UNMANIFESTED_PYTHON_SOURCE' for x in verify(r)['failures'])


def test_verifier_rejects_tamper(tmp_path):
    r=root(tmp_path);(r/'one.py').write_text('x=2\n')
    assert verify(r)['status']=='RELEASE_INTEGRITY_FAIL'


def test_verifier_rejects_duplicate_and_escape(tmp_path):
    r=root(tmp_path);p=r/'SOURCE_MANIFEST.json';m=json.loads(p.read_text());m['files']+=[m['files'][0],{'path':'../outside','size':0,'sha256':'a'*64}];p.write_text(json.dumps(m))
    assert sum(x['reason']=='INVALID_OR_DUPLICATE_RELATIVE_PATH' for x in verify(r)['failures'])==2


def test_verifier_rejects_symlink_even_equal_content(tmp_path):
    r=root(tmp_path);p=r/'one.py';p.rename(r/'copy');p.symlink_to(r/'copy')
    assert any(x['reason']=='SYMLINK_FORBIDDEN' for x in verify(r)['failures'])


def test_verifier_refuses_live_flags_even_with_rehashed_config(tmp_path):
    r=root(tmp_path);p=r/'CORDON_2025_CONFIG.json';cfg=json.loads(p.read_text());cfg['automatic_live_reload']=True;p.write_text(json.dumps(cfg))
    m=json.loads((r/'SOURCE_MANIFEST.json').read_text())
    for rec in m['files']:
        if rec['path']==p.name:rec.update(size=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest())
    (r/'SOURCE_MANIFEST.json').write_text(json.dumps(m))
    assert any('FORBIDDEN_LIVE' in x['reason'] for x in verify(r)['failures'])
