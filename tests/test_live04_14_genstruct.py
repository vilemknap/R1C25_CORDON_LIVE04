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
           'parameters': gs.capture_parameters(g),
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
    assert st3.load_memory(state) == (True, 'LOADED') and st3.eta == st.eta
    assert st3.updates_total == st.updates_total and st3.history_digest == st.history_digest
    other = record(c, cent=(0.1, 0.2, 0.3))
    assert gs.Structure(other, c).load_memory(state) == (False, 'OTHER_REFERENCE')


def test_reference_record_is_immutable_and_tied_to_the_parameters(tmp_path):
    c = cfg()
    rec = record(c)
    bad = json.loads(json.dumps(rec)); bad['centrality']['WORK'][0] = 0.0
    with pytest.raises(ContractError, match='RECORD_CHANGED'):
        gs.Structure(bad, c)
    with pytest.raises(ContractError, match='PARAMETERS_CHANGED:neighbour_radius_km'):
        gs.Structure(rec, cfg(neighbour_radius_km=15.0))
    # penalty weights are tuning knobs: a continuation with new weights keeps the reference
    assert gs.Structure(rec, cfg(neighbour_relative=0.7, production_anchor_relative=0.2)).record == rec

    D = np.array([[0.5, 2.0, 3.0], [2.0, 0.5, 4.0], [3.0, 4.0, 0.5]])

    class Mat:
        def __init__(self, arr):
            self.arr = arr

        def GetValues(self):
            return self.arr.tolist()

    class Visum:
        def __init__(self, arr):
            self.Net = type('N', (), {})()
            self.Net.Matrices = type('M', (), {'ItemByKey': lambda _s, no: Mat(arr)})()

    class Adapter:
        def __init__(self, arr=D):
            self.visum = Visum(arr)
            self.zones = list(ZONES)
    import hashlib
    rec = json.loads(json.dumps(rec))
    rec['distance_fingerprint'] = hashlib.sha256(np.ascontiguousarray(D, dtype='<f8').tobytes()).hexdigest()
    del rec['record_sha256']; rec['record_sha256'] = canonical_hash(rec)
    with pytest.raises(ContractError, match='LIVE04_GENSTRUCT_REFERENCE_MISSING_IN_CONTINUATION'):
        gs.establish(Adapter(), c, {}, continuation=True, folder=tmp_path, write_json=lambda p, o: None)
    good = {'generation_structure_reference': rec, 'origin_run_folder': rec['origin_run_folder']}
    with pytest.raises(ContractError, match='LIVE04_GENSTRUCT_REFERENCE_NOT_OF_THE_ORIGIN_RUN'):
        gs.establish(Adapter(), c, dict(good, origin_run_folder='/runs/OTHER'), continuation=True,
                     folder=tmp_path, write_json=lambda p, o: None)
    a = Adapter()
    st = gs.establish(a, c, good, continuation=True, folder=tmp_path, write_json=lambda p, o: None)
    assert a.generation_structure is st and st.record == rec
    # 9697 changed under the carried neighbour structure -> stop (the state hash does not cover it)
    D2 = D.copy(); D2[0, 1] = 2.5
    with pytest.raises(ContractError, match='LIVE04_GENSTRUCT_DISTANCE_MATRIX_CHANGED:9697'):
        gs.establish(Adapter(D2), c, good, continuation=True,
                     folder=tmp_path, write_json=lambda p, o: None)
    bad_zones = Adapter(); bad_zones.zones = [1, 3, 2]
    with pytest.raises(ContractError, match='LIVE04_GENSTRUCT_ZONE_ORDER_CHANGED'):
        gs.establish(bad_zones, c, good, continuation=True,
                     folder=tmp_path, write_json=lambda p, o: None)
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
    # review N12: 0.001 trips from each of 100 zones is not a centre of 100 origins
    M = np.zeros((102, 102)); M[2:, 0] = 0.001; M[2:12, 1] = 500.0
    tiny = gs._effective_origins(M, volume_weighted=True)
    assert tiny[1] > 5.0 and tiny[0] < 0.1 * tiny[1]
    # ties share the average rank: zero-potential zones are not ordered by zone number
    assert list(gs._pct_rank([0.0, 0.0, 0.0, 9.0])) == pytest.approx([1 / 3, 1 / 3, 1 / 3, 1.0])


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


