"""LIVE05: extra observation rows (NDS / ASD profiles, K1/K2 movements). Synthetic only."""
import numpy as np
import pytest

from cordon2025.common import ContractError
from cordon2025.live03_incidence import extra_contributions, EXTRA_GROUP_IDS, EXTRA_ROW_BASE
from cordon2025.live03_observations import Contract, validate_extra
from cordon2025.live04_config import load_config

X = [{'row_id': 1000, 'group_id': 20, 'kind': 'LINK', 'in_eid': 5, 'out_eid': None},
     {'row_id': 1001, 'group_id': 22, 'kind': 'PAIR', 'in_eid': 3, 'out_eid': 7},
     {'row_id': 1002, 'group_id': 22, 'kind': 'PAIR', 'in_eid': 7, 'out_eid': 3}]


def test_link_and_movement_contributions():
    assert extra_contributions((1, 3, 5, 7), X) == (((1000, 20), 1.0), ((1001, 22), 1.0))
    assert extra_contributions((7, 9, 3), X) == (((1002, 22), 1.0),)          # order matters
    assert extra_contributions((5, 6, 5), X) == (((1000, 20), 2.0),)          # every pass of a link
    assert extra_contributions((), X) == ()
    assert extra_contributions((1, 2), [dict(X[0], in_eid=None)]) == ()      # link not in the path store


def test_contract_counts_weights_and_targets():
    cfg = load_config()
    c = Contract(cfg['observations'])
    n = len(c.extra_rows)
    base = c.row_count('FIRST_LAST') - c.extra_row_count('FIRST_LAST')
    assert n == 130 and c.extra_row_count('FIRST_LAST') == n and c.extra_row_count('EXACT_TWO_HITS') == 0
    w = c.extra_weights()
    sh = cfg['observations']['extra_observations']['group_shares']
    o = cfg['observations']
    wc = (120.0 + (16 * float(o.get('c17_row_weight', 1.0)) ** 2 if c.station_cells else 0.0)
          + (c.profile_row_count('FIRST_LAST') * float((o.get('station_profiles') or {}).get('row_weight', 1.0)) ** 2
             if c.profile_cells else 0.0))
    for g, share in sh.items():
        ng = sum(1 for r in c.extra_rows if r['group'] == g)
        assert ng * w[g] ** 2 == pytest.approx(share / (1 - sum(sh.values())) * wc)
    assert sum(1 for r in c.extra_rows if r['group'] == 'NDS') == 94
    assert sum(1 for r in c.extra_rows if r['group'] == 'ASD') == 12
    assert sum(1 for r in c.extra_rows if r['group'] == 'KMOV') == 24
    assert base >= 120
    t = c.targets('FIRST_LAST')
    r0 = c.extra_rows[0]
    assert t[(r0['row_id'], EXTRA_GROUP_IDS[r0['group']])] == pytest.approx(r0['target'])
    assert t[(EXTRA_GROUP_IDS[r0['group']], r0['row_id'])] == 0.0
    assert all(k[0] < EXTRA_ROW_BASE for k in c.targets('EXACT_TWO_HITS'))
    ext = c.mathcfg_extension()['extra_observation_rows']
    assert len(ext) == n and {e['kind'] for e in ext} == {'LINK', 'PAIR'}
    # duplicates of the cordon stations were removed (user decision 2026-11-15)
    import csv
    from cordon2025.common import ROOT
    station = {(int(r['link_no']), int(r['from_node_no']), int(r['to_node_no']))
               for r in csv.DictReader(open(ROOT / 'data/audited/STATION_MAPPING.csv', encoding='utf-8-sig'), delimiter=';')}
    assert not {tuple(r['in_link']) for r in c.extra_rows if r['kind'] == 'LINK'} & station


def test_extra_config_guards():
    base = load_config()['observations']
    for patch, err in (({'group_shares': {'NDS': 0.5, 'ASD': 0.3, 'KMOV': 0.2}}, 'SHARE_RANGE'),
                       ({'group_shares': {'NDS': 0.1}}, 'GROUP_SHARES'),
                       ({'unexpected': 1}, 'KEYS')):
        obs = dict(base, extra_observations=dict(base['extra_observations'], **patch))
        with pytest.raises(ContractError, match=err):
            validate_extra(obs)
    obs = dict(base, extra_observations=dict(base['extra_observations'], file_sha256='0' * 64))
    with pytest.raises(ContractError, match='LIVE05_EXTRA_FILE_HASH_CHANGED'):
        Contract(obs)
    off = dict(base, extra_observations=dict(base['extra_observations'], enabled=False))
    c_off = Contract(off)
    assert c_off.extra_row_count('FIRST_LAST') == 0
    assert Contract(base).row_count('FIRST_LAST') == c_off.row_count('FIRST_LAST') + 130
