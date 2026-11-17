r"""Freeze the current Visum DIS skims as the calibrator's distance matrices (2026-11-17).

Run from Visum > Scripts > Execute script file on a SAVED 2025 version whose assignment
and PrT skims (DIS of NATIVE_CF/CL/CS/CS_noT/CW/CW_noT) were computed after the last
network edit - e.g. the LIVE04 checkpoint or a *_LIVE04_BASE_*.ver.

Writes DATA matrices (same matrix type as 9697):
  9720..9725  R1_BASE_DIS_<segment>_KM  = DIS of the segment, diagonal = 9697 diagonal
              (DIS has no intrazonal distance; 9697 holds the approved AMDY intrazonal km)
  9726        R1_BASE_DIS_IDP_WORK_KM   = r*CW + (1-r)*CW_noT, r = 9231 (RATIO_CW)
  9727        R1_BASE_DIS_IDP_SERV_KM   = r*CS + (1-r)*CS_noT, r = 9233 (RATIO_CS)
9697 is not changed.  Existing 9720..9727 are overwritten only when their CODE matches.
Then saves a NEW version <name>_DISTFRZ_<id>.ver (never overwrites the open file, never
LoadVersion).  Next step: RUN_R1_2025_RECOMPUTE_FOR_LIVE04_BASE.py in the same Visum
(recompute with the LONG mask on 9721), then the LIVE04 calibrator on the saved BASE.

Silent: the result goes to %LOCALAPPDATA%\R1C25_DISTANCE_FREEZE\<time>\RESULT.json.
"""
from __future__ import annotations
import hashlib
import json
import os
import traceback
import uuid
from datetime import datetime
from pathlib import Path

import numpy as np

SCHEMA = 'R1C25_FREEZE_SKIM_DISTANCES_V1'
SEGMENTS = ('NATIVE_CF', 'NATIVE_CL', 'NATIVE_CS', 'NATIVE_CS_NOT', 'NATIVE_CW', 'NATIVE_CW_NOT')
OSRM_NO, OSRM_CODE = 9697, 'R1_OSRM_DIST_KM'
TARGETS = {9720 + i: 'R1_BASE_DIS_%s_KM' % s for i, s in enumerate(SEGMENTS)}
TARGETS[9726] = 'R1_BASE_DIS_IDP_WORK_KM'
TARGETS[9727] = 'R1_BASE_DIS_IDP_SERV_KM'
RATIOS = {'W': (9231, 'RATIO_CW'), 'S': (9233, 'RATIO_CS')}
NO_PATH_KM = 999999.0
LONG_MIN_KM = 80.0
DOMESTIC_MAX_ZONE = 655


def _sha_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def _digest(a):
    return hashlib.sha256(np.ascontiguousarray(a, dtype='<f8').tobytes()).hexdigest()


def _items(coll):
    member = coll.GetAll
    return list(member() if callable(member) else member)


def _att(obj, name):
    return str(obj.AttValue(name)).strip()


def _values(matrix, n, label):
    a = np.array(matrix.GetValues(), dtype=np.float64, copy=True, order='C')
    if a.shape != (n, n) or not np.isfinite(a).all() or (a < 0).any():
        raise RuntimeError('FREEZE_INVALID_VALUES:' + label)
    return a


def zone_axis(visum):
    pairs = sorted((int(i), int(no)) for i, no in visum.Net.Zones.GetMultiAttValues('NO'))
    axis = [no for _, no in pairs]
    if not axis or len(set(axis)) != len(axis):
        raise RuntimeError('FREEZE_INVALID_ZONE_AXIS')
    return np.asarray(axis, dtype=np.int64)


