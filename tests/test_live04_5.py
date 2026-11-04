"""LIVE04.5.1: frozen-path predictor anchored on the captured rows.

Live run 2026-11-03 stopped with LIVE03_PREDICTOR_BASE_PARITY_FAIL (max 0.59 %):
Visum path volumes sit on a 0.001 lattice, the OD matrices do not, so
share * Q(parent) is not bit-identical to the captured rows.  Synthetic only.
"""
import json
import numpy as np
import pytest
from cordon2025.common import ContractError
from cordon2025 import live03_predictor as lp


class Frozen:
    """Two rows, one dseg, three ODs; row = sum share * Q."""
    def __init__(self, row, od, share):
        self.row, self.od, self.share = np.array(row), od, np.array(share, dtype=float)

    def predict(self, matrices, zone_nos):
        q = np.array([matrices['A'][o, d] for o, d in self.od])
        return np.bincount(self.row, weights=self.share * q, minlength=2)


def predictor(tmp_path, m0, matrices):
    p = object.__new__(lp.FrozenPathPredictor)
    p.methods = ('FIRST_LAST',)
    p.frozen = {'FIRST_LAST': Frozen([0, 0, 1], [(0, 1), (1, 0), (1, 2)], [1.0, 0.5, 1.0])}
    p.zone_nos = [1, 2, 3]
    p.m0 = {'FIRST_LAST': np.array(m0, dtype=float)}
    p.tolerance = 1e-6
    p.offset = None
    p.support = {}
    p.folder = tmp_path
    p.calls = 0; p.seconds = 0.0; p.records = []
    p.read_matrices = lambda: {'A': matrices}
    return p


def test_quantization_deviation_is_anchored_and_reported(tmp_path):
    q = np.zeros((3, 3)); q[0, 1] = 100.0004; q[1, 0] = 40.0; q[1, 2] = 12.0
    # captured rows from 0.001-lattice path volumes: 100.000 + 20.000 and 11.93 (0.58 %)
    p = predictor(tmp_path, [120.0, 11.93], q)
    audit = p.base_parity()
    assert audit['passes'] and audit['mode'] == 'ANCHORED_ON_CAPTURED_ROWS'
    raw = audit['raw_share_times_matrix_deviation']
    assert raw['max_relative_error_floor_1']['FIRST_LAST'] > 5e-3        # the live failure size
    assert raw['passes'] and json.loads((tmp_path / 'PREDICTOR_BASE_PARITY.json').read_text())['passes']
    # parent reproduces the captured rows exactly; a candidate carries only its demand change
    rows, _ = p.predict_from({'A': q}, 'PARENT')
    assert np.allclose(rows['FIRST_LAST'], [120.0, 11.93], atol=1e-12)
    cand = q.copy(); cand[1, 2] = 15.0; cand[0, 1] = 110.0004
    rows, _ = p.predict_from({'A': cand}, 'CANDIDATE')
    assert np.allclose(rows['FIRST_LAST'], [130.0, 14.93], atol=1e-9)


def test_large_raw_deviation_still_stops(tmp_path):
    q = np.zeros((3, 3)); q[0, 1] = 100.0; q[1, 0] = 40.0; q[1, 2] = 12.0
    p = predictor(tmp_path, [120.0, 30.0], q)          # paths do not belong to these matrices
    with pytest.raises(ContractError, match='LIVE03_PREDICTOR_RAW_SHARE_DEVIATION_TOO_LARGE'):
        p.base_parity()
    assert p.offset is None
    with pytest.raises(ContractError, match='LIVE03_PREDICTOR_BASE_PARITY_NOT_RUN'):
        p.predict_from({'A': q}, 'X')


def test_total_bias_limit(tmp_path):
    # every row off by 1 % (inside the row limit) -> systematic, not quantization
    q = np.zeros((3, 3)); q[0, 1] = 100.0; q[1, 0] = 40.0; q[1, 2] = 120.0
    p = predictor(tmp_path, [120.0 * 1.01, 120.0 * 1.01], q)
    with pytest.raises(ContractError, match='LIVE03_PREDICTOR_RAW_SHARE_DEVIATION_TOO_LARGE'):
        p.base_parity()


