"""LIVE04.11: component-level TD_CORDON (v7 TDJOINT1 granularity) with the v7 TDBLEND1
inner objective (50 % cordon / 50 % FineCDF IDP, normalised at the block start).
Synthetic mock only - not native PTV Visum evidence."""
import math
from types import SimpleNamespace
import numpy as np
import pytest
from fake_live04 import Live04Visum
from cordon2025.common import ROOT, read_json, ContractError
from cordon2025.live03_td import TDSpace, IdpBlend, IdpStepModel
from cordon2025.live04_config import load_config
from cordon2025.live04_cycle import run
from cordon2025 import live03_idp

OPT = {'min_free_disk_gib': 0, 'com_retry_initial_delay_seconds': 0., 'com_retry_max_delay_seconds': 0.}
GROUPS = {'WORK': ['WORK_E_C', 'WORK_E_noC'], 'SCHOOL': ['SCHOOL']}
TDC = {'trust_b': 0.25, 'trust_logc': 0.223, 'probe_b': 0.05, 'probe_logc': 0.058}


def _values():
    return [{'component': 'WORK_E_C', 'current_b': 1.75, 'current_c': -0.54},
            {'component': 'WORK_E_noC', 'current_b': 2.47, 'current_c': -0.94},
            {'component': 'SCHOOL', 'current_b': 0.0, 'current_c': -0.30}]


def test_component_space_has_own_b_and_c_per_component():
    fam = TDSpace(_values(), GROUPS, dict(TDC, grouping='FAMILY'))
    comp = TDSpace(_values(), GROUPS, dict(TDC, grouping='COMPONENT'))
    assert fam.names() == ['WORK.db', 'WORK.dlog_c', 'SCHOOL.db', 'SCHOOL.dlog_c']
    assert comp.names() == ['WORK_E_C.db', 'WORK_E_C.dlog_c', 'WORK_E_noC.db', 'WORK_E_noC.dlog_c',
                            'SCHOOL.db', 'SCHOOL.dlog_c']
    rows = {r['component']: r for r in comp.rows(np.array([0.1, 0.0, 0.0, math.log(2.0), 0.0, 0.0]))}
    assert rows['WORK_E_C']['candidate_b'] == pytest.approx(1.85) and rows['WORK_E_C']['candidate_c'] == -0.54
    assert rows['WORK_E_noC']['candidate_b'] == 2.47 and rows['WORK_E_noC']['candidate_c'] == pytest.approx(-1.88)
    assert rows['SCHOOL']['candidate_b'] == 0.0


def _idp(vals):
    return {k: {'fine_cdf_rmse': r, 'mean_relative_error': m} for k, (r, m) in vals.items()}


def test_blend_is_normalised_and_its_residual_reproduces_the_objective():
    g = SimpleNamespace(guarded=['A', 'B', 'LONG'], mean_floor=0.03, mean_tol=0.02, rmse_tol=0.01)
    before = _idp({'A': (0.06, -0.04), 'B': (0.11, -0.42), 'LONG': (0.02, 0.0)})
    b = IdpBlend(g, ['A', 'B'], before, 0.4, q_ref=1000.0)
    assert b.components == ['A', 'B'] and b.value(1000.0, before) == pytest.approx(1.0)
    # J_k = RMSE^2 + 0.25 mean^2 (sealed FineCDF form)
    assert b.j_ref == pytest.approx(0.06 ** 2 + 0.25 * 0.04 ** 2 + 0.11 ** 2 + 0.25 * 0.42 ** 2)
    rnd = np.random.default_rng(1)
    F = rnd.normal(size=(6, 3)) * 0.1
    model = IdpStepModel(g, before, F, 0.7)
    J = b.jacobian(model)
    assert J.shape == (4, 3)
    assert np.allclose(J[:2], F[[3, 4]]) and np.allclose(J[2:], 0.5 * F[[0, 1]])
    # 0.5 ||[a_c r ; a_i f]||^2 == (1-w) Q/Q_ref + w J/J_ref
    r = rnd.normal(size=7) * 10
    f = b.features(before)
    stacked = np.concatenate([b.a_cordon * r, b.a_idp * f])
    assert 0.5 * stacked @ stacked == pytest.approx(b.value(0.5 * r @ r, before))


