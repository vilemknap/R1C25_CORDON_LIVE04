"""Small native-procedure simulation using the actual supplied operation-15 script.
No PTV Visum, no fabricated direct OD restore: TD regenerates demand from utility.
"""
from types import SimpleNamespace
from pathlib import Path
import runpy
import base64
import gzip
import hashlib
import json
import numpy as np
import pytest

from cordon2025.common import ROOT, ContractError, canonical_hash, parent_module
from cordon2025.live04_guard import Live04GuardedCOM, Live04WriteAudit, WriteForbidden
from cordon2025.live04_utility_state import UtilityState, NUMBERS, SPECS, values_hash

SOURCE = ROOT / 'provenance/utility_restore/OPERATION_15_SOURCE.json'
REPLACEMENT = ROOT / 'RUN_R1_TD_UTILITY_TRANSACTIONAL.py'


class Attr:
    def __init__(self, **values):
        self.values = values
    def AttValue(self, key):
        if key not in self.values:
            raise AttributeError(key)
        return self.values[key]
    def SetAttValue(self, key, value):
        self.values[key] = value


class Matrix(Attr):
    def __init__(self, no, code, values):
        super().__init__(NO=no, CODE=code, DATASOURCETYPE='DATA', OBJECTTYPEREF='ZONE', MATRIXTYPE='SKIM')
        self.data = np.array(values, dtype=float)
        self.fail_after_write = False
    def GetValues(self):
        return self.data.tolist()
    def SetValues(self, values, add=False):
        assert self.AttValue('NO') in NUMBERS + tuple(range(9800, 9810)), 'OD writes must remain forbidden'
        self.data = np.array(values, dtype=float)
        if self.fail_after_write:
            self.fail_after_write = False
            raise RuntimeError('SETTER_MUTATED_THEN_FAILED')


class All:
    def __init__(self, items):
        self.items = items
    @property
    def GetAll(self):
        return self.items
    def ItemByKey(self, no):
        return next(x for x in self.items if x.AttValue('NO') == no)


