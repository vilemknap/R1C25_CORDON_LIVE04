"""Preflight for the eight fixed route-distance matrices of a LIVE04 run."""
from __future__ import annotations
import hashlib
import numpy as np
from .common import require, ContractError

SOURCES = ('NATIVE_CF', 'NATIVE_CL', 'NATIVE_CS', 'NATIVE_CS_NOT', 'NATIVE_CW', 'NATIVE_CW_NOT')
EXPECTED = {9720 + i: 'R1_BASE_DIS_' + code + '_KM' for i, code in enumerate(SOURCES)}
EXPECTED.update({9726: 'R1_BASE_DIS_WORK_KM', 9727: 'R1_BASE_DIS_SERV_KM'})
# Universal since 2026-11-18: no checkpoint-specific value pins. The run-start hashes of
# all eight matrices (and 9697 / zone order) are the authority for the whole run.


def _hash(values):
    return hashlib.sha256(np.ascontiguousarray(values, dtype='<f8').tobytes()).hexdigest()


def _is_data(matrix):
    # Visum COM returns enum attributes as numbers (1.0), a fixture may return 'DATA'.
    return _enum_is(matrix.AttValue('DATASOURCETYPE'), 1,
                    {'DATA', 'DATASOURCETYPEDATA', 'MATRIXDATASOURCETYPEDATA'})


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
                         {'MATRIXTYPEOD', 'MATRIXTYPEODMATRIX', 'ODMATRIX'}))


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
    require(_zone_od_type(original_matrix) and _is_data(original_matrix),
            'LIVE04_FROZEN_DISTANCE_ORIGINAL_TYPE')
    original = np.asarray(original_matrix.GetValues(), dtype='<f8')
    require(original.shape == (n, n) and np.isfinite(original).all() and (original >= 0).all(),
            'LIVE04_FROZEN_DISTANCE_ORIGINAL_INVALID')
    diagonal = np.diag(original)
    hashes = {}
    frozen = {}
    for no, code in EXPECTED.items():
        matrix = _matrix(visum, no)
        require(int(matrix.AttValue('NO')) == no and str(matrix.AttValue('CODE')).strip().upper() == code,
                'LIVE04_FROZEN_DISTANCE_IDENTITY:%d' % no)
        require(_zone_od_type(matrix) and _is_data(matrix),
                'LIVE04_FROZEN_DISTANCE_NOT_DATA:%d' % no)
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
