"""Build the offline release package from SOURCE_MANIFEST.json and verify the UNPACKED result.

Review 2026-11-19 (PKG-V7-RUN-OPTIONS): a reconstructed export lacked
provenance/v24917_v7/R1_RUN_OPTIONS_V24917_V7_7b4c681.json, so load_config() failed although the
live checkout passed.  Checking the checkout is not enough: this tool packs exactly the files of
SOURCE_MANIFEST.json (no extension / folder filter) plus the unmanifested user configuration
(CORDON_LIVE04_CONFIG.json, TRANSFER_2025_CONFIG.json) and SHA256SUMS.txt, unpacks the zip into a fresh folder and runs,
inside that folder and in an isolated interpreter:

  1. verify_release.verify()                       -> RELEASE_INTEGRITY_PASS (every file present,
                                                      size + SHA-256 as manifested)
  2. cordon2025.live04_config.load_config()         -> the LIVE04 configuration with all its pins
  3. cordon2025.live04_v7.verify_donor_files()      -> the v7 donor / run-options pins

Usage:  python tools/build_release_package.py [--output DIR]
Writes <release>.zip and <release>.PACKAGE_CHECK.json; exit code 0 only when all checks pass.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
# Not manifested on purpose (editable user configuration / the manifest itself), but required to run.
EXTRA = ('SOURCE_MANIFEST.json', 'SHA256SUMS.txt', 'CORDON_LIVE04_CONFIG.json', 'TRANSFER_2025_CONFIG.json')
CHECK = r'''
import json, sys
sys.path.insert(0, '.')
out = {}
import verify_release
r = verify_release.verify('.')
out['release_integrity'] = {'status': r['status'], 'failures': r['failures'][:20], 'checked_files': r.get('checked_files')}
try:
    from cordon2025.live04_config import load_config
    cfg = load_config()
    out['load_config'] = {'status': 'PASS', 'run_options_pin': cfg['v7'].get('run_options_pin') if isinstance(cfg.get('v7'), dict) else None}
except Exception as exc:
    out['load_config'] = {'status': 'FAIL', 'error': repr(exc)[:2000]}
try:
    from cordon2025 import live04_v7
    out['v7_pins'] = {'status': 'PASS', 'files': len(live04_v7.verify_donor_files())}
except Exception as exc:
    out['v7_pins'] = {'status': 'FAIL', 'error': repr(exc)[:2000]}
print(json.dumps(out))
'''


def manifest_files(root):
    m = json.loads((root / 'SOURCE_MANIFEST.json').read_text(encoding='utf-8'))
    names = []
    for rec in m['files']:
        rel = PurePosixPath(rec['path'])
        if rel.is_absolute() or '..' in rel.parts:
            raise SystemExit('INVALID_MANIFEST_PATH:' + rec['path'])
        if not (root / rel).is_file():
            raise SystemExit('MANIFESTED_FILE_MISSING_IN_SOURCE:' + rec['path'])
        names.append(rec['path'])
    return m['release'], names


def build(root, output):
    release, names = manifest_files(root)
    output.mkdir(parents=True, exist_ok=True)
    target = output / (release + '.zip')
    with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        for name in sorted(set(names) | set(EXTRA)):
            if not (root / name).is_file():
                raise SystemExit('REQUIRED_PACKAGE_FILE_MISSING_IN_SOURCE:' + name)
            z.write(root / name, name)
    return release, target, len(names)


def check(zip_path):
    with tempfile.TemporaryDirectory(prefix='r1c25_pkg_') as tmp:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(tmp)
        proc = subprocess.run([sys.executable, '-I', '-c', CHECK], cwd=tmp, capture_output=True, text=True, timeout=900)
    try:
        out = json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception:
        out = {'error': 'CHECK_PROCESS_FAILED', 'stdout': proc.stdout[-2000:], 'stderr': proc.stderr[-4000:]}
    ok = (out.get('release_integrity', {}).get('status') == 'RELEASE_INTEGRITY_PASS'
          and out.get('load_config', {}).get('status') == 'PASS' and out.get('v7_pins', {}).get('status') == 'PASS')
    out['status'] = 'PACKAGE_CHECK_PASS' if ok else 'PACKAGE_CHECK_FAIL'
    return out


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument('--output', type=Path, default=ROOT / 'OFFLINE_RESULTS' / 'PACKAGE')
    a = p.parse_args(argv)
    release, target, n = build(ROOT, a.output)
    out = check(target)
    h = hashlib.sha256(target.read_bytes()).hexdigest()
    out.update(release=release, zip=str(target), zip_sha256=h, manifested_files=n,
               note='Synthetic/offline package check; native PTV Visum validation pending')
    (a.output / (release + '.PACKAGE_CHECK.json')).write_text(json.dumps(out, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: out[k] for k in ('status', 'zip', 'manifested_files')}))
    return 0 if out['status'] == 'PACKAGE_CHECK_PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
