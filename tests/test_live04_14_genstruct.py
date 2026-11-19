"""LIVE04.14 GENSTRUCT1: production anchors, neighbourhood, attraction centrality, efficiency memory.

Synthetic data only - not native PTV Visum evidence."""
import copy
import json
import math
from pathlib import Path
import numpy as np
import pytest
from cordon2025.common import ROOT, read_json, ContractError, canonical_hash, parent_module
from cordon2025.live04_config import load_config
from cordon2025 import live04_generation_structure as gs

ZONES = [1, 2, 3]


def cfg(**over):
    c = copy.deepcopy(load_config())
    c['generation_structure'].update(over)
    return c


def record(c, *, share_w=(0.5, 0.5, 0.5), cent=(0.9, 0.1, 0.5), neighbours=None, target=1.0):
    g = c['generation_structure']
    nb = neighbours if neighbours is not None else [[[2, 1.0]], [[1, 1.0]], []]
    rec = {'schema': gs.SCHEMA, 'zones': ZONES, 'population': [1000.0, 1000.0, 0.0],
           'production_share': {'WORK': list(share_w), 'SERVICE': [1 - x for x in share_w]},
           'centrality': {'WORK': list(cent), 'SERVICE': list(cent)},
           'neighbours': {'WORK': nb, 'SERVICE': nb}, 'anchor_target': 'UNIT',
           'target_coefficients': {'%s|%s' % k: [target] * 3 for k in gs.GROUPS},
           'run_start_coefficients': {'%s|%s' % k: [1.0] * 3 for k in gs.GROUPS},
           'potential_attributes': {'WORK': 'NUM_PM', 'SERVICE': 'FA_2_SERVICE'},
           'fp_attributes': {}, 'distance_matrix': 9697, 'distance_fingerprint': 'x', 'od_matrices': {},
           'parameters': {k: copy.deepcopy(v) for k, v in g.items() if k not in ('note', 'efficiency_memory')},
           'origin_run_folder': '/runs/R'}
    rec['record_sha256'] = canonical_hash(rec)
    return rec


def zone_rows(coef):
    """coef: {(family, role): [z1, z2, z3]}"""
    rows = []
    for i, z in enumerate(ZONES):
        r = {'zone_no': z}
        for k, attr in gs.COEF.items():
            r[attr] = coef.get(k, [1.0] * 3)[i]
        rows.append(r)
    return rows


def problem(var_keys, G, target, lo=-0.5, hi=0.5):
    zf = parent_module('r1_15a2_zonal_count_fit_v24917')
    G = np.asarray(G, dtype=float)
    n = G.shape[0]
    return zf.FitProblem(ZONES, [{'countlocation_no': i} for i in range(n)], G, np.asarray(target, dtype=float),
                         np.ones(n), list(var_keys), np.zeros(len(var_keys)), np.full(len(var_keys), lo),
                         np.full(len(var_keys), hi), {})


FIT = {'ridge_relative': 0.01, 'max_iter': 20000, 'tolerance': 1e-13, 'nonlinear_pa_repair': False}


def solve(st, p, rows):
    return gs.solve(p, FIT, st, rows)[0]['x']


def test_release_config_and_validation():
    g = load_config()['generation_structure']
    assert g['enabled'] is True and g['anchor_target'] == 'UNIT' and g['neighbour_distance_matrix'] == 9697
    assert g['efficiency_memory']['enabled'] is True
    dflt = read_json(ROOT / 'provenance/live04_user_config/CORDON_LIVE04_CONFIG.RELEASE_DEFAULT.json')
    assert dflt['generation_structure'] == g
    for over, code in (({'anchor_target': 'X'}, 'ANCHOR_TARGET'), ({'neighbour_max': 0}, 'NEIGHBOUR_MAX'),
                       ({'attraction_anchor_min_relative': 1.0, 'attraction_anchor_max_relative': 0.5}, 'ATT_ORDER'),
                       ({'extra': 1}, 'FIELDS')):
        with pytest.raises(ContractError, match='LIVE04_GENSTRUCT_' + code):
            load_config(overrides={'generation_structure': over})
    with pytest.raises(ContractError, match='LIVE04_GENSTRUCT_MEMORY_ETA'):
        load_config(overrides={'generation_structure': {'efficiency_memory': {'eta_min': 2.0}}})


