"""User-confirmed S45 direction and native-entry check against the current key roster."""
import csv
from types import SimpleNamespace

import pytest

from cordon2025.common import ROOT, read_json
from cordon2025.live03_incidence import EXTRA_GROUP_IDS, extra_contributions
from cordon2025.live03_observations import Contract
from cordon2025.live04_config import load_config
from cordon2025.live05_extra import check_links


A = (99811855, 99800794, 1000030)
B = (99811855, 1000030, 99800794)


def test_confirmed_s45_keeps_targets_and_counts_the_correct_direction_only():
    cfg = load_config()
    contract = Contract(cfg['observations'])
    rows = {r['obs_id']: r for r in contract.extra_rows}
    assert len(rows) == 130
    assert rows['NDS_S45A']['in_link'] == A and rows['NDS_S45A']['target'] == 39799.
    assert rows['NDS_S45B']['in_link'] == B and rows['NDS_S45B']['target'] == 42441.
    assert read_json(ROOT / 'provenance/live04_user_config/CORDON_LIVE04_CONFIG.RELEASE_DEFAULT.json') == cfg
    spec = [dict(row_id=rows[name]['row_id'], group_id=EXTRA_GROUP_IDS['NDS'],
                 kind='LINK', in_eid=eid, out_eid=None)
            for name, eid in [('NDS_S45A', 101), ('NDS_S45B', 102)]]
    assert extra_contributions((101,), spec) == (((rows['NDS_S45A']['row_id'], EXTRA_GROUP_IDS['NDS']), 1.),)
    assert extra_contributions((102,), spec) == (((rows['NDS_S45B']['row_id'], EXTRA_GROUP_IDS['NDS']), 1.),)
    assert extra_contributions((101, 101), spec) == (((rows['NDS_S45A']['row_id'], EXTRA_GROUP_IDS['NDS']), 2.),)
    assert extra_contributions((103, 104, 105), spec) == ()  # Other split parts are not the count site.


def test_all_observation_links_pass_on_the_actual_20261117_network_roster(tmp_path):
    path = ROOT / 'docs/network_remap_20261117/evidence/EXTRA_OBSERVATION_NETWORK_KEYS.csv'
    with path.open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    keys = {tuple(int(r[a]) for a in ('NO', 'FROMNODENO', 'TONODENO')) for r in rows}
    assert len(keys) == 10832
    assert A in keys and B in keys
    assert (2004381, 1000030, 1000082) not in keys

    class Columns:
        def GetMultiAttValues(self, attr, active):
            assert active is False
            values = [(i + 1, row[attr]) for i, row in enumerate(rows)]
            return values[::-1] if attr == 'TONODENO' else values

    contract = Contract(load_config()['observations'])
    visum = SimpleNamespace(Net=SimpleNamespace(Links=Columns()))
    proof = check_links(visum, contract, tmp_path, native=True,
                        source_version='R1_VARIANTYBase_LIVE04_2025_4_LIVE04_BASE_d49e4158.ver')
    assert proof['status'] == 'PASS' and proof['missing'] == proof['closed_for_car'] == []
    assert proof['links'] == 120 and proof['network_links'] == 10832
    assert proof['affected_observations'] == []
    assert proof['counts'] == {'ASD': 12, 'KMOV': 24, 'NDS': 94}
    assert proof['row_weights'] == pytest.approx(contract.extra_weights())
