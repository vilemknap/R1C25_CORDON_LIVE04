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


@pytest.mark.parametrize('data_source', [1.0, '1.0'])
def test_frozen_distance_accepts_com_numeric_data_enum(data_source):
    visum, matrices = _visum()
    for no in (9697, 9720):
        matrix = matrices[no]
        original = matrix.AttValue
        matrix.AttValue = lambda key, original=original: (
            data_source if key.upper() == 'DATASOURCETYPE' else original(key))
    assert verify(visum, 2)['status'] == 'VERIFIED'


def test_frozen_distance_rejects_formula_original():
    visum, matrices = _visum()
    original = matrices[9697].AttValue
    matrices[9697].AttValue = lambda key: (
        'FORMULA' if key.upper() == 'DATASOURCETYPE' else original(key))
    with pytest.raises(ContractError, match='LIVE04_FROZEN_DISTANCE_ORIGINAL_TYPE'):
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


LIVE_COM_ENUMS = {'MATRIXTYPE': 'MATRIXTYPE_DEMAND', 'OBJECTTYPEREF': 'OBJECTTYPEREF_ZONE', 'DATASOURCETYPE': 'DATA'}


def test_frozen_distance_accepts_live_visum_enum_strings():
    """Values exactly as the live 2025 model returns them (INVENTORY_2025.json, M9697):
    MATRIXTYPE_DEMAND / OBJECTTYPEREF_ZONE / DATA. 2026-11-18 live stop ORIGINAL_TYPE."""
    visum, matrices = _visum()
    for m in matrices.values():
        m.AttValue = (lambda m: lambda key: LIVE_COM_ENUMS.get(key.upper()) or
                      {'NO': m.no, 'CODE': m.code}[key.upper()])(m)
    assert verify(visum, 2)['status'] == 'VERIFIED'
    m = matrices[9697]
    m.AttValue = lambda key: {'NO': 9697, 'CODE': m.code, 'MATRIXTYPE': 'MATRIXTYPE_SKIM',
                              'OBJECTTYPEREF': 'OBJECTTYPEREF_ZONE', 'DATASOURCETYPE': 'DATA'}[key.upper()]
    with pytest.raises(ContractError, match="LIVE04_FROZEN_DISTANCE_ORIGINAL_TYPE:MATRIXTYPE='MATRIXTYPE_SKIM'"):
        verify(visum, 2)


def test_frozen_distance_missing_matrix_is_named():
    visum, matrices = _visum()
    del matrices[9724]
    with pytest.raises(ContractError, match='LIVE04_FROZEN_DISTANCE_MISSING:9724'):
        verify(visum, 2)


def test_preflight_is_universal_and_run_start_hashes_guard_the_run():
    """No checkpoint pin: any consistent model verifies; the run-start hashes then hold."""
    visum, matrices = _visum()
    visum.origin = ''
    baseline = verify(visum, 2)
    assert baseline['authority'] == 'RUN_START_HASHES_NO_CHECKPOINT_PIN'
    matrices[9697].values[0, 1] += 1.
    with pytest.raises(ContractError, match='LIVE04_FROZEN_DISTANCE_CHANGED_DURING_RUN'):
        assert_unchanged(visum, 2, baseline)
    matrices[9697].values[0, 1] -= 1.
    assert_unchanged(visum, 2, baseline)
    visum.Net.Zones.GetMultiAttValues = lambda attr, active_only: [(1, 12), (2, 11)]
    with pytest.raises(ContractError, match='LIVE04_FROZEN_DISTANCE_CHANGED_DURING_RUN'):
        assert_unchanged(visum, 2, baseline)


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


class _WritableMatrix(Matrix):
    def __init__(self, no, code, arr, dseg='', matrix_type=3):
        super().__init__(no, code, arr)
        self.dseg, self.matrix_type, self.name = dseg, matrix_type, ''

    def AttValue(self, key):
        # floats like native Visum COM
        return {'NO': float(self.no), 'CODE': self.code, 'DSEGCODE': self.dseg, 'NAME': self.name, 'FORMULA': '',
                'OBJECTTYPEREF': 2.0, 'MATRIXTYPE': float(self.matrix_type),
                'DATASOURCETYPE': 1.0}[key.upper()]

    def SetAttValue(self, key, value):
        if key.upper() == 'CODE':
            self.code = value
        elif key.upper() == 'NAME':
            self.name = value

    def SetValues(self, arr, add):
        assert add is False
        self.values = np.array(arr, copy=True)


