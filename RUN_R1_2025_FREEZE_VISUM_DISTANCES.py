"""Freeze the current Visum DIS skims into DATA matrices for the next LIVE04 baseline.

Universal (2026-11-18): works on ANY saved 2025 version whose assignment and skims
are current; it is not tied to one checkpoint file.

Open the version, run this script, then run RUN_R1_2025_RECOMPUTE_FOR_LIVE04_BASE.py
in the same Visum instance (it reapplies the LONG mask on the frozen NATIVE_CL
distance and saves a new *_LIVE04_BASE_*.ver). This script never saves a .ver and
never changes 9697.

Sources (found by CODE = DIS and DSEGCODE, not by fixed numbers), one per segment:
  9720 NATIVE_CF, 9721 NATIVE_CL, 9722 NATIVE_CS, 9723 NATIVE_CS_noT,
  9724 NATIVE_CW, 9725 NATIVE_CW_noT        diagonal taken from 9697 (DIS has 0)
  9726 = RATIO_CW (9231) x 9724 + (1 - RATIO_CW) x 9725   (WORK / SCHOOL IDP)
  9727 = RATIO_CS (9233) x 9722 + (1 - RATIO_CS) x 9723   (SERVICE IDP)
Re-running on a version that already holds 9720-9727 overwrites them (same CODE).
A target number used by another matrix stops the script before any write.

The script cannot prove that DIS was computed after the last network change: run it
only on a version saved after a full recompute. The result with the source version,
its file SHA-256 and the hash of every matrix is written to
%LOCALAPPDATA%\\R1C25_DISTANCE_PREP\\FROZEN_DISTANCE_RESULT.json; the calibrator records
the same matrix hashes at run start and refuses any change during the run.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import traceback
import uuid
import numpy as np

EXPECTED_ZONES = 681
SEGMENTS = ((9720, 'NATIVE_CF'), (9721, 'NATIVE_CL'), (9722, 'NATIVE_CS'),
            (9723, 'NATIVE_CS_NOT'), (9724, 'NATIVE_CW'), (9725, 'NATIVE_CW_NOT'))
BLENDS = ((9726, 9231, 'RATIO_CW', 9724, 9725), (9727, 9233, 'RATIO_CS', 9722, 9723))
TARGET_CODES = {no: 'R1_BASE_DIS_' + dseg + '_KM' for no, dseg in SEGMENTS}
TARGET_CODES.update({9726: 'R1_BASE_DIS_WORK_KM', 9727: 'R1_BASE_DIS_SERV_KM'})
ORIGINAL = (9697, 'R1_OSRM_DIST_KM')
NO_PATH_KM = 100000.0        # Visum writes 999999 for OD pairs without a path


def sha_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def values(matrix, n):
    arr = np.asarray(matrix.GetValues(), dtype='<f8')
    if arr.shape != (n, n) or not np.isfinite(arr).all() or (arr < 0).any():
        raise RuntimeError('DISTANCE_SOURCE_INVALID_VALUES:' + str(matrix.AttValue('NO')))
    return np.ascontiguousarray(arr)


def digest(arr):
    return hashlib.sha256(np.ascontiguousarray(arr, dtype='<f8').tobytes()).hexdigest()


def enum_is(value, expected, aliases):
    token = ''.join(c for c in str(value).upper() if c.isalnum())
    if token in aliases:
        return True
    try:
        return not isinstance(value, bool) and float(value) == expected
    except (TypeError, ValueError, OverflowError):
        return False


def matrix_type_is_source(matrix):
    return (enum_is(matrix.AttValue('OBJECTTYPEREF'), 2, {'OBJECTTYPEREFZONE', 'ZONE', 'ZONES'})
            and enum_is(matrix.AttValue('MATRIXTYPE'), 3, {'MATRIXTYPEDEMAND', 'DEMAND', 'MATRIXTYPEOD', 'MATRIXTYPEODMATRIX', 'ODMATRIX'}))


def data_source_is_data(matrix):
    return enum_is(matrix.AttValue('DATASOURCETYPE'), 1, {'DATA', 'DATASOURCETYPEDATA', 'MATRIXDATASOURCETYPEDATA'})


def type_text(matrix):
    out = []
    for key in ('MATRIXTYPE', 'OBJECTTYPEREF', 'DATASOURCETYPE'):
        try:
            out.append('%s=%r' % (key, matrix.AttValue(key)))
        except Exception as exc:
            out.append('%s=<%s>' % (key, type(exc).__name__))
    return ','.join(out)


def blended_distance(eligible, restricted, ratio):
    if not np.isfinite(ratio).all() or np.any((ratio < 0) | (ratio > 1)):
        raise RuntimeError('DISTANCE_SPLIT_RATIO_OUT_OF_RANGE')
    return np.ascontiguousarray(ratio * eligible + (1.0 - ratio) * restricted, dtype='<f8')


def _code(matrix):
    return str(matrix.AttValue('CODE')).strip().upper()


def _number(value):
    return int(round(float(value)))


def _result_path():
    out = Path(os.environ.get('LOCALAPPDATA') or Path.home()) / 'R1C25_DISTANCE_PREP'
    out.mkdir(parents=True, exist_ok=True)
    return out / 'FROZEN_DISTANCE_RESULT.json'


def _write(path, report):
    path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')


def _inventory(visum):
    """{matrix_no: (code, dsegcode)} of all matrices, read in bulk."""
    coll = visum.Net.Matrices
    nos = coll.GetMultiAttValues('NO')
    codes = coll.GetMultiAttValues('CODE')
    dsegs = coll.GetMultiAttValues('DSEGCODE')
    if not ([i for i, _ in nos] == [i for i, _ in codes] == [i for i, _ in dsegs]):
        raise RuntimeError('DISTANCE_MATRIX_INVENTORY_ORDER_CHANGED')
    return {_number(no): (str(c).strip().upper(), str(d).strip().upper())
            for (_, no), (_, c), (_, d) in zip(nos, codes, dsegs)}


def prepare(visum):
    source = Path(str(visum.IO.CurrentVersionFile))
    report = {'schema': 'R1C25_FROZEN_DISTANCE_PREP_V2_UNIVERSAL', 'run_token': uuid.uuid4().hex,
              'status': 'STARTED', 'source_version': str(source), 'source_exists': source.is_file(),
              'save_version_called': False, 'source_9697_preserved': True, 'frozen': [], 'warnings': []}
    path = _result_path()
    wrote = False
    try:
        if not report['source_exists'] or source.suffix.lower() != '.ver':
            raise RuntimeError('DISTANCE_OPEN_A_SAVED_VER_FIRST')
        if '2022' in source.name:
            raise RuntimeError('DISTANCE_ONLY_2025_MODEL')
        st = source.stat()
        report.update({'source_bytes': st.st_size, 'source_mtime_epoch': st.st_mtime,
                       'source_sha256': sha_file(source)})
        zones = np.array([_number(v) for _, v in visum.Net.Zones.GetMultiAttValues('NO', False)], dtype='<i8')
        if len(zones) != EXPECTED_ZONES or len(set(zones.tolist())) != len(zones):
            raise RuntimeError('DISTANCE_ZONE_COUNT_OR_ORDER_INVALID:%d' % len(zones))
        n = len(zones)
        report['zone_order_sha256'] = hashlib.sha256(zones.tobytes()).hexdigest()

        inv = _inventory(visum)
        if inv.get(ORIGINAL[0], ('',))[0] != ORIGINAL[1]:
            raise RuntimeError('DISTANCE_ORIGINAL_9697_MISSING_OR_RECODED')
        original = visum.Net.Matrices.ItemByKey(ORIGINAL[0])
        if not matrix_type_is_source(original) or not data_source_is_data(original):
            raise RuntimeError('DISTANCE_ORIGINAL_9697_TYPE_CHANGED:' + type_text(original))
        original_values = values(original, n)
        report['m9697_sha256'] = digest(original_values)
        off = ~np.eye(n, dtype=bool)

        # targets: free, or already ours (re-freeze); never a foreign matrix
        for no, code in TARGET_CODES.items():
            if no in inv and inv[no][0] != code:
                raise RuntimeError('DISTANCE_TARGET_NUMBER_USED_BY_OTHER_MATRIX:%d:%s' % (no, inv[no][0]))
            others = [m for m, (c, _) in inv.items() if c == code and m != no]
            if others:
                raise RuntimeError('DISTANCE_TARGET_CODE_USED_BY_OTHER_NUMBER:%s:%s' % (code, others))
        report['refreeze'] = sorted(no for no in TARGET_CODES if no in inv)

        sources = {}
        for target_no, dseg in SEGMENTS:
            hits = [no for no, (c, d) in inv.items() if c == 'DIS' and d == dseg]
            if len(hits) != 1:
                raise RuntimeError('DISTANCE_SOURCE_DIS_NOT_UNIQUE:%s:%s' % (dseg, hits))
            source_no = hits[0]
            arr = values(visum.Net.Matrices.ItemByKey(source_no), n)
            no_path = int((arr[off] >= NO_PATH_KM).sum())
            if no_path:
                raise RuntimeError('DISTANCE_SOURCE_NO_PATH_CELLS:%s:%d' % (dseg, no_path))
            zero = int((arr[off] <= 0).sum())
            if zero:
                report['warnings'].append('%s: %d off-diagonal cells with DIS = 0 km' % (dseg, zero))
            frozen = arr.copy()
            np.fill_diagonal(frozen, np.diag(original_values))
            sources[target_no] = (source_no, dseg, digest(arr), frozen, digest(frozen))
        derived = {}
        for target_no, ratio_no, ratio_code, eligible_no, restricted_no in BLENDS:
            if inv.get(ratio_no, ('',))[0] != ratio_code:
                raise RuntimeError('DISTANCE_SPLIT_RATIO_IDENTITY:%d:%s' % (ratio_no, ratio_code))
            ratio = values(visum.Net.Matrices.ItemByKey(ratio_no), n)
            arr = blended_distance(sources[eligible_no][3], sources[restricted_no][3], ratio)
            derived[target_no] = (arr, digest(arr), ratio_no, digest(ratio))
        report['status'] = 'PREFLIGHT_PASS'
        _write(path, report)

        wrote = True
        stem = source.stem[:120]
        for target_no, (source_no, dseg, source_hash, frozen, frozen_hash) in sources.items():
            matrix = _target(visum, target_no, inv)
            matrix.SetAttValue('CODE', TARGET_CODES[target_no])
            matrix.SetAttValue('NAME', 'Frozen Visum DIS km %s from %s' % (dseg, stem))
            matrix.SetValues(frozen, False)
            if _number(matrix.AttValue('NO')) != target_no or digest(values(matrix, n)) != frozen_hash:
                raise RuntimeError('DISTANCE_TARGET_READBACK_MISMATCH:' + dseg)
            report['frozen'].append({'matrix_no': target_no, 'code': TARGET_CODES[target_no], 'source_no': source_no,
                                     'dseg': dseg, 'source_values_sha256': source_hash,
                                     'frozen_values_sha256': frozen_hash, 'diagonal_source': 'M9697',
                                     'mean_offdiag_km': float(frozen[off].mean())})
            _write(path, report)
        for target_no, (arr, expected_hash, ratio_no, ratio_hash) in derived.items():
            matrix = _target(visum, target_no, inv)
            matrix.SetAttValue('CODE', TARGET_CODES[target_no])
            matrix.SetAttValue('NAME', 'Frozen blended Visum DIS km from %s' % stem)
            matrix.SetValues(arr, False)
            if _number(matrix.AttValue('NO')) != target_no or digest(values(matrix, n)) != expected_hash:
                raise RuntimeError('DISTANCE_BLEND_READBACK_MISMATCH:%d' % target_no)
            report['frozen'].append({'matrix_no': target_no, 'code': TARGET_CODES[target_no],
                                     'values_sha256': expected_hash, 'split_ratio_matrix_no': ratio_no,
                                     'split_ratio_sha256': ratio_hash, 'diagonal_source': 'M9697',
                                     'mean_offdiag_km': float(arr[off].mean())})
            _write(path, report)
        # nothing the script read may have changed while it ran
        if digest(values(original, n)) != report['m9697_sha256']:
            raise RuntimeError('DISTANCE_FREEZE_9697_CHANGED')
        for source_no, dseg, source_hash, _, _ in sources.values():
            if digest(values(visum.Net.Matrices.ItemByKey(source_no), n)) != source_hash:
                raise RuntimeError('DISTANCE_FREEZE_SOURCE_SKIM_CHANGED:' + dseg)
        for _, _, ratio_no, ratio_hash in derived.values():
            if digest(values(visum.Net.Matrices.ItemByKey(ratio_no), n)) != ratio_hash:
                raise RuntimeError('DISTANCE_FREEZE_SPLIT_RATIO_CHANGED:%d' % ratio_no)
        report['status'] = 'FROZEN_IN_OPEN_MODEL_RUN_RECOMPUTE_BEFORE_SAVE'
        _write(path, report)
        return report
    except BaseException:
        report['status'] = 'MODEL_MAY_BE_CHANGED_CLOSE_WITHOUT_SAVING' if wrote else 'STOPPED_BEFORE_ANY_WRITE'
        report['error'] = traceback.format_exc()[-2000:]
        _write(path, report)
        raise


def _target(visum, no, inv):
    if no in inv:
        matrix = visum.Net.Matrices.ItemByKey(no)
    else:
        matrix = visum.Net.AddMatrix(no, 2, 3)
    if not matrix_type_is_source(matrix) or not data_source_is_data(matrix):
        raise RuntimeError('DISTANCE_TARGET_TYPE_MISMATCH:%d:%s' % (no, type_text(matrix)))
    return matrix


if __name__ == '__main__':
    prepare(Visum)
