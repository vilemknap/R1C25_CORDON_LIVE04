"""Preflight for the eight fixed route-distance matrices of a LIVE04 run."""
from __future__ import annotations
import hashlib
import numpy as np
from .common import require

SOURCES = ('NATIVE_CF', 'NATIVE_CL', 'NATIVE_CS', 'NATIVE_CS_NOT', 'NATIVE_CW', 'NATIVE_CW_NOT')
EXPECTED = {9720 + i: 'R1_BASE_DIS_' + code + '_KM' for i, code in enumerate(SOURCES)}
EXPECTED.update({9726: 'R1_BASE_DIS_WORK_KM', 9727: 'R1_BASE_DIS_SERV_KM'})
ZONE_ORDER_SHA256 = '665c38f37b106f106539501fce9bc17e8635400aeaf7cef9929f799c438afe34'
OSRM_VALUES_SHA256 = 'e0eb31eecc2d2d67da617e3ccd2cf66daeeb82bb4d56da1c933b5e7f70663cf2'
# DIS values from the saved C02_GENERATION_348fa1d3 checkpoint, with the approved
# intrazonal 9697 diagonal inserted. These are independent of later assignments.
RAW_VALUES_SHA256 = {
    9720: '01a0f926db820b1fc7ce9e5af1f42655ada3cfe22a39341603ea948f8358f888',
    9721: '74beea5ebb1304e716c52e732a1d350ccf5c32ab216a59271be9e989f6fd927a',
    9722: '76b5fe3e1bf7c5cd779360f3e4a86ba781904bb77c52222f93ac32a86dbb3148',
    9723: 'df58f1fa72a18a8f949befceb2569e608ea56d4371431e48467340d175419c5c',
    9724: 'b26c9c900b043b5dc2a0a4cbc46e9a6bf187585e84b06039ffece8c3a748d16c',
    9725: '88bb01989eb8bf84379459afea953c7d9944d5c75001d60f7a4266a52709fc7b',
}


def _hash(values):
    return hashlib.sha256(np.ascontiguousarray(values, dtype='<f8').tobytes()).hexdigest()


def _data_source(matrix):
    return ''.join(c for c in str(matrix.AttValue('DATASOURCETYPE')).upper() if c.isalnum())


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


def verify(visum, n):
    fixture = str(getattr(visum, 'origin', '')) == 'MOCK_LIVE04_681_ZONES_NOT_NATIVE'
    zones = np.asarray([int(no) for _, no in visum.Net.Zones.GetMultiAttValues('NO', False)], dtype='<i8')
    require(len(zones) == n and len(set(zones)) == n,
            'LIVE04_FROZEN_DISTANCE_ZONE_ORDER_INVALID')
    zone_hash = hashlib.sha256(zones.tobytes()).hexdigest()
    if not fixture:
        require(zone_hash == ZONE_ORDER_SHA256, 'LIVE04_FROZEN_DISTANCE_ZONE_ORDER_CHANGED')
    original_matrix = visum.Net.Matrices.ItemByKey(9697)
    require(str(original_matrix.AttValue('CODE')).strip().upper() == 'R1_OSRM_DIST_KM',
            'LIVE04_FROZEN_DISTANCE_ORIGINAL_IDENTITY')
    require(_zone_od_type(original_matrix) and _data_source(original_matrix)
            in ('1', 'DATA', 'DATASOURCETYPEDATA'), 'LIVE04_FROZEN_DISTANCE_ORIGINAL_TYPE')
    original = np.asarray(original_matrix.GetValues(), dtype='<f8')
    require(original.shape == (n, n) and np.isfinite(original).all() and (original >= 0).all(),
            'LIVE04_FROZEN_DISTANCE_ORIGINAL_INVALID')
    if not fixture:
        require(_hash(original) == OSRM_VALUES_SHA256, 'LIVE04_FROZEN_DISTANCE_ORIGINAL_CHANGED')
    diagonal = np.diag(original)
    hashes = {}
    frozen = {}
    for no, code in EXPECTED.items():
        matrix = visum.Net.Matrices.ItemByKey(no)
        require(int(matrix.AttValue('NO')) == no and str(matrix.AttValue('CODE')).strip().upper() == code,
                'LIVE04_FROZEN_DISTANCE_IDENTITY:%d' % no)
        require(_zone_od_type(matrix) and _data_source(matrix) in ('1', 'DATA', 'DATASOURCETYPEDATA'),
                'LIVE04_FROZEN_DISTANCE_NOT_DATA:%d' % no)
        values = np.ascontiguousarray(matrix.GetValues(), dtype='<f8')
        require(values.shape == (n, n) and np.isfinite(values).all() and (values >= 0).all(),
                'LIVE04_FROZEN_DISTANCE_VALUES:%d' % no)
        require(np.allclose(np.diag(values), diagonal, rtol=0, atol=1e-9),
                'LIVE04_FROZEN_DISTANCE_DIAGONAL:%d' % no)
        hashes[str(no)] = _hash(values)
        if not fixture and no in RAW_VALUES_SHA256:
            require(hashes[str(no)] == RAW_VALUES_SHA256[no],
                    'LIVE04_FROZEN_DISTANCE_RAW_HASH:%d' % no)
        frozen[no] = values
    for no, ratio_no, ratio_code, eligible, restricted in (
            (9726, 9231, 'RATIO_CW', 9724, 9725),
            (9727, 9233, 'RATIO_CS', 9722, 9723)):
        ratio_matrix = visum.Net.Matrices.ItemByKey(ratio_no)
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
            'source_hashes_pinned': not fixture}


def assert_unchanged(visum, n, baseline):
    current = verify(visum, n)
    require(current['matrix_hashes'] == baseline['matrix_hashes']
            and current['zone_order_sha256'] == baseline['zone_order_sha256']
            and current['osrm_values_sha256'] == baseline['osrm_values_sha256'],
            'LIVE04_FROZEN_DISTANCE_CHANGED_DURING_RUN')
    return current
