"""Freeze six verified Visum DIS skims into DATA matrices for the next LIVE04 baseline.

Open the C02 GENERATION checkpoint whose SHA-256 is pinned below. Run this script
once, then run RUN_R1_2025_RECOMPUTE_FOR_LIVE04_BASE.py in the same Visum instance.
The latter reapplies the LONG mask against frozen NATIVE_CL distance and saves a
new version. This script never saves or overwrites a .ver. On any error after a
write, close the changed model without saving and reopen the source checkpoint.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import traceback
import numpy as np

SOURCE_SHA256 = 'cddacecbd4ab507469bacad6808d9561b540d6f13f4eef604046a510e11fa034'
ZONE_SHA256 = '665c38f37b106f106539501fce9bc17e8635400aeaf7cef9929f799c438afe34'
OSRM_SHA256 = 'e0eb31eecc2d2d67da617e3ccd2cf66daeeb82bb4d56da1c933b5e7f70663cf2'
FROZEN = (
    (9720, 9844, 'NATIVE_CF', '3ae4374bc3d17213d4df3b17ca71ad73419f080698229e13851c2fa2d98022c1'),
    (9721, 9852, 'NATIVE_CL', '31c43ebe4b2d792d21dc6ed14e84a1206452b162ee4cee79b78633605447774f'),
    (9722, 9860, 'NATIVE_CS', '7f5d8dae782d660ff60771ab66e81e49579aeb41cdd964ebf4731bbbdc4d96c3'),
    (9723, 9868, 'NATIVE_CS_NOT', 'c4d6499d2c785cd797e90db33f6b1e424ebcc15bf8ff89069df8346e43f7d0c1'),
    (9724, 9876, 'NATIVE_CW', '26f0e900a19d5a4d68733a7abcebb1e70522b7d74dfed6189b3ee66f875d6617'),
    (9725, 9884, 'NATIVE_CW_NOT', '712633988dbba360651588afae0c34466f126b36e6b159c598fc59b54332c9b9'),
)


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
            and enum_is(matrix.AttValue('MATRIXTYPE'), 3, {'MATRIXTYPEOD', 'MATRIXTYPEODMATRIX', 'ODMATRIX'}))


def data_source_is_data(matrix):
    return enum_is(matrix.AttValue('DATASOURCETYPE'), 1, {'DATA', 'DATASOURCETYPEDATA'})


def blended_distance(eligible, restricted, ratio):
    if not np.isfinite(ratio).all() or np.any((ratio < 0) | (ratio > 1)):
        raise RuntimeError('DISTANCE_SPLIT_RATIO_OUT_OF_RANGE')
    return np.ascontiguousarray(ratio * eligible + (1.0 - ratio) * restricted, dtype='<f8')


def prepare(visum):
    source = Path(str(visum.IO.CurrentVersionFile))
    if not source.is_file() or sha_file(source) != SOURCE_SHA256:
        raise RuntimeError('DISTANCE_SOURCE_CHECKPOINT_SHA_MISMATCH')
    zones = np.array([int(v) for _, v in visum.Net.Zones.GetMultiAttValues('NO', False)], dtype='<i8')
    if len(zones) != 681 or hashlib.sha256(zones.tobytes()).hexdigest() != ZONE_SHA256:
        raise RuntimeError('DISTANCE_SOURCE_ZONE_ORDER_MISMATCH')
    original = visum.Net.Matrices.ItemByKey(9697)
    original_values = values(original, 681)
    if str(original.AttValue('CODE')).strip().upper() != 'R1_OSRM_DIST_KM' or digest(original_values) != OSRM_SHA256:
        raise RuntimeError('DISTANCE_ORIGINAL_9697_CHANGED')
    if not matrix_type_is_source(original) or not data_source_is_data(original):
        raise RuntimeError('DISTANCE_ORIGINAL_9697_TYPE_CHANGED')
    sources = {}
    for target_no, source_no, dseg, expected in FROZEN:
        matrix = visum.Net.Matrices.ItemByKey(source_no)
        if str(matrix.AttValue('CODE')).strip().upper() != 'DIS' or str(matrix.AttValue('DSEGCODE')).strip().upper() != dseg:
            raise RuntimeError('DISTANCE_SOURCE_IDENTITY:' + dseg)
        arr = values(matrix, 681)
        if digest(arr) != expected:
            raise RuntimeError('DISTANCE_SOURCE_SKIM_HASH_CHANGED:' + dseg)
        frozen = arr.copy()
        np.fill_diagonal(frozen, np.diag(original_values))
        sources[target_no] = (frozen, digest(frozen))
    derived = {}
    for target_no, ratio_no, ratio_code, eligible_no, restricted_no in (
            (9726, 9231, 'RATIO_CW', 9724, 9725),
            (9727, 9233, 'RATIO_CS', 9722, 9723)):
        ratio_matrix = visum.Net.Matrices.ItemByKey(ratio_no)
        if str(ratio_matrix.AttValue('CODE')).strip().upper() != ratio_code:
            raise RuntimeError('DISTANCE_SPLIT_RATIO_IDENTITY:' + ratio_code)
        ratio = values(ratio_matrix, 681)
        arr = blended_distance(sources[eligible_no][0], sources[restricted_no][0], ratio)
        derived[target_no] = (arr, digest(arr), ratio_no, digest(ratio))
    number_rows = visum.Net.Matrices.GetMultiAttValues('NO')
    code_rows = visum.Net.Matrices.GetMultiAttValues('CODE')
    if [i for i, _ in number_rows] != [i for i, _ in code_rows]:
        raise RuntimeError('DISTANCE_MATRIX_INVENTORY_ORDER_CHANGED')
    used = {int(float(no)) for _, no in number_rows}
    if any(no in used for no in range(9720, 9728)):
        raise RuntimeError('DISTANCE_TARGET_NUMBER_ALREADY_USED')
    target_codes = {'R1_BASE_DIS_' + dseg + '_KM' for _, _, dseg, _ in FROZEN}
    target_codes.update(('R1_BASE_DIS_WORK_KM', 'R1_BASE_DIS_SERV_KM'))
    if any(str(code).strip().upper() in target_codes for _, code in code_rows):
        raise RuntimeError('DISTANCE_TARGET_CODE_ALREADY_USED')
    report = {'status': 'PREFLIGHT_PASS', 'source_version': str(source), 'source_sha256': SOURCE_SHA256,
              'frozen': [], 'source_9697_preserved': True, 'save_version_called': False}
    out = Path(os.environ.get('LOCALAPPDATA') or Path.home()) / 'R1C25_DISTANCE_PREP'
    out.mkdir(parents=True, exist_ok=True)
    path = out / 'FROZEN_DISTANCE_RESULT.json'
    path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    try:
        for target_no, source_no, dseg, expected in FROZEN:
            matrix = visum.Net.AddMatrix(target_no, 2, 3)
            if not matrix_type_is_source(matrix) or not data_source_is_data(matrix):
                raise RuntimeError('DISTANCE_TARGET_TYPE_MISMATCH:' + dseg)
            matrix.SetAttValue('CODE', 'R1_BASE_DIS_' + dseg + '_KM')
            matrix.SetAttValue('NAME', 'Frozen baseline Visum DIS km ' + dseg)
            frozen, frozen_hash = sources[target_no]
            matrix.SetValues(frozen, False)
            if int(matrix.AttValue('NO')) != target_no or digest(values(matrix, 681)) != frozen_hash:
                raise RuntimeError('DISTANCE_TARGET_READBACK_MISMATCH:' + dseg)
            report['frozen'].append({'matrix_no': target_no, 'source_no': source_no,
                                     'dseg': dseg, 'source_values_sha256': expected,
                                     'frozen_values_sha256': frozen_hash,
                                     'diagonal_source': 'M9697_R1_OSRM_DIST_KM'})
            path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        for target_no, (arr, expected_hash, ratio_no, ratio_hash) in derived.items():
            matrix = visum.Net.AddMatrix(target_no, 2, 3)
            if not matrix_type_is_source(matrix) or not data_source_is_data(matrix):
                raise RuntimeError('DISTANCE_BLEND_TYPE_MISMATCH:' + str(target_no))
            matrix.SetAttValue('CODE', 'R1_BASE_DIS_WORK_KM' if target_no == 9726 else 'R1_BASE_DIS_SERV_KM')
            matrix.SetAttValue('NAME', 'Frozen baseline blended Visum DIS km')
            matrix.SetValues(arr, False)
            if int(matrix.AttValue('NO')) != target_no or digest(values(matrix, 681)) != expected_hash:
                raise RuntimeError('DISTANCE_BLEND_READBACK_MISMATCH:' + str(target_no))
            report['frozen'].append({'matrix_no': target_no, 'values_sha256': expected_hash,
                                     'split_ratio_matrix_no': ratio_no, 'split_ratio_sha256': ratio_hash,
                                     'diagonal_source': 'M9697_R1_OSRM_DIST_KM'})
            path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        if digest(values(original, 681)) != OSRM_SHA256 or sha_file(source) != SOURCE_SHA256:
            raise RuntimeError('DISTANCE_FREEZE_SOURCE_CHANGED')
        for _, source_no, dseg, expected in FROZEN:
            if digest(values(visum.Net.Matrices.ItemByKey(source_no), 681)) != expected:
                raise RuntimeError('DISTANCE_FREEZE_SOURCE_SKIM_CHANGED:' + dseg)
        for _, (_, _, ratio_no, ratio_hash) in derived.items():
            if digest(values(visum.Net.Matrices.ItemByKey(ratio_no), 681)) != ratio_hash:
                raise RuntimeError('DISTANCE_FREEZE_SPLIT_RATIO_CHANGED:' + str(ratio_no))
        report['status'] = 'FROZEN_IN_OPEN_MODEL_RUN_RECOMPUTE_BEFORE_SAVE'
        path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        return report
    except BaseException:
        report['status'] = 'MODEL_MAY_BE_CHANGED_CLOSE_WITHOUT_SAVING'
        report['error'] = traceback.format_exc()[-2000:]
        path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        raise


if __name__ == '__main__':
    prepare(Visum)