def test_disabled_is_the_donor_solve():
    c = cfg(enabled=False)
    st = gs.Structure(record(c), c)
    keys = [('WORK', 'PROD', 1), ('WORK', 'PROD', 2)]
    p = problem(keys, [[1.0, 0.2], [0.1, 1.0]], [0.3, 0.1])
    zf = parent_module('r1_15a2_zonal_count_fit_v24917')
    sol, audit = gs.solve(p, FIT, st, zone_rows({}))
    assert audit['status'] == 'DONOR_SOLVE'
    assert np.allclose(sol['x'], zf.solve(p, FIT)['x'])


def test_production_anchor_pulls_an_inflated_zone_back():
    """Zone 1 is at P_W = P_S = 3 (log 1.1) and nothing in the data asks for it."""
    c = cfg(neighbour_relative=0.0)
    st = gs.Structure(record(c), c)
    keys = [('WORK', 'PROD', 1), ('SERVICE', 'PROD', 1), ('WORK', 'PROD', 2)]
    p = problem(keys, [[0.0, 0.0, 1.0]], [0.0])            # data only sees zone 2
    rows = zone_rows({('WORK', 'PROD'): [3.0, 1.0, 1.0], ('SERVICE', 'PROD'): [3.0, 1.0, 1.0]})
    x = solve(st, p, rows)
    assert x[0] < -0.05 and x[1] < -0.05 and abs(x[2]) < 1e-6
    # the same data with the donor solve leaves the inflated zone where it is
    zf = parent_module('r1_15a2_zonal_count_fit_v24917')
    assert np.allclose(zf.solve(p, FIT)['x'][:2], 0.0, atol=1e-9)


def test_anchor_makes_further_growth_of_an_inflated_zone_expensive():
    """Same profile deficit, two candidate zones: the one already at 3x gets the smaller step."""
    c = cfg(neighbour_relative=0.0)
    st = gs.Structure(record(c, neighbours=[[], [], []]), c)
    keys = [('WORK', 'PROD', 1), ('WORK', 'PROD', 2)]
    p = problem(keys, [[1.0, 1.0]], [0.4])
    rows = zone_rows({('WORK', 'PROD'): [3.0, 1.0, 1.0]})
    x = solve(st, p, rows)
    assert x[1] > x[0] + 0.05


def test_neighbourhood_spreads_a_local_deficit():
    keys = [('WORK', 'PROD', 1), ('WORK', 'PROD', 2)]
    p = problem(keys, [[1.0, 0.0]], [0.4])                  # only zone 1 crosses the profile
    rows = zone_rows({})
    c0 = cfg(neighbour_relative=0.0)
    x0 = solve(gs.Structure(record(c0), c0), p, rows)
    c1 = cfg(neighbour_relative=2.0)
    x1 = solve(gs.Structure(record(c1), c1), p, rows)
    assert abs(x0[1]) < 1e-6 and x1[1] > 0.05             # the neighbour follows
    assert abs(x1[0] - x1[1]) < abs(x0[0] - x0[1])


def test_attraction_moves_in_central_zones_not_satellites():
    c = cfg(neighbour_relative=0.0, attraction_anchor_min_relative=0.0, attraction_anchor_max_relative=5.0)
    st = gs.Structure(record(c, cent=(0.95, 0.05, 0.5)), c)
    keys = [('WORK', 'ATT', 1), ('WORK', 'ATT', 2)]
    p = problem(keys, [[1.0, 1.0]], [0.4])                 # both could serve the profile
    x = solve(st, p, zone_rows({}))
    assert x[0] > 0.2 and x[1] < 0.05 * x[0]


def test_efficiency_memory_low_dimensional_secant():
    c = cfg()
    st = gs.Structure(record(c), c)
    rng = np.random.default_rng(3)
    keys = [('WORK', 'PROD', 1), ('WORK', 'ATT', 2), ('SERVICE', 'PROD', 1), ('SERVICE', 'ATT', 3)]
    G = rng.random((40, 4))
    x = np.array([0.2, 0.1, 0.15, 0.05])
    true = np.array([0.5, 1.0, 0.8, 1.0])
    d = (G * true[None, :]) @ x
    for _ in range(30):                                   # damped: prior weight + smoothing 0.3
        rec = st.learn(G, keys, x, d, np.ones(40))
    assert rec['status'] == 'UPDATED' and rec['weighted_error_after'] < rec['weighted_error_before'] + 1e-12
    assert st.eta[('WORK', 'PROD')] == pytest.approx(0.5, abs=0.05)
    assert st.eta[('SERVICE', 'PROD')] == pytest.approx(0.8, abs=0.05)
    # factors are clipped and never per zone
    assert set(st.eta) == set(gs.GROUPS)
    assert np.allclose(st.column_factors(keys), [st.eta[(k[0], k[1])] for k in keys])
    st2 = gs.Structure(record(c), c)
    st2.learn(G, keys, x, -d, np.ones(40))                 # opposite response -> clipped at eta_min
    assert min(st2.eta.values()) >= c['generation_structure']['efficiency_memory']['eta_min'] - 1e-12
    # the solver uses the corrected operator
    p = problem(keys, G[:1], [0.1])
    _, audit = gs.solve(p, FIT, st, zone_rows({}))
    assert audit['eta']['WORK|PROD'] == pytest.approx(st.eta[('WORK', 'PROD')])
    # persisted state is reloaded only for the same reference
    state = json.loads(json.dumps(st.memory_state()))
    st3 = gs.Structure(record(c), c)
    assert st3.load_memory(state) and st3.eta == st.eta
    other = record(c, cent=(0.1, 0.2, 0.3))
    assert not gs.Structure(other, c).load_memory(state)


