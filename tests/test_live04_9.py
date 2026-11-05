"""LIVE04.9: 16 station profile rows (total crossings per cordon station) next to the 120 FIRST_LAST
pairs and the 16 C17 margins.  Target = row + column sum of the D3 OA ALL RPDI cordon matrix;
model = station link volume (every hit of every saved path).  Synthetic mock only.
Since LIVE04.10 the release config uses the directional raw-detection profiles; these tests run the
LIVE04.9 mode (source D3_ALL_ROW_PLUS_COLUMN_SUM) from an explicit config file."""
import json
import csv
import sqlite3
import struct
from collections import Counter

import numpy as np
import pytest

from cordon2025.common import ROOT, read_json, parent_core, ContractError
from cordon2025.live03_incidence import first_last_contributions, C17_STATION, PROFILE_STATION
from cordon2025 import live03_observations as obs
from cordon2025.live04_config import load_config
from cordon2025.live04_cycle import run
from fake_live04 import Live04Visum

pytestmark = pytest.mark.station_profiles

OPT = {'min_free_disk_gib': 0, 'com_retry_initial_delay_seconds': 0., 'com_retry_max_delay_seconds': 0.}
D3_PROFILES = {'enabled': True, 'source': 'D3_ALL_ROW_PLUS_COLUMN_SUM', 'row_weight': 1.0}


@pytest.fixture
def d3cfg(tmp_path):
    cfg = json.loads((ROOT / 'CORDON_LIVE04_CONFIG.json').read_text(encoding='utf-8'))
    cfg['observations']['station_profiles'] = dict(D3_PROFILES)
    p = tmp_path / 'CORDON_LIVE04_CONFIG_D3_PROFILES.json'
    p.write_text(json.dumps(cfg), encoding='utf-8')
    return p


GEN_ONLY = {'max_cycles': 1, 'blocks_per_cycle': ['GENERATION'], 'td_cordon': {'enabled': False},
            'write_policy': {'td_parameter_writes': False}}


def test_contributions_count_every_hit():
    assert first_last_contributions([3, 5, 7], True, True) == (((3, 7), 1.0), ((3, PROFILE_STATION), 1.0),
                                                                ((5, PROFILE_STATION), 1.0), ((7, PROFILE_STATION), 1.0))
    assert first_last_contributions([4], True, True) == (((4, C17_STATION), 1.0), ((4, PROFILE_STATION), 1.0))
    assert first_last_contributions([2, 9, 2], True, True) == (((2, C17_STATION), 2.0), ((2, PROFILE_STATION), 2.0),
                                                                ((9, PROFILE_STATION), 1.0))
    # without profiles: unchanged LIVE03 semantics
    assert first_last_contributions([3, 5, 7], True) == (((3, 7), 1.0),)
    assert first_last_contributions([], True, True) == ()


def test_d3_mode_contract_has_152_rows_with_d3_row_plus_column_targets(d3cfg):
    cfg = load_config(d3cfg)
    sp = cfg['observations']['station_profiles']
    assert sp['enabled'] is True and sp['source'] == 'D3_ALL_ROW_PLUS_COLUMN_SUM'
    c = obs.Contract(cfg['observations'])
    assert c.row_count('FIRST_LAST') == 152 and c.row_count('EXACT_TWO_HITS') == 120
    with np.load(ROOT / 'data/audited/AUDITED_MATRICES.npz') as d:
        A = np.asarray(d['OA_ALL_D3_RPDI'], dtype=float)
    for s in range(1, 17):
        t = c.profile_cells[(s, PROFILE_STATION)] + c.profile_cells[(PROFILE_STATION, s)]
        assert t == pytest.approx(A[s - 1, :].sum() + A[:, s - 1].sum())
    assert c.profile_cells[(1, PROFILE_STATION)] + c.profile_cells[(PROFILE_STATION, 1)] == pytest.approx(63656.0)
    assert c.audit['station_profile_target_sum'] == pytest.approx(A[:16, :].sum() + A[:, :16].sum())
    assert c.mathcfg_extension()['first_last_profile_rows'] is True
    # disabled -> the 136-row LIVE03 contract, same hash as without the key
    off = dict(cfg['observations'], station_profiles=dict(sp, enabled=False))
    assert obs.Contract(off).row_count('FIRST_LAST') == 136
    assert 'first_last_profile_rows' not in obs.Contract(off).mathcfg_extension()


@pytest.mark.parametrize('bad', [{'enabled': 'yes', 'source': 'D3_ALL_ROW_PLUS_COLUMN_SUM', 'row_weight': 1.0},
                                 {'enabled': True, 'source': 'COUNTERS', 'row_weight': 1.0},
                                 {'enabled': True, 'source': 'D3_ALL_ROW_PLUS_COLUMN_SUM', 'row_weight': 0},
                                 {'enabled': True, 'unknown_field': 1}])
def test_invalid_station_profiles_refused(bad):
    with pytest.raises(ContractError, match='LIVE04_STATION_PROFILE'):
        load_config(overrides={'observations': {'station_profiles': bad}})