class TinyModel:
    def __init__(self, folder):
        self.folder = Path(folder)
        source = json.loads(SOURCE.read_text())
        original = gzip.decompress(base64.b64decode(source['content']))
        assert hashlib.sha256(original).hexdigest() == 'c86fc648a5995e6b2e2dfad712cdf1ed57f5f262573f3c4a2330483466775ce1'
        self.original_script = {'__name__': 'user_utility_original', '__file__': str(SOURCE)}
        exec(compile(original, str(SOURCE), 'exec'), self.original_script)
        self.script = runpy.run_path(str(REPLACEMENT), run_name='user_utility_test_fixture')
        self.folder.mkdir(parents=True, exist_ok=True)
        model = self.folder / 'MODEL_TEST.ver'; model.write_bytes(b'SYNTHETIC_NOT_VISUM')
        self.IO = SimpleNamespace(CurrentVersionFile=str(model))
        self.base = np.array([[2., 5.], [6., 3.]])
        mats = [Matrix(9002, 'BASE', self.base)]
        mats += [Matrix(no, 'R1_TD_U_' + c, self.base) for no, c in SPECS]
        self.flows = {}
        dsegs = []
        for i, code in enumerate(self.script['REQUIRED_DSEGS']):
            tt0 = Matrix(9800 + 2*i, 'TT0', np.full((2, 2), 10.))
            ttc = Matrix(9801 + 2*i, 'TTC', np.full((2, 2), 10. if code.endswith('NOT') else 30.))
            tt0.values['DSEGCODE'] = ttc.values['DSEGCODE'] = code
            mats.extend([tt0, ttc])
            if code in self.script['FLOW_NOS']:
                flow = Matrix(self.script['FLOW_NOS'][code], 'FLOW', np.zeros((2, 2)))
                self.flows[code] = flow
                ds = Attr(CODE=code); ds.ODMatrix = flow; dsegs.append(ds); mats.append(flow)
        self.zones = [10, 20]
        zones = SimpleNamespace(GetMultiAttValues=lambda name: list(enumerate(self.zones, 1)))
        self.Net = SimpleNamespace(Matrices=All(mats), Zones=zones, DemandSegments=All(dsegs))
        self.ops = [Attr(OPERATIONTYPE=75, ACTIVE=False, COMMENT='', NAME='') for _ in range(36)]
        self.ops[14] = Attr(OPERATIONTYPE=65, ACTIVE=True, COMMENT='TD utility', NAME='', SCRIPTFILE=str(REPLACEMENT))
        self.ops[16] = Attr(OPERATIONTYPE=46, ACTIVE=True, COMMENT='TD', NAME='')
        params = Attr(DSTRATSET=','.join(r['dstrat_code'] for r in self.script['MAPPING']))
        refs = {r['dstrat_code']: Attr(UTILITYFUNCTION='Matrix([NO]=%d)' % r['utility_no']) for r in self.script['MAPPING']}
        params.TripDistributionDStratParameters = lambda code: refs[code]
        self.refs = refs
        self.ops[16].TripDistributionParameters = params
        self.ops[29] = Attr(OPERATIONTYPE=9, ACTIVE=True, COMMENT='reset', NAME='')
        self.ops[35] = Attr(OPERATIONTYPE=101, ACTIVE=True, COMMENT='SUE', NAME='')
        self.Procedures = SimpleNamespace(Operations=All(self.ops), Execute=lambda: self.execute())
        self.coefficient = 1.
        self.updates = self.resets = 0
        self.saved_paths = True
        self.td()

    def matrix(self, no):
        return self.Net.Matrices.ItemByKey(no)

    def td(self):
        self.demand = self.coefficient * np.array([[0., 10.], [20., 0.]]) / self.matrix(9700).data
        share = .8 - .1 * (self.coefficient - 1.)
        for code, m in self.flows.items():
            m.data = self.demand * (1-share if code.endswith('NOT') else share)

    def execute(self, plan=None):
        positions = plan['selected_operation_positions'] if plan is not None else [i+1 for i, op in enumerate(self.ops) if op.values['ACTIVE']]
        if 15 in positions:
            self.updates += 1
            self.script['run'](self, self.folder / ('update_%03d' % self.updates))
        if 17 in positions:
            self.td()
        if 30 in positions:
            self.resets += 1; self.saved_paths = False
        if 36 in positions:
            self.saved_paths = True

    def native_snapshot(self):
        r = {'generation_hash': str(self.coefficient), 'td_hash': 'TD', 'addval_hash': 'A',
             'matrices': [{'matrix_no': m.AttValue('NO'), 'sha256_float64_le': values_hash(m.data)} for m in self.flows.values()],
             'matrix_hash': canonical_hash([values_hash(self.demand)]+[values_hash(m.data) for m in self.flows.values()])}
        r['state_hash'] = canonical_hash(r)
        return r


@pytest.fixture
def setup(tmp_path):
    raw = TinyModel(tmp_path)
    audit = Live04WriteAudit()
    guarded = Live04GuardedCOM(raw, 'Visum', audit)
    invalidations = []
    a = SimpleNamespace(visum=guarded, live02={'evaluation': {}}, com_retry_policy={'enabled': False},
                        invalidate_candidate_readback=lambda *args, **kwargs: invalidations.append(args))
    state = UtilityState(a)
    parent = state.augment_snapshot(raw.native_snapshot())
    state.set_parent(parent, tmp_path / 'parent')
    return raw, a, state, parent, audit, invalidations


def test_original_script_reproduces_non_idempotent_demand_restore(setup):
    raw, a, u, parent, audit, inv = setup
    raw.script = raw.original_script
    raw.coefficient = 1.1; raw.execute({'selected_operation_positions': [15, 17]})
    raw.coefficient = 1.; raw.execute({'selected_operation_positions': [15, 17]})
    assert raw.native_snapshot()['matrix_hash'] != parent['matrix_hash']
    assert u.augment_snapshot(raw.native_snapshot()) != parent


def test_repeated_probes_and_restores_are_exact_without_od_writes(setup, tmp_path):
    raw, a, u, parent, audit, inv = setup
    nodes = []
    for rep in range(3):
        raw.coefficient = 1.1
        plan = u.prepare({'selected_operation_positions': [15, 17]}, tmp_path / str(rep), raw.native_snapshot())
        assert 15 in plan['selected_operation_positions']
        raw.execute(plan); nodes.append(u.augment_snapshot(raw.native_snapshot()))
        raw.coefficient = 1.
        plan = u.prepare({'selected_operation_positions': [15, 17], 'restore_parent_state_hash': parent['state_hash']},
                         tmp_path / ('restore%d' % rep), raw.native_snapshot())
        assert 15 not in plan['selected_operation_positions']
        raw.execute(plan)
        assert u.augment_snapshot(raw.native_snapshot()) == parent
    assert nodes[0] == nodes[1] == nodes[2]
    assert raw.saved_paths and raw.resets == 0 and raw.updates == 3
    assert audit.summary()['direct_od_matrix_writes'] == 0
    assert audit.summary()['td_utility_state_restores'] == 48


