"""LIVE04.10.7: rollback check capture replays the geometry of the restored parent state.

The epoch keeps the previous capture (PREVIOUS) when a fresh one is written.  After a
rejected trial the rollback capture may replay CURRENT or PREVIOUS geometry - only with
the identical path key set and the all-link VOLVEH_DSEG proof of every DSeg.
Synthetic mock only - not native PTV Visum evidence."""
import json
import pytest
from cordon2025.common import ROOT, read_json, ContractError
from cordon2025.visum_startup import preflight
from cordon2025.live04_capture import capture
from cordon2025 import live04_epoch as epm
from cordon2025.live04_config import load_config
from test_live04_6 import setup, _link_volumes, _geometry_reads, _geometry_rows   # noqa: F401 (fixture)


def _cap(setup, out, ep, rollback=False):
    """One capture + epoch bookkeeping exactly as Live02Evaluator.evaluate does it."""
    v, c, _, ctl, opt = setup
    out.mkdir(parents=True, exist_ok=True)
    pre = preflight(v, c, out, ctl, opt); before = _geometry_reads(v)
    o = dict(opt, geometry_proof='FULL', full_proof_method='ALL_LINK_VOLUMES')
    if rollback:
        o['geometry_epoch'] = {'dir': str(ep), 'max_reuse': 3, 'full_proof_replay': True, 'include_previous': True}
    cache, evidence = capture(v, c, out, ctl, o, pre)
    ev = json.loads(evidence.read_text())
    ge = ev['geometry_epoch']
    if 'PREVIOUS' in (ge.get('source_by_mode') or {}).values() and not ge['fresh_modes']:
        epm.promote_previous(ep)
    epm.write_epoch(ep, cache, pre[0]['network_sha256'], ge['edge_dictionary_sha256'], ge['mode_audits'],
                    ge['fresh_modes'], ge['reused_modes'], 'ROLLBACK' if rollback else 'TRIAL', keep_previous=True)
    return ev, _geometry_reads(v) - before, cache


def test_fresh_capture_keeps_the_previous_epoch(setup, tmp_path):
    v = setup[0]; _link_volumes(v); ep = tmp_path / 'GEOMETRY_EPOCH'
    _cap(setup, tmp_path / 'a', ep)
    assert epm.meta(ep) and epm.meta(epm.previous_dir(ep)) is None
    _cap(setup, tmp_path / 'b', ep)
    assert epm.meta(ep)['written_from_label'] == 'TRIAL' and epm.meta(epm.previous_dir(ep)) is not None


def test_rollback_replays_parent_geometry_from_previous(setup, tmp_path):
    v = setup[0]; ep = tmp_path / 'GEOMETRY_EPOCH'
    _link_volumes(v)
    ev_parent, reads_parent, c_parent = _cap(setup, tmp_path / 'parent', ep)          # accepted state
    parent_routes = dict(v.routes)
    v.routes['C_NOT'] = v.routes['C_NOT'][::-1]; _link_volumes(v)                      # trial: other paths
    _, reads_trial, _ = _cap(setup, tmp_path / 'trial', ep)
    v.routes.update(parent_routes); _link_volumes(v)                                   # rollback restores
    ev, reads, c_rb = _cap(setup, tmp_path / 'rollback', ep, rollback=True)
    assert reads_parent > 0 and reads_trial > 0 and reads == 0                         # no geometry COM read
    ge = ev['geometry_epoch']
    assert sorted(ge['reused_modes']) == ['C', 'C_NOT']
    assert ge['source_by_mode']['C_NOT'] == 'PREVIOUS'
    checks = [x for x in ge['checks'] if x['mode'] == 'C_NOT']
    assert [(x['epoch'], x.get('status')) for x in checks] == [('CURRENT', 'MISMATCH'), ('PREVIOUS', 'PASS')]
    assert ev['geometry_identity_basis'] == 'EPOCH_REPLAY_ALL_LINK_VOLUME_CROSSCHECKED_THIS_CAPTURE'
    assert _geometry_rows(c_rb) == _geometry_rows(c_parent)
    # the parent epoch is CURRENT again, the trial epoch is PREVIOUS
    cur = epm.meta(ep); prev = epm.meta(epm.previous_dir(ep))
    assert cur['last_reuse_label'] == 'ROLLBACK' and prev is not None