def test_measured_refit_uses_the_effective_operator_once():
    """Review 2026-11-19 (P1): G_raw = 10, eta = 0.5, x = 0.2, measured delta = 1.
    The secant must correct G_raw*eta (prediction 1.0 at the trial), and the solver must not
    multiply the corrected operator by eta again (which would predict 0.5)."""
    zf = parent_module('r1_15a2_zonal_count_fit_v24917')
    c = cfg(neighbour_relative=0.0, production_anchor_relative=0.0, production_family_anchor_relative=0.0)
    st = gs.Structure(record(c, neighbours=[[], [], []]), c)
    st.eta[('WORK', 'PROD')] = 0.5
    keys = [('WORK', 'PROD', 1)]
    p = problem(keys, [[10.0]], [1.0])
    x_trial = np.array([0.2])
    # what live04_generation.refine does
    eta = st.column_factors(keys)
    base = __import__('copy').copy(p); base.G = p.G * eta[None, :]; base.genstruct_operator = 'EFFECTIVE'
    refined, _ = zf.measured_refit_problem(base, x_trial, np.array([1.0]), 0.5)
    refined.genstruct_operator = 'EFFECTIVE'
    assert float((refined.G @ x_trial)[0]) == pytest.approx(1.0)
    sol, audit = gs.solve(refined, FIT, st, zone_rows({}))
    assert audit['operator'] == 'EFFECTIVE_FROM_MEASURED_REFIT'
    assert np.allclose(sol['predicted_change'], refined.G @ sol['x'])       # no second eta
    # the normal design solve does apply eta to the RAW operator
    sol2, audit2 = gs.solve(p, FIT, st, zone_rows({}))
    assert audit2['operator'] == 'RAW_TIMES_ETA'
    assert np.allclose(sol2['predicted_change'], (p.G * 0.5) @ sol2['x'])


def test_penalty_matrix_equals_the_documented_formula():
    """0.5 x'Qx + q'x must equal the explicit penalty sum up to a constant (finite check)."""
    c = cfg(production_anchor_relative=0.7, production_family_anchor_relative=0.3, neighbour_relative=1.1,
            attraction_anchor_min_relative=0.2, attraction_anchor_max_relative=0.9, attraction_centrality_power=2.0)
    rec = record(c, share_w=(0.6, 0.3, 0.0), cent=(0.9, 0.2, 0.5), neighbours=[[[2, 0.7], [3, 0.3]], [[1, 1.0]], []])
    st = gs.Structure(rec, c)
    keys = [(f, r, z) for f in gs.FAMILIES for r in gs.ROLES for z in (1, 2)]
    p = problem(keys, np.zeros((1, len(keys))), [0.0])
    coef = {('WORK', 'PROD'): [2.0, 0.5, 1.0], ('SERVICE', 'PROD'): [1.5, 1.0, 3.0],
            ('WORK', 'ATT'): [4.0, 1.0, 1.0], ('SERVICE', 'ATT'): [1.0, 0.7, 1.0]}
    rows = zone_rows(coef)
    scale = 1.0
    Qs, q, _ = st.penalty(p, rows, scale)
    Q = Qs.dense()
    assert np.allclose(Q, Q.T)
    assert np.allclose(Qs @ np.arange(len(keys), dtype=float), Q @ np.arange(len(keys), dtype=float))
    y0 = {k: np.log(np.asarray(coef[k])) for k in coef}
    g = c['generation_structure']

    def explicit(x):
        xv = dict(zip(keys, x))
        y = {k: y0[k].copy() for k in y0}
        for (f, r, z), v in xv.items():
            y[(f, r)][z - 1] += v
        tot = 0.0
        for i, z in enumerate(ZONES):
            # exact production ratio, linearized at the current state
            r0 = sum(rec['production_share'][f][i] * np.exp(y0[(f, 'PROD')][i]) for f in gs.FAMILIES)
            lin = r0 - 1.0 + sum(rec['production_share'][f][i] * np.exp(y0[(f, 'PROD')][i])
                                 * xv.get((f, 'PROD', z), 0.0) for f in gs.FAMILIES)
            if any((f, 'PROD', z) in xv and rec['production_share'][f][i] > 0 for f in gs.FAMILIES):
                tot += 0.5 * g['production_anchor_relative'] * lin ** 2
            for f in gs.FAMILIES:
                if (f, 'PROD', z) in xv:
                    tot += 0.5 * g['production_family_anchor_relative'] * y[(f, 'PROD')][i] ** 2
                nb = rec['neighbours'][f][i]
                if nb and ((f, 'PROD', z) in xv or any((f, 'PROD', u) in xv for u, _ in nb)):
                    d = y[(f, 'PROD')][i] - sum(w * y[(f, 'PROD')][u - 1] for u, w in nb)
                    tot += 0.5 * g['neighbour_relative'] * d ** 2
                if (f, 'ATT', z) in xv:
                    w = g['attraction_anchor_min_relative'] + (g['attraction_anchor_max_relative']
                                                               - g['attraction_anchor_min_relative']) * (1 - rec['centrality'][f][i]) ** 2
                    tot += 0.5 * w * y[(f, 'ATT')][i] ** 2
        return tot
    rng = np.random.default_rng(5)
    x0 = np.zeros(len(keys))
    for _ in range(5):
        x = rng.normal(scale=0.3, size=len(keys))
        quad = 0.5 * x @ Q @ x + q @ x
        assert quad == pytest.approx(explicit(x) - explicit(x0), rel=1e-9, abs=1e-12)
    # the audited constant makes the full penalty exact and non-negative (review P3)
    assert st.last_penalty_constant == pytest.approx(explicit(x0))
    assert 0.5 * x @ Q @ x + q @ x + st.last_penalty_constant == pytest.approx(explicit(x)) and explicit(x) >= 0


