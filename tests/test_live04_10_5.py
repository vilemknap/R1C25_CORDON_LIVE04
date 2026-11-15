"""LIVE04.10.5: IDP-aware TD_CORDON step.

The inner Gauss-Newton step of TD_CORDON is solved under a linear model of the
IDP guard (mean distance error + fine-CDF RMSE per component, Jacobian from the
same native probes).  The native IDP guard still decides every step and the trial.
Synthetic mock only - not native PTV Visum evidence."""
import math
from types import SimpleNamespace
import numpy as np
import pytest
from fake_live04 import Live04Visum
from cordon2025.common import ROOT, read_json, ContractError
from cordon2025.live03_td import box_least_squares, constrained_least_squares, IdpStepModel
from cordon2025.live04_config import load_config
from cordon2025.live04_cycle import run
from cordon2025.live04_memory import RunMemory
from cordon2025 import live03_idp

OPT = {'min_free_disk_gib': 0, 'com_retry_initial_delay_seconds': 0., 'com_retry_max_delay_seconds': 0.}
# LIVE04.11 changed the release default to COMPONENT + blended objective; this module tests the
# LIVE04.10.5 IDP-aware step on the FAMILY parameter space, cordon-only inner objective.
TD_ONLY = {'max_cycles': 1, 'blocks_per_cycle': ['TD_CORDON'],
           'td_cordon': {'grouping': 'FAMILY', 'idp_objective_weight': 0.0}}


def go(tmp_path, v, overrides=None):
    over = dict(TD_ONLY); over.update(overrides or {})
    return run(v, output_root=tmp_path / 'runs', options=OPT, config_overrides=over)


def folder_of(tmp_path):
    folders = list((tmp_path / 'runs').glob('LIVE04_TGTD_*')); assert len(folders) == 1
    return folders[0]