def test_full_trial_rollback_adoption_and_next_parent(setup, tmp_path):
    raw, a, u, parent, audit, inv = setup
    full = {'selected_operation_positions': [15, 17, 30, 36]}
    raw.coefficient = 1.1; raw.execute(u.prepare(full, tmp_path / 'trial', raw.native_snapshot()))
    candidate = u.augment_snapshot(raw.native_snapshot())
    raw.coefficient = 1.; raw.execute(u.prepare(full, tmp_path / 'rollback', raw.native_snapshot()))
    assert u.augment_snapshot(raw.native_snapshot()) == parent
    raw.coefficient = 1.1; raw.execute(u.prepare(full, tmp_path / 'adopt', raw.native_snapshot()))
    assert u.augment_snapshot(raw.native_snapshot()) == candidate
    u.set_parent(candidate, tmp_path / 'accepted')
    raw.coefficient = 1.2; raw.execute(u.prepare(full, tmp_path / 'next', raw.native_snapshot()))
    assert u.augment_snapshot(raw.native_snapshot())['td_utility_state'] != candidate['td_utility_state']


@pytest.mark.parametrize('failure', ['wrong_parent', 'reference', 'axis', 'code', 'formula'])
def test_invalid_restore_is_blocked_before_any_matrix_write(setup, tmp_path, failure):
    raw, a, u, parent, audit, inv = setup
    plan = {'selected_operation_positions': [15, 17], 'restore_parent_state_hash': parent['state_hash']}
    if failure == 'wrong_parent': plan['restore_parent_state_hash'] = 'OTHER'
    if failure == 'reference': next(iter(raw.refs.values())).values['UTILITYFUNCTION'] = 'Matrix([NO]=9002)'
    if failure == 'axis': raw.zones.reverse()
    if failure == 'code': raw.matrix(9700).values['CODE'] = 'OTHER'
    if failure == 'formula': raw.matrix(9700).values['DATASOURCETYPE'] = 'FORMULA'
    with pytest.raises(ContractError):
        u.prepare(plan, tmp_path / 'bad', raw.native_snapshot())
    assert not audit.events


def test_restore_permission_is_narrow_and_is_released_after_partial_failure(setup, tmp_path):
    raw, a, u, parent, audit, inv = setup
    raw.coefficient = 1.1; raw.execute({'selected_operation_positions': [15, 17]}); raw.coefficient = 1.
    raw.matrix(9700).fail_after_write = True
    with pytest.raises(RuntimeError, match='MUTATED_THEN_FAILED'):
        u.prepare({'selected_operation_positions': [15, 17]}, tmp_path / 'bad', raw.native_snapshot())
    assert audit.td_utility_restore_expected is None and inv
    with pytest.raises(WriteForbidden):
        a.visum.Net.Matrices.ItemByKey(9700).SetValues(np.array(raw.base), False)
    with pytest.raises(WriteForbidden):
        a.visum.Net.Matrices.ItemByKey(9301).SetValues(np.zeros((2, 2)), False)
    plan = u.prepare({'selected_operation_positions': [15, 17]}, tmp_path / 'recovered', raw.native_snapshot())
    raw.execute(plan)
    assert u.augment_snapshot(raw.native_snapshot()) == parent


def test_snapshot_detects_unexpected_utility_change(setup):
    raw, a, u, parent, audit, inv = setup
    raw.matrix(9700).data[0, 1] += .1
    now = u.augment_snapshot(raw.native_snapshot())
    assert now['matrix_hash'] == parent['matrix_hash']
    assert now['state_hash'] != parent['state_hash']


def test_skim_changes_are_restored_and_enter_snapshot_identity(setup, tmp_path):
    raw, a, u, parent, audit, inv = setup
    raw.matrix(9801).data[0, 1] += 5.
    assert u.augment_snapshot(raw.native_snapshot())['state_hash'] != parent['state_hash']
    u.restore()
    assert u.augment_snapshot(raw.native_snapshot()) == parent
    assert audit.summary()['td_input_skim_restores'] == 1