def test_release_config_is_component_level_with_v7_weights():
    td = load_config()['td_cordon']
    assert td['grouping'] == 'COMPONENT' and td['idp_objective_weight'] == 0.5
    assert td['acceptance'] == 'BLENDED' and td['blended_max_cordon_degradation'] == 0.01
    assert sum(len(v) for v in td['groups'].values()) == 11
    assert read_json(ROOT / 'provenance/live04_user_config/CORDON_LIVE04_CONFIG.RELEASE_DEFAULT.json')['td_cordon'] == td


@pytest.mark.parametrize('bad,code', [({'grouping': 'ZONE'}, 'LIVE03_TD_POLICY'),
                                      ({'idp_objective_weight': 0.95}, 'idp_objective_weight')])
def test_config_validation(bad, code):
    with pytest.raises(ContractError, match=code):
        load_config(overrides={'td_cordon': bad})


@pytest.fixture
def synthetic_idp(monkeypatch):
    """Mock gravity responds per family only; make the IDP respond per component so the
    component search has something to separate: WORK_E_C may not get longer trips."""
    state = {}

    def evaluate(self, label='CURRENT'):
        v = state['v']
        c = v.ops[5].TripDistributionParameters.strata['1_WORK_E_C'].GravitationParameters.values['PARA_C']
        state.setdefault('c0', c)
        out = {k: {'objective': 0.0, 'fine_cdf_rmse': 0.05, 'fine_cdf_ks': 0.1, 'mean_model_km': 10.0,
                   'mean_target_km': 10.0, 'mean_relative_error': 0.0} for k in self.keys}
        out['WORK_E_C']['mean_relative_error'] = -0.035 - 0.6 * math.log(c / state['c0'])
        return out
    monkeypatch.setattr(live03_idp.IdpGuard, 'evaluate', evaluate)
    return state


def test_component_td_moves_components_of_one_family_differently(tmp_path, synthetic_idp):
    v = Live04Visum(tmp_path / 'model'); synthetic_idp['v'] = v
    run(v, output_root=tmp_path / 'runs', options=OPT,
        config_overrides={'max_cycles': 1, 'blocks_per_cycle': ['TD_CORDON']})
    f = list((tmp_path / 'runs').glob('LIVE04_TGTD_*'))[0]
    td = read_json(f / 'C01_TD_CORDON/TD_BLOCK_RESULT.json')
    names = [p['parameter'] for p in td['jacobian_probes']]
    assert len(names) == 22 and 'WORK_noE_C.dlog_c' in names and 'SCHOOL.db' in names
    assert td['objective_blend']['idp_weight'] == 0.5 and len(td['objective_blend']['components']) == 11
    first = dict(zip(td['idp_step_model']['parameters'], td['inner'][0]['step']))
    # same family, same cordon response in the mock; only WORK_E_C is held back by its IDP
    assert first['WORK_E_noC.dlog_c'] < first['WORK_E_C.dlog_c'] - 1e-3
    assert not [e for e in td['inner'] if e.get('idp') and not e['idp']['passes']]
    assert td['status'] == 'ACCEPTED' and td['acceptance_mode'] == 'BLENDED'
    acc = read_json(f / 'C01_TD_CORDON/TRIAL/ACCEPTANCE.json')
    assert acc['accepted'] and acc['td_blended_acceptance']['blended_relative_improvement'] >= 0.001
    e = td['inner'][0]
    assert e['blend_center'] == pytest.approx(1.0) and e['blend_measured'] < 1.0


# ------------------------------------------------------- blended acceptance (v7 TDBLEND1)
def _blend():
    g = SimpleNamespace(guarded=['A'], mean_floor=0.03, mean_tol=0.02, rmse_tol=0.01)
    return IdpBlend(g, ['A'], _idp({'A': (0.10, -0.40)}), 0.5, q_ref=1000.0)