def read_sources(visum, n):
    found, used = {}, {}
    for m in _items(visum.Net.Matrices):
        no = int(float(m.AttValue('NO')))
        used[no] = _att(m, 'CODE').upper()
        if used[no] == 'DIS':
            dseg = _att(m, 'DSEGCODE').upper()
            if dseg in SEGMENTS:
                if dseg in found:
                    raise RuntimeError('FREEZE_DUPLICATE_DIS:' + dseg)
                found[dseg] = m
    missing = [s for s in SEGMENTS if s not in found]
    if missing:
        raise RuntimeError('FREEZE_DIS_SKIM_MISSING:' + ','.join(missing))
    osrm = visum.Net.Matrices.ItemByKey(OSRM_NO)
    if _att(osrm, 'CODE').upper() != OSRM_CODE:
        raise RuntimeError('FREEZE_9697_IDENTITY')
    src = {'M9697': _values(osrm, n, 'M9697')}
    prov = {'M9697': {'matrix_no': OSRM_NO, 'sha256': _digest(src['M9697'])}}
    for s in SEGMENTS:
        a = _values(found[s], n, 'DIS_' + s)
        src[s] = a
        prov['DIS_' + s] = {'matrix_no': int(float(found[s].AttValue('NO'))), 'sha256': _digest(a)}
    for key, (no, code) in RATIOS.items():
        m = visum.Net.Matrices.ItemByKey(no)
        if _att(m, 'CODE').upper() != code:
            raise RuntimeError('FREEZE_RATIO_IDENTITY:%d' % no)
        r = _values(m, n, code)
        if (r > 1.0 + 1e-9).any():
            raise RuntimeError('FREEZE_RATIO_ABOVE_ONE:%d' % no)
        src['R_' + key] = np.clip(r, 0.0, 1.0)
        prov[code] = {'matrix_no': no, 'sha256': _digest(r)}
    for no, code in TARGETS.items():
        if no in used and used[no] != code:
            raise RuntimeError('FREEZE_TARGET_NUMBER_USED_BY_OTHER_MATRIX:%d:%s' % (no, used[no]))
    return src, prov, {no for no in TARGETS if no in used}


def build(src):
    """Pure numpy: the eight frozen matrices (tested offline)."""
    n = src['M9697'].shape[0]
    off = ~np.eye(n, dtype=bool)
    for s in SEGMENTS:
        d = src[s][off]
        if (d <= 0).any() or (d >= NO_PATH_KM).any():
            bad = int(((d <= 0) | (d >= NO_PATH_KM)).sum())
            raise RuntimeError('FREEZE_DIS_NO_PATH_OR_ZERO:%s:%d_pairs' % (s, bad))
    diag = np.diag(src['M9697']).copy()
    out = {}
    for i, s in enumerate(SEGMENTS):
        a = src[s].copy()
        np.fill_diagonal(a, diag)
        out[9720 + i] = a
    for no, key, tol, notol in ((9726, 'W', 'NATIVE_CW', 'NATIVE_CW_NOT'), (9727, 'S', 'NATIVE_CS', 'NATIVE_CS_NOT')):
        r = src['R_' + key]
        a = r * src[tol] + (1.0 - r) * src[notol]
        np.fill_diagonal(a, diag)
        out[no] = a
    for no, a in out.items():
        if a.shape != (n, n) or not np.isfinite(a).all() or (a < 0).any():
            raise RuntimeError('FREEZE_BUILD_INVALID:%d' % no)
    return out


def audit(src, frozen, axis):
    n = len(axis)
    off = ~np.eye(n, dtype=bool)
    dom = (axis <= DOMESTIC_MAX_ZONE)
    dd = off & dom[:, None] & dom[None, :]
    ref = src['M9697']
    out = {}
    for no, a in frozen.items():
        diff = a - ref
        out[str(no)] = {
            'code': TARGETS[no], 'sha256': _digest(a), 'sum_km': float(a.sum()),
            'domestic_mean_km': float(a[dd].mean()), 'osrm_domestic_mean_km': float(ref[dd].mean()),
            'domestic_mean_abs_diff_km': float(np.abs(diff[dd]).mean()),
            'domestic_pairs_ge_80_km': int((a[dd] >= LONG_MIN_KM).sum()),
            'osrm_domestic_pairs_ge_80_km': int((ref[dd] >= LONG_MIN_KM).sum()),
            'domestic_pairs_80_km_side_changed': int(((a >= LONG_MIN_KM) != (ref >= LONG_MIN_KM))[dd].sum()),
            'max_abs_diff_km_all_pairs': float(np.abs(diff[off]).max()) if n > 1 else 0.0}
    return out


def _add_matrix(visum, no, like):
    otype, mtype = like.AttValue('OBJECTTYPEREF'), like.AttValue('MATRIXTYPE')
    cands = [(no, otype, mtype)]
    try:
        cands.append((no, int(float(otype)), int(float(mtype))))
    except Exception:
        pass
    errors = []
    for args in cands + [(no, 2, 3)]:
        try:
            m = visum.Net.AddMatrix(*args)
        except Exception as exc:
            errors.append('%r:%s' % (args, exc))
            continue
        if str(m.AttValue('MATRIXTYPE')) == str(mtype) and str(m.AttValue('OBJECTTYPEREF')) == str(otype):
            return m
        try:
            visum.Net.RemoveMatrix(m)
        except Exception as exc:
            raise RuntimeError('FREEZE_ADDMATRIX_WRONG_TYPE_NOT_REMOVABLE:%d:%s' % (no, exc))
        errors.append('%r:type' % (args,))
    raise RuntimeError('FREEZE_ADDMATRIX_FAILED:%d:%s' % (no, ' | '.join(errors))[:600])