def test_production_anchor_uses_the_real_production_ratio():
    """Review P2: w = (0.5, 0.5), coefficients (3, 1/3): the weighted LOG is 0, but the real
    production is 1.667 x reference - the anchor must pull it down."""
    c = cfg(neighbour_relative=0.0, production_family_anchor_relative=0.0)
    st = gs.Structure(record(c, share_w=(0.5, 0.5, 0.5), neighbours=[[], [], []]), c)
    keys = [('WORK', 'PROD', 1), ('SERVICE', 'PROD', 1)]
    p = problem(keys, [[0.0, 0.0]], [0.0])
    rows = zone_rows({('WORK', 'PROD'): [3.0, 1.0, 1.0], ('SERVICE', 'PROD'): [1 / 3, 1.0, 1.0]})
    Q, q, audit = st.penalty(p, rows, 1.0)
    assert audit['constant'] == pytest.approx(0.5 * 0.05 * (0.5 * 3 + 0.5 / 3 - 1) ** 2)
    x = solve(st, p, rows)
    assert 0.5 * 3 * math.exp(x[0]) + 0.5 / 3 * math.exp(x[1]) < 1.6        # ratio moves towards 1
    assert x[0] < 0                                                          # mostly via the big coefficient


def test_efficiency_memory_numerics_and_loading():
    c = cfg(efficiency_memory=dict(load_config()['generation_structure']['efficiency_memory'], prior_weight=0.0))
    st = gs.Structure(record(c), c)
    keys = [('WORK', 'PROD', 1), ('SERVICE', 'PROD', 1)]
    G = np.array([[1.0, 1.0], [2.0, 2.0]])                 # collinear groups, prior_weight 0
    rec = st.learn(G, keys, np.array([0.1, 0.1]), np.array([0.1, 0.2]), np.ones(2))
    assert rec['status'] == 'UPDATED' and all(np.isfinite(list(st.eta.values())))
    good = {'schema': gs.MEMORY_SCHEMA, 'reference_sha256': st.record['record_sha256'],
            'eta': {'%s|%s' % k: 1.0 for k in gs.GROUPS}, 'updates': 3, 'history_digest': 'h'}
    for bad, reason in ((dict(good, eta=dict(good['eta'], **{'WORK|PROD': float('nan')})), 'NONFINITE'),
                        (dict(good, eta={'WORK|PROD': 1.0}), 'GROUPS'),
                        (dict(good, eta=dict(good['eta'], **{'WORK|PROD': 'x'})), 'NOT_NUMERIC'),
                        (dict(good, schema='X'), 'SCHEMA')):
        assert gs.Structure(record(c), c).load_memory(bad) == (False, reason)
    st2 = gs.Structure(record(c), c)
    ok, reason = st2.load_memory(dict(good, eta=dict(good['eta'], **{'WORK|PROD': 9.0, 'WORK|ATT': 0.01})))
    hi, lo = c['generation_structure']['efficiency_memory']['eta_max'], c['generation_structure']['efficiency_memory']['eta_min']
    assert ok and reason.startswith('CLIPPED_TO_CURRENT_BOUNDS') and st2.eta[('WORK', 'PROD')] == hi \
        and st2.eta[('WORK', 'ATT')] == lo and st2.updates_total == 3


