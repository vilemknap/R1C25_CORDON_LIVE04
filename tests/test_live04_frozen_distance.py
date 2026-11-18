"""Offline checks for frozen skim distances; no native Visum claim."""
from types import SimpleNamespace
import numpy as np
import pytest

from cordon2025.common import ContractError
from cordon2025.live04_config import FROZEN_IDP_DISTANCE_MAP, load_config
from cordon2025.live04_frozen_distance import EXPECTED, verify, assert_unchanged
from cordon2025.live03_idp import IdpGuard, _evaluate_component, reference
import RUN_R1_2025_FREEZE_VISUM_DISTANCES as freeze
from RUN_R1_2025_FREEZE_VISUM_DISTANCES import blended_distance


class Matrix:
    def __init__(self, no, code, values):
        self.no, self.code, self.values = no, code, values

    def AttValue(self, key):
        return {'NO': self.no, 'CODE': self.code, 'OBJECTTYPEREF': 2,
                'MATRIXTYPE': 3, 'DATASOURCETYPE': 'DATA'}[key.upper()]

    def GetValues(self):
        return self.values


def _visum():
    original = np.array([[2., 30.], [40., 3.]])
    matrices = {9697: Matrix(9697, 'R1_OSRM_DIST_KM', original)}
    matrices.update({no: Matrix(no, code, original.copy()) for no, code in EXPECTED.items()})
    matrices[9231] = Matrix(9231, 'RATIO_CW', np.full((2, 2), 0.75))
    matrices[9233] = Matrix(9233, 'RATIO_CS', np.full((2, 2), 0.70))
    zones = SimpleNamespace(GetMultiAttValues=lambda attr, active_only: [(1, 11), (2, 12)])
    return SimpleNamespace(origin='MOCK_LIVE04_681_ZONES_NOT_NATIVE',
                           Net=SimpleNamespace(Zones=zones, Matrices=SimpleNamespace(ItemByKey=matrices.__getitem__))), matrices


def test_frozen_distance_preflight_checks_identity_and_intrazonal_values():
    visum, matrices = _visum()
    assert verify(visum, 2)['status'] == 'VERIFIED'
    matrices[9721].values[0, 0] = 0
    with pytest.raises(ContractError, match='LIVE04_FROZEN_DISTANCE_DIAGONAL:9721'):
        verify(visum, 2)


def test_frozen_distance_preflight_checks_blends_and_data_type():
    visum, matrices = _visum()
    matrices[9726].values[0, 1] += 1.
    with pytest.raises(ContractError, match='LIVE04_FROZEN_DISTANCE_BLEND:9726'):
        verify(visum, 2)
    matrices[9726].values[0, 1] -= 1.
    matrices[9726].AttValue = lambda key: 'FORMULA' if key.upper() == 'DATASOURCETYPE' else {
        'NO': 9726, 'CODE': 'R1_BASE_DIS_WORK_KM', 'OBJECTTYPEREF': 2, 'MATRIXTYPE': 3}[key.upper()]
    with pytest.raises(ContractError, match='LIVE04_FROZEN_DISTANCE_NOT_DATA:9726'):
        verify(visum, 2)


def test_frozen_distance_preflight_accepts_numeric_com_enums():
    """Native Visum COM returns NO and the matrix enums as floats (2026-11-18 live stop
    LIVE04_FROZEN_DISTANCE_ORIGINAL_TYPE: DATASOURCETYPE 1.0 was read as text '10')."""
    visum, matrices = _visum()
    for m in matrices.values():
        m.AttValue = (lambda m: lambda key: {'NO': float(m.no), 'CODE': m.code, 'OBJECTTYPEREF': 2.0,
                                             'MATRIXTYPE': 3.0, 'DATASOURCETYPE': 1.0}[key.upper()])(m)
    visum.Net.Zones.GetMultiAttValues = lambda attr, active_only: [(1, 11.0), (2, 12.0)]
    assert verify(visum, 2)['status'] == 'VERIFIED'
    m = matrices[9697]
    m.AttValue = lambda key: {'NO': 9697.0, 'CODE': m.code, 'OBJECTTYPEREF': 2.0,
                              'MATRIXTYPE': 3.0, 'DATASOURCETYPE': 2.0}[key.upper()]
    with pytest.raises(ContractError, match='LIVE04_FROZEN_DISTANCE_ORIGINAL_TYPE'):
        verify(visum, 2)


def test_frozen_distance_missing_matrix_is_named():
    visum, matrices = _visum()
    del matrices[9724]
    with pytest.raises(ContractError, match='LIVE04_FROZEN_DISTANCE_MISSING:9724'):
        verify(visum, 2)


def test_native_preflight_checks_pinned_zone_osrm_and_component_hashes(monkeypatch):
    import hashlib
    from cordon2025 import live04_frozen_distance as authority
    visum, matrices = _visum()
    visum.origin = ''
    monkeypatch.setattr(authority, 'ZONE_ORDER_SHA256', hashlib.sha256(
        np.array([11, 12], dtype='<i8').tobytes()).hexdigest())
    monkeypatch.setattr(authority, 'OSRM_VALUES_SHA256', authority._hash(matrices[9697].values))
    monkeypatch.setattr(authority, 'RAW_VALUES_SHA256', {
        no: authority._hash(matrices[no].values) for no in range(9720, 9726)})
    assert verify(visum, 2)['source_hashes_pinned']
    matrices[9721].values[0, 1] += 1.
    with pytest.raises(ContractError, match='LIVE04_FROZEN_DISTANCE_RAW_HASH:9721'):
        verify(visum, 2)


