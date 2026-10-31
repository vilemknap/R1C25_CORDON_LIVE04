"""Cordon LIVE02 V24917 variant: targeted fit, STEP1, BNDGEN, LSGEN, COMBUSY2, PERF3."""
import json
import math
from pathlib import Path
import numpy as np
import pytest
from fake_live02 import Live02Visum
from cordon2025.common import parent_module, ROOT, read_json, ContractError
from cordon2025.live02_cycle import run
from cordon2025.live02_config import load_config, validate_config, GENERATION_ATTRS
from cordon2025.session import verify_run
from cordon2025 import live02_v24917 as v17

SUPERSEDED = pytest.mark.skip(reason='SUPERSEDED_IN_LIVE04_TREE: parent/ holds the v7 @ 977cef4 donors; the V24917-mode LIVE02/LIVE03 entrypoints fail closed on their old donor pins by design (docs/live04)')

OPT = {'min_free_disk_gib': 0, 'com_retry_initial_delay_seconds': 0., 'com_retry_max_delay_seconds': 0.}


def zone_values(v, attrs=GENERATION_ATTRS):
    return {a: [float(r[a]) for r in v.Net.Zones.rows] for a in attrs}


def go(tmp_path, v, overrides=None):
    return run(v, output_root=tmp_path / 'runs', options=OPT, config_overrides=overrides)


def folder_of(tmp_path):
    folders = list((tmp_path / 'runs').glob('LIVE02_TG_*')); assert len(folders) == 1
    return folders[0]


def globals_snapshot():
    mb = parent_module('r1_15a2_multiblock'); dp = parent_module('r1_15a2_demand_policy_v1')
    com = parent_module('r1_15a2_com_compat')
    return (list(mb.GENERATION_ATTRS), dict(mb.GENERATION_ATTR_MAP), mb._multiplicative_coefficient_bounds,
            mb._soft_multiplier_bounds, mb._signed_generation_refinement, dp.load_options, com._retry_budget)


@SUPERSEDED
def test_v24917_modules_are_byte_identical_and_options_pinned():
    assert v17.verify_donor_files() == v17.DONOR_FILES
    cfg = load_config()
    assert cfg['generation_mode'] == 'V24917_TARGETED_STEP1'
    src = read_json(ROOT / v17.RUN_OPTIONS_PIN)
    for k, val in cfg['v24917']['run_options'].items():
        assert k == 'fa_enabled' or src[k] == val
    opts = v17.run_options(cfg)
    assert opts['ts_enabled'] and opts['tg_max_trials'] == 3 and opts['bd_zones'] == list(range(650, 681))


@pytest.mark.parametrize('path,value,error', [
    (('v24917', 'run_options', 'ts_robust_margin'), 0.5, 'LIVE02_V24917_RUN_OPTION_DRIFT'),
    (('v24917', 'run_options', 'fa_enabled'), True, 'LIVE02_V24917_NOT_PORTED_OPTION'),
    (('v24917', 'run_options_environment_overrides'), True, 'LIVE02_V24917_ENV_OVERRIDES_FORBIDDEN'),
    (('generation_mode',), 'OTHER', 'LIVE02_GENERATION_MODE'),
])
def test_v24917_config_guards(path, value, error):
    cfg = read_json(ROOT / 'CORDON_LIVE02_CONFIG.json'); node = cfg
    for k in path[:-1]:
        node = node[k]
    node[path[-1]] = value
    with pytest.raises(ContractError, match=error):
        validate_config(cfg)


@SUPERSEDED
def test_step1_targeted_fit_accepts_in_place_with_one_recompute(tmp_path):
    v = Live02Visum(tmp_path / 'model'); before_globals = globals_snapshot()
    r = go(tmp_path, v)
    f = Path(r['output_directory'])
    assert r['status'] == 'MOCK_LIVE02_TG_ACCEPTED' and r['generation_mode'] == 'V24917_TARGETED_STEP1'
    assert v.executions == 1 and not v.writes          # one native recompute, kept in place
    c = f / 'C01_GENERATION'
    assert not (c / 'ADOPTED').exists() and not (c / 'ROLLBACK').exists()
    fit = json.loads((c / 'DESIGN' / 'V24917_TARGETED_GENERATION' / 'V24917_FIT_SUMMARY.json').read_text())
    assert fit['status'] == 'V24917_TARGETED_FIT' and fit['phase'] == 'CATCH_UP' and fit['model_obs_ratio'] < 0.8
    assert fit['fit_summary']['profiles'] > 0 and fit['fit_summary']['rows'] > 0
    plan = json.loads((c / 'STEP1_PLAN_01.json').read_text())
    assert plan['mode'] == 'LINEAR_FIT' and plan['scale'] is not None and plan['predicted_rel_improvement'] > 0
    block = json.loads((c / 'GENERATION_BLOCK_RESULT.json').read_text())
    assert block['adopted_in_place'] is True and block['attempts'][0]['status'] == 'ELIGIBLE'
    assert r['objective_final'] < r['objective_baseline']
    assert r['v24917']['step1']['kept'] == 1 and r['v24917']['step1']['rho'] is not None
    assert (c / 'V24917_TIMING.json').exists() and 'procedure_sequence' in r['v24917']['timing']
    # The trial diagnostic of the accepted state keeps its capture database.
    assert (c / 'TRY_01' / 'DIAGNOSTICS' / 'p.sqlite').exists()
    assert globals_snapshot() == before_globals   # every in-memory V24917 patch removed
    assert verify_run(f)['completed']