def _station_volumes(cache):
    """Independent link volumes: decode every saved path, count station-link traversals."""
    core = parent_core()
    stations = {}
    with open(ROOT / 'data/audited/STATION_MAPPING.csv', encoding='utf-8-sig') as f:
        for r in csv.DictReader(f, delimiter=';'):
            stations[(int(r['link_no']), int(r['from_node_no']), int(r['to_node_no']))] = int(r['station_id'])
    db = sqlite3.connect(cache)
    edges = {int(e): (int(a), int(b), int(c)) for e, a, b, c in db.execute('SELECT eid,link_no,from_no,to_no FROM edges')}
    out = Counter()
    q = 'SELECT g.edge_ids,g.edge_count,v.dseg,v.volume FROM geometry g JOIN volumes v ON v.gid=g.gid'
    for blob, n, dseg, vol in db.execute(q):
        code = core.norm_code(dseg)
        if not code.startswith(('NATIVE_', 'EXOG_EE_')) or not n:
            continue
        for e in struct.unpack('<%dI' % n, blob):
            s = stations.get(edges[e])
            if s:
                out[s] += float(vol)
    db.close()
    return out


def test_mock_run_profile_rows_equal_station_link_volumes(tmp_path, d3cfg):
    v = Live04Visum(tmp_path / 'model')
    run(v, output_root=tmp_path / 'runs', options=OPT, config_path=d3cfg, config_overrides=GEN_ONLY)
    f = next((tmp_path / 'runs').glob('LIVE04_TGTD_*'))
    contract = read_json(f / 'OBSERVATION_CONTRACT.json')
    assert contract['rows']['FIRST_LAST'] == 152 and len(contract['station_profile_parts']) == 16
    gen = read_json(f / 'C01_GENERATION' / 'GENERATION_BLOCK_RESULT.json')
    assert gen['objective_before']['metrics']['FIRST_LAST']['pairs'] == 152
    cap = f / '01_BASELINE_CAPTURE'
    rows = [r for r in csv.DictReader(open(cap / 'CORDON_PAIR_RESULTS.csv', encoding='utf-8-sig'), delimiter=';')
            if r['method'] == 'FIRST_LAST' and int(r['destination_station']) == PROFILE_STATION]
    assert len(rows) == 16
    expected = _station_volumes(cap / 'p.sqlite')
    assert sum(expected.values()) > 0
    for r in rows:
        s = int(r['origin_station'])
        assert float(r['model']) == pytest.approx(expected.get(s, 0.0), abs=1e-6)
        assert float(r['observed']) == pytest.approx(next(p['target_crossings'] for p in contract['station_profile_parts']
                                                          if p['station'] == s))
    res = read_json(f / '00_RESULT.json')
    assert res['observation_semantics'].endswith('_PLUS_STATION_PROFILES')


def test_supply_mix_runs_on_152_rows(tmp_path, d3cfg):
    """SupplyMix maps every directed key incl. the 16 profiles; accepted or exactly rolled back."""
    v = Live04Visum(tmp_path / 'model', route_gamma=0.3, addval_beta=0.4, bypass_anchor=True)
    over = dict(GEN_ONLY, v7={'run_options': {'sp_start_cycle': 1}}, _allow_donor_overrides=True)
    r = run(v, output_root=tmp_path / 'runs', options=OPT, config_path=d3cfg, config_overrides=over)
    f = next((tmp_path / 'runs').glob('LIVE04_TGTD_*'))
    rec = read_json(f / 'C01_SUPPLY_ADDVAL1' / 'SUPPLYMIX_BLOCK_RESULT.json')
    assert 'error' not in rec or not rec['error'], rec
    assert rec['status'] in ('ACCEPTED', 'NO_ACCEPTED_TRIAL', 'NO_CANDIDATE', 'NO_DRIVER_PROFILES'), rec['status']
    design = read_json(f / 'C01_SUPPLY_ADDVAL1' / 'DESIGN' / 'SUPPLY_PATH_SEQUENCE_DESIGN.json') \
        if (f / 'C01_SUPPLY_ADDVAL1' / 'DESIGN' / 'SUPPLY_PATH_SEQUENCE_DESIGN.json').exists() else None
    if rec['status'] != 'ACCEPTED':
        rb = read_json(f / 'C01_SUPPLY_ADDVAL1' / 'ROLLBACK_SUMMARY.json')
        assert rb['passes'] and rb['snapshot_equal']
    assert r['status'] != 'LIVE04_STOPPED_WITH_ERROR'


def test_td_block_runs_on_152_rows(tmp_path, d3cfg):
    v = Live04Visum(tmp_path / 'model')
    r = run(v, output_root=tmp_path / 'runs', options=OPT, config_path=d3cfg, config_overrides={'max_cycles': 1, 'blocks_per_cycle': ['TD_CORDON']})
    blocks = [(b['block'], b['status']) for c in r['cycles'] for b in c['blocks']]
    assert blocks and blocks[0][0] == 'TD_CORDON' and 'ERROR' not in blocks[0][1], blocks
    f = next((tmp_path / 'runs').glob('LIVE04_TGTD_*'))
    assert read_json(f / 'OBSERVATION_CONTRACT.json')['rows']['FIRST_LAST'] == 152