def test_zone_inputs_fail_closed_and_only_missing_attributes_fall_back():
    class Zones:
        def __init__(self, data, errors):
            self.data, self.errors = data, errors

        def GetMultiAttValues(self, attr, active):
            assert active is False
            if attr in self.errors:
                raise self.errors[attr]
            return [(i + 1, v) for i, v in enumerate(self.data[attr])]

    def visum(data, errors=None):
        v = type('V', (), {})(); v.Net = type('N', (), {})(); v.Net.Zones = Zones(data, errors or {})
        return v
    missing = RuntimeError('ZONE: Could not find attribute with ID NUM_PM.')
    assert gs._first_readable(visum({'B': [1.0, 2.0]}, {'A': missing}), ['A', 'B'], 2)[0] == 'B'
    busy = RuntimeError('(-2147418111, Call was rejected by callee.)')
    with pytest.raises(RuntimeError, match='rejected'):
        gs._first_readable(visum({'B': [1.0, 2.0]}, {'A': busy}), ['A', 'B'], 2)
    with pytest.raises(ContractError, match='LIVE04_GENSTRUCT_ZONE_VALUES_INVALID:A'):
        gs._first_readable(visum({'A': [1.0, float('nan')], 'B': [1.0, 2.0]}), ['A', 'B'], 2)
    with pytest.raises(ContractError, match='LIVE04_GENSTRUCT_ZONE_VALUES_INVALID:P'):
        gs._zone_values(visum({'P': [1.0, -5.0]}), 'P', 2)


def test_learning_is_transactional_and_removes_the_route_correction(monkeypatch, tmp_path):
    from cordon2025 import live04_generation as gen
    c = cfg()
    st = gs.Structure(record(c), c)
    keys = [('WORK', 'PROD', 1)]
    G = np.array([[1.0], [2.0]])

    class Ev:
        method = 'M'
    adapter = type('A', (), {})()
    adapter.generation_structure, adapter.evaluator, adapter.generation_structure_folder = st, Ev(), tmp_path
    context = {'_genfix2_effect_model': {'problems': {'M': {'G_raw': G, 'var_keys': keys, 'order': [0, 1]}},
                                         'bd': None}}
    before = {'valid': True}; after = {'valid': True}
    monkeypatch.setattr(gen, 'implemented_vector', lambda var_keys, preview, scale, bd: np.array([0.1]))
    monkeypatch.setattr(gen.fit_objective, 'measured_vectors', lambda b, a, m: (np.zeros(2), np.array([0.1, 0.2])))
    monkeypatch.setattr(gen.fit_objective, 'captured_terms', lambda b, m: {'w': np.ones(2)})
    seen = {}
    real_learn = st.learn

    def spy(G_, k, x, d, w):
        seen['d'] = np.array(d)
        return real_learn(G_, k, x, d, w)
    monkeypatch.setattr(st, 'learn', spy)
    gen.learn_efficiency(adapter, context, 1.0, {}, before, after, tmp_path, route_correction=np.array([0.05, 0.1]))
    assert np.allclose(seen['d'], [0.05, 0.1])               # measured minus the route-memory part
    eta_ok = dict(st.eta)
    # a failed persist restores the in-memory factors
    import cordon2025.io as cio
    monkeypatch.setattr(cio, 'write_json', lambda p, o: (_ for _ in ()).throw(OSError('DISK_FULL')))
    with pytest.raises(OSError, match='DISK_FULL'):
        gen.learn_efficiency(adapter, context, 1.0, {}, before, after, tmp_path)
    assert st.eta == eta_ok
    # never from an invalid capture
    with pytest.raises(ContractError, match='LIVE04_GENSTRUCT_LEARN_INVALID_CAPTURE'):
        gen.learn_efficiency(adapter, context, 1.0, {}, before, {'valid': False}, tmp_path)


