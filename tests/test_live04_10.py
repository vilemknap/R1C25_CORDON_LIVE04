"""LIVE04.10: 32 directional station profiles (one per directed station edge).

Target = raw ANPR detections OA per sign (E41 SDP RAW dataset) x D3 zone coefficient OA_RPDI.
Model  = volume of every saved path on that directed station edge (every hit, also the hits in the
middle of a multi-station trip, which the FIRST_LAST matrix does not contain).
Which edge carries '+' and which '-' is fixed by the georeferenced report maps (sign_edges, user
decision 2026-11-05); the agreement of the model paths with it is only recorded.
Synthetic mock only - NOT native PTV Visum evidence."""
import csv
import hashlib
import json
import sqlite3
import struct
from collections import Counter, defaultdict

import pytest

from cordon2025.common import ROOT, read_json, parent_core, ContractError
from cordon2025.live03_incidence import (first_last_contributions, side_contexts, station_sides, C17_STATION,
                                         PROFILE_STATION, PROFILE_STATION_B)
from cordon2025 import live03_observations as obs
from cordon2025.live04_config import load_config
from cordon2025.live04_cycle import run
from fake_live04 import Live04Visum

pytestmark = pytest.mark.station_profiles

OPT = {'min_free_disk_gib': 0, 'com_retry_initial_delay_seconds': 0., 'com_retry_max_delay_seconds': 0.}
GEN_ONLY = {'max_cycles': 1, 'blocks_per_cycle': ['GENERATION'], 'td_cordon': {'enabled': False},
            'write_policy': {'td_parameter_writes': False}}
EVIDENCE = ROOT / 'data/audited/STATION_PROFILE_EVIDENCE.json'
SIGN_EDGES = ROOT / 'data/audited/STATION_PROFILE_SIGN_EDGES.json'


def _station_map():
    out = {}
    with open(ROOT / 'data/audited/STATION_MAPPING.csv', encoding='utf-8-sig') as f:
        for r in csv.DictReader(f, delimiter=';'):
            out[(int(r['link_no']), int(r['from_node_no']), int(r['to_node_no']))] = int(r['station_id'])
    return out


# ------------------------------------------------------------------ unit level
def test_directional_contributions_count_every_hit_per_edge():
    assert first_last_contributions([3, 5, 7], True, 'DIRECTIONAL', [0, 1, 1]) == (
        ((3, 7), 1.0), ((3, PROFILE_STATION), 1.0), ((5, PROFILE_STATION_B), 1.0), ((7, PROFILE_STATION_B), 1.0))
    # cyclic trip through one station: entry on one edge, exit on the other
    assert first_last_contributions([2, 2], True, 'DIRECTIONAL', [0, 1]) == (
        ((2, C17_STATION), 2.0), ((2, PROFILE_STATION), 1.0), ((2, PROFILE_STATION_B), 1.0))
    assert first_last_contributions([4], True, 'DIRECTIONAL', [1]) == (((4, C17_STATION), 1.0), ((4, PROFILE_STATION_B), 1.0))
    with pytest.raises(ContractError, match='LIVE04_PROFILE_SIDES_MISSING'):
        first_last_contributions([4], True, 'DIRECTIONAL')
    # LIVE04.9 and LIVE03 semantics unchanged
    assert first_last_contributions([3, 5, 7], True, True) == (((3, 7), 1.0), ((3, PROFILE_STATION), 1.0),
                                                                ((5, PROFILE_STATION), 1.0), ((7, PROFILE_STATION), 1.0))
    assert first_last_contributions([3, 5, 7], True) == (((3, 7), 1.0),)


def test_side_contexts_and_sides():
    assert side_contexts([16, 3, 1], [0, 1, 0]) == [(16, 0, 'DEP', 3), (3, 1, 'ARR', 16), (3, 1, 'DEP', 1), (1, 0, 'ARR', 3)]
    assert side_contexts([2, 2], [0, 1]) == []
    sides = station_sides(_station_map())
    assert len(sides) == 32 and Counter(sides.values()) == {0: 16, 1: 16}
    # SDP15 (split carriageway, two links): side A = the smaller (link_no, from, to)
    assert sides[(9800634, 9900317, 9900312)] == 0 and sides[(9800637, 9900314, 9900318)] == 1
    with pytest.raises(ContractError, match='TWO_EDGES'):
        station_sides({(1, 2, 3): 1})


