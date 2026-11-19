"""RUN_R1_2025_RESET_WS_COEFFICIENTS_TO_UNIT.py on a synthetic host (not native PTV Visum)."""
import csv
import importlib.util
import json
from pathlib import Path
import pytest
from cordon2025.common import ROOT


def load():
    spec = importlib.util.spec_from_file_location('unit_reset', ROOT / 'RUN_R1_2025_RESET_WS_COEFFICIENTS_TO_UNIT.py')
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


class Zones:
    def __init__(self, rows, fail_attr=None):
        self.rows, self.fail_attr, self.writes = rows, fail_attr, []

    def GetMultiAttValues(self, attr, active):
        assert active is False
        return [(i + 1, r[attr]) for i, r in enumerate(self.rows)]

    def SetMultiAttValues(self, attr, rows):
        self.writes.append(attr)
        for index, value in rows:
            self.rows[index - 1][attr] = float(value)
        if attr == self.fail_attr:
            self.rows[0][attr] = 2.0          # corrupt readback


class Visum:
    def __init__(self, ver, rows, fail_attr=None):
        self.IO = type('IO', (), {'CurrentVersionFile': str(ver)})()
        self.Net = type('N', (), {})()
        self.Net.Zones = Zones(rows, fail_attr)


def rows(n=681):
    out = []
    for i in range(n):
        foreign = i >= 650
        out.append({'NO': i + 1, 'NOT_ZAHR': 0.0 if foreign else 1.0, 'ADD_PROD_W': 3.26 if i == 458 else 1.0,
                    'ADD_PROD_S': 2.37, 'ADD_ATT_W': 5.29, 'ADD_ATT_S': 0.5, 'ADD_SALARY': 0.7})
    return out


def test_reset_sets_domestic_ws_to_one_and_keeps_foreign(tmp_path, monkeypatch):
    m = load()
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'app'))
    ver = tmp_path / 'R1_2025_LIVE04_COPY.ver'; ver.write_bytes(b'VER')
    v = Visum(ver, rows())
    rep = m.reset(v)
    assert rep['status'] == 'RESET_IN_OPEN_MODEL_RUN_RECOMPUTE_BEFORE_SAVE' and rep['save_version_called'] is False
    z = v.Net.Zones.rows
    assert all(z[i][a] == 1.0 for i in range(650) for a in m.WS_ATTRIBUTES)
    assert all(z[i]['ADD_ATT_W'] == 5.29 and z[i]['ADD_PROD_S'] == 2.37 for i in range(650, 681))   # foreign
    assert all(r['ADD_SALARY'] == 0.7 for r in z)                                                  # off by default
    assert rep['changed']['ADD_PROD_W']['zones'] == 1 and rep['changed']['ADD_ATT_W']['zones'] == 650
    prev = list(csv.DictReader(open(rep['previous_values_csv'], encoding='utf-8')))
    assert {'attribute': 'ADD_PROD_W', 'zone_no': '459', 'value_before': '3.26'}.items() <= prev[0].items()
    assert ver.read_bytes() == b'VER'                                                              # no save
    # the LIVE04.14 preflight now passes on the reset values
    import numpy as np
    from cordon2025 import live04_generation_structure as gs
    coef = {k: np.array([r[a] for r in z]) for k, a in gs.COEF.items()}
    dom = np.array([r['NOT_ZAHR'] >= 0.5 for r in z])
    assert gs.unit_start_check([r['NO'] for r in z], coef, None, dom,
                               'REQUIRE_UNIT_WS_ON_ACTUATABLE_DOMESTIC_ZONES')['status'] == 'PROVEN_UNIT_BASE'


def test_reset_refuses_the_original_and_reports_a_failed_readback(tmp_path, monkeypatch):
    m = load()
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'app'))
    orig = tmp_path / 'R1_VARIANTYBase.ver'; orig.write_bytes(b'VER')
    with pytest.raises(RuntimeError, match='NOT_AN_ISOLATED_COPY'):
        m.reset(Visum(orig, rows()))
    last = json.loads((tmp_path / 'app/R1C25_UNIT_BASE_PREP/UNIT_RESET_RESULT_LAST.json').read_text())
    assert last['status'] == 'STOPPED_BEFORE_ANY_WRITE'
    ver = tmp_path / 'R1_2025_TEST.ver'; ver.write_bytes(b'VER')
    with pytest.raises(RuntimeError, match='UNIT_RESET_READBACK:ADD_ATT_W'):
        m.reset(Visum(ver, rows(), fail_attr='ADD_ATT_W'))
    last = json.loads((tmp_path / 'app/R1C25_UNIT_BASE_PREP/UNIT_RESET_RESULT_LAST.json').read_text())
    assert last['status'] == 'MODEL_MAY_BE_CHANGED_CLOSE_WITHOUT_SAVING'
    bad = rows(); bad[3]['ADD_ATT_S'] = ''
    with pytest.raises(RuntimeError, match='UNIT_RESET_BLANK_VALUE:ADD_ATT_S'):
        m.reset(Visum(ver, bad))