def test_reference_record_is_immutable_and_tied_to_the_parameters(tmp_path):
    c = cfg()
    rec = record(c)
    bad = json.loads(json.dumps(rec)); bad['centrality']['WORK'][0] = 0.0
    with pytest.raises(ContractError, match='RECORD_CHANGED'):
        gs.Structure(bad, c)
    with pytest.raises(ContractError, match='PARAMETERS_CHANGED'):
        gs.Structure(rec, cfg(neighbour_relative=0.7))

    class Adapter:
        pass
    with pytest.raises(ContractError, match='LIVE04_GENSTRUCT_REFERENCE_MISSING_IN_CONTINUATION'):
        gs.establish(Adapter(), c, {}, continuation=True, folder=tmp_path, write_json=lambda p, o: None)
    a = Adapter()
    st = gs.establish(a, c, {'generation_structure_reference': rec}, continuation=True, folder=tmp_path,
                      write_json=lambda p, o: None)
    assert a.generation_structure is st and st.record == rec
    a2 = Adapter()
    assert gs.establish(a2, cfg(enabled=False), {}, continuation=False, folder=tmp_path,
                        write_json=lambda p, o: None) is None and a2.generation_structure is None


def test_effective_inbound_origins_and_rank():
    M = np.zeros((4, 4))
    M[1:, 0] = 1.0           # zone 0 attracts equally from 3 origins
    M[1, 2] = 5.0            # zone 2 from one origin
    e = gs._effective_origins(M)
    assert e[0] == pytest.approx(3.0) and e[2] == pytest.approx(1.0) and e[1] == 0.0
    assert list(gs._pct_rank([5.0, 1.0, 3.0])) == [1.0, 0.0, 0.5]


# ----------------------------------------------------------------- mock run
def test_mock_run_captures_structure_and_learns(tmp_path):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from fake_live04 import Live04Visum
    from cordon2025.live04_cycle import run
    from cordon2025 import live04_continue as cont
    opt = {'min_free_disk_gib': 0, 'com_retry_initial_delay_seconds': 0., 'com_retry_max_delay_seconds': 0.}
    over = {'blocks_per_cycle': ['GENERATION'], 'td_cordon': {'enabled': False},
            'write_policy': {'td_parameter_writes': False}, 'max_cycles': 1}
    v = Live04Visum(tmp_path / 'model')
    r = run(v, output_root=tmp_path / 'runs', options=opt, config_overrides=over)
    f = next((tmp_path / 'runs').glob('LIVE04_TGTD_*'))
    ref = read_json(f / 'GENSTRUCT1_REFERENCE.json')
    assert ref['source'] == 'MEASURED_AT_RUN_START' and ref['zones'] == len(v.Net.Zones.rows)
    anchors = read_json(f / cont.ANCHORS_FILE)
    assert anchors['generation_structure_reference']['record_sha256'] == ref['record_sha256']
    fit = read_json(f / 'C01_GENERATION/DESIGN/V7_TARGETED_GENERATION/V24917_FIT_SUMMARY.json')
    assert fit['fit_summary']['genstruct1']['status'] == 'GENSTRUCT1_SOLVE'
    gen = read_json(f / 'C01_GENERATION/GENERATION_BLOCK_RESULT.json')
    measured = [a for a in gen['attempts'] if a.get('decision')]
    assert measured and all(a['genstruct1_efficiency']['status'] in ('UPDATED', 'NO_PREDICTED_EFFECT') for a in measured)
    assert read_json(f / 'GENSTRUCT1_EFFICIENCY.json')['schema'] == gs.MEMORY_SCHEMA
    assert r['status'].startswith('MOCK_LIVE04_')