# ------------------------------------------------------------------ LIVE04.5.2
from pathlib import Path
from fake_live04 import Live04Visum
from cordon2025.common import read_json
from cordon2025.live04_cycle import run
from cordon2025 import live02_adapter as la
from cordon2025 import live02_evaluation as le

OPT = {'min_free_disk_gib': 0, 'com_retry_initial_delay_seconds': 0., 'com_retry_max_delay_seconds': 0.}
RELAX = {'idp_guard': {'max_fine_cdf_rmse_degradation': 1.0, 'max_mean_error_degradation': 1.0}}
GEN_ONLY = {'blocks_per_cycle': ['GENERATION'], 'td_cordon': {'enabled': False},
            'write_policy': {'td_parameter_writes': False}}


def go(tmp_path, v, overrides=None):
    over = {'max_cycles': 1}
    over.update(overrides or {})
    return run(v, output_root=tmp_path / 'runs', options=OPT, config_overrides=over)


def folder_of(tmp_path):
    folders = list((tmp_path / 'runs').glob('LIVE04_TGTD_*')); assert len(folders) == 1
    return folders[0]


def diag(rows, obj=100.0):
    return {'valid': True, 'methods': {'FIRST_LAST': {'model': list(rows), 'objective': obj}},
            'path_signature': {'X': {'keys_and_volumes_sha256': 'base'}}, '_pre': [None] * 5}


class Evaluator:
    methods = ('FIRST_LAST',)
    control = opt = None

    def __init__(self, captured):
        self.captured = captured; self.calls = 0

    def evaluate(self, visum, folder, label, full_geometry=True, keep_db=True, geometry_proof="FULL"):
        self.calls += 1
        return self.captured


def adapter(captured):
    a = object.__new__(la.CordonTrialAdapter)
    a.live02 = {'evaluation': {'rollback_proof': 'PATH_VOLUME_SIGNATURE_THEN_FULL_CAPTURE',
                               'trial_full_geometry_check': True, 'keep_trial_capture_db': False}}
    a.raw_visum = None
    a.evaluator = Evaluator(captured)
    a.snapshot = lambda: {'state_hash': 'S'}
    return a


def test_rollback_rows_within_tolerance_reuse_parent(tmp_path, monkeypatch):
    monkeypatch.setattr(le, 'path_volume_signature', lambda *a: {'X': {'keys_and_volumes_sha256': 'other'}})
    base = diag([500.0, 12.0, 0.0]); a = adapter(diag([500.4, 12.6, 0.3], 100.05))
    r = a.rollback_diagnostic_equivalence(base, {'state_hash': 'S'}, tmp_path / 'RB')
    assert r['passes'] and r['basis'] == 'EXACT_SNAPSHOT_PLUS_FULL_CAPTURE_ROWS_WITHIN_TOLERANCE'
    assert r['exact_signature_equal'] is False and r['tolerant_rows']['passes']
    # the same (state, signature) is not captured a second time
    r2 = a.rollback_diagnostic_equivalence(base, {'state_hash': 'S'}, tmp_path / 'RB2')
    assert r2['passes'] and r2['basis'].endswith('ALREADY_PROVEN_EQUIVALENT_FOR_THIS_STATE') and a.evaluator.calls == 1


def test_rollback_rows_outside_tolerance_fail_and_capture_is_reused(tmp_path, monkeypatch):
    monkeypatch.setattr(le, 'path_volume_signature', lambda *a: {'X': {'keys_and_volumes_sha256': 'other'}})
    base = diag([500.0, 12.0]); far = diag([520.0, 12.0], 130.0); a = adapter(far)
    r = a.rollback_diagnostic_equivalence(base, {'state_hash': 'S'}, tmp_path / 'RB')
    assert not r['passes'] and r['reason'] == 'ROLLBACK_CORDON_ROWS_OUTSIDE_TOLERANCE'
    assert a.diagnostics(tmp_path / 'D', 'ROLLBACK') is far and a.evaluator.calls == 1   # no second capture