# ------------------------------------------------------------------ solver
def _problem(seed, n=6, rows=40):
    rnd = np.random.default_rng(seed)
    A = rnd.normal(size=(rows, n)) * rnd.uniform(1, 1e3, size=n)[None, :]
    r = rnd.normal(size=rows) * 1e3
    scale = np.array([0.25, 0.223] * (n // 2))
    return A, r, -scale, scale, scale


def _obj(A, r, x, scale, damping):
    As = A * scale[None, :]; H = As.T @ As
    lam = damping * max(float(np.mean(np.diag(H))), 1e-300)
    z = x / scale
    return 0.5 * float(np.sum((A @ x + r) ** 2)) + 0.5 * lam * float(z @ z)


@pytest.mark.parametrize('seed', range(5))
def test_solver_equals_box_solver_when_constraints_are_slack(seed):
    A, r, lo, hi, scale = _problem(seed)
    xb = box_least_squares(A, r, lo, hi, scale, 1e-3)
    C = np.eye(6)[:2]; d = np.array([1e6, 1e6])
    xc = constrained_least_squares(A, r, lo, hi, scale, 1e-3, C, d)
    assert np.allclose(xc, xb, atol=2e-4)


@pytest.mark.parametrize('seed', range(5))
def test_solver_respects_linear_constraints_and_beats_scaled_box_step(seed):
    A, r, lo, hi, scale = _problem(seed)
    rnd = np.random.default_rng(100 + seed)
    xb = box_least_squares(A, r, lo, hi, scale, 1e-3)
    C = rnd.normal(size=(8, 6)); d = np.abs(rnd.normal(size=8)) * 0.02
    xc = constrained_least_squares(A, r, lo, hi, scale, 1e-3, C, d)
    assert np.all(C @ xc <= d + 1e-12) and np.all(xc >= lo - 1e-12) and np.all(xc <= hi + 1e-12)
    # the naive alternative (shrink the unconstrained step until feasible) is never better
    cx = C @ xb; over = cx > d
    t = min(1.0, float(np.min(d[over] / cx[over]))) if np.any(over) else 1.0
    assert _obj(A, r, xc, scale, 1e-3) <= _obj(A, r, t * xb, scale, 1e-3) * (1 + 1e-6)


def test_solver_returns_zero_when_no_feasible_direction_improves():
    A, r, lo, hi, scale = _problem(7)
    C = np.vstack([np.eye(6), -np.eye(6)]); d = np.zeros(12)
    assert np.allclose(constrained_least_squares(A, r, lo, hi, scale, 1e-3, C, d), 0.0)


# ------------------------------------------------------------- IDP model
def _guard(keys=('A', 'B')):
    return SimpleNamespace(guarded=list(keys), mean_floor=0.03, mean_tol=0.02, rmse_tol=0.01)


def _idp(mean, rmse):
    return {k: {'mean_relative_error': mean[k], 'fine_cdf_rmse': rmse[k]} for k in mean}


def test_idp_constraints_reproduce_the_guard_rule_for_a_linear_response():
    """slack_use=1: linear-model feasibility == IdpGuard.decide on the exact linear response."""
    g = _guard()
    before = _idp({'A': -0.035, 'B': 0.37}, {'A': 0.058, 'B': 0.05})
    F = np.array([[-1.5, 0.2], [0.3, -2.0], [0.05, 0.01], [0.0, -0.1]])
    m = IdpStepModel(g, before, F, 1.0)
    C, d = m.constraints(before)
    real = live03_idp.IdpGuard.__new__(live03_idp.IdpGuard)
    real.guarded = g.guarded; real.mean_floor = g.mean_floor; real.mean_tol = g.mean_tol; real.rmse_tol = g.rmse_tol
    rnd = np.random.default_rng(3)
    agree = 0
    for _ in range(400):
        s = rnd.uniform(-0.3, 0.3, size=2)
        after = m.predict(before, s)
        feasible = bool(np.all(C @ s <= d + 1e-12))
        assert feasible == real.decide(before, after)['passes']
        agree += feasible
    assert 20 < agree < 380          # both outcomes exercised


def test_idp_model_from_probes_and_broyden_update():
    g = _guard(('A',))
    before = _idp({'A': 0.0}, {'A': 0.1})
    probes = [(0, 0.05, _idp({'A': -0.01}, {'A': 0.1})), (1, 0.1, _idp({'A': 0.02}, {'A': 0.11}))]
    m = IdpStepModel.from_probes(g, before, probes, 2, 0.7)
    assert np.allclose(m.F, [[-0.2, 0.2], [0.0, 0.1]])
    s = np.array([0.1, 0.0])
    assert m.update(before, _idp({'A': -0.05}, {'A': 0.1}), s)
    assert np.allclose(m.F @ s, [-0.05, 0.0])                          # secant condition
    assert IdpStepModel.from_probes(g, before, probes[:1] + [(1, 0.1, {'error': 'X'})], 2, 0.7) is None
    assert not m.update(before, {'error': 'X'}, s)


def test_slack_use_keeps_a_margin():
    g = _guard(('A',))
    before = _idp({'A': 0.0}, {'A': 0.1})
    m = IdpStepModel(g, before, np.array([[1.0], [0.0]]), 0.5)
    C, d = m.constraints(before)
    assert d.tolist() == pytest.approx([0.025, 0.025, 0.005])         # half of 0.05 / 0.05 / 0.01


# -------------------------------------------------------- memory + config
def test_memory_keeps_the_idp_jacobian_with_the_td_jacobian(tmp_path):
    cfg = read_json(ROOT / 'CORDON_LIVE04_CONFIG.json')['memory']
    mem = RunMemory(cfg, tmp_path); mem.begin_cycle(1)
    F = np.arange(8.0).reshape(4, 2)
    mem.store_td(['a', 'b'], {'M': np.ones((3, 2))}, 'TEST', idp=F)
    mem.begin_cycle(2)
    assert np.array_equal(mem.td_idp_jacobian(['a', 'b'], 2), F)
    assert mem.td_idp_jacobian(['a', 'b'], 3) is None and mem.td_idp_jacobian(['a', 'c'], 2) is None
    mem.save()
    assert 'IDP_GUARD_FEATURES' in np.load(tmp_path / 'RUN_MEMORY_TD_J.npz')
    assert read_json(tmp_path / 'RUN_MEMORY.json')['td']['idp_jacobian'] is True
    mem.store_td(['a', 'b'], {'M': np.ones((3, 2))}, 'TEST')
    assert mem.td_idp_jacobian(['a', 'b'], 2) is None


def test_release_config_enables_the_idp_aware_step():
    cfg = load_config()
    td = cfg['td_cordon']
    assert td['idp_constrained_step'] is True and td['idp_constraint_slack_use'] == 0.7
    assert read_json(ROOT / 'provenance/live04_user_config/CORDON_LIVE04_CONFIG.RELEASE_DEFAULT.json')['td_cordon'] == td


@pytest.mark.parametrize('bad,code', [({'idp_constrained_step': 'yes'}, 'LIVE04_TD_IDP_CONSTRAINED_STEP'),
                                      ({'idp_constraint_slack_use': 0.0}, 'idp_constraint_slack_use'),
                                      ({'idp_constraint_slack_use': 1.5}, 'idp_constraint_slack_use')])
def test_config_validation(bad, code):
    with pytest.raises(ContractError, match=code):
        load_config(overrides={'td_cordon': bad})


# ---------------------------------------------------- end-to-end (mock)
@pytest.fixture
def synthetic_idp(monkeypatch):
    """The mock's IDP hardly reacts to WORK/SERVICE b/c, so replace it by a synthetic IDP:
    WORK_E_C mean distance error = -0.035 - 0.6 * log(c/c0) of 1_WORK_E_C (the cordon of the
    mock wants dlog_c(WORK) < 0, i.e. longer WORK trips, which this IDP forbids beyond -0.1)."""
    state = {}

    def evaluate(self, label='CURRENT'):
        v = state['v']
        c = v.ops[5].TripDistributionParameters.strata['1_WORK_E_C'].GravitationParameters.values['PARA_C']
        state.setdefault('c0', c)
        out = {}
        for k in self.keys:
            out[k] = {'objective': 0.0, 'fine_cdf_rmse': 0.05, 'fine_cdf_ks': 0.1, 'mean_model_km': 10.0,
                      'mean_target_km': 10.0, 'mean_relative_error': 0.0}
        out['WORK_E_C']['mean_relative_error'] = -0.035 - 0.6 * math.log(c / state['c0'])
        state.setdefault('calls', []).append((label, out['WORK_E_C']['mean_relative_error']))
        return out
    monkeypatch.setattr(live03_idp.IdpGuard, 'evaluate', evaluate)
    return state


@pytest.mark.parametrize('constrained', [False, True])
def test_td_block_with_and_without_idp_aware_step(tmp_path, synthetic_idp, constrained):
    v = Live04Visum(tmp_path / 'model'); synthetic_idp['v'] = v
    go(tmp_path, v, {'td_cordon': dict(TD_ONLY['td_cordon'], idp_constrained_step=constrained)})
    td = read_json(folder_of(tmp_path) / 'C01_TD_CORDON/TD_BLOCK_RESULT.json')
    idp_rejections = [e for e in td['inner'] if e.get('idp') and not e['idp']['passes']]
    if not constrained:
        # previous behaviour: the cordon-optimal first step violates the IDP guard
        assert td['idp_step_model']['mode'] == 'OFF'
        assert td['inner'][0]['status'] == 'INNER_REJECTED' and idp_rejections
        return
    assert td['idp_step_model']['mode'] == 'NATIVE_PROBES'
    F = td['idp_step_model']['jacobian']['WORK_E_C.mean_relative_error']
    assert F['WORK.dlog_c'] == pytest.approx(-0.6, rel=1e-6) and F['WORK.db'] == pytest.approx(0.0, abs=1e-9)
    # every IDP-aware step passes the native guard and the linear prediction is exact here
    assert not idp_rejections and td['inner'][0]['status'] == 'INNER_ACCEPTED'
    for e in td['inner']:
        if 'idp' in e:
            got = next(c['mean_rel_after'] for c in e['idp']['components'] if c['component'] == 'WORK_E_C')
            assert got == pytest.approx(e['idp_predicted']['WORK_E_C']['mean_relative_error'], abs=1e-9)
            assert abs(got) <= 0.035 + 0.02          # allowed = max(|before|, floor) + tolerance
    assert td['status'] == 'ACCEPTED'
    acc = read_json(folder_of(tmp_path) / 'C01_TD_CORDON/TRIAL/ACCEPTANCE.json')
    assert acc['accepted'] and acc['idp_guard']['passes']


def test_td_idp_jacobian_reused_from_memory(tmp_path, synthetic_idp, monkeypatch):
    from cordon2025.live03_evaluation import Live03Evaluator
    orig = Live03Evaluator.block_gate

    def gate(self, blk, before, after, rows):
        d = orig(self, blk, before, after, rows)
        if blk == 'TD_CORDON' and 'diagnostic_hash' in after:
            d['accepted'] = False; d.setdefault('reasons', []).append('TEST_FORCED_REJECTION')
        return d
    monkeypatch.setattr(Live03Evaluator, 'block_gate', gate)
    v = Live04Visum(tmp_path / 'model', route_gamma=0.5); synthetic_idp['v'] = v
    go(tmp_path, v, {'max_cycles': 2, 'stop_after_cycle_without_change': False})
    f = folder_of(tmp_path)
    c2 = read_json(f / 'C02_TD_CORDON/TD_BLOCK_RESULT.json')
    assert c2['jacobian_source'] == 'MEMORY_VERIFIED' and c2['idp_step_model']['mode'] == 'MEMORY'
    assert not [e for e in c2['inner'] if e.get('idp') and not e['idp']['passes']]