@SUPERSEDED
def test_step1_rejected_trials_end_with_verified_full_rollback(tmp_path):
    v = Live02Visum(tmp_path / 'model'); v.response = -1.0
    before = zone_values(v)
    r = go(tmp_path, v)
    assert r['status'] == 'MOCK_LIVE02_NO_ACCEPTED_TG_CHANGE'
    assert zone_values(v) == before
    c = folder_of(tmp_path) / 'C01_GENERATION'
    rb = json.loads((c / 'ROLLBACK' / 'ROLLBACK_VERIFICATION.json').read_text())
    assert rb['passes'] and rb['snapshot_equal']
    block = json.loads((c / 'GENERATION_BLOCK_RESULT.json').read_text())
    assert block['status'] == 'CONFIGURED_GENERATION_SEARCH_EXHAUSTED'
    assert block['attempts'][0]['status'] == 'REJECTED'
    assert not (c / 'TRY_01' / 'DIAGNOSTICS' / 'p.sqlite').exists()   # PERF3: rejected capture removed
    assert v.executions == 1 + 1                                      # trial + final rollback recompute


@SUPERSEDED
def test_step1_overshoot_then_secant_step_accepted(tmp_path):
    v = Live02Visum(tmp_path / 'model'); v.response = 40.0
    r = go(tmp_path, v)
    block = json.loads((folder_of(tmp_path) / 'C01_GENERATION' / 'GENERATION_BLOCK_RESULT.json').read_text())
    statuses = [a['status'] for a in block['attempts']]
    assert statuses[0] == 'REJECTED'
    if 'ELIGIBLE' in statuses:
        assert block['attempts'][statuses.index('ELIGIBLE')]['plan_mode'] == 'SECANT_MEASURED'
        assert block['attempts'][-1]['candidate']['scale'] < block['attempts'][0]['candidate']['scale']
        assert r['accepted_states'] == 1 and not (folder_of(tmp_path) / 'C01_GENERATION' / 'ROLLBACK').exists()
    else:
        assert r['accepted_states'] == 0
    # A second trial first restores the parent parameters by COM only (no recompute).
    if len(statuses) >= 2:
        assert (folder_of(tmp_path) / 'C01_GENERATION' / 'TRY_02' / 'RESTORE_PARENT_PARAMETERS' /
                'ROLLBACK_PARAMETER_READBACK.json').exists()
        assert v.executions == len(statuses) + (0 if 'ELIGIBLE' in statuses else 1)


@SUPERSEDED
def test_step1_pre_apply_gate_rejects_without_writes(tmp_path, monkeypatch):
    base = parent_module('r1_15a2_supply_visum').base
    monkeypatch.setattr(base, 'generation_apply_gate', lambda d, c: {'passes': False, 'reasons': ['GENERATION_PA_GAP_WORK']})
    v = Live02Visum(tmp_path / 'model')
    r = go(tmp_path, v)
    block = json.loads((folder_of(tmp_path) / 'C01_GENERATION' / 'GENERATION_BLOCK_RESULT.json').read_text())
    assert all(a['status'] == 'REJECTED' and a['pre_apply_gate_rejected'] for a in block['attempts'])
    assert v.executions == 0 and not [w for w in v.allowed_writes if w[0] == 'ZONE']
    assert r['accepted_states'] == 0 and r['status'] == 'MOCK_LIVE02_NO_ACCEPTED_TG_CHANGE'


