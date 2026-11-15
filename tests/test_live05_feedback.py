"""LIVE05.8 procedure feedback (TD utility step + vignette split) - synthetic, never native evidence."""
import types
import numpy as np
import pytest
from cordon2025.common import ROOT
from cordon2025.io import read_json
from cordon2025 import live05_feedback as fbm

N = 4
U, TTC, TT0, OD, VEH, DT, RATIO = 9700, 9800, 9801, 9301, 9302, 9235, 9231


class Mat:
    def __init__(self, host, no, values, code='', dseg='', formula=''):
        self.host, self.no, self.values = host, no, np.array(values, dtype=float)
        self.code, self.dseg, self.formula = code, dseg, formula

    def AttValue(self, name):
        return {'NO': self.no, 'CODE': self.code, 'DSEGCODE': self.dseg, 'FORMULA': self.formula,
                'DATASOURCETYPE': 'FORMULA' if self.formula else 'DATA'}[name.upper()]

    def GetValues(self):
        return tuple(tuple(r) for r in self.values)

    def SetValues(self, values, add=False):
        assert add is False and isinstance(values, np.ndarray)
        self.host.matrix_writes.append(self.no)
        self.values = np.array(values, dtype=float, copy=True)


class Coll:
    def __init__(self, items):
        self.items = items

    def GetAll(self):
        return list(self.items)

    def ItemByKey(self, no):
        for m in self.items:
            if getattr(m, 'no', None) == no:
                return m
        raise KeyError(no)


class Op:
    def __init__(self, typ, active=1, comment=''):
        self.v = {'OPERATIONTYPE': typ, 'ACTIVE': active, 'COMMENT': comment, 'NAME': ''}

    def AttValue(self, name):
        return self.v[name.upper()]

    def SetAttValue(self, name, value):
        self.v[name.upper()] = int(value)


class Procedures:
    def __init__(self, host, ops):
        self.host, self.Operations = host, Coll(ops)

    def Execute(self):
        self.host.execute()


class FakeVisum:
    """1 TG, 2 feedback script, 3 TD, 4 realization script, 5 assignment, 6 skim."""

    def __init__(self, vignette_formula='Matrix(9235)'):
        self.matrix_writes = []
        self.param = 1.0
        i = np.arange(N)
        self.base = 1.0 + 0.1 * np.abs(i[:, None] - i[None, :])
        mats = [Mat(self, U, self.base), Mat(self, TTC, np.ones((N, N)), 'TTC', 'NATIVE_CW'),
                Mat(self, TT0, np.ones((N, N)), 'TT0', 'NATIVE_CW'), Mat(self, OD, np.zeros((N, N))),
                Mat(self, VEH, np.zeros((N, N))), Mat(self, DT, np.full((N, N), 3.0)),
                Mat(self, RATIO, np.zeros((N, N)), formula=vignette_formula)]
        self.Net = types.SimpleNamespace(Matrices=Coll(mats))
        self.ops = [Op(45), Op(65, comment='R1 TD utility step'), Op(46), Op(65, comment='realization'), Op(101), Op(103)]
        self.Procedures = Procedures(self, self.ops)
        self.m = {x.no: x for x in mats}
        self.executions = []
        # converged start as a saved version: one full run, then the feedback step has run once
        self.execute()

    def execute(self):
        active = [bool(o.v['ACTIVE']) for o in self.ops]
        self.executions.append(active)
        m = self.m
        if active[1]:            # MSA utility step: congestion ratio of the previous assignment and OD flows
            ratio = m[TTC].values / m[TT0].values * (1.0 + 1e-4 * m[OD].values.sum())
            m[U].values = 0.5 * m[U].values + 0.5 * self.base * ratio
        if active[2]:            # TD
            m[OD].values = 100.0 * self.param * np.exp(-m[U].values)
        if active[3]:            # realization (vignette split reads the referenced matrix)
            ref = m[DT].values if 'Matrix(9235)' in m[RATIO].formula else m[TTC].values
            m[VEH].values = m[OD].values * (0.5 + 0.01 * ref)
        if active[4] and active[5]:
            m[TTC].values = 1.0 + 0.01 * m[VEH].values     # congested skim of this assignment


