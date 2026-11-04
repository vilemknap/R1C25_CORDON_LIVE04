"""LIVE04.6: faster trial capture - station-link volume cross-check instead of re-reading
the full path-link hierarchy of every same-mode DSeg.  Synthetic mock only."""
import json
import pytest
from cordon2025.common import ROOT, read_config, parent_core
from cordon2025.visum_startup import preflight, settings, ReadControl
from cordon2025.live04_capture import capture
from fake_visum_startup import FakeVisum


def _link_volumes(v, scale=1.0):
    """Per-DSeg VOLVEH_DSEG(code,AP) exactly as the fixture's own path lists imply."""
    core = parent_core()
    for row in v.Net.Links.rows:
        for code in v.dsegs:
            row['VOLVEH_DSEG(%s,AP)' % code] = 0.0
    index = {(r['NO'], r['FROMNODENO'], r['TONODENO']): r for r in v.Net.Links.rows}
    for code, ds in v.dsegs.items():
        mode = core.norm_code(ds.mode)
        paths = v.routes[mode]
        if v.same_mode_geometry_mismatch and core.norm_code(code) == 'EXOG_EE_CF':
            paths = paths[::-1]
        vols = [float(ds.ODMatrix.values[0, 1]), float(ds.ODMatrix.values[1, 2])]
        for edges, q in zip(paths, vols):
            for key in edges:
                index[tuple(key)]['VOLVEH_DSEG(%s,AP)' % code] += q * scale


@pytest.fixture
def setup(tmp_path):
    v = FakeVisum(tmp_path / 'model'); out = tmp_path / 'out'; out.mkdir()
    cfg = read_config(ROOT / 'CORDON_2025_AGGRESSIVE_CONFIG.json')
    opt = settings({'page_size': 2, 'min_free_disk_gib': 0, 'com_retry_attempts': 64,
                    'com_retry_initial_delay_seconds': 0., 'com_retry_max_delay_seconds': 0.})
    opt = dict(opt, geometry_proof='STATION_LINK_VOLUME_CROSSCHECK')
    return v, cfg, out, ReadControl(out), opt


def _geometry_reads(v):
    return sum(n for (kind, _), n in v.list_counts.items() if kind == 'geometry')


def test_crosscheck_pass_reads_geometry_once_per_mode(setup):
    v, c, out, ctl, opt = setup; _link_volumes(v)
    pre = preflight(*setup); before = _geometry_reads(v)
    cache, evidence = capture(v, c, out, ctl, opt, pre)
    ev = json.loads(evidence.read_text())
    assert ev['geometry_identity_basis'] == 'STATION_LINK_VOLUME_CROSSCHECKED_THIS_CAPTURE'
    checks = [x['check'] for x in ev['full_geometry_checks']]
    assert len(checks) == 12 and checks.count('FULL_REPRESENTATIVE') == 2
    assert checks.count('STATION_LINK_VOLUME_MATCH') == 10
    assert all(x['status'] == 'PASS' for x in ev['geometry_station_crosschecks'])
    assert _geometry_reads(v) - before == 2             # was 12 with the full proof
    assert 'geometry_representative' in ev['capture_timing_seconds']
    assert (out / 'CAPTURE_TIMING.json').is_file()
    assert not v.writes and not v.unbounded


def test_full_proof_reads_every_dseg(setup):
    v, c, out, ctl, opt = setup; _link_volumes(v)
    pre = preflight(*setup); before = _geometry_reads(v)
    capture(v, c, out, ctl, dict(opt, geometry_proof='FULL'), pre)
    assert _geometry_reads(v) - before == 12


def test_crosscheck_mismatch_falls_back_to_full_proof_and_fails_closed(setup):
    v, c, out, ctl, opt = setup; v.same_mode_geometry_mismatch = True; _link_volumes(v)
    with pytest.raises(Exception, match='FULL_SAME_MODE_GEOMETRY_DIFFERS'):
        capture(v, c, out, ctl, opt, preflight(*setup))
    xc = json.loads((out / 'GEOMETRY_CROSSCHECK.json').read_text())
    assert any(x['status'] == 'MISMATCH' and x['fallback'] == 'FULL_SAME_MODE_GEOMETRY_PROOF' for x in xc)
    assert not (out / 'SNAPSHOT_EVIDENCE.json').exists()