def test_zero_time_cold_state_is_blocked_before_native_script_consumes_it(setup):
    raw, a, u, parent, audit, inv = setup
    for no in u.time_specs:
        raw.matrix(no).data[:] = 0.
    with pytest.raises(ContractError, match='REQUIRES_COMPLETED_TIME_SKIMS'):
        UtilityState(a)
    assert not audit.events


def test_full_adapter_replays_parent_epoch_after_native_skims(setup, tmp_path, monkeypatch):
    from cordon2025.live04_adapter import CordonLive04Adapter
    from cordon2025.live03_adapter import CordonLive03Adapter
    raw, a, u, parent, audit, inv = setup
    adapter = CordonLive04Adapter.__new__(CordonLive04Adapter)
    adapter.visum = a.visum; adapter.live02 = a.live02; adapter.com_retry_policy = a.com_retry_policy
    adapter.td_utility_state = u; u.adapter = adapter
    monkeypatch.setattr(CordonLive03Adapter, 'snapshot', lambda self: raw.native_snapshot())

    def native(self, folder, block, plan):
        raw.execute(plan)
        # A full assignment/skim stage overwrites its DATA time results.
        for no, (_, code) in u.time_specs.items():
            if code == 'TTC':
                raw.matrix(no).data *= 1.05
        return .001

    monkeypatch.setattr(CordonLive03Adapter, '_execute_perf1_plan', native)
    full = {'selected_operation_positions': [15, 17, 30, 36]}
    raw.coefficient = 1.1
    adapter._execute_perf1_plan(tmp_path / 'trial', 'GENERATION', full)
    child = adapter.snapshot()
    raw.coefficient = 1.
    adapter._execute_perf1_plan(tmp_path / 'rollback', 'GENERATION', full)
    assert adapter.snapshot() == parent
    raw.coefficient = 1.1
    adapter._execute_perf1_plan(tmp_path / 'adopt', 'GENERATION', full)
    assert adapter.snapshot() == child
    assert audit.td_time_restore_numbers is None and audit.td_utility_restore_expected is None


def test_stop_does_not_prevent_complete_read_only_failure_verification(setup, tmp_path):
    from cordon2025.live02_cycle import LiveControl
    raw, a, u, parent, audit, inv = setup
    ctl = LiveControl(tmp_path, RuntimeError)
    a.evaluator = SimpleNamespace(control=ctl)
    (tmp_path / 'STOP_REQUESTED').touch()
    assert u.augment_snapshot(raw.native_snapshot()) == parent
    u.set_parent(parent, tmp_path / 'atomic_parent')
    assert ctl.recovery_depth == 0
    with pytest.raises(RuntimeError, match='USER_STOP_REQUESTED'):
        ctl.checkpoint('NEXT_ACTION')


def test_stop_is_checked_before_each_retry_attempt(setup, tmp_path, monkeypatch):
    from cordon2025.live02_cycle import LiveControl
    raw, a, u, parent, audit, inv = setup
    ctl = LiveControl(tmp_path, RuntimeError)
    a.evaluator = SimpleNamespace(control=ctl)
    calls = []

    def retry(func, **kwargs):
        func()
        (tmp_path / 'STOP_REQUESTED').touch()
        return func()

    monkeypatch.setattr(u.com, 'com_call_with_retry', retry)
    with pytest.raises(RuntimeError, match='USER_STOP_REQUESTED'):
        u.call(lambda: calls.append('native'), 'RETRY_TEST')
    assert calls == ['native']


def test_snapshot_rejects_changed_td_utility_reference(setup):
    raw, a, u, parent, audit, inv = setup
    next(iter(raw.refs.values())).values['UTILITYFUNCTION'] = 'Matrix([NO]=9002)'
    with pytest.raises(ContractError, match='TD_UTILITY_REFERENCE_CHANGED'):
        u.augment_snapshot(raw.native_snapshot())


def test_bit_exact_restore_includes_signed_zero(setup, tmp_path):
    raw, a, u, parent, audit, inv = setup
    raw.matrix(9801).data[0, 0] = -0.0
    parent = u.augment_snapshot(raw.native_snapshot())
    u.set_parent(parent, tmp_path / 'signed_parent')
    raw.matrix(9801).data[0, 0] = 0.0
    assert u.augment_snapshot(raw.native_snapshot()) != parent
    u.restore()
    assert np.signbit(raw.matrix(9801).data[0, 0])
    assert u.augment_snapshot(raw.native_snapshot()) == parent


