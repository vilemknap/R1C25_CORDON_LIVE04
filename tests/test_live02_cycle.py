"""LIVE02 end-to-end on the synthetic 681-zone host (never native evidence)."""
import csv
import json
import sys
from pathlib import Path
import numpy as np
import pytest
from fake_live02 import Live02Visum
from cordon2025.live02_cycle import run
from cordon2025.session import verify_run
from cordon2025.live02_config import GENERATION_ATTRS

OPT = {'min_free_disk_gib': 0, 'com_retry_initial_delay_seconds': 0., 'com_retry_max_delay_seconds': 0.}


def zone_values(v):
    return {a: [float(r[a]) for r in v.Net.Zones.rows] for a in GENERATION_ATTRS}


LEGACY = {'generation_mode': 'HOTFIX2_BACKTRACKING'}


def go(tmp_path, v, overrides=None):
    """These tests pin the original HOTFIX2 backtracking path (still selectable)."""
    merged = dict(LEGACY); merged.update(overrides or {})
    return run(v, output_root=tmp_path / 'runs', options=OPT, config_overrides=merged)


def folder_of(tmp_path):
    folders = list((tmp_path / 'runs').glob('LIVE02_TG_*'))
    assert len(folders) == 1
    return folders[0]


def result_of(tmp_path):
    return json.loads((folder_of(tmp_path) / '00_RESULT.json').read_text())


def test_accept_first_candidate_end_to_end(tmp_path):
    v = Live02Visum(tmp_path / 'model')
    before = zone_values(v); source_bytes = v.source.read_bytes()
    r = go(tmp_path, v)
    f = Path(r['output_directory'])
    assert r['status'] == 'MOCK_LIVE02_TG_ACCEPTED' and r['accepted_states'] == 1
    assert r['objective_final'] < r['objective_baseline']
    assert not v.writes, v.writes
    assert r['write_audit'].get('FORBIDDEN', 0) == 0 and r['direct_od_matrix_writes'] is False
    # Model stays in the accepted state; parameters exported; source untouched.
    after = zone_values(v)
    rows = list(csv.DictReader((f / 'ACCEPTED_TG_PARAMETERS.csv').open(encoding='utf-8-sig'), delimiter=';'))
    assert len(rows) == r['changed_tg_parameters'] > 0
    for row in rows:
        i = [z['NO'] for z in v.Net.Zones.rows].index(int(row['zone_no']))
        assert after[row['attr']][i] == pytest.approx(float(row['accepted']))
        assert before[row['attr']][i] == pytest.approx(float(row['run_start']))
    assert v.source.read_bytes() == source_bytes and v.saved_versions == [r['saved_version']['path']]
    # Donor transaction evidence.
    trial = f / 'C01_GENERATION' / 'TRY_01'
    proof = json.loads((trial / 'ROLLBACK' / 'ROLLBACK_DIAGNOSTIC_REUSE_PROOF.json').read_text())
    assert proof['passes'] and proof['path_signature_equal']
    rb = json.loads((trial / 'ROLLBACK' / 'ROLLBACK_VERIFICATION.json').read_text())
    assert rb['passes'] and rb['load_version_called'] is False and rb['direct_od_matrix_writes'] is False
    adopt = json.loads((f / 'C01_GENERATION' / 'ADOPTED' / 'ADOPTION_ACCEPTANCE.json').read_text())
    assert adopt['reproducible_vs_evaluation'] is True and adopt['decision']['accepted'] is True
    plan = json.loads((trial / 'ASSIGNMENT' / 'PROCEDURE_EXECUTION_PLAN.json').read_text())
    assert plan['mode'] == 'PHASE_SPECIFIC' and plan['skipped_originally_active_positions'] == [21]
    assert all(o.values['ACTIVE'] for o in v.ops)  # ACTIVE flags restored
    gap = json.loads((trial / 'ASSIGNMENT' / 'ASSIGNMENT_QUALITY_SCOPE_EVIDENCE.json').read_text())
    assert gap['source'] == 'PRT_ASS_QUALITY_LIST' and gap['operation_no'] == 20
    ident = json.loads((f / 'DONOR_TRANSACTION_IDENTITY.json').read_text())
    assert ident['donor_files_modified'] is False and len(ident['functions']) >= 13
    diag = json.loads((trial / 'DIAGNOSTICS' / 'CORDON_DIAGNOSTIC.json').read_text())
    assert all(len(m['model']) == 120 for m in diag['methods'].values())
    assert not (trial / 'DIAGNOSTICS' / 'p.sqlite').exists()  # trial capture DB not retained
    assert (f / 'C01_GENERATION' / 'ADOPTED' / 'DIAGNOSTICS' / 'p.sqlite').exists()
    assert verify_run(f)['completed']
    assert v.executions == 3  # trial, rollback recompute, adoption


