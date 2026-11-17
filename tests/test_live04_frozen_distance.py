"""Offline checks for frozen skim distances; no native Visum claim."""
from types import SimpleNamespace
import numpy as np
import pytest

from cordon2025.common import ContractError
from cordon2025.live04_config import FROZEN_IDP_DISTANCE_MAP, load_config
from cordon2025.live04_frozen_distance import EXPECTED, verify
from cordon2025.live03_idp import IdpGuard
from RUN_R1_2025_FREEZE_VISUM_DISTANCES import blended_distance


class Matrix:
    def __init__(self, no, code, values):
        self.no, self.code, self.values = no, code, values

    def AttValue(self, key):
        return {'NO': self.no, 'CODE': self.code}[key.upper()]

    def GetValues(self):
        return self.values


def _visum():
    original = np.array([[2., 30.], [40., 3.]])
    matrices = {9697: Matrix(9697, 'R1_OSRM_DIST_KM', original)}
    matrices.update({no: Matrix(no, code, original.copy()) for no, code in EXPECTED.items()})
    return SimpleNamespace(Net=SimpleNamespace(Matrices=SimpleNamespace(ItemByKey=matrices.__getitem__))), matrices


def test_frozen_distance_preflight_checks_identity_and_intrazonal_values():
    visum, matrices = _visum()
    assert verify(visum, 2)['status'] == 'VERIFIED'
    matrices[9721].values[0, 0] = 0
    with pytest.raises(ContractError, match='LIVE04_FROZEN_DISTANCE_DIAGONAL:9721'):
        verify(visum, 2)


def test_blended_distance_uses_od_ratio_and_keeps_shared_diagonal():
    eligible = np.array([[2., 10.], [20., 3.]])
    restricted = np.array([[2., 30.], [40., 3.]])
    ratio = np.array([[0.7, 0.25], [1., 0.6]])
    assert np.array_equal(blended_distance(eligible, restricted, ratio),
                          np.array([[2., 25.], [20., 3.]]))
    with pytest.raises(RuntimeError, match='DISTANCE_SPLIT_RATIO_OUT_OF_RANGE'):
        blended_distance(eligible, restricted, np.full((2, 2), 1.01))


def test_live04_component_map_and_long_basis_are_consistent():
    cfg = load_config()
    assert cfg['idp_guard']['distance_matrix_by_component'] == FROZEN_IDP_DISTANCE_MAP
    assert FROZEN_IDP_DISTANCE_MAP['LONG_COMPOSITE'] == cfg['v7']['long_post_td_mask']['distance_matrix_no'] == 9721
    assert set(FROZEN_IDP_DISTANCE_MAP.values()) == {9721, 9726, 9727}


def test_idp_rejects_modified_frozen_distance(monkeypatch):
    from cordon2025 import live03_idp
    visum, matrices = _visum()

    class Metrics:
        def __init__(self, distance):
            self.distance = distance

        def evaluate(self, _mats):
            return {'WORK_E_C': {k: 0. for k in
                    ('objective', 'fine_cdf_rmse', 'fine_cdf_ks', 'mean_model_km',
                     'mean_target_km', 'mean_relative_error')}}

    ref = SimpleNamespace(CONFIG={'distance_matrix': 9697, 'max_fine_cdf_rmse_degradation': 0.,
                                  'mean_error_floor': 0., 'max_mean_error_degradation': 0.},
                          TARGETS={'WORK_E_C': {'matrix_nos': []}}, Metrics=Metrics)
    monkeypatch.setattr(live03_idp, 'reference', lambda: ref)
    guard = IdpGuard(visum, 2, {'distance_matrix_by_component': {'WORK_E_C': 9726}})
    assert guard.evaluate()['WORK_E_C']['objective'] == 0.
    matrices[9726].values[0, 1] += 1.
    with pytest.raises(ContractError, match='LIVE03_IDP_FROZEN_DISTANCE_CHANGED:9726'):
        guard.evaluate()
