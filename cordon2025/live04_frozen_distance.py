"""Preflight for the eight fixed route-distance matrices of a LIVE04 run."""
from __future__ import annotations
import hashlib
import re
import numpy as np
from .common import require, ContractError

SOURCES = ('NATIVE_CF', 'NATIVE_CL', 'NATIVE_CS', 'NATIVE_CS_NOT', 'NATIVE_CW', 'NATIVE_CW_NOT')
EXPECTED = {9720 + i: 'R1_BASE_DIS_' + code + '_KM' for i, code in enumerate(SOURCES)}
EXPECTED.update({9726: 'R1_BASE_DIS_WORK_KM', 9727: 'R1_BASE_DIS_SERV_KM'})
# Universal since 2026-11-18: no checkpoint-specific value pins. The run-start hashes of
# all eight matrices (and 9697 / zone order) are the authority for the whole run.


def _hash(values):
    return hashlib.sha256(np.ascontiguousarray(values, dtype='<f8').tobytes()).hexdigest()


def _enum_is(value, expected, aliases):
    token = ''.join(c for c in str(value).upper() if c.isalnum())
    if token in aliases:
        return True
    try:
        return not isinstance(value, bool) and float(value) == expected
    except (TypeError, ValueError, OverflowError):
        return False


def _zone_od_type(matrix):
    return (_enum_is(matrix.AttValue('OBJECTTYPEREF'), 2, {'OBJECTTYPEREFZONE', 'ZONE', 'ZONES'})
            and _enum_is(matrix.AttValue('MATRIXTYPE'), 3,
                         {'MATRIXTYPEDEMAND', 'DEMAND', 'MATRIXTYPEOD', 'MATRIXTYPEODMATRIX', 'ODMATRIX'}))


def _data_source_is_data(matrix):
    return _enum_is(matrix.AttValue('DATASOURCETYPE'), 1,
                    {'DATA', 'DATASOURCETYPEDATA'})


def _number(value):
    try:
        return int(round(float(value)))
    except (TypeError, ValueError, OverflowError):
        return None


def _is_skim(matrix):
    return _enum_is(matrix.AttValue('MATRIXTYPE'), 4, {'MATRIXTYPESKIM', 'SKIM'})


def skim_dependencies(visum, matrix, depth=0, seen=None):
    """Matrix numbers of skims a (formula) matrix depends on, recursively.

    The split ratios 9231/9233 are formula matrices rewritten by procedure step
    R1 20D on every run. With DT_MODE='FROZEN' they read the DATA matrices
    9235/9236; with 'LIVE' they read the tCur skims of the running assignment and
    would drift during calibration, so the frozen blends 9726/9727 would no longer
    match. Detected at run start instead of after the first block.
    """
    seen = set() if seen is None else seen
    if _is_skim(matrix):
        return [_number(matrix.AttValue('NO'))]
    if _data_source_is_data(matrix) or depth > 6:
        return []
    out = []
    for ref in re.findall(r'Matrix\(\s*(?:\[NO\]\s*=\s*)?(\d+)\s*\)', str(matrix.AttValue('FORMULA')), re.I):
        no = int(ref)
        if no in seen:
            continue
        seen.add(no)
        out += skim_dependencies(visum, _matrix(visum, no), depth + 1, seen)
    return out


def _type_text(matrix):
    out = []
    for key in ('MATRIXTYPE', 'OBJECTTYPEREF', 'DATASOURCETYPE'):
        try:
            out.append('%s=%r' % (key, matrix.AttValue(key)))
        except Exception as exc:
            out.append('%s=<%s>' % (key, type(exc).__name__))
    return ','.join(out)


def _matrix(visum, no):
    try:
        matrix = visum.Net.Matrices.ItemByKey(no)
    except Exception as exc:
        raise ContractError('LIVE04_FROZEN_DISTANCE_MISSING:%d (run RUN_R1_2025_FREEZE_VISUM_DISTANCES.py '
                            'and RUN_R1_2025_RECOMPUTE_FOR_LIVE04_BASE.py first): %s' % (no, str(exc)[:200]))
    require(matrix is not None, 'LIVE04_FROZEN_DISTANCE_MISSING:%d' % no)
    return matrix