def test_all_candidates_worse_restores_exact_baseline(tmp_path):
    v = Live02Visum(tmp_path / 'model'); v.response = -1.0
    before = zone_values(v)
    r = go(tmp_path, v)
    assert r['status'] == 'MOCK_LIVE02_NO_ACCEPTED_TG_CHANGE'
    assert r['last_cycle_status'] == 'CONFIGURED_GENERATION_SEARCH_EXHAUSTED'
    attempts = r['cycles'][0]['attempts']
    assert len(attempts) == 6 and all(a['status'] == 'REJECTED' for a in attempts)
    assert zone_values(v) == before and r['saved_version'] is None and r['model_state'] == 'BASELINE_RESTORED'
    restore = json.loads((Path(r['output_directory']) / 'RESTORE_POINT.json').read_text())
    from cordon2025.common import canonical_hash
    assert r['changed_tg_parameters'] == 0
    assert not v.writes


def failing_gate(monkeypatch):
    from cordon2025.common import parent_module
    base = parent_module('r1_15a2_supply_visum').base
    calls = []
    def gate(design, cfg):
        calls.append(cfg.get('max_generation_pa_relative_gap'))
        return {'passes': False, 'reasons': ['GENERATION_PA_GAP_WORK']}
    monkeypatch.setattr(base, 'generation_apply_gate', gate)
    return calls


def test_pre_apply_gate_shortcut_rejects_without_any_model_write(tmp_path, monkeypatch):
    calls = failing_gate(monkeypatch)
    v = Live02Visum(tmp_path / 'model')
    r = go(tmp_path, v)
    assert calls and all(c == 0.02 for c in calls)
    attempts = r['cycles'][0]['attempts']
    assert all(a['status'] == 'REJECTED' for a in attempts) and r['accepted_states'] == 0
    assert r['gate_events'] == len(attempts) == 6
    assert v.executions == 0 and not [w for w in v.allowed_writes if w[0] == 'ZONE']
    trial = json.loads((Path(r['output_directory']) / 'C01_GENERATION' / 'TRY_01' / 'TRIAL_RESULT.json').read_text())
    assert trial['status'] == 'REJECTED_PRE_APPLY_GATE' and trial['model_mutated'] is False


def test_tgfix_without_shortcut_uses_donor_rollback_and_continues(tmp_path, monkeypatch):
    failing_gate(monkeypatch)
    v = Live02Visum(tmp_path / 'model')
    r = go(tmp_path, v, {'generation_search': {'pre_apply_gate_shortcut': False, 'max_trials': 2}})
    attempts = r['cycles'][0]['attempts']
    assert [a['status'] for a in attempts] == ['REJECTED', 'REJECTED']
    assert all(a['error'] == 'GENERATION_GATE:GENERATION_PA_GAP_WORK' for a in attempts)
    assert v.executions == 2  # donor rollback recompute after each gated attempt
    assert r['accepted_states'] == 0 and not v.writes


def test_procedure_failure_mid_trial_is_rolled_back(tmp_path):
    v = Live02Visum(tmp_path / 'model'); v.fail_execute_on = {1}
    before = zone_values(v)
    with pytest.raises(Exception, match='NOT_A_PLATEAU'):
        go(tmp_path, v)
    res = result_of(tmp_path)
    assert res['status'] == 'LIVE02_STOPPED_MODEL_VERIFIED_AT_LAST_ACCEPTED_STATE' and res['model_state_verified'] is True
    assert zone_values(v) == before
    trial = json.loads((folder_of(tmp_path) / 'C01_GENERATION' / 'TRY_01' / 'TRIAL_RESULT.json').read_text())
    assert trial['status'] == 'FAILED_BUT_ROLLBACK_VERIFIED' and 'SYNTHETIC_PROCEDURE_FAILURE' in trial['error']


def test_parameter_overwritten_by_procedure_sequence_is_detected(tmp_path):
    v = Live02Visum(tmp_path / 'model'); v.overwrite_after_execute = ('ADD_PROD_W', 0, 9.0); v.overwrite_on = {1}
    before = zone_values(v)
    with pytest.raises(Exception, match='NOT_A_PLATEAU'):
        go(tmp_path, v)
    trial = json.loads((folder_of(tmp_path) / 'C01_GENERATION' / 'TRY_01' / 'TRIAL_RESULT.json').read_text())
    assert 'CANDIDATE_PARAMETERS_OVERWRITTEN' in trial['error']
    assert zone_values(v) == before and result_of(tmp_path)['model_state_verified'] is True