def test_resolution_on_the_survey_evidence():
    """A model whose side A behaves like '+' resolves to '+' = A with high agreement; swapped -> B."""
    doc = json.loads(EVIDENCE.read_text(encoding='utf-8'))
    for st in doc['stations']:
        raw = {g: st['signs'][g]['contexts'] for g in '+-'}
        same = obs.resolve_sign_sides(raw, {0: raw['+'], 1: raw['-']})
        swap = obs.resolve_sign_sides(raw, {0: raw['-'], 1: raw['+']})
        # a model with the survey's own (noisy) split: agreement = weighted mean r^2, above the 0.5 minimum
        assert same > 0.5 and swap == pytest.approx(-same), (st['station'], same, swap)
        # a deterministic model (each context on one edge only), as assigned paths are
        det = {0: {}, 1: {}}
        for c in set(raw['+']) | set(raw['-']):
            n = raw['+'].get(c, 0) + raw['-'].get(c, 0)
            det[0 if raw['+'].get(c, 0) >= raw['-'].get(c, 0) else 1][c] = n
        assert obs.resolve_sign_sides(raw, det) > 0.8, st['station']
        assert obs.resolve_sign_sides(raw, {0: {}, 1: {}}) == 0.0


def test_survey_evidence_is_aggregated_and_consistent():
    doc = json.loads(EVIDENCE.read_text(encoding='utf-8'))
    text = EVIDENCE.read_text(encoding='utf-8')
    assert 'ECV' not in text      # no licence plates in the release
    assert doc['source_d3_sha256'] == hashlib.sha256((ROOT / 'data/source/D3.xlsx').read_bytes()).hexdigest()
    by = {st['station']: st for st in doc['stations']}
    # raw detections SDP1 (6-18 h, OA): '+' = to Bratislava 30 384, '-' 28 774 (user check 2026-11-05)
    assert by[1]['signs']['+']['oa_detections_12h'] == 30384 and by[1]['signs']['-']['oa_detections_12h'] == 28774
    # the stations in the middle of multi-station trips: target ~ counters C3/C7/C9 (RPDI 38 190 / 8 962 / 6 981)
    for s, counter in ((3, 38190), (7, 8962), (9, 6981)):
        assert abs(by[s]['target_rpdi_both'] / counter - 1) < 0.03
    assert by[3]['zone_coefficient_oa_rpdi'] == pytest.approx(1.3290, abs=5e-4)


# --------------------------------------------------------------- contract level
def test_release_contract_has_168_rows_with_raw_targets():
    cfg = load_config()
    sp = cfg['observations']['station_profiles']
    assert sp['enabled'] is True and sp['source'] == 'E41_RAW_DETECTIONS_DIRECTIONAL'
    c = obs.Contract(cfg['observations'])
    assert c.profile_directional and c.row_count('FIRST_LAST') == 168 and c.row_count('EXACT_TWO_HITS') == 120
    assert c.mathcfg_extension()['first_last_profile_rows'] == 'DIRECTIONAL'
    doc = json.loads(EVIDENCE.read_text(encoding='utf-8'))
    for st, part in zip(doc['stations'], c.audit['station_profile_parts']):
        assert part['target_plus'] == pytest.approx(st['signs']['+']['target_rpdi'])
        assert part['target_minus'] == pytest.approx(st['signs']['-']['target_rpdi'])
    assert c.audit['station_profile_mode'] == 'DIRECTIONAL'
    with pytest.raises(ContractError, match='LIVE04_PROFILE_DIRECTIONS_NOT_RESOLVED'):
        c.targets('FIRST_LAST')
    assert len(c.targets('EXACT_TWO_HITS')) == 240
    off = dict(cfg['observations'], station_profiles=dict(sp, enabled=False))
    assert obs.Contract(off).row_count('FIRST_LAST') == 136