def test_td_inner_probe_order_does_not_change_utility_weights(setup, tmp_path):
    raw, a, u, parent, audit, inv = setup
    repeated = []
    # No OD restore between evaluations: this is the TD inner-search situation.
    for i, coefficient in enumerate((1.1, .9, 1.1, 1.2, 1.1)):
        raw.coefficient = coefficient
        plan = u.prepare({'selected_operation_positions': [15, 17]}, tmp_path / str(i), raw.native_snapshot())
        with u.input_scope(plan):
            raw.execute(plan)
        if coefficient == 1.1:
            repeated.append(u.augment_snapshot(raw.native_snapshot()))
    assert repeated[0] == repeated[1] == repeated[2]
    assert not any(e['kind'] == 'FORBIDDEN' for e in audit.events)
    assert raw.saved_paths and raw.resets == 0


def test_replacement_standalone_matches_original_script(tmp_path):
    a = TinyModel(tmp_path / 'original'); b = TinyModel(tmp_path / 'replacement')
    a.script = a.original_script
    for raw in (a, b):
        raw.coefficient = 1.1
        raw.execute({'selected_operation_positions': [15, 17]})
    for no in NUMBERS:
        assert values_hash(a.matrix(no).data) == values_hash(b.matrix(no).data)
    assert np.array_equal(a.demand, b.demand)


def test_old_script_is_blocked_before_first_parameter_or_matrix_write(setup, tmp_path):
    raw, a, u, parent, audit, inv = setup
    old = tmp_path / 'old_operation.py'
    payload = json.loads(SOURCE.read_text())
    old.write_bytes(gzip.decompress(base64.b64decode(payload['content'])))
    raw.ops[14].values['SCRIPTFILE'] = str(old)
    with pytest.raises(ContractError, match='REPLACE_OPERATION_SCRIPT'):
        UtilityState(a)
    assert not audit.events


def test_input_scope_handshake_fails_closed_and_cleans_up(setup, tmp_path):
    from cordon2025.live04_utility_state import transaction_inputs
    raw, a, u, parent, audit, inv = setup
    raw.coefficient = 1.1
    plan = u.prepare({'selected_operation_positions': [15, 17]}, tmp_path / 'trial', raw.native_snapshot())
    raw.script = raw.original_script     # simulate a host failing to pass Python context
    with pytest.raises(ContractError, match='MUST_USE_PARENT_INPUTS_ONCE'):
        with u.input_scope(plan):
            raw.execute(plan)
    assert transaction_inputs(raw, raw.zones, {}) is None
    raw.coefficient = 1.
    restore = u.prepare({'selected_operation_positions': [15, 17]}, tmp_path / 'restore', raw.native_snapshot())
    with u.input_scope(restore):
        raw.execute(restore)
    assert u.augment_snapshot(raw.native_snapshot()) == parent


def test_input_scope_rejects_a_different_model(setup, tmp_path):
    from cordon2025.live04_utility_state import transaction_inputs
    raw, a, u, parent, audit, inv = setup
    other = TinyModel(tmp_path / 'other')
    # The scope is marked as parent/no-updater: no success handshake is expected.
    with pytest.raises(ContractError, match='MODEL_CHANGED'):
        with u.input_scope({'selected_operation_positions': []}):
            transaction_inputs(other, raw.zones, {})


def test_production_adapter_predictor_restore_path_uses_utility_transaction(setup, tmp_path, monkeypatch):
    from cordon2025.live04_adapter import CordonLive04Adapter
    from cordon2025.live03_adapter import CordonLive03Adapter
    from cordon2025.live03_predictor import FrozenPathPredictor
    from cordon2025 import live04_opmap
    raw, a, u, parent, audit, inv = setup
    adapter = CordonLive04Adapter.__new__(CordonLive04Adapter)
    adapter.visum = a.visum; adapter.live02 = a.live02; adapter.com_retry_policy = a.com_retry_policy
    adapter.td_utility_state = u; u.adapter = adapter
    adapter.cfg = {}; adapter._long_post_td_mask_enabled = False; adapter.assignment_invalidated = False
    monkeypatch.setattr(CordonLive03Adapter, 'snapshot', lambda self: raw.native_snapshot())
    monkeypatch.setattr(live04_opmap, 'approved_live_positions', lambda *args: [36])
    perf = parent_module('r1_15a2_acceleration_v24915p1')
    com = parent_module('r1_15a2_com_compat')
    inventory = [{k:v for k,v in r.items() if k != 'object'} for r in com.operation_rows(a.visum)]
    monkeypatch.setattr(perf, 'phase_recompute_plan', lambda *args: {'inventory': inventory, 'selected_operation_positions': [15,17,30,36]})
    rt = parent_module('r1_15a2_runtime_v1')
    monkeypatch.setattr(rt, 'execute_procseq', lambda *args: raw.execute())
    predictor = FrozenPathPredictor.__new__(FrozenPathPredictor)
    predictor.adapter = adapter; predictor.calls = 0; predictor.seconds = 0
    raw.coefficient = 1.1
    predictor.run_demand('GENERATION', tmp_path / 'probe')
    raw.coefficient = 1.
    assert predictor.restore_demand('GENERATION', parent, tmp_path / 'restore') == parent
    assert raw.resets == 0 and raw.saved_paths and not adapter.assignment_invalidated


