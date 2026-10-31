from pathlib import Path
import importlib.util,json,pytest,hashlib
from cordon2025.common import ROOT
spec=importlib.util.spec_from_file_location('patch_tool',ROOT/'tools/apply_diagfast_patch.py')
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)

@pytest.mark.parametrize('path',['../escape.py','/abs.py','x\\y.py','C:drive.py','foo/../../bar'])
def test_patch_traversal_rejected(path):
    with pytest.raises(ValueError,match='UNSAFE_MEMBER'):p.safe_member(path)

def test_patch_wrong_base_zip_never_publishes(tmp_path):
    patch=tmp_path/'patch';patch.mkdir()
    (patch/'PATCH_MANIFEST.json').write_text(json.dumps({'base_zip_sha256':p.BASE_ZIP_SHA,'files':[]}))
    bad=tmp_path/'bad.zip';bad.write_bytes(b'wrong')
    with pytest.raises(ValueError,match='BASE_ZIP_SHA_MISMATCH'):
        p.install(bad,None,tmp_path/'out',patch)
    assert not (tmp_path/'out').exists() and not list(tmp_path.glob('*.lock'))

def test_patch_existing_output_not_overwritten(tmp_path):
    out=tmp_path/'out';out.mkdir();(out/'keep').write_bytes(b'safe')
    with pytest.raises(ValueError,match='OUTPUT_MUST_BE_NEW'):p.install(None,tmp_path,out,tmp_path)
    assert (out/'keep').read_bytes()==b'safe'

def test_patch_symlink_rejected(tmp_path):
    out=tmp_path/'out';out.symlink_to(tmp_path/'target',target_is_directory=True)
    with pytest.raises(ValueError,match='SYMLINK'):p.install(None,tmp_path,out,tmp_path)

def test_patch_parallel_lock_not_stolen(tmp_path):
    out=tmp_path/'out';lock=out.parent/('.r1df_'+hashlib.sha256(str(out).encode()).hexdigest()[:16]+'.lock')
    lock.write_text('other')
    with pytest.raises(ValueError,match='LOCKED_NO_STEAL'):p.install(None,tmp_path,out,tmp_path)
    assert lock.read_text()=='other'
