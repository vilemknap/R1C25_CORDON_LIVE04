"""2026-11-17: frozen Visum DIS skims replace OSRM 9697 for the LONG mask and the IDP guard."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from cordon2025 import distance_authority as da
from cordon2025.common import ContractError, parent_module
from cordon2025.live04_config import load_config

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('freeze_dist', ROOT / 'RUN_R1_2025_FREEZE_SKIM_DISTANCES.py')
fz = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fz)


class M:
    def __init__(self, host, no, code, values, dseg='', mtype=3, otype=2):
        self.host = host
        self.attrs = {'NO': float(no), 'CODE': code, 'DSEGCODE': dseg, 'MATRIXTYPE': mtype,
                      'OBJECTTYPEREF': otype, 'NAME': ''}
        self.values = np.array(values, dtype=float)

    def AttValue(self, k):
        return self.attrs[k]

    def SetAttValue(self, k, v):
        self.attrs[k] = v

    def GetValues(self):
        return self.values.copy()

    def SetValues(self, a, add):
        assert add is False and isinstance(a, np.ndarray)
        self.host.writes.append(int(self.attrs['NO']))
        self.values = a.copy()


class Mats:
    def __init__(self, items):
        self.items = items

    def GetAll(self):
        return list(self.items)

    def ItemByKey(self, no):
        for m in self.items:
            if int(m.attrs['NO']) == int(no):
                return m
        return None


def host(tmp_path, n=4, name='R1_LIVE04_2025_BASE.ver', extra=()):
    src = tmp_path / name
    src.write_bytes(b'saved')
    v = SimpleNamespace(writes=[], saved=[])
    i = np.arange(n)
    osrm = 10.0 + np.abs(i[:, None] - i[None, :]) * 30.0
    np.fill_diagonal(osrm, 1.5)
    items = [M(v, 9697, 'R1_OSRM_DIST_KM', osrm)]
    for k, s in enumerate(fz.SEGMENTS):
        a = osrm * (1.1 if s.endswith('_NOT') else 1.0) + k * 0.01
        np.fill_diagonal(a, 0.0)
        items.append(M(v, 9844 + 8 * k, 'DIS', a, dseg=s.replace('_NOT', '_noT'), mtype=4))
    items.append(M(v, 9231, 'RATIO_CW', np.full((n, n), 0.75)))
    items.append(M(v, 9233, 'RATIO_CS', np.full((n, n), 0.5)))
    items += list(extra)
    mats = Mats(items)

    def add(no, otype, mtype):
        m = M(v, no, '', np.zeros((n, n)), mtype=mtype, otype=otype)
        mats.items.append(m)
        return m

    def save(path):
        Path(path).write_bytes(b'new')
        v.saved.append(path)
    v.IO = SimpleNamespace(CurrentVersionFile=str(src))
    v.Net = SimpleNamespace(Matrices=mats, AddMatrix=add, RemoveMatrix=lambda m: mats.items.remove(m),
                            Zones=SimpleNamespace(GetMultiAttValues=lambda k: [(j + 1, j + 1) for j in range(n)]))
    v.SaveVersion = save
    return v, src, osrm


def test_build_keeps_osrm_diagonal_and_blends_by_ratio(tmp_path):
    v, src, osrm = host(tmp_path)
    s, _, _ = fz.read_sources(v, 4)
    out = fz.build(s)
    assert set(out) == set(fz.TARGETS) == set(da.FROZEN)
    for no, a in out.items():
        assert np.allclose(np.diag(a), 1.5)
    off = ~np.eye(4, dtype=bool)
    assert np.allclose(out[9721][off], s['NATIVE_CL'][off])
    assert np.allclose(out[9726][off], (0.75 * s['NATIVE_CW'] + 0.25 * s['NATIVE_CW_NOT'])[off])
    assert np.allclose(out[9727][off], (0.5 * s['NATIVE_CS'] + 0.5 * s['NATIVE_CS_NOT'])[off])


def test_build_rejects_no_path_sentinel(tmp_path):
    v, src, osrm = host(tmp_path)
    s, _, _ = fz.read_sources(v, 4)
    s['NATIVE_CW'][0, 1] = 999999.0
    with pytest.raises(RuntimeError, match='FREEZE_DIS_NO_PATH'):
        fz.build(s)


def test_run_writes_eight_matrices_and_saves_new_version(tmp_path):
    v, src, osrm = host(tmp_path)
    res = fz.run(v, tmp_path / 'out')
    assert res['status'] == 'FROZEN_SAVED' and src.read_bytes() == b'saved'
    assert Path(res['saved_version']).name.startswith(src.stem + '_DISTFRZ_')
    assert sorted(v.writes) == sorted(fz.TARGETS)
    for no, code in fz.TARGETS.items():
        m = v.Net.Matrices.ItemByKey(no)
        assert m.attrs['CODE'] == code and m.attrs['MATRIXTYPE'] == 3
    assert np.array_equal(v.Net.Matrices.ItemByKey(9697).values, osrm)          # 9697 untouched
    assert json.loads((tmp_path / 'out' / 'RESULT.json').read_text(encoding='utf-8'))['status'] == 'FROZEN_SAVED'
    # refreeze: same CODE is overwritten, nothing added
    v.IO.CurrentVersionFile = res['saved_version']
    n_items = len(v.Net.Matrices.items)
    assert fz.run(v, tmp_path / 'out2')['status'] == 'FROZEN_SAVED'
    assert len(v.Net.Matrices.items) == n_items


def test_run_refuses_foreign_matrix_on_target_number(tmp_path):
    v0 = SimpleNamespace(writes=[])
    v, src, _ = host(tmp_path, extra=[M(v0, 9721, 'SOMETHING_ELSE', np.zeros((4, 4)))])
    with pytest.raises(RuntimeError, match='FREEZE_TARGET_NUMBER_USED_BY_OTHER_MATRIX:9721'):
        fz.run(v, tmp_path / 'out')
    assert not v.writes and not v.saved


def test_run_refuses_2022_model(tmp_path):
    v, src, _ = host(tmp_path, name='R1_2022_MODEL.ver')
    with pytest.raises(RuntimeError, match='FREEZE_ONLY_2025_MODEL'):
        fz.run(v, tmp_path / 'out')


def test_constants_match_calibrator():
    assert fz.TARGETS == da.FROZEN and fz.SEGMENTS == da.SEGMENTS


def test_config_binds_long_mask_to_frozen_cl():
    cfg = load_config()
    lm = cfg['v7']['long_post_td_mask']
    assert (lm['distance_matrix_no'], lm['distance_matrix_code']) == (9721, 'R1_BASE_DIS_NATIVE_CL_KM')
    mod = parent_module('r1_15a2_long_support_distance_v24917')
    assert (mod.MATRIX_NO, mod.MATRIX_CODE) == (9721, 'R1_BASE_DIS_NATIVE_CL_KM')
    assert da.configured(cfg) == {9721: ['LONG_POST_TD_MASK', 'IDP:LONG_COMPOSITE'], 9726: ['IDP:WORK', 'IDP:SCHOOL'],
                                  9727: ['IDP:SERV']}
    try:
        load_config(overrides={'v7': {'long_post_td_mask': {'distance_matrix_no': 9697,
                                                             'distance_matrix_code': 'R1_OSRM_DIST_KM'}}})
        assert (mod.MATRIX_NO, mod.MATRIX_CODE) == (9697, 'R1_OSRM_DIST_KM')
        with pytest.raises(ContractError):
            load_config(overrides={'v7': {'long_post_td_mask': {'distance_matrix_no': 9726,
                                                                 'distance_matrix_code': 'R1_BASE_DIS_IDP_WORK_KM'}}})
    finally:
        load_config()
    assert mod.MATRIX_NO == 9721


def test_idp_component_map_covers_every_component_once():
    from cordon2025.live03_idp import reference
    keys = list(reference().TARGETS)
    m = da.idp_component_map(keys, da.IDP_DEFAULT)
    assert m['WORK_E_C'] == 9726 and m['SCHOOL'] == 9726 and m['SERV_stud'] == 9727 and m['LONG_COMPOSITE'] == 9721
    with pytest.raises(ContractError):
        da.idp_component_map(keys, {'WORK': 9726, 'SERV': 9727})


def test_idp_guard_uses_component_distances():
    from cordon2025.live03_idp import IdpGuard, reference
    ref = reference()
    n = 40
    rng = np.random.default_rng(5)
    base = rng.uniform(0.5, 250.0, size=(n, n))
    d = {9697: base, 9721: base * 1.3, 9726: base * 0.7, 9727: base * 0.9}
    items = [M(None, no, da.CODES[no], a) for no, a in d.items()]
    nos = sorted({no for t in ref.TARGETS.values() for no in t['matrix_nos']})
    items += [M(None, no, 'P', rng.uniform(0.0, 1.0, size=(n, n))) for no in nos]
    visum = SimpleNamespace(Net=SimpleNamespace(Matrices=Mats(items)))
    g = IdpGuard(visum, n, {'distance_matrices': dict(da.IDP_DEFAULT)})
    out = g.evaluate()
    mats = {no: visum.Net.Matrices.ItemByKey(no).GetValues() for no in nos}
    for no in (9721, 9726, 9727):
        exp = ref.Metrics(d[no]).evaluate(mats)
        for k, dn in g.distance_by_component.items():
            if dn == no:
                assert out[k]['mean_model_km'] == pytest.approx(float(exp[k]['mean_model_km']))
                assert out[k]['fine_cdf_rmse'] == pytest.approx(float(exp[k]['fine_cdf_rmse']))
    plain = IdpGuard(visum, n, {}).evaluate()
    assert plain['WORK_E_C']['mean_model_km'] != pytest.approx(out['WORK_E_C']['mean_model_km'])
    assert g.decide(out, out)['distance_matrices']['LONG_COMPOSITE'] == 9721
    bad = [m for m in items if int(m.attrs['NO']) != 9727]
    with pytest.raises(ContractError, match='DISTANCE_MATRIX_MISSING:9727'):
        IdpGuard(SimpleNamespace(Net=SimpleNamespace(Matrices=Mats(bad))), n, {'distance_matrices': dict(da.IDP_DEFAULT)})


def test_preflight_reports_missing_frozen_matrix(tmp_path):
    cfg = load_config()
    n = 3
    items = [M(None, no, da.CODES[no], np.ones((n, n))) for no in (9721, 9726)]
    visum = SimpleNamespace(Net=SimpleNamespace(Matrices=Mats(items)))
    with pytest.raises(ContractError, match='DISTANCE_AUTHORITY_PREFLIGHT:9727'):
        da.preflight(visum, cfg, n, tmp_path)
    assert json.loads((tmp_path / 'DISTANCE_AUTHORITY.json').read_text())['status'] == 'FAIL'
