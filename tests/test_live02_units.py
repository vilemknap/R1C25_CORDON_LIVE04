"""LIVE02 unit tests: config contract, donor identity, write guard, FIX1."""
import copy
import json
import types
import numpy as np
import pytest
from cordon2025.common import ROOT, read_json, ContractError, parent_module
from cordon2025.live02_config import (load_config, validate_config, adapter_config, donor_runtime_matches_source,
                                      live01_view, GENERATION_ATTRS)
from cordon2025.live02_guard import GuardedCOM, WriteAudit, WriteForbidden, _plain
from cordon2025.live02_namespace import DonorTransaction, rebind_module
from cordon2025.live01_visum import ReadOnlyObject, is_com_method


def base_cfg():
    return read_json(ROOT / 'CORDON_LIVE02_CONFIG.json')


def test_config_valid_and_every_donor_value_matches_pinned_source():
    cfg = load_config(overrides={'generation_mode': 'HOTFIX2_BACKTRACKING'})
    assert donor_runtime_matches_source(cfg) == []
    a = adapter_config(cfg, 1, [1, 2])
    assert a['apply'] is False and a['backtracking_scales'] == [1.0, 0.75, 0.5, 0.25, 0.125, 0.0625]
    assert a['trial_calibration']['max_trials_per_block'] == {'GENERATION': 6}
    v = adapter_config(load_config(), 1, [1, 2])     # default V24917: tg_max_trials = 3
    assert v['backtracking_scales'] == [1.0, 0.75, 0.5] and v['trial_calibration']['max_trials_per_block'] == {'GENERATION': 3}
    assert v['v24917_targeted_generation']['enabled'] is True
    assert a['supply']['gap_readback'] == {'maximum_gap': 0.005, 'operation_no': 20, 'source': 'PRT_ASS_QUALITY_LIST'}
    assert a['performance']['v24915_perf1']['phase_specific_procseq']['enabled'] is True
    assert a['live01_search_stage']['name'] == 'SIGNED_EXPLORE'
    assert adapter_config(cfg, 7, None)['live01_search_stage']['name'] == 'SIGNED_REFINE'


@pytest.mark.parametrize('path,value,error', [
    (('write_policy', 'td_parameter_writes'), True, 'LIVE02_FORBIDDEN_WRITE_FLAG:td_parameter_writes'),
    (('write_policy', 'direct_od_matrix_writes'), True, 'LIVE02_FORBIDDEN_WRITE_FLAG:direct_od_matrix_writes'),
    (('write_policy', 'load_version'), True, 'LIVE02_FORBIDDEN_WRITE_FLAG:load_version'),
    (('write_policy', 'overwrite_source_version'), True, 'LIVE02_FORBIDDEN_WRITE_FLAG:overwrite_source_version'),
    (('execution_mode',), 'PRODUCTION', 'LIVE02_PRODUCTION_NOT_AUTHORIZED'),
    (('max_tg_cycles',), 11, 'LIVE02_CONFIG_INT:max_tg_cycles'),
    (('acceptance', 'method'), 'BOTH', 'LIVE02_ACCEPTANCE_METHOD'),
    (('acceptance', 'secondary_method'), 'ALL_ORDERED_UNIQUE_PAIRS', 'LIVE02_ACCEPTANCE_METHOD'),
    (('generation_search', 'max_generation_pa_relative_gap'), 0.03, 'LIVE02_DONOR_RUNTIME_DRIFT'),
    (('generation_search', 'backtracking_scales'), [1.0, 0.8, 0.6, 0.4, 0.2, 0.1], 'LIVE02_DONOR_RUNTIME_DRIFT'),
    (('donor_runtime', 'supply', 'gap_readback', 'maximum_gap'), 0.05, 'LIVE02_DONOR_RUNTIME_DRIFT'),
    (('isolated_copy_guard', 'forbidden_version_name_tokens'), [], 'LIVE02_2022_GUARD_REQUIRED'),
    (('live01_contract_sha256',), '0' * 64, 'LIVE02_LIVE01_CONTRACT_CHANGED'),
])
def test_config_rejects_unsafe_or_drifted_values(path, value, error):
    cfg = base_cfg(); node = cfg
    for k in path[:-1]:
        node = node[k]
    node[path[-1]] = value
    with pytest.raises(ContractError, match=error):
        validate_config(cfg)


def test_config_unknown_field_and_live01_view_stays_read_only():
    cfg = base_cfg(); cfg['apply'] = True
    with pytest.raises(ContractError, match='LIVE02_UNKNOWN_CONFIG_FIELD'):
        validate_config(cfg)
    view = live01_view(base_cfg(), 3)
    assert view['writes_enabled'] is False and view['apply_permitted'] is False and view['outer_cycle'] == 3


def test_explicit_donor_override_requires_flag():
    with pytest.raises(ContractError, match='DRIFT'):
        load_config(overrides={'generation_search': {'max_generation_pa_relative_gap': 0.001}})
    cfg = load_config(overrides={'_allow_donor_overrides': True,
                                 'generation_search': {'max_generation_pa_relative_gap': 0.001}})
    assert cfg['generation_search']['max_generation_pa_relative_gap'] == 0.001