def test_memory_snapshots_bind_memories_to_the_accepted_state(tmp_path):
    from cordon2025 import live04_memory_snapshots as ms
    c = cfg()
    st = gs.Structure(record(c), c)
    adapter = type('A', (), {})()
    adapter.generation_structure = st
    adapter.idp_generation_model = None; adapter.idp_run_reference = None; adapter.run_memory = None
    run1 = tmp_path / 'R1'; run1.mkdir()
    assert ms.record(adapter, run1, 'S0', 'RUN_START')
    st.eta[('WORK', 'PROD')] = 0.7
    assert ms.record(adapter, run1, 'S1', 'C01_GENERATION')         # checkpoint state C01
    st.eta[('WORK', 'PROD')] = 0.4                                   # learned later (C03)
    assert ms.record(adapter, run1, 'S3', 'C03_GENERATION')
    assert not ms.record(adapter, run1, 'S1', 'LATER')                # first write wins
    fresh = gs.Structure(record(c), c)
    adapter2 = type('A', (), {})()
    adapter2.generation_structure = fresh
    adapter2.idp_generation_model = None; adapter2.idp_run_reference = None; adapter2.run_memory = None
    out = ms.restore(adapter2, run1, 'S1')
    assert out['status'] == 'SNAPSHOT_OF_OPENED_STATE' and fresh.eta[('WORK', 'PROD')] == 0.7   # not 0.4
    assert ms.restore(adapter2, run1, 'UNKNOWN')['status'] == 'NO_SNAPSHOT_FOR_OPENED_STATE_FRESH_MEMORIES'


def test_penalty_is_sparse_and_scales_linearly():
    """Review: the penalty must not be a dense nv x nv matrix (681 zones x 4 groups)."""
    import time
    zones = list(range(1, 682))
    c = cfg()
    g = c['generation_structure']
    nb = [[[zones[(i + k) % 681], 1.0 / 12] for k in range(1, 13)] for i in range(681)]
    rec = {'schema': gs.SCHEMA, 'zones': zones, 'population': [1000.0] * 681,
           'production_share': {'WORK': [0.4] * 681, 'SERVICE': [0.6] * 681},
           'centrality': {'WORK': list(np.linspace(0, 1, 681)), 'SERVICE': list(np.linspace(0, 1, 681))},
           'neighbours': {'WORK': nb, 'SERVICE': nb}, 'anchor_target': 'UNIT',
           'target_coefficients': {'%s|%s' % k: [1.0] * 681 for k in gs.GROUPS},
           'run_start_coefficients': {'%s|%s' % k: [1.0] * 681 for k in gs.GROUPS},
           'potential_attributes': {}, 'fp_attributes': {}, 'distance_matrix': 9697, 'distance_fingerprint': 'x',
           'od_matrices': {}, 'parameters': gs.capture_parameters(g), 'origin_run_folder': '/r'}
    rec['record_sha256'] = canonical_hash(rec)
    st = gs.Structure(rec, c)
    keys = [(f, r, z) for f in gs.FAMILIES for r in gs.ROLES for z in zones]
    zf = parent_module('r1_15a2_zonal_count_fit_v24917')
    p = zf.FitProblem(zones, [], np.zeros((0, len(keys))), np.zeros(0), np.zeros(0), keys, np.zeros(len(keys)),
                      -np.ones(len(keys)), np.ones(len(keys)), {})
    rows = [{'zone_no': z, **{a: 1.5 for a in gs.COEF.values()}} for z in zones]
    t = time.time()
    Q, q, audit = st.penalty(p, rows, 1.0)
    built = time.time() - t
    assert isinstance(Q, gs.SparseSym) and Q.nnz < 60 * len(keys)       # linear, not 2724^2
    x = np.random.default_rng(1).normal(size=len(keys))
    t = time.time()
    for _ in range(200):
        Q @ x
    assert (time.time() - t) / 200 < 0.01 and built < 30.0


def test_memory_snapshot_is_bound_to_its_declared_state(tmp_path):
    from cordon2025 import live04_memory_snapshots as ms
    c = cfg()
    st = gs.Structure(record(c), c)
    adapter = type('A', (), {})()
    adapter.generation_structure = st; adapter.idp_generation_model = None; adapter.idp_run_reference = None
    adapter.run_memory = None
    st.eta[('WORK', 'PROD')] = 0.7
    ms.record(adapter, tmp_path, 'S1', 'C01')
    data = json.loads((tmp_path / ms.FILE).read_text())
    data['snapshots']['S9'] = data['snapshots'].pop('S1')          # move a valid record to another key
    (tmp_path / ms.FILE).write_text(json.dumps(data))
    fresh = gs.Structure(record(c), c)
    a2 = type('A', (), {})()
    a2.generation_structure = fresh; a2.idp_generation_model = None; a2.idp_run_reference = None
    a2.run_memory = None
    with pytest.raises(ContractError, match='LIVE04_MEMORY_SNAPSHOT_DECLARES_ANOTHER_STATE'):
        ms.restore(a2, tmp_path, 'S9')
    assert fresh.eta[('WORK', 'PROD')] == 1.0
    # review N5: an existing but corrupted file is never mistaken for a missing one
    (tmp_path / ms.FILE).write_text('{"schema": "X"}')
    with pytest.raises(ContractError, match='LIVE04_MEMORY_SNAPSHOT_FILE_CORRUPTED'):
        ms.restore(a2, tmp_path, 'S9')
    (tmp_path / ms.FILE).write_text('{broken')
    with pytest.raises(ContractError, match='LIVE04_MEMORY_SNAPSHOT_FILE_CORRUPTED'):
        ms.restore(a2, tmp_path, 'S9')
    (tmp_path / ms.FILE).unlink()                                   # explicit: fresh memories
    assert ms.restore(a2, tmp_path, 'S9')['status'] == 'NO_SNAPSHOT_FOR_OPENED_STATE_FRESH_MEMORIES'



