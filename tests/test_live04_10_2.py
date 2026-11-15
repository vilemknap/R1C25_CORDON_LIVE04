"""LIVE04.10.2: cheaper FULL capture (user decision 2026-11-05).

The full proof no longer re-reads the path-link hierarchy of every same-mode DSeg (~50 min native).
It reads the representative DSeg's geometry once per mode and proves the other DSegs by
(1) the identical path key set (collector: FULL_PARENT_KEYS_DIFFER) and
(2) VOLVEH_DSEG(code,AP) on ALL network links = volume implied by the read geometry x the DSeg's own path volumes.
Any mismatch falls back to the original full read in the same capture.  The accepted trade-off: the
LIVE04.7.1 counterexample (swapped paths with identical all-link volumes) is not detected by (2).
Synthetic mock only - NOT native PTV Visum evidence.
"""
import json

import pytest

from cordon2025.common import ContractError
from cordon2025.visum_startup import preflight
from cordon2025.live04_capture import capture, ALL_LINK_BASIS
from cordon2025 import live04_confirm as lc
from cordon2025.live04_config import load_config
from test_live04_7 import setup, crossing_network, equal_od_volumes, link_volumes, first_last_pairs, stations  # noqa: F401


def _run(v, c, folder, ctl, opt):
    folder.mkdir(parents=True, exist_ok=True)
    cache, evidence = capture(v, c, folder, ctl, opt, preflight(v, c, folder, ctl, opt))
    return cache, json.loads(evidence.read_text())


def test_all_link_proof_gives_the_same_store_as_reading_every_dseg(setup, tmp_path):
    v, c, out, ctl, opt = setup
    A, B, _ = crossing_network(v)
    v.routes['C'] = A; equal_od_volumes(v, 'C'); link_volumes(v)
    full = dict(opt, geometry_proof='FULL')
    old, ev_old = _run(v, c, tmp_path / 'old', ctl, dict(full, full_proof_method='READ_ALL_DSEGS'))
    new, ev_new = _run(v, c, tmp_path / 'new', ctl, dict(full, full_proof_method='ALL_LINK_VOLUMES'))
    assert ev_old['geometry_identity_basis'] == lc.FULL_BASIS
    assert ev_new['geometry_identity_basis'] == ALL_LINK_BASIS and lc.is_fully_proven(
        {'geometry_identity_basis': ev_new['geometry_identity_basis']})
    assert 'geometry_full_proof' in ev_old['capture_timing_seconds']
    assert 'geometry_full_proof' not in ev_new['capture_timing_seconds']
    assert 'geometry_all_link_proof' in ev_new['capture_timing_seconds']
    proofs = ev_new['geometry_all_link_proofs']
    assert proofs and all(p['status'] == 'PASS' for p in proofs) and proofs[0]['compared_link_values'] > 0
    checks = {x['check'] for x in ev_new['full_geometry_checks']}
    assert 'ALL_LINK_VOLUME_MATCH' in checks and 'FULL_SAME_MODE_MATCH' not in checks
    st = stations(v)
    for mode in ('C',):
        assert first_last_pairs(old, st, mode) == first_last_pairs(new, st, mode)
    assert ev_old['final_path_volume_signature'] == ev_new['final_path_volume_signature']


def test_differently_routed_dseg_with_other_volumes_falls_back_and_is_refused(setup, tmp_path):
    v, c, out, ctl, opt = setup
    A, B, _ = crossing_network(v)
    v.routes['C'] = A
    v.override = {'NATIVE_CS': B}
    equal_od_volumes(v, 'C')
    for code, ds in v.dsegs.items():                  # unequal OD volumes -> link volumes differ
        if code.upper().startswith('NATIVE_CS') and 'NOT' not in code.upper():
            ds.ODMatrix.values[0, 1] = 15.0; ds.ODMatrix.values[1, 2] = 4.0
    link_volumes(v)
    with pytest.raises(Exception, match='FULL_SAME_MODE_GEOMETRY_DIFFERS'):
        _run(v, c, tmp_path / 'x', ctl, dict(opt, geometry_proof='FULL', full_proof_method='ALL_LINK_VOLUMES'))
    proof = json.loads((tmp_path / 'x' / 'GEOMETRY_ALL_LINK_PROOF.json').read_text())
    assert proof[0]['status'] == 'MISMATCH' and proof[0]['fallback'] == 'FULL_SAME_MODE_GEOMETRY_PROOF'


def test_documented_trade_off_the_swapped_paths_counterexample_passes(setup, tmp_path):
    """Accepted by the user: identical all-link volumes with swapped paths are not detected by the cheap
    proof (the old READ_ALL_DSEGS method refuses it, test_live04_7)."""
    v, c, out, ctl, opt = setup
    A, B, _ = crossing_network(v)
    v.routes['C'] = A
    v.override = {'NATIVE_CS': B}
    equal_od_volumes(v, 'C'); link_volumes(v)
    _, ev = _run(v, c, tmp_path / 'y', ctl, dict(opt, geometry_proof='FULL', full_proof_method='ALL_LINK_VOLUMES'))
    assert ev['geometry_identity_basis'] == ALL_LINK_BASIS
    with pytest.raises(Exception, match='FULL_SAME_MODE_GEOMETRY_DIFFERS'):
        _run(v, c, tmp_path / 'z', ctl, dict(opt, geometry_proof='FULL', full_proof_method='READ_ALL_DSEGS'))