def cfg(enabled=True, **over):
    f = {'enabled': enabled, 'utility_matrix_nos': [U], 'time_skim_codes': ['TTC', 'TT0'],
         'time_skim_dsegs': ['NATIVE_CW'], 'formula_matrix_nos': [RATIO], 'formula_allowed_reference_nos': [DT],
         'expected_feedback_operations': 1}
    f.update(over)
    return {'procedure_feedback': f, 'write_policy': {'procedure_feedback_state_matrix_writes': enabled}}


def state(v):
    return {k: v.m[k].values.copy() for k in (U, TTC, OD, VEH)}


def same(a, b):
    return all(np.array_equal(a[k], b[k]) for k in a)


def run_full(v):
    v.Procedures.Execute()


def run_demand(v, fb, plan=(1, 2, 3, 4)):
    """demand-only slice like the predictor: plan filtered when reproducing, ACTIVE flags scoped."""
    from cordon2025.common import parent_module
    perf1 = parent_module('r1_15a2_acceleration_v24915p1')
    p = fb.filter_plan({'selected_operation_positions': list(plan)})
    with fb.execution(assignment=False):
        with perf1.activate_operation_plan(v, p):
            v.Procedures.Execute()


def test_resolution_and_audit(tmp_path):
    v = FakeVisum()
    audit = types.SimpleNamespace()
    fb = fbm.ProcedureFeedback(v, cfg(), tmp_path, forbidden_matrix_nos=[OD, VEH], audit=audit)
    assert fb.positions == [2]
    assert fb.roles == {U: 'TD_UTILITY', TTC: 'TIME_SKIM_TTC_NATIVE_CW', TT0: 'TIME_SKIM_TT0_NATIVE_CW'}
    assert audit.feedback_state_matrices == frozenset(fb.roles)
    assert fb.formula_references == [DT]
    assert read_json(tmp_path / 'PROCEDURE_FEEDBACK.json')['feedback_operation_positions'] == [2]


def test_fail_closed_resolution(tmp_path):
    v = FakeVisum()
    with pytest.raises(Exception, match='LIVE05_FEEDBACK_STATE_OVERLAPS'):
        fbm.ProcedureFeedback(v, cfg(), tmp_path, forbidden_matrix_nos=[U])
    with pytest.raises(Exception, match='LIVE05_FEEDBACK_OPERATION_COUNT'):
        fbm.ProcedureFeedback(v, cfg(expected_feedback_operations=2), tmp_path)
    v.ops[1].v['ACTIVE'] = 0
    with pytest.raises(Exception, match='LIVE05_FEEDBACK_OPERATION_COUNT'):
        fbm.ProcedureFeedback(v, cfg(), tmp_path)
    with pytest.raises(Exception, match='LIVE05_FEEDBACK_UTILITY_MATRIX_MISSING'):
        fbm.ProcedureFeedback(FakeVisum(), cfg(utility_matrix_nos=[9999]), tmp_path)
    with pytest.raises(Exception, match='LIVE05_FEEDBACK_WRITE_POLICY_MUST_MATCH'):
        fbm.validate(dict(cfg(), write_policy={'procedure_feedback_state_matrix_writes': False}))
    with pytest.raises(Exception, match='LIVE05_FEEDBACK_CONFIG_FIELDS'):
        fbm.options({'procedure_feedback': {'enabled': True, 'lambda': 0.5}})


def test_without_feedback_handling_restore_differs():
    """The live failure 2026-11-15 (LIVE03_DEMAND_RESTORE_SNAPSHOT_DIFFERS) in miniature."""
    v = FakeVisum()
    parent = state(v)
    v.param = 1.2
    run_full(v)                         # probe/trial with the feedback step
    v.param = 1.0
    run_full(v)                         # restore with the same procedure
    assert not np.array_equal(v.m[OD].values, parent[OD])


def test_probe_restore_is_exact(tmp_path):
    v = FakeVisum()
    fb = fbm.ProcedureFeedback(v, cfg(), tmp_path)
    fb.capture('BASELINE')
    parent = state(v)
    for p in (1.3, 0.8):                # two probes, each runs the feedback step (prediction of the trial)
        v.param = p
        run_demand(v, fb)
        assert not np.array_equal(v.m[U].values, parent[U])
    v.param = 1.0
    with fb.reproduce():
        run_demand(v, fb)
    assert same(state(v), parent)
    assert v.executions[-1][1] is False and v.ops[1].v['ACTIVE'] == 1     # skipped, flag restored
    assert fb.counts['matrices_written'] >= 1