def test_report_sign_edges():
    doc = json.loads(SIGN_EDGES.read_text(encoding='utf-8'))
    smap = _station_map()
    by = {st['station']: st for st in doc['stations']}
    assert sorted(by) == list(range(1, 17))
    for s, st in by.items():
        assert {tuple(st['plus_edge']), tuple(st['minus_edge'])} == {k for k, v in smap.items() if v == s}
    # SDP1: '+' = to Bratislava = 9800210 (9900152 -> 9900156), as on the report map and in the data
    assert by[1]['plus_edge'] == [9800210, 9900152, 9900156] and by[1]['agrees_with_e41_data']
    # SDP8 / SDP10: the report map is followed although the E41 contexts point the other way
    assert not by[8]['agrees_with_e41_data'] and not by[10]['agrees_with_e41_data']
    assert by[8]['source'].startswith('REPORT_MAP') and by[10]['source'].startswith('REPORT_MAP')
    assert by[5]['source'] == 'REPORT_MAP_obr5' and by[5]['plus_edge'] == [2002315, 1002980, 1000321]
    assert all(st['source'].startswith('REPORT_MAP') for st in by.values())
    assert sum(st['agrees_with_e41_data'] for st in by.values()) == 14


@pytest.mark.parametrize('bad, code', [
    ({'sign_edges_sha256': '0' * 64}, 'SIGN_EDGES_HASH_CHANGED'),
    ({'sign_edges': 'data/audited/NOPE.json'}, 'SIGN_EDGES_MISSING'),
    ({'evidence_sha256': '0' * 64}, 'EVIDENCE_HASH_CHANGED'),
    ({'evidence': 'data/audited/NOPE.json'}, 'EVIDENCE_MISSING'),
    ({'min_direction_agreement': 0.5}, 'S$'),
    ({'row_weight': 0}, 'WEIGHT')])
def test_invalid_directional_profiles_refused(bad, code):
    with pytest.raises(ContractError, match='LIVE04_STATION_PROFILE' + ('' if code == 'S$' else '.*') + code):
        cfg = load_config(overrides={'observations': {'station_profiles': bad}})
        obs.Contract(cfg['observations'])