def test_trial_captures_are_unchanged(setup, tmp_path):
    """The station cross-check of trials is not affected by the full-proof method."""
    v, c, out, ctl, opt = setup
    A, B, _ = crossing_network(v)
    v.routes['C'] = A; equal_od_volumes(v, 'C'); link_volumes(v)
    _, ev = _run(v, c, tmp_path / 't', ctl, dict(opt, full_proof_method='ALL_LINK_VOLUMES'))
    assert ev['geometry_identity_basis'] == 'STATION_LINK_VOLUME_CROSSCHECKED_THIS_CAPTURE'
    assert not ev['geometry_all_link_proofs']


def test_config_default_and_validation():
    assert load_config()['evaluation']['full_geometry_proof'] == 'ALL_LINK_VOLUMES'
    assert load_config(overrides={'evaluation': {'full_geometry_proof': 'READ_ALL_DSEGS'}})
    with pytest.raises(ContractError, match='FULL_GEOMETRY_PROOF'):
        load_config(overrides={'evaluation': {'full_geometry_proof': 'NOPE'}})


def test_unknown_method_refused_by_capture(setup, tmp_path):
    v, c, out, ctl, opt = setup
    with pytest.raises(ContractError, match='UNKNOWN_FULL_PROOF_METHOD'):
        _run(v, c, tmp_path / 'u', ctl, dict(opt, geometry_proof='FULL', full_proof_method='X'))


# ------------------------------------------------------------------ LIVE04.10.3
def test_final_readback_by_link_volumes_gives_the_identical_signature(setup, tmp_path):
    """The signature from the start read + the all-link re-read equals the one from re-reading 12 path lists
    (exact floats, the evaluator and the rollback proof compare it bit for bit)."""
    from cordon2025.live02_evaluation import path_volume_signature
    v, c, out, ctl, opt = setup
    A, B, _ = crossing_network(v)
    v.routes['C'] = A; equal_od_volumes(v, 'C'); link_volumes(v)
    full = dict(opt, geometry_proof='FULL', full_proof_method='ALL_LINK_VOLUMES')
    _, old = _run(v, c, tmp_path / 'old', ctl, dict(full, final_readback='PATH_LISTS'))
    _, new = _run(v, c, tmp_path / 'new', ctl, dict(full, final_readback='ALL_LINK_VOLUMES'))
    assert old['final_readback_basis'] == 'PATH_LISTS' and new['final_readback_basis'] == 'ALL_LINK_VOLUMES'
    assert new['final_path_volume_signature'] == old['final_path_volume_signature']
    pre = preflight(v, c, tmp_path / 'new', ctl, full)
    assert path_volume_signature(v, pre[4], ctl, full) == new['final_path_volume_signature']


def test_link_volume_change_during_capture_is_refused(setup, tmp_path, monkeypatch):
    from cordon2025 import live04_capture as cap
    v, c, out, ctl, opt = setup
    A, B, _ = crossing_network(v)
    v.routes['C'] = A; equal_od_volumes(v, 'C'); link_volumes(v)
    orig = cap._all_link_volumes; calls = []

    def changing(visum, dsegs, control, o, cache):
        calls.append(1)
        if len(calls) > 2:                       # the final re-read sees a changed model
            for row in visum.Net.Links.rows:
                for k in list(row):
                    if k.startswith('VOLVEH_DSEG('):
                        row[k] = row[k] + 1.0
        return orig(visum, dsegs, control, o, cache)
    monkeypatch.setattr(cap, '_all_link_volumes', changing)
    with pytest.raises(ContractError, match='LINK_VOLUMES_CHANGED_DURING_CAPTURE'):
        _run(v, c, tmp_path / 'x', ctl, dict(opt, geometry_proof='FULL', full_proof_method='ALL_LINK_VOLUMES',
                                             final_readback='ALL_LINK_VOLUMES'))


def test_final_readback_falls_back_without_all_link_proof(setup, tmp_path):
    v, c, out, ctl, opt = setup
    A, B, _ = crossing_network(v)
    v.routes['C'] = A; equal_od_volumes(v, 'C'); link_volumes(v)
    _, ev = _run(v, c, tmp_path / 's', ctl, dict(opt, final_readback='ALL_LINK_VOLUMES'))      # station cross-check
    assert ev['final_readback_basis'] == 'PATH_LISTS'
    _, ev = _run(v, c, tmp_path / 'r', ctl, dict(opt, geometry_proof='FULL', full_proof_method='READ_ALL_DSEGS',
                                                 final_readback='ALL_LINK_VOLUMES'))
    assert ev['final_readback_basis'] == 'PATH_LISTS'


def test_trial_proven_by_all_links_needs_no_confirmation(tmp_path):
    diag = {'valid': True, 'geometry_identity_basis': ALL_LINK_BASIS, 'full_geometry_check': True}

    class A:
        class evaluator:
            @staticmethod
            def evaluate(*a, **k):
                raise AssertionError('no confirmation capture expected')
    out = lc.confirm_before_accept(A(), tmp_path / 'C', diag, {}, lambda d: (0.0, {'accepted': True}), True)
    assert out[0] is diag and out[3]['status'] == 'NOT_REQUIRED_FULL_GEOMETRY_CAPTURE'


def test_release_config_trials_full_and_fast_final_readback():
    ev = load_config()['evaluation']
    assert ev['trial_geometry_proof'] == 'FULL' and ev['full_geometry_proof'] == 'ALL_LINK_VOLUMES'
    assert ev['final_readback'] == 'ALL_LINK_VOLUMES'
    with pytest.raises(ContractError, match='FINAL_READBACK'):
        load_config(overrides={'evaluation': {'final_readback': 'NOPE'}})