def test_frozen_matrix_change_fails_closed_and_reports_unverified_state(tmp_path):
    v = Live02Visum(tmp_path / 'model'); v.frozen_change_on = {1}
    src = v.source.read_bytes()
    with pytest.raises(Exception, match='ROLLBACK_FAILED_MANUAL_REOPEN'):
        go(tmp_path, v)
    res = result_of(tmp_path)
    assert res['status'] == 'LIVE02_STOPPED_MODEL_STATE_NOT_VERIFIED_REOPEN_SOURCE_OR_SAVED_VERSION'
    trial = json.loads((folder_of(tmp_path) / 'C01_GENERATION' / 'TRY_01' / 'TRIAL_RESULT.json').read_text())
    assert 'DEMAND_MUTATED_FIXED_MATRIX:9116' in trial['primary_error']
    assert v.source.read_bytes() == src and v.saved_versions == []


def test_assignment_gap_not_tight_during_trial(tmp_path):
    v = Live02Visum(tmp_path / 'model'); v.gap_by_execution = {1: 0.05}
    before = zone_values(v)
    with pytest.raises(Exception, match='NOT_A_PLATEAU'):
        go(tmp_path, v)
    trial = json.loads((folder_of(tmp_path) / 'C01_GENERATION' / 'TRY_01' / 'TRIAL_RESULT.json').read_text())
    assert 'ASSIGNMENT_NOT_TIGHT' in trial['error'] and zone_values(v) == before


def test_adoption_not_reproducible_is_rejected_and_rolled_back(tmp_path):
    v = Live02Visum(tmp_path / 'model'); v.response_by_execution = {3: 1.3}
    before = zone_values(v)
    with pytest.raises(Exception, match='ADOPTION_REJECTED'):
        go(tmp_path, v)
    adopt = json.loads((folder_of(tmp_path) / 'C01_GENERATION' / 'ADOPTED' / 'ADOPTION_ACCEPTANCE.json').read_text())
    assert adopt['reproducible_vs_evaluation'] is False
    assert zone_values(v) == before and result_of(tmp_path)['model_state_verified'] is True


def test_user_stop_during_trial_is_deferred_until_rollback(tmp_path):
    v = Live02Visum(tmp_path / 'model')
    def stop(host):
        if host.executions == 1:
            folder_of(tmp_path).joinpath('STOP_REQUESTED').write_text('x')
        else:
            assert host.executions == 2  # rollback recompute still runs
    v.on_execute = stop
    before = zone_values(v)
    with pytest.raises(Exception, match='USER_STOP_REQUESTED'):
        go(tmp_path, v)
    assert zone_values(v) == before and v.executions == 2
    assert result_of(tmp_path)['model_state_verified'] is True


def test_non_isolated_model_name_is_blocked_before_any_write(tmp_path):
    v = Live02Visum(tmp_path / 'model')
    master = v.source.with_name('R1_2025_MASTER.ver'); master.write_bytes(b'X')
    v.IO.CurrentVersionFile = str(master)
    with pytest.raises(Exception, match='LIVE02_OPEN_MODEL_IS_NOT_MARKED_AS_ISOLATED_COPY'):
        go(tmp_path, v)
    assert result_of(tmp_path)['status'] == 'LIVE02_BLOCKED_BEFORE_ANY_WRITE'
    assert v.executions == 0 and not v.allowed_writes


def test_two_cycles_continue_from_accepted_state(tmp_path):
    v = Live02Visum(tmp_path / 'model')
    r = go(tmp_path, v, {'max_tg_cycles': 2})
    assert [c['outer_cycle'] for c in r['cycles']] == [1, 2]
    assert r['cycles'][0]['status'] == 'ACCEPTED'
    if r['cycles'][1]['status'] == 'ACCEPTED':
        assert r['cycles'][1]['objective_before'] == pytest.approx(r['cycles'][0]['objective_after'])
    assert r['objective_final'] <= r['cycles'][0]['objective_after'] + 1e-9
    assert not v.writes


def test_launcher_without_visum_and_bootstrap_import_restoration(tmp_path):
    import RUN_R1_2025_CORDON_LIVE02_TG_CYCLE as entry
    assert entry.main({})['reason'] == 'VISUM_NOT_INJECTED'
    import cordon_live02_bootstrap as bootstrap
    import cordon_visum_bootstrap as original
    v = Live02Visum(tmp_path / 'model')
    path_before = list(sys.path); mods = {k: m for k, m in sys.modules.items() if original._owned(k)}
    result = bootstrap.launch({'Visum': v}, output_root=tmp_path / 'runs', options=OPT,
                              config_overrides={'generation_mode': 'HOTFIX2_BACKTRACKING',
                                                'generation_search': {'max_trials': 1}})
    assert result['status'] == 'MOCK_LIVE02_TG_ACCEPTED', result
    assert list(sys.path) == path_before
    assert {k: m for k, m in sys.modules.items() if original._owned(k)} == mods
    assert not hasattr(sys, '_r1_cordon2025_busy')