def test_frozen_distance_hashes_do_not_drift_between_blocks():
    visum, matrices = _visum()
    baseline = verify(visum, 2)
    assert assert_unchanged(visum, 2, baseline)['matrix_hashes'] == baseline['matrix_hashes']
    matrices[9726].values[0, 1] += 1.
    with pytest.raises(ContractError, match='LIVE04_FROZEN_DISTANCE_BLEND:9726'):
        assert_unchanged(visum, 2, baseline)


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
    monkeypatch.setattr(live03_idp, '_evaluate_component', lambda *args: {
        k: 0. for k in ('objective', 'fine_cdf_rmse', 'fine_cdf_ks', 'mean_model_km',
                        'mean_target_km', 'mean_relative_error')})
    guard = IdpGuard(visum, 2, {'distance_matrix_by_component': {'WORK_E_C': 9726}})
    assert guard.evaluate()['WORK_E_C']['objective'] == 0.
    matrices[9726].values[0, 1] += 1.
    with pytest.raises(ContractError, match='LIVE03_IDP_FROZEN_DISTANCE_CHANGED:9726'):
        guard.evaluate()


def test_one_component_finecdf_matches_pinned_reference_and_ignores_foreign_empty_scope():
    ref = reference()
    distance = np.full((4, 4), 50.)
    np.fill_diagonal(distance, 2.)
    distance[0, 3] = distance[3, 0] = 150.
    matrix_nos = {int(no) for target in ref.TARGETS.values() for no in target['matrix_nos']}
    matrices = {no: np.ones((4, 4)) for no in matrix_nos}
    metric = ref.Metrics(distance)
    combined = metric.evaluate(matrices)
    for key in ref.TARGETS:
        selected = _evaluate_component(metric, matrices, key, ref)
        for field, value in selected.items():
            assert value == pytest.approx(combined[key][field], rel=1e-12, abs=1e-12)
    long_only = ref.Metrics(np.array([[150.]]))
    one_cell = {no: np.ones((1, 1)) for no in matrix_nos}
    with pytest.raises(Exception, match='No conditioned demand'):
        long_only.evaluate(one_cell)
    assert np.isfinite(_evaluate_component(long_only, one_cell, 'LONG_COMPOSITE', ref)['objective'])


def test_freeze_creates_readable_data_matrices_from_pinned_sources(tmp_path, monkeypatch):
    import hashlib
    source = tmp_path / 'checkpoint.ver'
    source.write_bytes(b'synthetic checkpoint')
    n = 681
    original = np.full((n, n), 15., dtype='<f8')
    np.fill_diagonal(original, 2.)

    class WritableMatrix(Matrix):
        def __init__(self, no, code, arr, dseg='', matrix_type=3):
            super().__init__(no, code, arr)
            self.dseg, self.matrix_type = dseg, matrix_type

        def AttValue(self, key):
            return {'NO': self.no, 'CODE': self.code, 'DSEGCODE': self.dseg,
                    'OBJECTTYPEREF': 2, 'MATRIXTYPE': self.matrix_type,
                    'DATASOURCETYPE': 1}[key.upper()]

        def SetAttValue(self, key, value):
            if key.upper() == 'CODE':
                self.code = value

        def SetValues(self, arr, add):
            assert add is False
            self.values = np.array(arr, copy=True)

    matrices = {9697: WritableMatrix(9697, 'R1_OSRM_DIST_KM', original)}
    pinned = []
    for i, (_, source_no, dseg, _) in enumerate(freeze.FROZEN):
        arr = np.full((n, n), 20. + i)
        np.fill_diagonal(arr, 0.)
        matrices[source_no] = WritableMatrix(source_no, 'DIS', arr, dseg=dseg, matrix_type=4)
        pinned.append((9720 + i, source_no, dseg, freeze.digest(arr)))
    matrices[9231] = WritableMatrix(9231, 'RATIO_CW', np.full((n, n), 0.75))
    matrices[9233] = WritableMatrix(9233, 'RATIO_CS', np.full((n, n), 0.70))
    added = []

    class Collection:
        def ItemByKey(self, no):
            return matrices[no]

        def GetMultiAttValues(self, key):
            return [(i + 1, m.AttValue(key)) for i, m in enumerate(matrices.values())]

    class Net:
        Matrices = Collection()

        def AddMatrix(self, no, object_type, matrix_type):
            added.append((no, object_type, matrix_type))
            m = WritableMatrix(no, '', np.zeros((n, n)), matrix_type=matrix_type)
            matrices[no] = m
            return m

    zones = np.arange(1, n + 1, dtype='<i8')
    Net.Zones = SimpleNamespace(GetMultiAttValues=lambda key, active_only: list(enumerate(zones, 1)))
    visum = SimpleNamespace(Net=Net(), IO=SimpleNamespace(CurrentVersionFile=str(source)))
    monkeypatch.setattr(freeze, 'SOURCE_SHA256', hashlib.sha256(source.read_bytes()).hexdigest())
    monkeypatch.setattr(freeze, 'ZONE_SHA256', hashlib.sha256(zones.tobytes()).hexdigest())
    monkeypatch.setattr(freeze, 'OSRM_SHA256', freeze.digest(original))
    monkeypatch.setattr(freeze, 'FROZEN', tuple(pinned))
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    report = freeze.prepare(visum)
    assert report['status'] == 'FROZEN_IN_OPEN_MODEL_RUN_RECOMPUTE_BEFORE_SAVE'
    assert added == [(no, 2, 3) for no in range(9720, 9728)]
    assert np.array_equal(matrices[9721].GetValues().diagonal(), original.diagonal())
    assert matrices[9726].GetValues()[0, 1] == 0.75 * 24. + 0.25 * 25.
    assert matrices[9727].GetValues()[0, 1] == pytest.approx(0.70 * 22. + 0.30 * 23.)
    assert np.array_equal(matrices[9697].GetValues(), original)
