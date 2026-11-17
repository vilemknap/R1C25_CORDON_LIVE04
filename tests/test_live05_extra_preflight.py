"""Regression: a link split must fail before capture and identify the affected rows."""
from types import SimpleNamespace

import pytest

from cordon2025.common import ContractError, read_json
from cordon2025.live05_extra import check_links


OLD = (2004381, 1000030, 1000082)
NEW = [(99811855, 1000030, 99800794), (99811856, 99800794, 99800795),
       (99811857, 99800795, 99800792), (99811844, 99800792, 99800791),
       (99811842, 99800791, 1000082)]


class Columns:
    def __init__(self, keys, mode='C,C_noT', damage=None):
        self.rows = [dict(zip(('NO', 'FROMNODENO', 'TONODENO'), k), TSYSSET=mode) for k in keys]
        self.damage = damage
        self.reads = []

    def GetMultiAttValues(self, attr, active):
        assert active is False
        self.reads.append(attr)
        rows = [(i + 1, row[attr]) for i, row in enumerate(self.rows)]
        if self.damage == attr:
            rows = rows[:-1]
        return rows[::-1] if attr == 'TONODENO' else rows


def contract():
    return SimpleNamespace(
        extra_rows=[{'obs_id': 'NDS_S45A', 'group': 'NDS',
                     'in_link': (OLD[0], OLD[2], OLD[1]), 'out_link': None},
                    {'obs_id': 'NDS_S45B', 'group': 'NDS', 'in_link': OLD, 'out_link': None}],
        extra_links=lambda: {OLD, (OLD[0], OLD[2], OLD[1])},
        audit={'extra_observations': {'counts': {'NDS': 2}, 'row_weights': {'NDS': 1.}}})


def network(keys, **kwargs):
    return SimpleNamespace(Net=SimpleNamespace(Links=Columns(keys, **kwargs)))


def test_old_export_passes_but_the_split_live_network_reports_both_observations(tmp_path):
    before = network([OLD, (OLD[0], OLD[2], OLD[1])])
    assert check_links(before, contract(), tmp_path / 'before')['status'] == 'PASS'
    keys = NEW + [(n, b, a) for n, a, b in NEW]
    current = network(keys)
    with pytest.raises(ContractError, match='observations=NDS_S45A,NDS_S45B'):
        check_links(current, contract(), tmp_path / 'current', source_version='edited_2025_LIVE04.ver')
    report = read_json(tmp_path / 'current/EXTRA_OBSERVATION_LINKS.json')
    assert report['missing'] == [list(OLD), [OLD[0], OLD[2], OLD[1]]]
    assert report['source_version'] == 'edited_2025_LIVE04.ver'
    assert report['network_links'] == 10 and report['read_only']
    assert {r['obs_id'] for r in report['affected_observations']} == {'NDS_S45A', 'NDS_S45B'}
    assert report['missing_link_candidates'][0]['incident_to_old_endpoints']['count'] == 4
    assert (tmp_path / 'current/EXTRA_OBSERVATION_NETWORK_KEYS.csv').is_file()
    assert len(current.Net.Links.reads) == 4  # Diagnostics make no extra COM reads or writes.


@pytest.mark.parametrize('mode', ['C', 'C_noT', 'C_NOT', ' c_not '])
def test_car_modes_use_the_same_case_insensitive_aliases(mode):
    assert check_links(network([OLD, (OLD[0], OLD[2], OLD[1])], mode=mode), contract())['status'] == 'PASS'


def test_a_closed_car_link_still_blocks_and_identifies_the_rows(tmp_path):
    with pytest.raises(ContractError, match='missing=0,closed=2'):
        check_links(network([OLD, (OLD[0], OLD[2], OLD[1])], mode='LNV,NV'), contract(), tmp_path)
    assert len(read_json(tmp_path / 'EXTRA_OBSERVATION_LINKS.json')['affected_observations']) == 2


def test_inconsistent_column_coverage_and_duplicate_network_keys_are_not_accepted():
    with pytest.raises(ContractError, match='COLUMN_COVERAGE_MISMATCH'):
        check_links(network([OLD], damage='TONODENO'), contract())
    with pytest.raises(ContractError, match='DUPLICATE_OR_INVALID_LINK_KEY'):
        check_links(network([OLD, OLD]), contract())


def test_native_cycle_rejects_missing_rows_before_constructing_the_baseline_evaluator(tmp_path, monkeypatch):
    import cordon2025.live04_cycle as cycle
    monkeypatch.setattr(cycle, 'Contract', lambda obs: contract())
    monkeypatch.setattr(cycle, 'model_preflight', lambda *args: ([], {
        'source_version': str(tmp_path / 'R1_2025_LIVE04.ver')}))
    calls = []

    def forbidden_baseline(*args, **kwargs):
        calls.append('baseline')
        raise AssertionError('BASELINE_MUST_NOT_START_WITH_MISSING_OBSERVATION_LINKS')

    monkeypatch.setattr(cycle, 'Live04Evaluator', forbidden_baseline)
    visum = network(NEW)
    visum.origin = 'NATIVE_INJECTED_VISUM'
    with pytest.raises(ContractError, match='LIVE05_EXTRA_OBSERVATION_LINKS_NOT_IN_NETWORK'):
        cycle.run(visum, output_root=tmp_path / 'runs', options={'min_free_disk_gib': 0})
    assert calls == []
    folder = next((tmp_path / 'runs').glob('LIVE04_TGTD_*'))
    assert read_json(folder / 'EXTRA_OBSERVATION_LINKS.json')['status'] == 'FAIL'
    assert not (folder / '01_BASELINE_CAPTURE').exists()
