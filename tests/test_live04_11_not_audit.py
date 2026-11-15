"""LIVE04.11: read-only _noT audit script (screenline, vignette-only links, matrix shares) on a tiny fake."""
import importlib.util
import json
from types import SimpleNamespace
from cordon2025.common import ROOT


def _load():
    spec = importlib.util.spec_from_file_location('not_audit', ROOT / 'RUN_R1_2025_NOT_SHARE_AUDIT.py')
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


class Coll:
    def __init__(self, rows): self.rows = rows
    def GetMultiAttValues(self, name, _):
        return [(i + 1, r.get(name, 0.0)) for i, r in enumerate(self.rows)]


class Obj:
    def __init__(self, d): self.d = d
    def AttValue(self, k): return self.d[k]


def test_audit_finds_d1_and_parallel_road_and_shares(tmp_path, monkeypatch):
    m = _load()
    x, y = 221722.27, 5346485.28
    def link(no, ts, typ, off, vol_cw, vol_not):
        # parallel to D1 (24 deg), shifted by `off` metres perpendicular to it (along the screenline)
        cx, cy = x - 0.4067 * off, y + 0.9135 * off
        r = {'NO': no, 'FROMNODENO': no * 10, 'TONODENO': no * 10 + 1, 'TYPENO': typ, 'TSYSSET': ts, 'LENGTH': 1.0,
             'ADDVAL1': 0, 'V0PRT': 100, r'FROMNODE\XCOORD': cx - 457, r'FROMNODE\YCOORD': cy - 203,
             r'TONODE\XCOORD': cx + 457, r'TONODE\YCOORD': cy + 203}
        r['VOLVEH_DSEG(NATIVE_CW,AP)'] = vol_cw; r['VOLVEH_DSEG(NATIVE_CW_noT,AP)'] = vol_not
        return r
    rows = [link(1, 'B,C,LNV,NV', 2, 0, 20000, 0),             # D1 (vignette only)
            link(2, 'B,C,C_noT,LNV,NV', 10, 1500, 9000, 6000),  # parallel I-road
            link(3, 'B,C,C_noT', 30, 40000, 500, 500)]          # far away, not crossing
    mats = [Obj({'NO': 9301, 'CODE': 'NATIVE_CW', 'NAME': 'cw', 'SUM': 700.0, 'DIAGSUM': 0.0}),
            Obj({'NO': 9302, 'CODE': 'NATIVE_CW_noT', 'NAME': 'cwn', 'SUM': 300.0, 'DIAGSUM': 0.0})]
    ops = [Obj({'NO': 11, 'OPERATIONTYPE': 65, 'COMMENT': 'kappa-band', 'ACTIVE': 1})]
    v = SimpleNamespace(IO=SimpleNamespace(CurrentVersionFile='x.ver'),
                        Procedures=SimpleNamespace(Operations=SimpleNamespace(GetAll=ops)),
                        Net=SimpleNamespace(Matrices=SimpleNamespace(GetAll=mats), Links=Coll(rows)))
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    res = m.main({'Visum': v})
    assert res['no_vignette_share_by_matrix_code']['NATIVE_CW']['no_vignette_share'] == 0.3
    assert res['vignette_only_links_by_type'] == {'2': {'links': 1, 'km': 1.0}}
    sl = res['screenlines']['SDP1']
    assert sl['links_crossing'] == 2 and sl['car_total'] == 35000 and sl['no_vignette_total'] == 6000
    assert [r['NO'] for r in sl['top10']] == [1, 2]
    out = next(tmp_path.glob('R1C25_BOOT/NOT_SHARE_AUDIT_*'))
    assert (out / 'SCREENLINE_SDP1.csv').is_file() and json.loads((out / 'NOT_SHARE_AUDIT.json').read_text())['read_only']


class Attrs:
    def __init__(self, editable): self.editable = editable
    def ItemByKey(self, k): return SimpleNamespace(Editable=self.editable)


class MObj(Obj):
    def __init__(self, d, editable=True):
        super().__init__(d); self.Attributes = Attrs(editable)
    def AttValue(self, k):
        if k not in self.d:
            raise KeyError(k)
        return self.d[k]


def test_matrix_catalogue_finds_skims_and_ratio_formula_editability():
    m = _load()
    mats = [MObj({'NO': 9231, 'CODE': 'RATIO_CW', 'DATASOURCETYPE': 'FORMULA',
                  'FORMULA': 'If(Matrix(201)+Matrix(202)>0;Matrix(201)/(Matrix(201)+Matrix(202));0.75)'}),
            MObj({'NO': 701, 'CODE': 'TCUR_C', 'MATRIXTYPE': 'Skim', 'SUM': 5.0}),
            MObj({'NO': 9301, 'CODE': 'NATIVE_CW', 'MATRIXTYPE': 'Demand'})]
    v = SimpleNamespace(Net=SimpleNamespace(Matrices=SimpleNamespace(GetAll=mats)))
    cat = m.matrix_catalogue(v)
    assert [r['no'] for r in cat['matrices']] == [701, 9231, 9301]
    assert [r['no'] for r in cat['skim_like']] == [701]
    r = cat['ratio_matrices']['9231']
    assert r['formula_editable'] is True and r['formula'].startswith('If(Matrix(201)')