@SUPERSEDED
def test_combusy2_rejected_call_repeats_block_from_intact_parent(tmp_path, monkeypatch):
    cb = parent_module('r1_15a2_combusy2_v24917')
    monkeypatch.setattr(cb, '_pump_sleep', lambda s: None)
    v = Live02Visum(tmp_path / 'model'); v.busy_on = {1}
    r = go(tmp_path, v)
    assert r['status'] == 'MOCK_LIVE02_TG_ACCEPTED'
    f = folder_of(tmp_path)
    assert (f / 'C01_GENERATION' / 'ROLLBACK' / 'ROLLBACK_VERIFICATION.json').exists()   # rolled back first
    assert (f / 'C01_GENERATION_RETRY1' / 'GENERATION_BLOCK_RESULT.json').exists()       # then repeated
    assert v.executions == 3   # failed trial, rollback recompute, repeated trial
    assert cb._STATE['block_retries'] >= 1


@SUPERSEDED
def test_boundary_lever_consistency_and_activation(tmp_path):
    v = Live02Visum(tmp_path / 'model')
    zones = [int(z['NO']) for z in v.Net.Zones.rows]
    crossing = zones[650:681]                 # mock zones without ADD/ZAHR actuator
    r = go(tmp_path, v, {'_allow_donor_overrides': True, 'v24917': {'run_options': {'bd_zones': crossing}}})
    status = json.loads((folder_of(tmp_path) / 'V24917_RUNTIME_STATUS.json').read_text())
    assert status['boundary']['active'] is True and status['boundary']['zones'] == crossing
    bd = parent_module('r1_15a2_boundary_generation_v24917')
    assert all(a in status['generation_attributes'] for a in bd.ALL_ATTRS)
    assert r['v24917']['boundary_active'] is True
    assert not v.writes and parent_module('r1_15a2_multiblock').GENERATION_ATTRS == list(GENERATION_ATTRS)


@SUPERSEDED
def test_boundary_zones_with_add_actuator_are_excluded(tmp_path):
    v = Live02Visum(tmp_path / 'model')
    zones = [int(z['NO']) for z in v.Net.Zones.rows]
    r = go(tmp_path, v, {'_allow_donor_overrides': True, 'v24917': {'run_options': {'bd_zones': zones[:5]}}})
    status = json.loads((folder_of(tmp_path) / 'V24917_RUNTIME_STATUS.json').read_text())
    assert status['boundary']['active'] is False
    assert status['boundary']['audit']['excluded_has_add_or_zahr_actuator'] == zones[:5]


@SUPERSEDED
def test_long_school_lever_rows_are_written_snapshotted_and_restored(tmp_path):
    v = Live02Visum(tmp_path / 'model'); v.enable_long_school(); v.response = -1.0
    attrs = ('ADD_PROD_L', 'ADD_ATT_L', 'ADD_PROD_SCH', 'ADD_ATT_SCH')
    before = zone_values(v, GENERATION_ATTRS + attrs)
    r = go(tmp_path, v)
    status = json.loads((folder_of(tmp_path) / 'V24917_RUNTIME_STATUS.json').read_text())
    assert status['long_school']['active'] is True
    fit = json.loads((folder_of(tmp_path) / 'C01_GENERATION' / 'DESIGN' / 'V24917_TARGETED_GENERATION' /
                      'V24917_FIT_SUMMARY.json').read_text())
    assert fit['long_school']['status'] == 'OK' and fit['long_school']['long_profile_volume'] > 0
    assert r['v24917']['adapter_counts']['extra_rows_written'] > 0
    assert r['accepted_states'] == 0 and zone_values(v, GENERATION_ATTRS + attrs) == before
    summary = json.loads((folder_of(tmp_path) / 'WRITE_AUDIT_SUMMARY.json').read_text())
    assert 'ADD_PROD_L' in summary['tg_attributes_written'] and not summary['forbidden_attempts']


@SUPERSEDED
def test_long_school_accepted_state_contains_extra_attributes(tmp_path):
    v = Live02Visum(tmp_path / 'model'); v.enable_long_school()
    r = go(tmp_path, v)
    assert r['status'] == 'MOCK_LIVE02_TG_ACCEPTED'
    import csv
    rows = list(csv.DictReader((folder_of(tmp_path) / 'ACCEPTED_TG_PARAMETERS.csv').open(encoding='utf-8-sig'), delimiter=';'))
    assert {'ADD_PROD_L'} & {r_['attr'] for r_ in rows}


def test_legacy_hotfix2_mode_still_selectable(tmp_path):
    v = Live02Visum(tmp_path / 'model')
    r = go(tmp_path, v, {'generation_mode': 'HOTFIX2_BACKTRACKING'})
    assert r['generation_mode'] == 'HOTFIX2_BACKTRACKING' and r['v24917'] is None
    assert (folder_of(tmp_path) / 'C01_GENERATION' / 'ADOPTED').exists() and v.executions == 3