def test_attribute_not_readable_falls_back_to_full_proof(setup):
    v, c, out, ctl, opt = setup                       # no VOLVEH_DSEG attributes in the fixture
    pre = preflight(*setup); before = _geometry_reads(v)
    cache, evidence = capture(v, c, out, ctl, opt, pre)
    ev = json.loads(evidence.read_text())
    assert ev['geometry_identity_basis'] == 'FULL_SAME_MODE_GEOMETRY_COMPARED_THIS_CAPTURE'
    assert all(x['status'] == 'UNAVAILABLE' for x in ev['geometry_station_crosschecks'])
    assert _geometry_reads(v) - before == 12


def test_unit_mismatch_on_representative_falls_back(setup):
    v, c, out, ctl, opt = setup; _link_volumes(v, scale=2.0)   # e.g. PCU instead of vehicles
    cache, evidence = capture(v, c, out, ctl, opt, preflight(*setup))
    ev = json.loads(evidence.read_text())
    assert ev['geometry_identity_basis'] == 'FULL_SAME_MODE_GEOMETRY_COMPARED_THIS_CAPTURE'
    assert all(x['status'] == 'MISMATCH' for x in ev['geometry_station_crosschecks'])


def test_config_enables_crosscheck_for_trials_only():
    cfg = json.loads((ROOT / 'CORDON_LIVE04_CONFIG.json').read_text(encoding='utf-8'))
    assert cfg['evaluation']['trial_geometry_proof'] == 'STATION_LINK_VOLUME_CROSSCHECK'
    src = (ROOT / 'cordon2025/live02_evaluation.py').read_text(encoding='utf-8')
    assert "if str(label) == 'BASELINE':\n            geometry_proof = 'FULL'" in src


def test_config_rejects_unknown_proof_mode():
    from cordon2025 import live02_config
    src = (ROOT / 'cordon2025/live02_config.py').read_text(encoding='utf-8')
    assert 'LIVE02_INVALID_TRIAL_GEOMETRY_PROOF' in src


def test_capture_signature_equals_separate_signature_read(setup):
    from cordon2025.live02_evaluation import path_volume_signature
    v, c, out, ctl, opt = setup; _link_volumes(v)
    pre = preflight(*setup)
    cache, evidence = capture(v, c, out, ctl, opt, pre)
    ev = json.loads(evidence.read_text())
    assert ev['final_path_volume_signature'] == path_volume_signature(v, pre[4], ctl, opt)


# ---------------------------------------------------------------- LIVE04.7 epoch
def _epoch_capture(setup, out, epoch_dir, max_reuse=3, label='STEP1_TRIAL'):
    from cordon2025.live04_epoch import write_epoch
    v, c, _, ctl, opt = setup
    out.mkdir(parents=True, exist_ok=True)
    pre = preflight(v, c, out, ctl, opt); before = _geometry_reads(v)
    o = dict(opt, geometry_epoch={'dir': str(epoch_dir), 'max_reuse': max_reuse})
    cache, evidence = capture(v, c, out, ctl, o, pre)
    ev = json.loads(evidence.read_text())
    ge = ev['geometry_epoch']
    write_epoch(epoch_dir, cache, pre[0]['network_sha256'], ge['edge_dictionary_sha256'], ge['mode_audits'],
                ge['fresh_modes'], ge['reused_modes'], label)
    return ev, _geometry_reads(v) - before, cache


def _geometry_rows(cache):
    import sqlite3
    with sqlite3.connect(cache) as db:
        return db.execute('SELECT mode,orig,dest,path_index,edge_ids,edge_count,sequence_sha256,geometry_kind '
                          'FROM geometry ORDER BY mode,orig,dest,path_index').fetchall()


def test_epoch_replay_reads_no_geometry_and_rebuilds_identical_store(setup, tmp_path):
    v = setup[0]; _link_volumes(v); ep = tmp_path / 'EPOCH'
    ev1, reads1, c1 = _epoch_capture(setup, tmp_path / 'c1', ep)
    assert reads1 == 2 and ev1['geometry_epoch']['reused_modes'] == []
    ev2, reads2, c2 = _epoch_capture(setup, tmp_path / 'c2', ep)
    assert reads2 == 0
    assert sorted(ev2['geometry_epoch']['reused_modes']) == ['C', 'C_NOT']
    assert ev2['geometry_identity_basis'] == 'EPOCH_REPLAY_ALL_LINK_VOLUME_CROSSCHECKED_THIS_CAPTURE'
    assert all(x['status'] == 'PASS' for x in ev2['geometry_epoch']['checks'])
    assert _geometry_rows(c1) == _geometry_rows(c2)
    meta = json.loads((ep / 'EPOCH.json').read_text())
    assert all(m['reuses'] == 1 for m in meta['modes'].values())