class _DsegWithoutOD(Attr):
    def __init__(self, code, message):
        super().__init__(CODE=code)
        self.message = message
    @property
    def ODMatrix(self):
        raise RuntimeError(self.message)


def test_dseg_without_allocated_od_matrix_is_skipped(setup):
    """Live model 2026-11-16: Visum COM raises for a DSeg with no OD matrix instead of returning None."""
    raw, a, u, parent, audit, inv = setup
    raw.Net.DemandSegments.items.append(_DsegWithoutOD('NV_NO_MATRIX', 'No OD demand matrix allocated to this demand segment.'))
    state = UtilityState(a)
    assert state.enabled and len(state.time_specs) == 10
    raw.Net.DemandSegments.items[-1] = _DsegWithoutOD('BROKEN', 'RPC server unavailable')
    with pytest.raises(RuntimeError, match='RPC server unavailable'):
        UtilityState(a)


def _embed(raw, code=None, filename='', internal=1):
    """Visum 2026 / R1 procedure: script embedded in the .ver (EXECUTESCRIPTPARA, no SCRIPTFILE)."""
    op = raw.ops[14]
    op.values.pop('SCRIPTFILE', None)
    params = Attr(USEINTERNALSCRIPTCODE=internal, FILENAME=filename)
    if code is not None:
        params.values['INTERNALSCRIPTCODE'] = code
    op.ExecuteScriptParameters = params
    return params


def test_embedded_internal_script_code_is_validated(setup):
    """Live run 2026-11-16: op 15 has FILENAME='' and USEINTERNALSCRIPTCODE=1."""
    raw, a, u, parent, audit, inv = setup
    _embed(raw, REPLACEMENT.read_text(encoding='utf-8'))
    state = UtilityState(a)
    assert state.update_script_reference == ('INTERNAL', 'ExecuteScriptParameters')
    assert state.update_script_sha256 == hashlib.sha256(REPLACEMENT.read_text(encoding='utf-8').encode('utf-8')).hexdigest()
    assert not audit.events


def test_embedded_original_script_requires_replacement(setup):
    raw, a, u, parent, audit, inv = setup
    payload = json.loads(SOURCE.read_text())
    _embed(raw, gzip.decompress(base64.b64decode(payload['content'])).decode('utf-8'))
    with pytest.raises(ContractError, match='REPLACE_OPERATION_SCRIPT'):
        UtilityState(a)
    assert not audit.events


def test_external_filename_from_execute_script_parameters(setup, tmp_path):
    raw, a, u, parent, audit, inv = setup
    copy = tmp_path / 'RUN_R1_TD_UTILITY_TRANSACTIONAL.py'
    copy.write_bytes(REPLACEMENT.read_bytes())
    _embed(raw, code='', filename=str(copy), internal=0)
    state = UtilityState(a)
    assert state.update_script_reference == ('FILE', 'ExecuteScriptParameters', str(copy))


def test_unreadable_script_reports_what_was_tried(setup):
    raw, a, u, parent, audit, inv = setup
    _embed(raw, code=None)
    with pytest.raises(ContractError, match='REFERENCE_UNREADABLE:ExecuteScriptParameters:internal=1'):
        UtilityState(a)


def test_embedded_script_change_during_run_is_detected(setup):
    raw, a, u, parent, audit, inv = setup
    params = _embed(raw, REPLACEMENT.read_text(encoding='utf-8'))
    state = UtilityState(a)
    params.values['INTERNALSCRIPTCODE'] += '\n# edited\n'
    with pytest.raises(ContractError, match='SCRIPT_CHANGED_DURING_CALIBRATION'):
        state.validate_operation()