def test_donor_transaction_runs_identical_code_objects_with_cordon_names_only():
    marker = object()
    led = lambda *a, **k: {'total': 0.0}
    dh = lambda d: 'x'
    tx = DonorTransaction(led, dh)
    ident = tx.identity()
    assert ident['donor_files_modified'] is False and ident['module_globals_patched'] is False
    ctrl = parent_module('r1_15a2_overnight_controller_v24915p2')
    coupled = parent_module('r1_15a2_overnight_controller_coupled_v24915p2_force100')
    # Original modules untouched.
    assert ctrl.ledger is not led and ctrl.diagnostic_hash is not dh
    assert coupled._evaluate_candidate is ctrl._evaluate_candidate
    assert tx.ctrl_ns['_evaluate_candidate'].__code__ is ctrl._evaluate_candidate.__code__
    assert tx.ctrl_ns['_evaluate_candidate'].__globals__['ledger'] is led
    assert tx.ctrl_ns['_rollback_candidate'].__globals__['diagnostic_hash'] is dh
    assert tx.coupled_ns['_generation_update_once_impl'].__globals__['_evaluate_candidate'] is tx.evaluate
    assert getattr(tx.evaluate, '__r1_generation_gate_nonfatal__', False) is True
    assert tx.coupled_ns['_generation_update_once'].__code__ is coupled._generation_update_once.__code__


def test_rebind_does_not_leak_into_module():
    mod = types.ModuleType('m')
    exec('X=1\ndef f():\n    return X\ndef g():\n    return f()', mod.__dict__)
    ns = rebind_module(mod, {'X': 2})
    assert ns['g']() == 2 and mod.g() == 1


class FakeDispatch:
    """Mimic pywin32 CDispatch: callable (DISPID_VALUE) and carries _oleobj_."""
    _oleobj_ = object()
    def __init__(self, children=None, values=None):
        self.children = children or {}; self.values = values or {}
    def __call__(self, *a):
        raise AssertionError('DEFAULT_DISPATCH_MUST_NOT_BE_CALLED')
    def __getattr__(self, name):
        if name in ('children', 'values'):
            raise AttributeError(name)
        if name in self.children:
            return self.children[name]
        raise AttributeError(name)
    def AttValue(self, name):
        return self.values[name]
    def SetAttValue(self, name, value):
        self.values[name] = value
    def SetValues(self, v):
        raise AssertionError('MUST_BE_BLOCKED_BEFORE_COM')
    def SetMultiAttValues(self, attr, rows, flag=False):
        self.values[attr] = rows


def test_fix1_readonly_proxy_accepts_callable_com_objects():
    from cordon2025.visum_startup import settings, ReadControl
    zones = FakeDispatch(values={'NO': 5})
    visum = FakeDispatch({'Net': FakeDispatch({'Zones': zones})})
    assert not is_com_method(visum.children['Net']) and is_com_method(zones.AttValue)
    import tempfile, pathlib
    proxy = ReadOnlyObject(visum, ReadControl(pathlib.Path(tempfile.mkdtemp())), settings({}))
    assert proxy.Net.Zones.AttValue('NO') == 5     # LIVE01 raised COM_CALL_NOT_AUTHORIZED:Net here
    with pytest.raises(ValueError, match='LIVE01_COM_WRITE_FORBIDDEN'):
        proxy.Net.Zones.SetAttValue('NO', 1)


def test_guard_allows_only_tg_zone_writes_active_flags_and_execute(tmp_path):
    zones = FakeDispatch(values={})
    op = FakeDispatch(values={'ACTIVE': 1})
    params = FakeDispatch(values={})
    op.children['TripDistributionParameters'] = params
    ops = FakeDispatch({'GetAll': (op,)})
    proc = FakeDispatch({'Operations': ops})
    executed = []
    proc.children['Execute'] = lambda: executed.append(1)
    mat = FakeDispatch(values={})
    io = FakeDispatch({'SaveVersion': lambda p: None, 'LoadVersion': lambda p: None})
    visum = FakeDispatch({'Net': FakeDispatch({'Zones': zones, 'Matrices': FakeDispatch({'ItemByKey': lambda n: mat})}),
                          'Procedures': proc, 'IO': io})
    audit = WriteAudit(tmp_path / 'a.jsonl')
    g = GuardedCOM(visum, 'Visum', audit)
    for attr in GENERATION_ATTRS:
        g.Net.Zones.SetMultiAttValues(attr, [[1, 1.0]], False)
    with pytest.raises(WriteForbidden):
        g.Net.Zones.SetMultiAttValues('NOT_ZAHR', [[1, 0.0]], False)
    with pytest.raises(WriteForbidden):
        g.Net.Matrices.ItemByKey(9301).SetValues([[1.0]])
    item = g.Procedures.Operations.GetAll[0]
    item.SetAttValue('ACTIVE', 0)
    assert op.values['ACTIVE'] == 0
    with pytest.raises(WriteForbidden):
        item.SetAttValue('COMMENT', 'x')
    with pytest.raises(WriteForbidden):
        item.TripDistributionParameters.SetAttValue('ACTIVE', 1)
    g.Procedures.Execute()
    assert executed == [1]
    for name in ('SaveVersion', 'LoadVersion'):
        with pytest.raises(WriteForbidden):
            getattr(g.IO, name)('x.ver')
    with pytest.raises(WriteForbidden):
        g.Net.foo = 1
    summary = audit.summary()
    assert summary['tg_attributes_written'] == sorted(GENERATION_ATTRS)
    assert summary['counts']['ZONE_TG_WRITE'] == 9 and summary['counts']['FORBIDDEN'] == 7
    assert len((tmp_path / 'a.jsonl').read_text().splitlines()) == len(audit.events)


def test_guard_fast_path_returns_plain_matrices_unwrapped():
    arr = tuple(tuple(float(i + j) for j in range(50)) for i in range(50))
    assert _plain(arr) and _plain(((1, 2.0), (2, 3.0)))
    assert not _plain((FakeDispatch(),))
    g = GuardedCOM(FakeDispatch({'GetValues': lambda: arr}))
    assert g.GetValues() is arr
