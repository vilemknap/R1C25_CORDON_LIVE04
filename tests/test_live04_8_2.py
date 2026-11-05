"""LIVE04.8.2: the user-editable configs may be edited without breaking release integrity; LIVE04 allows long runs."""
import json
import shutil
import importlib.util
from pathlib import Path

import pytest

from cordon2025 import live04_config as c4
from cordon2025 import live03_config as c3

ROOT = Path(__file__).resolve().parents[1]
USER_CONFIGS = ('CORDON_LIVE04_CONFIG.json', 'TRANSFER_2025_CONFIG.json')


def _verifier(root):
    spec = importlib.util.spec_from_file_location('_vr_8_2', root / 'verify_release.py')
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


def test_user_configs_are_not_hashed_but_release_defaults_are():
    manifest = json.loads((ROOT / 'SOURCE_MANIFEST.json').read_text(encoding='utf-8'))
    paths = {f['path'] for f in manifest['files']}
    for name in USER_CONFIGS:
        assert name not in paths
        default = 'provenance/live04_user_config/' + name.replace('.json', '.RELEASE_DEFAULT.json')
        assert default in paths
        assert json.loads((ROOT / default).read_text(encoding='utf-8')).keys() == \
            json.loads((ROOT / name).read_text(encoding='utf-8')).keys()


def test_edited_max_cycles_keeps_release_integrity(tmp_path):
    dst = tmp_path / 'R1C25_LIVE04'
    shutil.copytree(ROOT, dst, ignore=shutil.ignore_patterns('__pycache__', '.pytest_cache', 'OFFLINE_RESULTS'))
    p = dst / 'CORDON_LIVE04_CONFIG.json'
    cfg = json.loads(p.read_text(encoding='utf-8')); cfg['max_cycles'] = 100
    p.write_text(json.dumps(cfg, indent=1), encoding='utf-8')
    proof = _verifier(dst).verify(dst)
    assert proof['status'] == 'RELEASE_INTEGRITY_PASS', proof['failures'][:5]
    # A code edit is still caught.
    (dst / 'cordon2025' / 'live04_cycle.py').write_text('# tampered\n', encoding='utf-8')
    assert _verifier(dst).verify(dst)['status'] == 'RELEASE_INTEGRITY_FAIL'


def test_live04_accepts_100_cycles_live03_keeps_its_cap():
    assert c4.load_config(overrides={'max_cycles': 100})['max_cycles'] == 100
    assert c4.load_config(overrides={'max_cycles': c4.LIVE04_MAX_CYCLES})['max_cycles'] == c4.LIVE04_MAX_CYCLES
    with pytest.raises(Exception, match='max_cycles'):
        c4.load_config(overrides={'max_cycles': c4.LIVE04_MAX_CYCLES + 1})
    with pytest.raises(Exception, match='max_cycles'):
        c3.validate_sections(dict(c3.load_config() if hasattr(c3, 'load_config') else {}, max_cycles=11))