def verify(visum, n):
    zones = np.asarray([int(round(float(no))) for _, no in visum.Net.Zones.GetMultiAttValues('NO', False)], dtype='<i8')
    require(len(zones) == n and len(set(zones)) == n,
            'LIVE04_FROZEN_DISTANCE_ZONE_ORDER_INVALID')
    zone_hash = hashlib.sha256(zones.tobytes()).hexdigest()
    original_matrix = _matrix(visum, 9697)
    require(str(original_matrix.AttValue('CODE')).strip().upper() == 'R1_OSRM_DIST_KM',
            'LIVE04_FROZEN_DISTANCE_ORIGINAL_IDENTITY')
    require(_zone_od_type(original_matrix) and _data_source_is_data(original_matrix),
            'LIVE04_FROZEN_DISTANCE_ORIGINAL_TYPE:' + _type_text(original_matrix))
    original = np.asarray(original_matrix.GetValues(), dtype='<f8')
    require(original.shape == (n, n) and np.isfinite(original).all() and (original >= 0).all(),
            'LIVE04_FROZEN_DISTANCE_ORIGINAL_INVALID')
    diagonal = np.diag(original)
    hashes = {}
    frozen = {}
    for no, code in EXPECTED.items():
        matrix = _matrix(visum, no)
        require(_number(matrix.AttValue('NO')) == no and str(matrix.AttValue('CODE')).strip().upper() == code,
                'LIVE04_FROZEN_DISTANCE_IDENTITY:%d' % no)
        require(_zone_od_type(matrix) and _data_source_is_data(matrix),
                'LIVE04_FROZEN_DISTANCE_NOT_DATA:%d:%s' % (no, _type_text(matrix)))
        values = np.ascontiguousarray(matrix.GetValues(), dtype='<f8')
        require(values.shape == (n, n) and np.isfinite(values).all() and (values >= 0).all(),
                'LIVE04_FROZEN_DISTANCE_VALUES:%d' % no)
        require(np.allclose(np.diag(values), diagonal, rtol=0, atol=1e-9),
                'LIVE04_FROZEN_DISTANCE_DIAGONAL:%d' % no)
        hashes[str(no)] = _hash(values)
        frozen[no] = values
    for no, ratio_no, ratio_code, eligible, restricted in (
            (9726, 9231, 'RATIO_CW', 9724, 9725),
            (9727, 9233, 'RATIO_CS', 9722, 9723)):
        ratio_matrix = _matrix(visum, ratio_no)
        require(str(ratio_matrix.AttValue('CODE')).strip().upper() == ratio_code,
                'LIVE04_FROZEN_DISTANCE_RATIO_IDENTITY:%d' % ratio_no)
        skims = skim_dependencies(visum, ratio_matrix)
        require(not skims, 'LIVE04_FROZEN_DISTANCE_RATIO_FOLLOWS_SKIMS:%d:%s (set DT_MODE=FROZEN in step R1 20D)'
                % (ratio_no, sorted(set(skims))))
        ratio = np.asarray(ratio_matrix.GetValues(), dtype='<f8')
        require(ratio.shape == (n, n) and np.isfinite(ratio).all()
                and (ratio >= 0).all() and (ratio <= 1).all(),
                'LIVE04_FROZEN_DISTANCE_RATIO_VALUES:%d' % ratio_no)
        expected = ratio * frozen[eligible] + (1.0 - ratio) * frozen[restricted]
        require(np.allclose(frozen[no], expected, rtol=0, atol=1e-9),
                'LIVE04_FROZEN_DISTANCE_BLEND:%d' % no)
    return {'status': 'VERIFIED', 'matrix_hashes': hashes,
            'distance_matrices': list(EXPECTED), 'diagonal_source': 9697,
            'zone_order_sha256': zone_hash, 'osrm_values_sha256': _hash(original),
            'authority': 'RUN_START_HASHES_NO_CHECKPOINT_PIN'}


def assert_unchanged(visum, n, baseline):
    current = verify(visum, n)
    require(current['matrix_hashes'] == baseline['matrix_hashes']
            and current['zone_order_sha256'] == baseline['zone_order_sha256']
            and current['osrm_values_sha256'] == baseline['osrm_values_sha256'],
            'LIVE04_FROZEN_DISTANCE_CHANGED_DURING_RUN')
    return current
