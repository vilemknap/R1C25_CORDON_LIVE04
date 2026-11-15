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


def test_mock_cycle_carries_extra_rows(tmp_path, monkeypatch):
    """Mock run with LIVE05 rows on synthetic links: rows reach the ledger, the link check passes."""
    import hashlib
    import fake_live04
    from fake_live04 import Live04Visum
    monkeypatch.setattr(fake_live04, 'LIVE05_ROWS', True)
    from cordon2025.common import read_json
    from cordon2025.live04_cycle import run
    v = Live04Visum(tmp_path / 'model')
    links = [(int(r['NO']), int(r['FROMNODENO']), int(r['TONODENO'])) for r in v.Net.Links.rows]
    by_from = {}
    for k in links:
        by_from.setdefault(k[1], []).append(k)
    pair = next((a, b) for a in links for b in by_from.get(a[2], []) if b[2] != a[1])
    lines = ['obs_id;group;kind;in_link;out_link;target_rpdi;source']
    for i, k in enumerate(links[:4]):
        lines.append('N%d;NDS;LINK;%d:%d:%d;;%.1f;synthetic' % ((i,) + k + (500.0 + 100 * i,)))
    lines.append('A0;ASD;LINK;%d:%d:%d;;800.0;synthetic' % links[4])
    lines.append('K0;KMOV;PAIR;%d:%d:%d;%d:%d:%d;300.0;synthetic' % (pair[0] + pair[1]))
    f = tmp_path / 'extra.csv'
    f.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    ex = {'enabled': True, 'file': str(f), 'file_sha256': hashlib.sha256(f.read_bytes()).hexdigest(),
          'group_shares': {'NDS': 0.15, 'ASD': 0.10, 'KMOV': 0.05}}
    over = {'max_cycles': 1, 'blocks_per_cycle': ['GENERATION'], 'td_cordon': {'enabled': False},
            'write_policy': {'td_parameter_writes': False}, 'observations': {'extra_observations': ex}}
    r = run(v, output_root=tmp_path / 'runs', options={'min_free_disk_gib': 0, 'com_retry_initial_delay_seconds': 0.,
                                                      'com_retry_max_delay_seconds': 0.}, config_overrides=over)
    folder = next((tmp_path / 'runs').glob('LIVE04_TGTD_*'))
    chk = read_json(folder / 'EXTRA_OBSERVATION_LINKS.json')
    assert chk['status'] == 'PASS', chk
    assert chk['links'] == len(set(links[:5]) | set(pair)) and chk['counts'] == {'NDS': 4, 'ASD': 1, 'KMOV': 1}
    assert r['extra_observations']['status'] == 'PASS'
    gen = read_json(folder / 'C01_GENERATION/GENERATION_BLOCK_RESULT.json')
    base = Contract(load_config(overrides={'observations': {'extra_observations': dict(ex, enabled=False)}})['observations'])
    assert gen['objective_before']['metrics']['FIRST_LAST']['pairs'] == base.row_count('FIRST_LAST') + 6


class _Coll:
    """GetMultiAttValues with a deliberately different enumeration order per attribute."""
    def __init__(self, rows):
        self.rows = rows

    def GetMultiAttValues(self, name, only_active=None):
        assert only_active is False
        out = [(i + 1, r[name]) for i, r in enumerate(self.rows)]
        return out[::-1] if name in ('TONODENO', 'T0PRT') else out


def test_columns_are_joined_by_object_index():
    from types import SimpleNamespace
    from cordon2025.live05_extra import check_links
    from cordon2025 import live04_nodevdf as nv
    links = _Coll([{'NO': 1, 'FROMNODENO': 10, 'TONODENO': 11, 'TSYSSET': 'C'},
                   {'NO': 2, 'FROMNODENO': 11, 'TONODENO': 12, 'TSYSSET': 'LNV'}])
    contract = SimpleNamespace(extra_rows=[1], extra_links=lambda: {(1, 10, 11), (2, 11, 12)},
                               audit={'extra_observations': {'counts': {}, 'row_weights': {}}})
    out = check_links(SimpleNamespace(Net=SimpleNamespace(Links=links)), contract, native=False)
    assert out['missing'] == [] and out['closed_for_car'] == [[2, 11, 12]]
    nodes = [{'NO': 1, 'TYPENO': 1, 'CAPPRT': 900, 'T0PRT': 5}, {'NO': 2, 'TYPENO': 2, 'CAPPRT': 1800, 'T0PRT': 0}]
    net = lambda rows: SimpleNamespace(Net=SimpleNamespace(Nodes=_Coll(rows)))
    a = nv.fingerprint(net(nodes))['groups']['nodes']
    b = nv.fingerprint(net(nodes[::-1]))['groups']['nodes']
    assert a['sha256'] == b['sha256'] and a['readable'] == ['TYPENO', 'CAPPRT', 'T0PRT']
    c = nv.fingerprint(net([dict(nodes[0], T0PRT=6), nodes[1]]))['groups']['nodes']
    assert c['sha256'] != a['sha256']