def write(visum, frozen, existing):
    like = visum.Net.Matrices.ItemByKey(OSRM_NO)
    rows = []
    for no, a in sorted(frozen.items()):
        m = visum.Net.Matrices.ItemByKey(no) if no in existing else _add_matrix(visum, no, like)
        m.SetAttValue('CODE', TARGETS[no])
        m.SetAttValue('NAME', 'R1 frozen Visum DIS km %s (%s)' % (TARGETS[no][11:-3], datetime.now().strftime('%Y-%m-%d')))
        m.SetValues(np.array(a, dtype=np.float64, copy=True, order='C'), False)
        back = np.array(m.GetValues(), dtype=np.float64)
        if back.shape != a.shape or float(np.abs(back - a).max()) > 1e-9:
            raise RuntimeError('FREEZE_READBACK_MISMATCH:%d' % no)
        if _att(m, 'CODE').upper() != TARGETS[no]:
            raise RuntimeError('FREEZE_CODE_READBACK:%d' % no)
        rows.append({'matrix_no': no, 'code': TARGETS[no], 'created': no not in existing})
    return rows


def run(visum, out_dir=None):
    out = Path(out_dir or (Path(os.environ.get('LOCALAPPDATA') or Path.home()) / 'R1C25_DISTANCE_FREEZE'
                           / datetime.now().strftime('%Y%m%d_%H%M%S')))
    out.mkdir(parents=True, exist_ok=True)
    result = {'schema': SCHEMA, 'status': 'STARTED', 'model_changed': False, 'saved_version': None,
              'load_version_called': False, 'source_version_overwritten': False}
    path = out / 'RESULT.json'

    def dump():
        path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    dump()
    try:
        src_path = Path(str(visum.IO.CurrentVersionFile).strip())
        if not src_path.is_file() or src_path.suffix.lower() != '.ver':
            raise RuntimeError('FREEZE_OPEN_A_SAVED_VER_FIRST:' + str(src_path))
        if '2025' not in src_path.name or '2022' in src_path.name:
            raise RuntimeError('FREEZE_ONLY_2025_MODEL:' + src_path.name)
        src_sha = _sha_file(src_path)
        result.update(source_version=str(src_path), source_version_sha256=src_sha)
        axis = zone_axis(visum)
        src, prov, existing = read_sources(visum, len(axis))
        frozen = build(src)
        result.update(sources=prov, audit=audit(src, frozen, axis), zone_count=len(axis),
                      freshness_note='DIS must come from an assignment run after the last network edit; '
                                     'the script cannot certify that.')
        dump()
        result['model_changed'] = True
        result['matrices'] = write(visum, frozen, existing)
        target = src_path.with_name(src_path.stem + '_DISTFRZ_' + uuid.uuid4().hex[:8] + src_path.suffix)
        if target.exists():
            raise RuntimeError('FREEZE_SAVE_TARGET_EXISTS')
        visum.SaveVersion(str(target))
        if _sha_file(src_path) != src_sha:
            result['source_version_overwritten'] = True
            raise RuntimeError('FREEZE_SOURCE_VERSION_CHANGED')
        result.update(status='FROZEN_SAVED', saved_version=str(target), saved_version_sha256=_sha_file(target),
                      next_step='RUN_R1_2025_RECOMPUTE_FOR_LIVE04_BASE.py on the saved version')
        return result
    except BaseException:
        result['status'] = ('FAILED_MODEL_CHANGED_CLOSE_WITHOUT_SAVING' if result['model_changed']
                            and not result['saved_version'] else 'FAILED')
        result['error'] = traceback.format_exc()[-3000:]
        raise
    finally:
        dump()
        try:
            last = Path(os.environ.get('LOCALAPPDATA') or Path.home()) / 'R1C25_DISTANCE_FREEZE' / 'LAST_RESULT.json'
            last.write_text(path.read_text(encoding='utf-8'), encoding='utf-8')
        except Exception:
            pass


if __name__ == '__main__':
    import io as _io, sys as _sys
    _saved = (_sys.stdout, _sys.stderr); _buf = _io.StringIO(); _sys.stdout = _sys.stderr = _buf
    try:
        run(Visum)  # noqa: F821  (injected by Visum)
    except BaseException:
        _buf.write(traceback.format_exc())
    finally:
        _sys.stdout, _sys.stderr = _saved
