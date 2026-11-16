"""LIVE04 startup integrity message names which copy of a file is on disk (2026-11-16 live run)."""
import hashlib, importlib.util, json
from cordon2025.common import ROOT


def _boot():
    spec = importlib.util.spec_from_file_location('_b', ROOT / 'cordon_live04_bootstrap.py')
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod


def test_mismatch_reports_expected_and_actual_identity(tmp_path):
    good = b'x = 1\ny = 2\n'
    (tmp_path / 'a.py').write_bytes(good.replace(b'\n', b'\r\n'))
    (tmp_path / 'b.py').write_bytes(b'stale\n')
    files = [{'path': p, 'size': len(good), 'sha256': hashlib.sha256(good).hexdigest()} for p in ('a.py', 'b.py')]
    (tmp_path / 'SOURCE_MANIFEST.json').write_text(json.dumps({'files': files}))
    out = _boot()._explain_integrity(tmp_path, [{'path': p, 'reason': 'HASH_OR_SIZE_MISMATCH'} for p in ('a.py', 'b.py')]
                                     + [{'path': 'c.py', 'reason': 'UNMANIFESTED_PYTHON_SOURCE'}])
    assert out[0]['hint'] == 'CRLF_LINE_ENDINGS_ONLY' and out[0]['expected_sha256_12'] == files[0]['sha256'][:12]
    assert 'hint' not in out[1] and out[1]['actual_size'] == 6 and out[1]['expected_size'] == len(good)
    assert out[2] == {'path': 'c.py', 'reason': 'UNMANIFESTED_PYTHON_SOURCE'}