def _freeze_model(tmp_path, n=681, name='ANY_2025_LIVE04_VERSION.ver', source_numbers=None):
    source = tmp_path / name
    source.write_bytes(b'synthetic saved version')
    original = np.full((n, n), 15., dtype='<f8')
    np.fill_diagonal(original, 2.)
    matrices = {9697: _WritableMatrix(9697, 'R1_OSRM_DIST_KM', original)}
    numbers = source_numbers or [9844 + 8 * i for i in range(6)]
    for i, (no, (_, dseg)) in enumerate(zip(numbers, freeze.SEGMENTS)):
        arr = np.full((n, n), 20. + i)
        np.fill_diagonal(arr, 0.)
        matrices[no] = _WritableMatrix(no, 'DIS', arr, dseg=dseg.replace('_NOT', '_noT'), matrix_type=4)
    matrices[9231] = _WritableMatrix(9231, 'RATIO_CW', np.full((n, n), 0.75))
    matrices[9233] = _WritableMatrix(9233, 'RATIO_CS', np.full((n, n), 0.70))
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
            m = _WritableMatrix(no, '', np.zeros((n, n)), matrix_type=matrix_type)
            matrices[no] = m
            return m

    zones = np.arange(1, n + 1, dtype='<i8')
    Net.Zones = SimpleNamespace(GetMultiAttValues=lambda key, active_only: [(i, float(z)) for i, z in enumerate(zones, 1)])
    visum = SimpleNamespace(Net=Net(), IO=SimpleNamespace(CurrentVersionFile=str(source)))
    return visum, matrices, added, original


def test_freeze_is_universal_and_creates_readable_data_matrices(tmp_path, monkeypatch):
    import json
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    # arbitrary file and arbitrary DIS matrix numbers: sources are found by CODE + DSEGCODE
    visum, matrices, added, original = _freeze_model(tmp_path, source_numbers=[7001, 7002, 7003, 7004, 7005, 7006])
    report = freeze.prepare(visum)
    assert report['status'] == 'FROZEN_IN_OPEN_MODEL_RUN_RECOMPUTE_BEFORE_SAVE'
    assert added == [(no, 2, 3) for no in range(9720, 9728)]
    assert np.array_equal(matrices[9721].GetValues().diagonal(), original.diagonal())
    assert matrices[9726].GetValues()[0, 1] == 0.75 * 24. + 0.25 * 25.
    assert matrices[9727].GetValues()[0, 1] == pytest.approx(0.70 * 22. + 0.30 * 23.)
    assert np.array_equal(matrices[9697].GetValues(), original)
    assert {f['source_no'] for f in report['frozen'] if 'source_no' in f} == {7001, 7002, 7003, 7004, 7005, 7006}
    saved = json.loads((tmp_path / 'R1C25_DISTANCE_PREP' / 'FROZEN_DISTANCE_RESULT.json').read_text())
    assert saved['source_sha256'] and saved['status'] == report['status']
    # the calibrator accepts exactly what the script wrote (no checkpoint pins)
    assert verify(visum, 681)['status'] == 'VERIFIED'
    # re-freeze on the same model overwrites (same CODE), adds nothing
    matrices[7002].values[0, 1] = 99.
    added.clear()
    assert freeze.prepare(visum)['refreeze'] == list(range(9720, 9728))
    assert added == [] and matrices[9721].GetValues()[0, 1] == 99.