def test_rollback_snapshot_difference_never_uses_tolerance(tmp_path, monkeypatch):
    monkeypatch.setattr(le, 'path_volume_signature', lambda *a: {'X': {'keys_and_volumes_sha256': 'other'}})
    a = adapter(diag([500.0]))
    r = a.rollback_diagnostic_equivalence(diag([500.0]), {'state_hash': 'PARENT'}, tmp_path / 'RB')
    assert not r['passes'] and 'tolerant_rows' not in r and a.evaluator.calls == 0


def _gap_fails_on(monkeypatch, calls):
    sc = la._supply.SupplyContractError
    orig = la.CordonTrialAdapter.gap
    seen = {'n': 0}

    def gap(self):
        seen['n'] += 1
        if seen['n'] in calls:
            raise sc('ASSIGNMENT_NOT_TIGHT: gap=0.05 maximum=0.005 source=TEST')
        return orig(self)
    monkeypatch.setattr(la.CordonTrialAdapter, 'gap', gap)
    return seen


def test_generation_trial_gap_not_tight_is_rejected_and_search_continues(tmp_path, monkeypatch):
    _gap_fails_on(monkeypatch, {1})
    v = Live04Visum(tmp_path / 'model')
    r = go(tmp_path, v, GEN_ONLY)
    gen = read_json(folder_of(tmp_path) / 'C01_GENERATION/GENERATION_BLOCK_RESULT.json')
    assert gen['attempts'][0]['status'] == 'REJECTED_ASSIGNMENT_NOT_TIGHT'
    assert read_json(folder_of(tmp_path) / 'C01_GENERATION/ROLLBACK/ROLLBACK_VERIFICATION.json')['passes']
    assert r['status'] in ('MOCK_LIVE04_ACCEPTED', 'MOCK_LIVE04_NO_ACCEPTED_CHANGE')


def test_td_trial_gap_not_tight_is_rejected_not_fatal(tmp_path, monkeypatch):
    _gap_fails_on(monkeypatch, {1})
    v = Live04Visum(tmp_path / 'model')
    r = go(tmp_path, v, dict(RELAX, blocks_per_cycle=['TD_CORDON']))
    td = read_json(folder_of(tmp_path) / 'C01_TD_CORDON/TD_BLOCK_RESULT.json')
    assert td['status'] == 'TRIAL_REJECTED_ASSIGNMENT_NOT_TIGHT' and td['rollback']['passes']
    assert r['status'] == 'MOCK_LIVE04_NO_ACCEPTED_CHANGE'


def test_predictor_unavailable_falls_back_without_stopping(tmp_path, monkeypatch):
    def fail(self):
        raise ContractError('LIVE03_PREDICTOR_RAW_SHARE_DEVIATION_TOO_LARGE:TEST')
    monkeypatch.setattr(lp.FrozenPathPredictor, 'base_parity', fail)
    v = Live04Visum(tmp_path / 'model')
    r = go(tmp_path, v, dict(RELAX))
    f = folder_of(tmp_path)
    gen = read_json(f / 'C01_GENERATION/GENERATION_BLOCK_RESULT.json')
    assert gen['native_prediction']['status'] == 'UNAVAILABLE_FALLBACK_GENFIX2_FINAL_EFFECT'
    assert gen['prediction_authority'] == 'FINAL_IMPLEMENTED_EFFECT_ROWS'
    td = read_json(f / 'C01_TD_CORDON/TD_BLOCK_RESULT.json')
    assert td['status'] == 'NO_TD_CANDIDATE' and td['stop_reason'] == 'PREDICTOR_UNAVAILABLE'
    assert r['status'].startswith('MOCK_LIVE04_')