def test_epoch_max_reuse_forces_fresh_read(setup, tmp_path):
    v = setup[0]; _link_volumes(v); ep = tmp_path / 'EPOCH'
    _epoch_capture(setup, tmp_path / 'c1', ep, max_reuse=1)
    _, r2, _ = _epoch_capture(setup, tmp_path / 'c2', ep, max_reuse=1)
    ev3, r3, _ = _epoch_capture(setup, tmp_path / 'c3', ep, max_reuse=1)
    assert r2 == 0 and r3 == 2
    assert all(x['reason'] == 'MAX_REUSE_REACHED' for x in ev3['geometry_epoch']['checks'])
    meta = json.loads((ep / 'EPOCH.json').read_text())
    assert all(m['reuses'] == 0 and m['source'] == 'COM_READ' for m in meta['modes'].values())


def test_epoch_changed_routes_same_keys_detected_by_link_volumes(setup, tmp_path):
    v = setup[0]; _link_volumes(v); ep = tmp_path / 'EPOCH'
    _epoch_capture(setup, tmp_path / 'c1', ep)
    v.routes['C_NOT'] = v.routes['C_NOT'][::-1]        # same path keys, different link sequences
    _link_volumes(v)
    ev2, r2, c2 = _epoch_capture(setup, tmp_path / 'c2', ep)
    checks = {x['mode']: x for x in ev2['geometry_epoch']['checks']}
    assert checks['C_NOT']['status'] == 'MISMATCH' and checks['C']['status'] == 'PASS'
    assert ev2['geometry_epoch']['fresh_modes'] == ['C_NOT'] and r2 == 1
    old = [r for r in _geometry_rows(tmp_path / 'c1' / 'p.sqlite') if r[0] == 'C_NOT'] if (tmp_path / 'c1' / 'p.sqlite').exists() else None
    new = [r for r in _geometry_rows(c2) if r[0] == 'C_NOT']
    assert new and (old is None or [r[6] for r in new] != [r[6] for r in old])   # fresh COM sequences stored


def test_epoch_key_set_change_is_not_reused(setup, tmp_path):
    v = setup[0]; _link_volumes(v); ep = tmp_path / 'EPOCH'
    _epoch_capture(setup, tmp_path / 'c1', ep)
    meta = json.loads((ep / 'EPOCH.json').read_text())
    meta['modes']['C']['parent_keys_sha256'] = '0' * 64
    (ep / 'EPOCH.json').write_text(json.dumps(meta))
    ev2, r2, _ = _epoch_capture(setup, tmp_path / 'c2', ep)
    checks = {x['mode']: x for x in ev2['geometry_epoch']['checks']}
    assert checks['C']['reason'] == 'PATH_KEY_SET_CHANGED' and r2 == 1


def test_epoch_unreadable_volumes_fall_back(setup, tmp_path):
    v = setup[0]; ep = tmp_path / 'EPOCH'
    _link_volumes(v)
    _epoch_capture(setup, tmp_path / 'c1', ep)
    for row in v.Net.Links.rows:
        for k in [k for k in row if k.startswith('VOLVEH_DSEG')]:
            del row[k]
    ev2, r2, _ = _epoch_capture(setup, tmp_path / 'c2', ep)
    assert r2 == 12 and ev2['geometry_epoch']['reused_modes'] == []
    assert ev2['geometry_identity_basis'] == 'FULL_SAME_MODE_GEOMETRY_COMPARED_THIS_CAPTURE'


def test_config_epoch_validation():
    cfg = json.loads((ROOT / 'CORDON_LIVE04_CONFIG.json').read_text(encoding='utf-8'))
    assert cfg['evaluation']['geometry_epoch'] == dict(cfg['evaluation']['geometry_epoch'], enabled=True, max_reuse=3)
    src = (ROOT / 'cordon2025/live02_evaluation.py').read_text(encoding='utf-8')
    assert "str(label) != 'BASELINE' and geometry_proof != 'FULL'" in src
