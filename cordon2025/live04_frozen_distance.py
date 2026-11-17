"""Preflight for the eight fixed route-distance matrices of a LIVE04 run."""
from __future__ import annotations
import hashlib
import numpy as np
from .common import require

SOURCES = ('NATIVE_CF', 'NATIVE_CL', 'NATIVE_CS', 'NATIVE_CS_NOT', 'NATIVE_CW', 'NATIVE_CW_NOT')
EXPECTED = {9720 + i: 'R1_BASE_DIS_' + code + '_KM' for i, code in enumerate(SOURCES)}
EXPECTED.update({9726: 'R1_BASE_DIS_WORK_KM', 9727: 'R1_BASE_DIS_SERV_KM'})


def verify(visum, n):
    original = np.asarray(visum.Net.Matrices.ItemByKey(9697).GetValues(), dtype='<f8')
    require(original.shape == (n, n) and np.isfinite(original).all(), 'LIVE04_FROZEN_DISTANCE_ORIGINAL_INVALID')
    diagonal = np.diag(original)
    hashes = {}
    for no, code in EXPECTED.items():
        matrix = visum.Net.Matrices.ItemByKey(no)
        require(int(matrix.AttValue('NO')) == no and str(matrix.AttValue('CODE')).strip().upper() == code,
                'LIVE04_FROZEN_DISTANCE_IDENTITY:%d' % no)
        values = np.ascontiguousarray(matrix.GetValues(), dtype='<f8')
        require(values.shape == (n, n) and np.isfinite(values).all() and (values >= 0).all(),
                'LIVE04_FROZEN_DISTANCE_VALUES:%d' % no)
        require(np.allclose(np.diag(values), diagonal, rtol=0, atol=1e-9),
                'LIVE04_FROZEN_DISTANCE_DIAGONAL:%d' % no)
        hashes[str(no)] = hashlib.sha256(values.tobytes()).hexdigest()
    return {'status': 'VERIFIED', 'matrix_hashes': hashes,
            'distance_matrices': list(EXPECTED), 'diagonal_source': 9697}
