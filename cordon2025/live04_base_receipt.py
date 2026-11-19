"""LIVE04.14 unit-base receipt: proof that the demand of the opened .ver was recomputed natively
AFTER its W/S coefficients were set (review cc3c3c4, finding 2).

unit_start_check() only sees coefficient VALUES.  A model whose coefficients were reset to 1 but
whose person OD matrices 9101-9117 still come from the old calibrated state would pass it, and
its stale demand would become the immutable run reference (centrality, OD links, production
shares).  The file name (*_LIVE04_BASE_*) proves nothing.

RUN_R1_2025_RECOMPUTE_FOR_LIVE04_BASE.py therefore issues a sealed receipt next to the .ver it
saves.  The receipt binds three things that LIVE04 re-checks at a fresh run start
(generation_structure.reference_start_policy = REQUIRE_UNIT_WS_ON_ACTUATABLE_DOMESTIC_ZONES):

  * identity of the saved .ver           (SHA-256 of the opened file)
  * the input W/S coefficients           (exact values per Zone.NO, read before AND after the
                                          recompute - the recompute refuses if they moved)
  * the output person OD matrices        (SHA-256 of the float64 values of 9101-9117 after the
                                          native recompute)

Any later change (a second reset without recompute, edited matrices, another .ver) breaks one of
the three equalities and the run stops before the reference is captured.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from .common import canonical_hash, parent_module, require

SCHEMA = 'R1C25_LIVE04_BASE_RECEIPT_V1'
SUFFIX = '.LIVE04_BASE_RECEIPT.json'
PERSON_OD_MATRICES = tuple(range(9101, 9118))
WS_ATTRIBUTES = ('ADD_PROD_W', 'ADD_PROD_S', 'ADD_ATT_W', 'ADD_ATT_S')
METHOD = 'NATIVE_RECOMPUTE_AFTER_COEFFICIENTS_SHA_BOUND'


def sha_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def ws_values(values_by_attr):
    """{attr: {zone_no(str): float}} for the four W/S attributes, canonical (exact floats)."""
    require(set(values_by_attr) >= set(WS_ATTRIBUTES), 'LIVE04_BASE_RECEIPT_WS_ATTRIBUTES')
    return {a: {str(int(float(z))): float(v) for z, v in sorted(values_by_attr[a].items(), key=lambda t: int(float(t[0])))}
            for a in WS_ATTRIBUTES}


def read_ws(visum, zones, zone_indices=None, retry_policy=None):
    com = parent_module('r1_15a2_com_compat')
    out = {}
    for a in WS_ATTRIBUTES:
        vals = com.indexed_zone_values(visum, a, list(zones), retry_policy=retry_policy, zone_indices=zone_indices)
        out[a] = {str(int(z)): float(v) for z, v in zip(zones, vals)}
    return ws_values(out)


def person_od(visum, matrix_nos=PERSON_OD_MATRICES):
    """Value fingerprints of the person OD matrices (read-only)."""
    rt = parent_module('r1_15a2_runtime_v1')
    rows = []
    for no in matrix_nos:
        try:
            mat = visum.Net.Matrices.ItemByKey(int(no))
        except Exception:
            mat = None
        require(mat is not None, 'LIVE04_BASE_RECEIPT_PERSON_MATRIX_MISSING:%d' % no)
        fp = rt._fingerprint_matrix_object(mat, 'MATRIX:%d' % no, 'PERSON_OD')
        rows.append({'matrix_no': int(no), 'rows': fp['rows'], 'cols': fp['cols'], 'sum': fp['sum'],
                     'sha256_float64_le': fp['sha256_float64_le']})
    return rows


def _body(receipt):
    return {k: v for k, v in receipt.items() if k != 'receipt_sha256'}


def seal(receipt):
    out = _body(receipt)
    out['receipt_sha256'] = canonical_hash(out)
    return out


def path_for(version_path):
    p = Path(version_path)
    return p.with_name(p.stem + SUFFIX)


def issue(visum, *, saved_version, ws, matrices, source_version=None, source_sha256=None,
          recompute_folder=None, unit_reset=None):
    """Sealed receipt for a .ver that was just saved after a native recompute; written next to it."""
    saved = Path(saved_version)
    receipt = seal({'schema': SCHEMA, 'method': METHOD,
                    'saved_version': {'name': saved.name, 'sha256': sha_file(saved)},
                    'source_version': {'name': Path(source_version).name if source_version else None,
                                       'sha256': source_sha256},
                    'recompute_folder': str(recompute_folder) if recompute_folder else None,
                    'ws_coefficients': ws_values(ws), 'ws_sha256': canonical_hash(ws_values(ws)),
                    'person_od_matrices': list(matrices), 'person_od_sha256': canonical_hash(list(matrices)),
                    'unit_reset': unit_reset})
    target = path_for(saved)
    tmp = target.with_name(target.name + '.tmp')
    tmp.write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    os.replace(tmp, target)
    return receipt, target


def _load(path):
    try:
        rec = json.loads(Path(path).read_text(encoding='utf-8'))
    except Exception as exc:
        raise RuntimeError('LIVE04_BASE_RECEIPT_UNREADABLE:%s:%s' % (Path(path).name, exc))
    require(isinstance(rec, dict) and rec.get('schema') == SCHEMA, 'LIVE04_BASE_RECEIPT_SCHEMA:' + Path(path).name)
    require(rec.get('receipt_sha256') == canonical_hash(_body(rec)), 'LIVE04_BASE_RECEIPT_SEAL_BROKEN:' + Path(path).name)
    return rec


def find(opened_version):
    """Receipt whose saved .ver has exactly the bytes of the opened file (sidecar first, then any
    receipt in the same folder - a renamed byte-identical copy is still the same model)."""
    opened = Path(opened_version)
    require(opened.is_file(), 'LIVE04_BASE_RECEIPT_OPENED_VERSION_NOT_A_FILE')
    sha = sha_file(opened)
    candidates = [path_for(opened)] + sorted(p for p in opened.parent.glob('*' + SUFFIX) if p != path_for(opened))
    seen = []
    for p in candidates:
        if not p.is_file():
            continue
        rec = _load(p)
        seen.append(p.name)
        if rec['saved_version']['sha256'] == sha:
            return p, rec, sha
    raise RuntimeError('LIVE04_BASE_RECEIPT_MISSING_FOR_OPENED_VERSION:%s (receipts in folder: %s). Reset the W/S '
                       'coefficients, run RUN_R1_2025_RECOMPUTE_FOR_LIVE04_BASE.py and open the *_LIVE04_BASE_*.ver '
                       'it saved; a .ver changed or re-saved after the recompute has no receipt.'
                       % (opened.name, seen or 'none'))


def verify(visum, zones, ws_now, zone_indices=None, retry_policy=None):
    """Fresh run start: opened .ver == receipt .ver, coefficients == receipt inputs, person OD ==
    receipt outputs.  Read-only; raises on any difference."""
    opened = str(visum.IO.CurrentVersionFile)
    path, rec, sha = find(opened)
    now = ws_values(ws_now)
    if now != rec['ws_coefficients']:
        diff = sorted({(a, z) for a in WS_ATTRIBUTES for z in now[a]
                       if now[a][z] != rec['ws_coefficients'][a].get(z)})
        raise RuntimeError('LIVE04_BASE_RECEIPT_COEFFICIENTS_CHANGED_AFTER_RECOMPUTE:%d values (e.g. %s); recompute '
                           'again after the last coefficient change' % (len(diff), diff[:5]))
    od = person_od(visum, [r['matrix_no'] for r in rec['person_od_matrices']])
    require([r['matrix_no'] for r in rec['person_od_matrices']] == list(PERSON_OD_MATRICES),
            'LIVE04_BASE_RECEIPT_PERSON_MATRIX_SET')
    bad = [a['matrix_no'] for a, b in zip(od, rec['person_od_matrices'])
           if a['sha256_float64_le'] != b['sha256_float64_le'] or (a['rows'], a['cols']) != (b['rows'], b['cols'])]
    require(not bad, 'LIVE04_BASE_RECEIPT_PERSON_DEMAND_DIFFERS_FROM_RECOMPUTE:%s' % bad)
    return {'status': 'VERIFIED_RECOMPUTED_BASE', 'receipt': path.name, 'receipt_sha256': rec['receipt_sha256'],
            'saved_version_sha256': sha, 'ws_sha256': rec['ws_sha256'], 'person_od_sha256': rec['person_od_sha256'],
            'recompute_folder': rec.get('recompute_folder')}
