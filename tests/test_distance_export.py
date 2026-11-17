"""The export must retain zone order and never turn a no-path sentinel into a trip length."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('distance_export', ROOT / 'RUN_R1_EXPORT_CURRENT_VISUM_DISTANCES.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class Matrix:
    def __init__(self, no, code, dseg, values):
        self.attrs = {'NO': no, 'CODE': code, 'DSEGCODE': dseg}
        self.values = values

    def AttValue(self, key):
        return self.attrs[key]

    def GetValues(self):
        return self.values.copy()


def test_export_includes_all_segments_and_preserves_zone_order(tmp_path):
    source = tmp_path / 'LIVE04_TEST_2025.ver'
    source.write_bytes(b'saved model')
    reference = np.array([[0, 10, 20], [11, 0, 30], [21, 31, 0]], dtype=float)
    matrices = [Matrix(9697, 'R1_OSRM_DIST_KM', '', reference)]
    for i, seg in enumerate(mod.SEGMENTS):
        a = reference.copy()
        a[0, 1] = 16 + i
        a[1, 2] = 999999.0
        matrices.append(Matrix(9844 + 8 * i, 'DIS', seg, a))
    visum = SimpleNamespace(
        IO=SimpleNamespace(CurrentVersionFile=str(source)),
        Net=SimpleNamespace(
            Zones=SimpleNamespace(GetMultiAttValues=lambda key: [(3, 30), (1, 10), (2, 20)]),
            Matrices=SimpleNamespace(GetAll=lambda: matrices),
        ),
    )
    report = mod.export(visum)
    assert report['status'] == 'EXPORTED_READ_ONLY' and report['freshness_certified'] is False
    assert report['comparison_to_9697']['NATIVE_CF']['pairs_difference_at_least_5_km'] == 1
    assert report['comparison_to_9697']['NATIVE_CF']['no_path_offdiagonal_pairs'] == 1
    out = sorted(tmp_path.glob('R1_DISTANCE_EXPORT_*'))[0]
    with np.load(out / 'CURRENT_VISUM_DISTANCES.npz') as data:
        assert data['zone_no'].tolist() == [10, 20, 30]
        assert data['M9697'][0, 1] == 10
        assert data['DIS_NATIVE_CF'][0, 1] == 16
    assert source.read_bytes() == b'saved model'


def test_export_rejects_missing_dis_before_output(tmp_path):
    source = tmp_path / 'LIVE04_TEST_2025.ver'
    source.write_bytes(b'saved model')
    matrix = Matrix(9697, 'R1_OSRM_DIST_KM', '', np.zeros((1, 1)))
    visum = SimpleNamespace(
        IO=SimpleNamespace(CurrentVersionFile=str(source)),
        Net=SimpleNamespace(
            Zones=SimpleNamespace(GetMultiAttValues=lambda key: [(1, 10)]),
            Matrices=SimpleNamespace(GetAll=lambda: [matrix]),
        ),
    )
    try:
        mod.export(visum)
    except RuntimeError as exc:
        assert 'DIST_EXPORT_MISSING_MATRICES' in str(exc)
    else:
        raise AssertionError('missing passenger skims accepted')
    assert not list(tmp_path.glob('R1_DISTANCE_EXPORT_*'))