def test_tampered_evidence_arithmetic_refused(tmp_path):
    doc = json.loads(EVIDENCE.read_text(encoding='utf-8'))
    doc['stations'][2]['signs']['+']['target_rpdi'] *= 1.5
    p = tmp_path / 'ev.json'; p.write_text(json.dumps(doc), encoding='utf-8')
    over = {'evidence': str(p), 'evidence_sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
    with pytest.raises(ContractError, match='EVIDENCE_ARITHMETIC'):
        obs.Contract(load_config(overrides={'observations': {'station_profiles': over}})['observations'])


# ------------------------------------------------------------------ mock runs
def _edge_volumes_and_contexts(cache):
    """Independent decode of every saved OA path: volume per directed station edge + side contexts."""
    core = parent_core()
    smap = _station_map(); side_of = station_sides(smap)
    db = sqlite3.connect(cache)
    edges = {int(e): (int(a), int(b), int(c)) for e, a, b, c in db.execute('SELECT eid,link_no,from_no,to_no FROM edges')}
    vol = Counter(); ctx = defaultdict(float)
    q = 'SELECT g.edge_ids,g.edge_count,v.dseg,v.volume FROM geometry g JOIN volumes v ON v.gid=g.gid'
    for blob, n, dseg, v in db.execute(q):
        code = core.norm_code(dseg)
        if not code.startswith(('NATIVE_', 'EXOG_EE_')) or not n:
            continue
        seq = [edges[e] for e in struct.unpack('<%dI' % n, blob)]
        hits = [smap[e] for e in seq if e in smap]; sides = [side_of[e] for e in seq if e in smap]
        for e in seq:
            if e in smap:
                vol[e] += float(v)
        for c in side_contexts(hits, sides):
            ctx[c] += float(v)
    db.close()
    return vol, ctx, smap, side_of


def _synthetic_sign_edges(tmp_path, plus_side):
    """Sign table with '+' = side `plus_side` (A/B) at every station."""
    doc = json.loads(SIGN_EDGES.read_text(encoding='utf-8'))
    side_of = station_sides(_station_map())
    for st in doc['stations']:
        a, b = sorted((tuple(st['plus_edge']), tuple(st['minus_edge'])), key=lambda k: side_of[k])
        st['plus_edge'], st['minus_edge'] = (list(a), list(b)) if plus_side == 0 else (list(b), list(a))
    p = tmp_path / ('SYNTHETIC_SIGN_EDGES_%d.json' % plus_side)
    p.write_text(json.dumps(doc), encoding='utf-8')
    return {'observations': {'station_profiles': {'sign_edges': str(p),
                                                  'sign_edges_sha256': hashlib.sha256(p.read_bytes()).hexdigest()}}}


def _merge(*parts):
    from cordon2025.live02_config import merge
    out = {}
    for p in parts:
        out = merge(out, p)
    for p in parts:
        if p.get('_allow_donor_overrides'):
            out['_allow_donor_overrides'] = True
    return out


@pytest.fixture(scope='module')
def release_run(tmp_path_factory):
    """Mock run with the release config (report sign table, E41 targets)."""
    tmp = tmp_path_factory.mktemp('l10')
    v = Live04Visum(tmp / 'model')
    r = run(v, output_root=tmp / 'runs', options=OPT, config_overrides=GEN_ONLY)
    f = next((tmp / 'runs').glob('LIVE04_TGTD_*'))
    return r, f, _edge_volumes_and_contexts(f / '01_BASELINE_CAPTURE' / 'p.sqlite')


def _check_rows(f, vol, smap, side_of, plus_edge_of):
    contract = read_json(f / 'OBSERVATION_CONTRACT.json')
    assert contract['rows']['FIRST_LAST'] == 168
    gen = read_json(f / 'C01_GENERATION' / 'GENERATION_BLOCK_RESULT.json')
    assert gen['objective_before']['metrics']['FIRST_LAST']['pairs'] == 168
    rows = [x for x in csv.DictReader(open(f / '01_BASELINE_CAPTURE' / 'CORDON_PAIR_RESULTS.csv', encoding='utf-8-sig'),
                                      delimiter=';')
            if x['method'] == 'FIRST_LAST' and int(x['destination_station']) in (PROFILE_STATION, PROFILE_STATION_B)]
    assert len(rows) == 32
    parts = {p['station']: p for p in contract['station_profile_parts']}
    edge_of = {(s, side_of[k]): k for k, s in smap.items()}
    for x in rows:
        s, side = int(x['origin_station']), (0 if int(x['destination_station']) == PROFILE_STATION else 1)
        e = edge_of[(s, side)]
        assert float(x['model']) == pytest.approx(vol.get(e, 0.0), abs=1e-6)
        want = parts[s]['target_plus'] if e == plus_edge_of[s] else parts[s]['target_minus']
        assert float(x['observed']) == pytest.approx(want)
    assert sum(vol.values()) > 0


def test_mock_release_run_uses_the_report_sign_table(release_run):
    r, f, (vol, ctx, smap, side_of) = release_run
    assert r['status'].startswith('MOCK_LIVE04'), r
    assert r['observation_semantics'].endswith('_PLUS_STATION_PROFILES_DIRECTIONAL')
    d = r['station_profile_directions']
    assert d['authority'] == 'REPORT_MAPS_SIGN_EDGES' and len(d['stations']) == 16
    doc = json.loads(SIGN_EDGES.read_text(encoding='utf-8'))
    plus = {st['station']: tuple(st['plus_edge']) for st in doc['stations']}
    for x in d['stations']:
        assert tuple(x['plus_edge']) == plus[x['station']]
        assert -1.0 <= x['model_agreement_with_fixed'] <= 1.0      # diagnostic only, never blocks
    _check_rows(f, vol, smap, side_of, plus)


@pytest.mark.parametrize('plus_side', [0, 1])
def test_mock_run_rows_follow_the_sign_table(tmp_path, release_run, plus_side):
    _, _, (vol, ctx, smap, side_of) = release_run
    v = Live04Visum(tmp_path / 'model')
    r = run(v, output_root=tmp_path / 'runs', options=OPT,
            config_overrides=_merge(GEN_ONLY, _synthetic_sign_edges(tmp_path, plus_side)))
    assert r['status'].startswith('MOCK_LIVE04'), r
    assert all(x['plus_side'] == plus_side for x in r['station_profile_directions']['stations'])
    f = next((tmp_path / 'runs').glob('LIVE04_TGTD_*'))
    _check_rows(f, vol, smap, side_of, {s: k for k, s in smap.items() if side_of[k] == plus_side})


def test_sign_edge_outside_the_station_refused(tmp_path):
    doc = json.loads(SIGN_EDGES.read_text(encoding='utf-8'))
    doc['stations'][0]['plus_edge'] = [1, 2, 3]
    p = tmp_path / 'se.json'; p.write_text(json.dumps(doc), encoding='utf-8')
    over = {'sign_edges': str(p), 'sign_edges_sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
    v = Live04Visum(tmp_path / 'model')
    # LIVE04.10.1: refused when the contract is built, before the run touches the model
    with pytest.raises(ContractError, match='LIVE04_PROFILE_SIGN_EDGE_NOT_A_STATION_EDGE:SDP1'):
        run(v, output_root=tmp_path / 'runs', options=OPT,
            config_overrides=_merge(GEN_ONLY, {'observations': {'station_profiles': over}}))
    assert not v.writes if hasattr(v, 'writes') else True


def test_supply_mix_runs_on_168_rows(tmp_path):
    v = Live04Visum(tmp_path / 'model', route_gamma=0.3, addval_beta=0.4, bypass_anchor=True)
    over = _merge(GEN_ONLY, {'v7': {'run_options': {'sp_start_cycle': 1}}, '_allow_donor_overrides': True})
    r = run(v, output_root=tmp_path / 'runs', options=OPT, config_overrides=over)
    f = next((tmp_path / 'runs').glob('LIVE04_TGTD_*'))
    rec = read_json(f / 'C01_SUPPLY_ADDVAL1' / 'SUPPLYMIX_BLOCK_RESULT.json')
    assert 'error' not in rec or not rec['error'], rec
    assert rec['status'] in ('ACCEPTED', 'NO_ACCEPTED_TRIAL', 'NO_CANDIDATE', 'NO_DRIVER_PROFILES'), rec['status']
    if rec['status'] != 'ACCEPTED':
        rb = read_json(f / 'C01_SUPPLY_ADDVAL1' / 'ROLLBACK_SUMMARY.json')
        assert rb['passes'] and rb['snapshot_equal']
    assert r['status'] != 'LIVE04_STOPPED_WITH_ERROR'
    assert read_json(f / 'OBSERVATION_CONTRACT.json')['rows']['FIRST_LAST'] == 168


def test_td_block_runs_on_168_rows(tmp_path):
    v = Live04Visum(tmp_path / 'model')
    r = run(v, output_root=tmp_path / 'runs', options=OPT, config_overrides={'max_cycles': 1, 'blocks_per_cycle': ['TD_CORDON']})
    blocks = [(b['block'], b['status']) for c in r['cycles'] for b in c['blocks']]
    assert blocks and blocks[0][0] == 'TD_CORDON' and 'ERROR' not in blocks[0][1], blocks
    f = next((tmp_path / 'runs').glob('LIVE04_TGTD_*'))
    assert read_json(f / 'OBSERVATION_CONTRACT.json')['rows']['FIRST_LAST'] == 168


def test_sign_table_checked_statically_against_the_station_mapping(tmp_path):
    """LIVE04.10.1: a sign edge that is not one of the two mapped station edges stops already when the
    contract is built (READINESS check OBSERVATION_CONTRACT, calibration start) - no path capture needed."""
    doc = json.loads(SIGN_EDGES.read_text(encoding='utf-8'))
    doc['stations'][7]['plus_edge'] = [1, 2, 3]
    p = tmp_path / 'se.json'; p.write_text(json.dumps(doc), encoding='utf-8')
    over = {'sign_edges': str(p), 'sign_edges_sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
    with pytest.raises(ContractError, match='LIVE04_PROFILE_SIGN_EDGE_NOT_A_STATION_EDGE:SDP8'):
        obs.Contract(load_config(overrides={'observations': {'station_profiles': over}})['observations'])