def test_second_trial_after_rollback_still_finds_the_parent(setup, tmp_path):
    v = setup[0]; ep = tmp_path / 'GEOMETRY_EPOCH'; _link_volumes(v)
    _, _, c_parent = _cap(setup, tmp_path / 'parent', ep)
    parent = dict(v.routes)
    for k in (1, 2):
        v.routes['C_NOT'] = parent['C_NOT'][::-1]; _link_volumes(v)
        _cap(setup, tmp_path / ('trial%d' % k), ep)
        v.routes.update(parent); _link_volumes(v)
        ev, reads, c_rb = _cap(setup, tmp_path / ('rb%d' % k), ep, rollback=True)
        assert reads == 0 and _geometry_rows(c_rb) == _geometry_rows(c_parent)


def test_rollback_with_other_paths_reads_geometry_from_visum(setup, tmp_path):
    """Neither epoch matches the restored assignment -> normal COM read (no replay)."""
    v = setup[0]; ep = tmp_path / 'GEOMETRY_EPOCH'; _link_volumes(v)
    _cap(setup, tmp_path / 'parent', ep)
    v.routes['C_NOT'] = v.routes['C_NOT'][::-1]; _link_volumes(v)
    _cap(setup, tmp_path / 'trial', ep)
    _link_volumes(v, scale=1.5)                                    # volumes no epoch explains
    ev, reads, _ = _cap(setup, tmp_path / 'rollback', ep, rollback=True)
    assert reads > 0 and ev['geometry_epoch']['reused_modes'] == []
    assert all(x.get('status') == 'MISMATCH' for x in ev['geometry_epoch']['checks'])


def test_trial_and_baseline_captures_never_replay(tmp_path):
    src = (ROOT / 'cordon2025/live02_evaluation.py').read_text(encoding='utf-8')
    assert "rollback_replay = bool(epoch.get('rollback_replay')) and str(label) == 'ROLLBACK'" in src
    assert "(geometry_proof != 'FULL' or rollback_replay)" in src


def test_release_config_enables_rollback_replay():
    cfg = load_config()
    assert cfg['evaluation']['geometry_epoch']['rollback_replay'] is True
    assert read_json(ROOT / 'provenance/live04_user_config/CORDON_LIVE04_CONFIG.RELEASE_DEFAULT.json')[
        'evaluation']['geometry_epoch'] == cfg['evaluation']['geometry_epoch']
    with pytest.raises(ContractError, match='LIVE02_INVALID_GEOMETRY_EPOCH_ROLLBACK_REPLAY'):
        load_config(overrides={'evaluation': {'geometry_epoch': {'rollback_replay': 'yes'}}})


def test_failed_directory_renames_never_break_the_run(setup, tmp_path, monkeypatch):
    """Windows may refuse a directory rename (open handle, antivirus): rotation and swap are
    best effort - the epochs stay usable and every replay is still proven."""
    import os as _os
    v = setup[0]; ep = tmp_path / 'GEOMETRY_EPOCH'; _link_volumes(v)
    _cap(setup, tmp_path / 'parent', ep)
    real = _os.replace

    def refuse(src, dst):
        if 'GEOMETRY_EPOCH' in str(src) and not str(src).endswith('.tmp'):
            raise PermissionError('locked')
        return real(src, dst)
    monkeypatch.setattr(epm.os, 'replace', refuse)
    monkeypatch.setattr(epm, '_retry', lambda fn, attempts=5, delay=0.5: fn())
    ev, reads, _ = _cap(setup, tmp_path / 'trial', ep)               # rotation refused -> CURRENT overwritten
    assert epm.meta(ep)['written_from_label'] == 'TRIAL' and epm.meta(epm.previous_dir(ep)) is None
    assert epm.promote_previous(ep) is False and epm.meta(ep) is not None
