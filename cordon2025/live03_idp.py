"""IDP trip-length guard for LIVE03 (TD weight = cordon only; IDP = degradation guard).

The fine 512-node DIST_KM CDF metrics and the soft acceptance thresholds are the
UNMODIFIED donor FineCDF v1.9 reference (parent/reference_v19, SHA-256 pinned):
``Metrics(distance).evaluate(matrices)`` and CONFIG
max_fine_cdf_rmse_degradation / mean_error_floor / max_mean_error_degradation.
The IDP objective itself is NOT minimized here; a candidate is rejected when any
guarded component degrades its fine-CDF RMSE or relative mean error beyond the
donor soft-reference tolerances (v1.9 ``acceptable(strict=False)`` per component).
Matrices are read only (Visum.Net.Matrices.ItemByKey(no).GetValues()).
"""
from __future__ import annotations
import importlib.util
from pathlib import Path
import numpy as np
from .common import PARENT, require
from .io import sha256, write_json

REFERENCE = 'reference_v19/R1_BC_AUTO_DIST_ONLY_FINECDF_SOFT_v1_9.py'
REFERENCE_SHA256 = 'fcdfa535940296e6cc793b6416c7c0a56c18aae8d5d20beddb064a170c673ff5'
REFERENCE_ID = 'R1_BC_AUTO_DIST_ONLY_FINECDF_SOFT_V1_9_20261017'
_CACHE = {}


def reference():
    if 'mod' not in _CACHE:
        path = PARENT / REFERENCE
        require(path.is_file(), 'LIVE03_IDP_REFERENCE_MISSING')
        require(sha256(path) == REFERENCE_SHA256, 'LIVE03_IDP_REFERENCE_HASH_CHANGED')
        spec = importlib.util.spec_from_file_location('r1_bc_finecdf_v19_' + REFERENCE_SHA256[:12], str(path))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        require(getattr(mod, 'SCRIPT_ID', None) == REFERENCE_ID, 'LIVE03_IDP_REFERENCE_ID_MISMATCH')
        _CACHE['mod'] = mod
    return _CACHE['mod']


def _read(visum, no, n):
    m = visum.Net.Matrices.ItemByKey(int(no))
    arr = np.asarray(m.GetValues(), dtype=float)
    require(arr.shape == (n, n) and np.all(np.isfinite(arr)) and np.all(arr >= 0), 'LIVE03_IDP_MATRIX_INVALID:%s' % no)
    return arr


class IdpGuard:
    def __init__(self, visum, n_zones, cfg):
        self.ref = reference()
        self.cfg = dict(cfg)
        self.visum = visum
        self.n = int(n_zones)
        self.distance_no = int(self.ref.CONFIG['distance_matrix'])
        distance = _read(visum, self.distance_no, self.n)
        self.metrics = self.ref.Metrics(distance)
        self.keys = list(self.ref.TARGETS)
        guarded = self.cfg.get('components') or self.keys
        require(set(guarded) <= set(self.keys), 'LIVE03_IDP_UNKNOWN_COMPONENT')
        self.guarded = list(guarded)
        self.matrix_nos = sorted({int(no) for k in self.keys for no in self.ref.TARGETS[k]['matrix_nos']})
        conf = self.ref.CONFIG
        self.rmse_tol = float(self.cfg.get('max_fine_cdf_rmse_degradation', conf['max_fine_cdf_rmse_degradation']))
        self.mean_floor = float(self.cfg.get('mean_error_floor', conf['mean_error_floor']))
        self.mean_tol = float(self.cfg.get('max_mean_error_degradation', conf['max_mean_error_degradation']))

    def evaluate(self, label='CURRENT'):
        mats = {no: _read(self.visum, no, self.n) for no in self.matrix_nos}
        out = self.metrics.evaluate(mats)
        return {k: {f: float(v[f]) for f in ('objective', 'fine_cdf_rmse', 'fine_cdf_ks', 'mean_model_km',
                                                 'mean_target_km', 'mean_relative_error')} for k, v in out.items()}

    def decide(self, before, after):
        reasons = []
        rows = []
        for k in self.guarded:
            b, a = before[k], after[k]
            allowed_mean = max(abs(b['mean_relative_error']), self.mean_floor) + self.mean_tol
            ok_rmse = a['fine_cdf_rmse'] <= b['fine_cdf_rmse'] + self.rmse_tol
            ok_mean = abs(a['mean_relative_error']) <= allowed_mean
            rows.append({'component': k, 'rmse_before': b['fine_cdf_rmse'], 'rmse_after': a['fine_cdf_rmse'],
                         'mean_rel_before': b['mean_relative_error'], 'mean_rel_after': a['mean_relative_error'],
                         'mean_rel_allowed_abs': allowed_mean, 'passes': ok_rmse and ok_mean})
            if not ok_rmse:
                reasons.append('IDP_FINE_CDF_RMSE_DEGRADED:' + k)
            if not ok_mean:
                reasons.append('IDP_MEAN_DISTANCE_DEGRADED:' + k)
        return {'schema': 'LIVE03_IDP_GUARD_V1', 'passes': not reasons, 'reasons': reasons, 'components': rows,
                'reference_sha256': REFERENCE_SHA256, 'role': 'DEGRADATION_GUARD_ONLY_NOT_OBJECTIVE',
                'tolerances': {'max_fine_cdf_rmse_degradation': self.rmse_tol, 'mean_error_floor': self.mean_floor,
                               'max_mean_error_degradation': self.mean_tol}}

    def write(self, folder, name, payload):
        write_json(Path(folder) / name, payload)