TDC_B = {'blended_min_relative_improvement': 0.001, 'blended_max_cordon_degradation': 0.01}


def test_blended_gate_accepts_small_cordon_loss_for_a_large_idp_gain():
    from cordon2025.live03_td import blended_gate
    b = _blend(); before = _idp({'A': (0.10, -0.40)}); better = _idp({'A': (0.08, -0.20)})
    dec = {'accepted': False, 'reasons': ['CORDON_OBJECTIVE_NOT_IMPROVED', 'SECONDARY_METHOD_DEGRADED'],
           'secondary_relative_degradation': 0.004}
    out = blended_gate(dec, b, 1000.0, 1005.0, before, better, TDC_B)
    a = out['td_blended_acceptance']
    assert out['accepted'] and out['reasons'] == [] and a['cordon_relative_degradation'] == pytest.approx(0.005)
    j0 = 0.10 ** 2 + 0.25 * 0.40 ** 2; j1 = 0.08 ** 2 + 0.25 * 0.20 ** 2
    assert a['blended_value'] == pytest.approx(0.5 * 1.005 + 0.5 * j1 / j0)
    assert sorted(a['soft_reasons_replaced']) == ['CORDON_OBJECTIVE_NOT_IMPROVED', 'SECONDARY_METHOD_DEGRADED']


@pytest.mark.parametrize('q1,idp1,sec,reason', [
    (1015.0, (0.05, -0.05), 0.0, 'TD_CORDON_DEGRADED_TOO_MUCH'),          # cordon -1.5 %
    (1000.0, (0.10, -0.40), 0.0, 'TD_BLENDED_OBJECTIVE_NOT_IMPROVED'),    # nothing gained
    (1002.0, (0.05, -0.05), 0.02, 'TD_SECONDARY_DEGRADED_TOO_MUCH')])
def test_blended_gate_rejections(q1, idp1, sec, reason):
    from cordon2025.live03_td import blended_gate
    b = _blend()
    out = blended_gate({'reasons': [], 'secondary_relative_degradation': sec}, b, 1000.0, q1,
                       _idp({'A': (0.10, -0.40)}), _idp({'A': idp1}), TDC_B)
    assert not out['accepted'] and reason in out['reasons']


def test_blended_gate_keeps_hard_reasons_and_needs_idp():
    from cordon2025.live03_td import blended_gate
    b = _blend(); before = _idp({'A': (0.10, -0.40)})
    out = blended_gate({'reasons': ['LIVE04_ROW_GEH_GUARD_FAILED']}, b, 1000.0, 990.0, before,
                       _idp({'A': (0.05, -0.05)}), TDC_B)
    assert not out['accepted'] and out['reasons'] == ['LIVE04_ROW_GEH_GUARD_FAILED']
    out = blended_gate({'reasons': []}, b, 1000.0, 990.0, before, {'error': 'X'}, TDC_B)
    assert not out['accepted'] and out['reasons'] == ['TD_BLENDED_IDP_UNAVAILABLE']


def test_blended_gate_measures_cordon_loss_from_the_block_start():
    """Inner steps judge F against the trust-region centre but the cordon loss against the block
    start, so several accepted inner steps cannot add up to more than the 1 % allowance."""
    from cordon2025.live03_td import blended_gate
    b = _blend(); c = _idp({'A': (0.08, -0.20)}); better = _idp({'A': (0.05, -0.05)})
    ok = blended_gate({'reasons': []}, b, 1008.0, 1009.0, c, better, TDC_B, q_base=1000.0)
    assert ok['accepted'] and ok['td_blended_acceptance']['cordon_relative_degradation'] == pytest.approx(0.009)
    no = blended_gate({'reasons': []}, b, 1008.0, 1012.0, c, better, TDC_B, q_base=1000.0)
    assert not no['accepted'] and 'TD_CORDON_DEGRADED_TOO_MUCH' in no['reasons']