def test_reference_requires_a_unit_base():
    zones = [1, 2, 3]
    unit = {k: np.ones(3) for k in gs.GROUPS}
    dom = np.array([True, True, False])
    ok = gs.unit_start_check(zones, unit, [1, 2, 3], dom, 'REQUIRE_UNIT_WS_ON_ACTUATABLE_DOMESTIC_ZONES')
    assert ok['status'] == 'PROVEN_UNIT_BASE' and ok['checked_zones'] == 2
    off = dict(unit); off[('WORK', 'ATT')] = np.array([1.0, 5.29, 7.0])   # zone 3 is foreign: exempt
    with pytest.raises(ContractError, match=r'NOT_A_UNIT_BASE:WORK\|ATT=1 zones \(e.g. \[2\]\)'):
        gs.unit_start_check(zones, off, [1, 2, 3], dom, 'REQUIRE_UNIT_WS_ON_ACTUATABLE_DOMESTIC_ZONES')
    acc = gs.unit_start_check(zones, off, [1, 2, 3], dom, 'ACCEPT_CURRENT_MODEL')
    assert acc['status'] == 'NOT_UNIT_BASE' and acc['non_unit']['WORK|ATT']['zones'] == 1


def test_run_memory_state_round_trip():
    from cordon2025.live04_memory import RunMemory
    cfgm = load_config()['memory']
    m = RunMemory(cfgm)
    m.begin_cycle(3)
    m.store_td(['b', 'c'], {'M': np.array([[1.0, 2.0], [3.0, 4.0]])}, 'NATIVE', idp=np.ones((4, 2)))
    m.record_tg_correction({'WORK|PROD|1': 0.1}, 0.5, {'M': np.array([1.0, 2.0])}, {'M': np.array([0.5, 1.0])})
    st = json.loads(json.dumps(m.state()))
    m2 = RunMemory(cfgm)
    assert m2.load_state(st) == (True, 'LOADED')
    m2.begin_cycle(4)
    assert np.allclose(m2.td_jacobian(['b', 'c'], {'M': 2})['M'], [[1.0, 2.0], [3.0, 4.0]])
    assert m2.tg['scale'] == 0.5 and np.allclose(m2.tg['correction']['M'], [1.0, 2.0])
    bad = json.loads(json.dumps(st)); bad['td']['J']['M'][0][0] = float('nan')
    assert RunMemory(cfgm).load_state(json.loads(json.dumps(bad, allow_nan=True))) == (False, 'TD_NONFINITE')


def test_neighbour_link_kept_when_only_the_neighbour_is_a_variable():
    """Review cc3c3c4 (P1): zone A is fixed at 1, its neighbour B (coefficient 2) is a variable.
    A's neighbourhood term must exist and pull B towards A; dropping it lost the link."""
    c = cfg(production_anchor_relative=0.0, production_family_anchor_relative=0.0, neighbour_relative=1.0)
    st = gs.Structure(record(c, neighbours=[[[2, 1.0]], [], []]), c)          # only A lists B
    keys = [('WORK', 'PROD', 2)]                                              # A (zone 1) is fixed
    p = problem(keys, [[0.0]], [0.0])
    rows = zone_rows({('WORK', 'PROD'): [1.0, 2.0, 1.0]})
    Q, q, audit = st.penalty(p, rows, 1.0)
    assert Q.nnz == 1 and q[0] > 0                    # 0.5 (y_A - y_B)^2 with y_A = 0, y_B = log 2
    assert audit['constant'] == pytest.approx(0.5 * math.log(2.0) ** 2)
    x = solve(st, p, rows)
    assert x[0] < -0.1                                 # B moves towards A