def test_freeze_accepts_live_visum_enum_strings(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    visum, matrices, added, _ = _freeze_model(tmp_path)
    live = {'MATRIXTYPE': 'MATRIXTYPE_DEMAND', 'OBJECTTYPEREF': 'OBJECTTYPEREF_ZONE', 'DATASOURCETYPE': 'DATA'}
    orig_attvalue = _WritableMatrix.AttValue
    monkeypatch.setattr(_WritableMatrix, 'AttValue', lambda self, key: (
        live[key.upper()] if key.upper() in live and self.matrix_type == 3 else orig_attvalue(self, key)))
    assert freeze.prepare(visum)['status'] == 'FROZEN_IN_OPEN_MODEL_RUN_RECOMPUTE_BEFORE_SAVE'
    assert verify(visum, 681)['status'] == 'VERIFIED'


def test_freeze_refuses_foreign_target_no_path_and_ambiguous_source(tmp_path, monkeypatch):
    import json
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    result = tmp_path / 'R1C25_DISTANCE_PREP' / 'FROZEN_DISTANCE_RESULT.json'
    visum, matrices, added, _ = _freeze_model(tmp_path)
    matrices[9723] = _WritableMatrix(9723, 'SOMETHING_ELSE', np.zeros((681, 681)))
    with pytest.raises(RuntimeError, match='DISTANCE_TARGET_NUMBER_USED_BY_OTHER_MATRIX:9723'):
        freeze.prepare(visum)
    assert added == [] and json.loads(result.read_text())['status'] == 'STOPPED_BEFORE_ANY_WRITE'
    visum, matrices, added, _ = _freeze_model(tmp_path)
    matrices[9852].values[3, 4] = 999999.
    with pytest.raises(RuntimeError, match='DISTANCE_SOURCE_NO_PATH_CELLS:NATIVE_CL:1'):
        freeze.prepare(visum)
    assert added == []
    visum, matrices, added, _ = _freeze_model(tmp_path)
    matrices[8000] = _WritableMatrix(8000, 'DIS', np.ones((681, 681)), dseg='NATIVE_CW', matrix_type=4)
    with pytest.raises(RuntimeError, match='DISTANCE_SOURCE_DIS_NOT_UNIQUE:NATIVE_CW'):
        freeze.prepare(visum)
    visum, _, _, _ = _freeze_model(tmp_path, name='R1_2022_MODEL.ver')
    with pytest.raises(RuntimeError, match='DISTANCE_ONLY_2025_MODEL'):
        freeze.prepare(visum)


class _FormulaRatio(Matrix):
    def __init__(self, no, code, values, formula):
        super().__init__(no, code, values)
        self.formula = formula

    def AttValue(self, key):
        return {'NO': self.no, 'CODE': self.code, 'OBJECTTYPEREF': 'OBJECTTYPEREF_ZONE',
                'MATRIXTYPE': 'MATRIXTYPE_DEMAND', 'DATASOURCETYPE': 'FORMULA', 'FORMULA': self.formula}[key.upper()]


class _Skim(Matrix):
    def AttValue(self, key):
        return {'NO': self.no, 'CODE': self.code, 'OBJECTTYPEREF': 'OBJECTTYPEREF_ZONE',
                'MATRIXTYPE': 'MATRIXTYPE_SKIM', 'DATASOURCETYPE': 'DATA', 'FORMULA': ''}[key.upper()]


def test_ratio_following_skims_is_refused_at_run_start():
    """R1 20D DT_MODE=LIVE makes 9231/9233 follow the tCur skims of the run; the frozen
    blends would stop matching after the first assignment. Refuse at start."""
    visum, matrices = _visum()
    matrices[9235] = Matrix(9235, 'VIG_DT_W', np.full((2, 2), 3.0))
    frozen = '0.74+(1-0.74)/(1+Exp(-(4.45+0.5*(12.84*Matrix(9235)/60-10))))'
    matrices[9231] = _FormulaRatio(9231, 'RATIO_CW', np.full((2, 2), 0.75), frozen)
    assert verify(visum, 2)['status'] == 'VERIFIED'
    matrices[9872] = _Skim(9872, 'TTC', np.full((2, 2), 9.0))
    matrices[9880] = _Skim(9880, 'TTC', np.full((2, 2), 11.0))
    matrices[9231].formula = '0.74+(1-0.74)/(1+Exp(-(4.45+0.5*(12.84*Max(0,Matrix(9880)-Matrix(9872))/60-10))))'
    with pytest.raises(ContractError, match=r'LIVE04_FROZEN_DISTANCE_RATIO_FOLLOWS_SKIMS:9231:\[9872, 9880\]'):
        verify(visum, 2)


def test_freeze_refuses_non_copy_name_and_ratio_following_skims(tmp_path, monkeypatch):
    import json
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    result = tmp_path / 'R1C25_DISTANCE_PREP' / 'FROZEN_DISTANCE_RESULT.json'
    visum, _, added, _ = _freeze_model(tmp_path, name='R1_BASE_2025_ORIGINAL.ver')
    with pytest.raises(RuntimeError, match='DISTANCE_OPEN_MODEL_IS_NOT_AN_ISOLATED_COPY'):
        freeze.prepare(visum)
    assert added == [] and json.loads(result.read_text())['status'] == 'STOPPED_BEFORE_ANY_WRITE'
    visum, matrices, added, _ = _freeze_model(tmp_path)
    n = 681
    matrices[9872] = _WritableMatrix(9872, 'TTC', np.full((n, n), 9.0), dseg='NATIVE_CW', matrix_type=4)
    ratio = _WritableMatrix(9231, 'RATIO_CW', np.full((n, n), 0.75))
    ratio.AttValue = lambda key: {'DATASOURCETYPE': 'FORMULA', 'FORMULA': '0.7+0.01*Matrix(9872)'}.get(
        key.upper(), _WritableMatrix.AttValue(ratio, key))
    matrices[9231] = ratio
    with pytest.raises(RuntimeError, match=r'DISTANCE_SPLIT_RATIO_FOLLOWS_SKIMS:9231:\[9872\]'):
        freeze.prepare(visum)
    assert added == []
