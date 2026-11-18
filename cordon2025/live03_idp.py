"""FineCDF trip-length metrics for the TD objective and IDP degradation guard.

The fine 512-node DIST_KM CDF metrics and the soft acceptance thresholds are the
UNMODIFIED donor FineCDF v1.9 reference (parent/reference_v19, SHA-256 pinned):
``Metrics(distance).evaluate(matrices)`` and CONFIG
max_fine_cdf_rmse_degradation / mean_error_floor / max_mean_error_degradation.
The TD block can blend these metrics into its search objective. Its acceptance
guard rejects a candidate when any guarded component degrades its fine-CDF
RMSE or relative mean error beyond the
donor soft-reference tolerances (v1.9 ``acceptable(strict=False)`` per component).
Matrices are read only (Visum.Net.Matrices.ItemByKey(no).GetValues()).
"""
from __future__ import annotations
import hashlib
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


def _evaluate_component(metric, matrices, key, ref):
    """Evaluate one frozen-distance component with the pinned FineCDF v1.9 algebra.

    The reference ``Metrics.evaluate`` iterates over every target. Calling it
    for each distance would also evaluate unrelated components on that distance
    and can fail on their empty conditioning intervals.
    """
    target = ref.TARGETS[key]
    (idx, distance, bins, count, fine_bins, _), fine_x, goal = metric.cache[key]
    weights = np.zeros(len(idx), dtype=float)
    for no in target['matrix_nos']:
        weights += matrices[no].ravel()[idx]
    mass = float(weights.sum())
    require(mass > 0, 'LIVE03_IDP_NO_CONDITIONED_DEMAND:' + key)
    hist = np.bincount(bins, weights=weights, minlength=count)
    shares = hist / mass
    mean_exact = float(np.dot(weights, distance) / mass)
    if target['mean_basis'].startswith('BIN_MIDPOINT'):
        centres = (np.asarray(target['edges'][:-1]) + np.asarray(target['edges'][1:])) / 2
        mean = float(np.dot(shares, centres))
    else:
        mean = mean_exact
    rel = (mean - target['mean_km']) / target['mean_km']
    model_cdf = np.cumsum(np.bincount(fine_bins, weights=weights, minlength=len(fine_x))) / mass
    cdf_diff = model_cdf - goal
    require(abs(model_cdf[-1] - 1.0) < 1e-8, 'LIVE03_IDP_CDF_NOT_NORMALIZED:' + key)
    residual = np.r_[cdf_diff / np.sqrt(len(fine_x)),
                     np.sqrt(ref.CONFIG['shape_mean_weight']) * rel]
    return {'objective': float(residual @ residual),
            'fine_cdf_rmse': float(np.sqrt(np.mean(cdf_diff ** 2))),
            'fine_cdf_ks': float(np.max(np.abs(cdf_diff))),
            'mean_model_km': mean, 'mean_target_km': float(target['mean_km']),
            'mean_relative_error': float(rel)}


class IdpGuard:
    def __init__(self, visum, n_zones, cfg):
        self.ref = reference()
        self.cfg = dict(cfg)
        self.visum = visum
        self.n = int(n_zones)
        self.distance_no = int(self.ref.CONFIG['distance_matrix'])
        self.keys = list(self.ref.TARGETS)
        selected = self.cfg.get('distance_matrix_by_component')
        if selected is None:
            self.distance_by_component = {k: self.distance_no for k in self.keys}
        else:
            require(isinstance(selected, dict) and set(selected) == set(self.keys),
                    'LIVE03_IDP_DISTANCE_COMPONENT_SCOPE')
            self.distance_by_component = {k: int(selected[k]) for k in self.keys}
        distances = {no: _read(visum, no, self.n)
                     for no in sorted(set(self.distance_by_component.values()))}
        self.fixed_distance_hashes = ({no: hashlib.sha256(np.ascontiguousarray(arr, dtype='<f8').tobytes()).hexdigest()
                                       for no, arr in distances.items()} if selected is not None else {})
        self.metrics_by_no = {no: self.ref.Metrics(arr) for no, arr in distances.items()}
        self.metrics = self.metrics_by_no[self.distance_no] if self.distance_no in self.metrics_by_no else None
        guarded = self.cfg.get('components') or self.keys
        require(set(guarded) <= set(self.keys), 'LIVE03_IDP_UNKNOWN_COMPONENT')
        self.guarded = list(guarded)
        self.matrix_nos = sorted({int(no) for k in self.keys for no in self.ref.TARGETS[k]['matrix_nos']})
        conf = self.ref.CONFIG
        self.rmse_tol = float(self.cfg.get('max_fine_cdf_rmse_degradation', conf['max_fine_cdf_rmse_degradation']))
        self.mean_floor = float(self.cfg.get('mean_error_floor', conf['mean_error_floor']))
        self.mean_tol = float(self.cfg.get('max_mean_error_degradation', conf['max_mean_error_degradation']))

    def evaluate(self, label='CURRENT'):
        for no, expected in self.fixed_distance_hashes.items():
            current = _read(self.visum, no, self.n)
            actual = hashlib.sha256(np.ascontiguousarray(current, dtype='<f8').tobytes()).hexdigest()
            require(actual == expected, 'LIVE03_IDP_FROZEN_DISTANCE_CHANGED:%d' % no)
        mats = {no: _read(self.visum, no, self.n) for no in self.matrix_nos}
        return {k: _evaluate_component(self.metrics_by_no[self.distance_by_component[k]], mats, k, self.ref)
                for k in self.keys}

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