def test_trial_then_rollback_is_exact_and_trials_share_the_parent(tmp_path):
    v = FakeVisum()
    fb = fbm.ProcedureFeedback(v, cfg(), tmp_path)
    fb.capture('BASELINE')
    parent = state(v)
    v.param = 1.25
    with fb.execution(assignment=True):
        run_full(v)
    first = state(v)
    assert v.executions[-1][1] is True                      # the trial includes the congestion feedback
    v.param = 1.0
    wrapped = fb.wrap_rollback(lambda: (fb.reproducing, fb.execution(assignment=True)))
    flag, ctx = wrapped()
    assert flag is True
    with fb.reproduce(), fb.execution(assignment=True):
        run_full(v)
    assert same(state(v), parent)                           # exact rollback, no tolerance needed
    v.param = 1.25                                          # the same trial again from the same parent
    with fb.execution(assignment=True):
        run_full(v)
    assert same(state(v), first)


def test_accepted_trial_becomes_the_feedback_parent(tmp_path):
    v = FakeVisum()
    fb = fbm.ProcedureFeedback(v, cfg(), tmp_path)
    fb.capture('BASELINE')
    v.param = 1.25
    with fb.execution(assignment=True):
        run_full(v)
    fb.capture('C01_GENERATION')                            # accepted
    accepted = state(v)
    v.param = 0.9
    run_demand(v, fb)                                       # probe of the next block
    v.param = 1.25
    with fb.reproduce():
        run_demand(v, fb)
    assert same(state(v), accepted)
    with fb.reproduce(), fb.execution(assignment=True):     # assignment repair of the accepted state
        run_full(v)
    assert same(state(v), accepted)


def test_live_vignette_split_stops_before_any_write(tmp_path):
    """DT_MODE='LIVE': the saved demand used the skims of the run before the saved one -> not reproducible."""
    v = FakeVisum(vignette_formula='0.7+Matrix(9800)')
    parent = state(v)
    v.param = 1.4                       # without the guard: one LIVE trial + rollback misses the parent
    run_full(v)
    v.param = 1.0
    v.ops[1].v['ACTIVE'] = 0
    run_full(v)
    assert not np.array_equal(v.m[VEH].values, parent[VEH])
    with pytest.raises(Exception, match='LIVE05_VIGNETTE_SPLIT_NOT_FROZEN_NOT_REPRODUCIBLE'):
        fbm.ProcedureFeedback(FakeVisum(vignette_formula='0.7+Matrix(9800)'), cfg(), tmp_path)
    assert FakeVisum(vignette_formula='0.7+Matrix(9800)').matrix_writes == []


def test_guard_allows_only_resolved_feedback_matrices():
    from cordon2025.live04_guard import Live04WriteAudit, _policy
    from cordon2025.live02_guard import WriteForbidden
    audit = Live04WriteAudit()
    a = np.ones((3, 3))
    label = 'Visum.Net.Matrices.ItemByKey(9700)()'
    with pytest.raises(WriteForbidden):
        _policy(label, 'SetValues', (a, False), audit)
    audit.feedback_state_matrices = frozenset({9700})
    _policy(label, 'SetValues', (a, False), audit)
    assert audit.summary()['feedback_state_matrix_writes'] == 1
    with pytest.raises(WriteForbidden):
        _policy('Visum.Net.Matrices.ItemByKey(9301)()', 'SetValues', (a, False), audit)
    with pytest.raises(WriteForbidden):
        _policy(label, 'SetValues', (a * np.nan, False), audit)


def test_release_config_enables_feedback():
    from cordon2025.live04_config import validate_config, CONFIG_FILE
    c = validate_config(read_json(ROOT / CONFIG_FILE))       # the release file itself (not a host patch)
    o = fbm.validate(c)
    assert o['enabled'] and o['utility_matrix_nos'] == list(range(9700, 9716))
    assert o['formula_matrix_nos'] == [9231, 9232, 9233, 9234]
    d = read_json(ROOT / 'provenance/live04_user_config/CORDON_LIVE04_CONFIG.RELEASE_DEFAULT.json')
    assert d['procedure_feedback'] == c['procedure_feedback']
    assert d['write_policy']['procedure_feedback_state_matrix_writes'] is True