def test_stopped_run_saves_last_accepted_state(tmp_path, monkeypatch):
    import cordon2025.live03_td as td

    def boom(*a, **k):
        raise RuntimeError('TEST_TD_BLOCK_FAILURE')
    monkeypatch.setattr(td, 'td_block', boom)
    v = Live04Visum(tmp_path / 'model')
    with pytest.raises(RuntimeError, match='TEST_TD_BLOCK_FAILURE'):
        go(tmp_path, v, dict(RELAX))
    f = folder_of(tmp_path)
    res = read_json(f / '00_RESULT.json')
    assert res['status'] == 'LIVE04_STOPPED_MODEL_VERIFIED_AT_LAST_ACCEPTED_STATE' and res['accepted_states'] == 1
    saved = res['saved_version_at_stop']
    assert saved and '_LIVE04_ACCEPTED_' in saved['path'] and saved['source_sha256_unchanged']
    assert read_json(f / 'SAVED_ACCEPTED_VERSION.json')['path'] == saved['path']


# ------------------------------------------------------------------ LIVE04.5.3 silent
class Pref:
    def __init__(self, values):
        self.values = dict(values); self.sets = []

    def AttValue(self, attr):
        if attr not in self.values:
            raise AttributeError(attr)
        return self.values[attr]

    def SetAttValue(self, attr, value):
        self.sets.append((attr, value)); self.values[attr] = value


class Prefs:
    def __init__(self, gui):
        self.GUI = gui


class SilentHost:
    def __init__(self, gui):
        self.UserPreferences = Prefs(gui)
        self.MessageFileName = r'C:\old\msg.txt'

    def SetMessageFileName(self, name):
        self.MessageFileName = name


def silent_module():
    import importlib.util
    from cordon2025.common import ROOT
    spec = importlib.util.spec_from_file_location('_t_silent', ROOT / 'cordon_visum_silent.py')
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


def test_silent_scope_suppresses_and_restores_exactly(tmp_path):
    import sys
    gui = Pref({'SuppressWarningsDuringProcExec': 0, 'SaveWarningsToErrorFile': 0})
    host = SilentHost(gui); out, err = sys.stdout, sys.stderr
    mod = silent_module()
    with pytest.raises(RuntimeError, match='BOOM'):
        with mod.silent(host, tmp_path) as rep:
            assert gui.values == {'SuppressWarningsDuringProcExec': 1, 'SaveWarningsToErrorFile': 1}
            assert host.MessageFileName == str(tmp_path / 'VISUM_MESSAGES.txt')
            print('hidden from Visum')
            import warnings; warnings.warn('numpy-like warning')
            raise RuntimeError('BOOM')
    assert rep['procedure_warnings'] == 'SUPPRESSED_VERIFIED' and rep['com_path'] == 'UserPreferences.GUI'
    assert gui.values == {'SuppressWarningsDuringProcExec': 0, 'SaveWarningsToErrorFile': 0}   # restored after error
    assert host.MessageFileName == r'C:\old\msg.txt' and rep['restored']
    assert sys.stdout is out and sys.stderr is err
    log = (tmp_path / 'PYTHON_CONSOLE.log').read_text(encoding='utf-8')
    assert 'hidden from Visum' in log and 'numpy-like warning' in log
    assert json.loads((tmp_path / 'SILENT_MODE.json').read_text())['restored'] is True


def test_silent_scope_without_preference_access_does_not_block(tmp_path):
    mod = silent_module()

    class NoPrefs:
        pass
    with mod.silent(NoPrefs(), tmp_path) as rep:
        pass
    assert rep['procedure_warnings'] == 'NOT_ACCESSIBLE' and 'Suppress output of warnings' in rep['manual_setting']


def test_already_silent_preference_is_not_rewritten(tmp_path):
    gui = Pref({'SuppressWarningsDuringProcExec': 1, 'SaveWarningsToErrorFile': 1})
    with silent_module().silent(SilentHost(gui), tmp_path):
        pass
    assert gui.sets == []


def test_launchers_print_nothing(tmp_path, monkeypatch, capsys):
    import cordon_transfer_bootstrap as bootstrap
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'local'))
    r = bootstrap.launch({'Visum': object()}, 'UNKNOWN', output_root=tmp_path / 'runs')
    assert r['status'] == 'TRANSFER2025_UNKNOWN_STOPPED'
    assert capsys.readouterr().out == ''
