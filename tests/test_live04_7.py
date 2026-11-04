"""LIVE04.7.1: accelerated captures can never accept a wrong cordon matrix.

Link volumes do not identify path flows: paths 1->2 and 3->4 give the same station
and even ALL-link volumes as 1->4 and 3->2 when both pairs share links, but a
different FIRST_LAST matrix.  These tests build exactly that counterexample, show
that the accelerated proofs (LIVE04.6 station cross-check, LIVE04.7 epoch) PASS on
it, and prove that the acceptance path decides on an independent full capture.
Synthetic mock only - NOT native PTV Visum evidence.
"""
import json
import sqlite3
import pytest
import fake_visum_startup as fvs
from fake_visum_startup import FakeVisum
from cordon2025.common import ROOT, read_config, parent_core
from cordon2025.authority import mapping
from cordon2025.visum_startup import preflight, settings, ReadControl
from cordon2025.live04_capture import capture
from cordon2025 import live04_confirm as lc

X, Y = 990001, 990002


def crossing_network(v):
    """Stations A,B,C,D and a shared middle link m: A->m->B / C->m->D  vs  A->m->D / C->m->B."""
    idx, _ = mapping(ROOT / 'data/audited/STATION_MAPPING.csv')
    by = {}
    for key, st in idx.items():
        by.setdefault(st, []).append(key)
    sA, sB, sC, sD = (sorted(by[s])[0] for s in (2, 4, 7, 9))
    e1, e3 = (80001, sA[2], X), (80004, sC[2], X)
    m = (80002, X, Y)
    e2, e4 = (80003, Y, sB[1]), (80005, Y, sD[1])
    for key in (e1, e3, m, e2, e4):
        v.Net.Links.rows.append({'NO': key[0], 'FROMNODENO': key[1], 'TONODENO': key[2], 'TSYSSET': 'C,C_noT,LNV,NV'})
    A = [[sA, e1, m, e2, sB], [sC, e3, m, e4, sD]]          # 2->4 and 7->9
    B = [[sA, e1, m, e4, sD], [sC, e3, m, e2, sB]]          # 2->9 and 7->4
    return A, B, {'A': sA, 'B': sB, 'C': sC, 'D': sD}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    v = FakeVisum(tmp_path / 'model'); v.override = {}
    orig = fvs.ListObj.SetObjects

    def set_objects(self, origin, code, routefilter):
        orig(self, origin, code, routefilter)
        norm = parent_core().norm_code(code)
        if self.kind == 'geometry' and norm in self.host.override:
            self.rows = []
            for (o, d), edges in zip([(10, 20), (20, 30)], self.host.override[norm]):
                self.rows.append([o, d, 1, '', '', '', ''])
                for i, key in enumerate(edges, 1):
                    self.rows.append(['', '', '', i, *key])
    monkeypatch.setattr(fvs.ListObj, 'SetObjects', set_objects)
    out = tmp_path / 'out'; out.mkdir()
    cfg = read_config(ROOT / 'CORDON_2025_AGGRESSIVE_CONFIG.json')
    opt = settings({'page_size': 2, 'min_free_disk_gib': 0, 'com_retry_attempts': 64,
                    'com_retry_initial_delay_seconds': 0., 'com_retry_max_delay_seconds': 0.})
    return v, cfg, out, ReadControl(out), dict(opt, geometry_proof='STATION_LINK_VOLUME_CROSSCHECK')


def equal_od_volumes(v, mode, q=15.0):
    for ds in v.dsegs.values():
        if parent_core().norm_code(ds.mode) == mode:
            ds.ODMatrix.values[0, 1] = q; ds.ODMatrix.values[1, 2] = q


def link_volumes(v):
    core = parent_core()
    for row in v.Net.Links.rows:
        for code in v.dsegs:
            row['VOLVEH_DSEG(%s,AP)' % code] = 0.0
    index = {(r['NO'], r['FROMNODENO'], r['TONODENO']): r for r in v.Net.Links.rows}
    for code, ds in v.dsegs.items():
        paths = v.override.get(core.norm_code(code)) or v.routes[core.norm_code(ds.mode)]
        for edges, q in zip(paths, [float(ds.ODMatrix.values[0, 1]), float(ds.ODMatrix.values[1, 2])]):
            for key in edges:
                index[tuple(key)]['VOLVEH_DSEG(%s,AP)' % code] += q


def first_last_pairs(store, station_of, mode):
    """FIRST_LAST station pair per path straight from a capture store (edges decoded)."""
    with sqlite3.connect(store) as db:
        edges = {e: (n, f, t) for e, n, f, t in db.execute('SELECT eid,link_no,from_no,to_no FROM edges')}
        out = []
        for o, d, blob in db.execute('SELECT orig,dest,edge_ids FROM geometry WHERE mode=? ORDER BY orig,dest', (mode,)):
            import array
            a = array.array('I'); a.frombytes(blob)
            hits = [station_of[edges[e]] for e in a if edges[e] in station_of]
            out.append((o, d, hits[0], hits[-1]))
    return out


def stations(v):
    idx, _ = mapping(ROOT / 'data/audited/STATION_MAPPING.csv')
    return idx


def test_station_crosscheck_passes_on_counterexample_but_full_proof_rejects_it(setup):
    v, c, out, ctl, opt = setup
    A, B, _ = crossing_network(v)
    v.routes['C'] = A
    v.override = {'NATIVE_CS': B}                 # non-representative DSeg routed differently
    equal_od_volumes(v, 'C'); link_volumes(v)
    pre = preflight(*setup)
    cache, evidence = capture(v, c, out, ctl, opt, pre)
    ev = json.loads(evidence.read_text())
    assert ev['geometry_identity_basis'] == 'STATION_LINK_VOLUME_CROSSCHECKED_THIS_CAPTURE'   # weakness
    assert not lc.is_fully_proven({'geometry_identity_basis': ev['geometry_identity_basis']})
    # the independent full proof (used before every acceptance) refuses this state
    out2 = out.parent / 'full'; out2.mkdir()
    with pytest.raises(Exception, match='FULL_SAME_MODE_GEOMETRY_DIFFERS'):
        capture(v, c, out2, ctl, dict(opt, geometry_proof='FULL'), preflight(v, c, out2, ctl, opt))


def test_epoch_passes_on_counterexample_full_capture_sees_other_first_last(setup, tmp_path):
    from cordon2025.live04_epoch import write_epoch
    v, c, out, ctl, opt = setup
    A, B, _ = crossing_network(v)
    v.routes['C'] = A; equal_od_volumes(v, 'C'); link_volumes(v)
    ep = tmp_path / 'EPOCH'

    def run(folder, o):
        folder.mkdir(parents=True, exist_ok=True)
        pre = preflight(v, c, folder, ctl, o)
        cache, evidence = capture(v, c, folder, ctl, o, pre)
        ev = json.loads(evidence.read_text()); ge = ev['geometry_epoch']
        write_epoch(ep, cache, pre[0]['network_sha256'], ge['edge_dictionary_sha256'], ge['mode_audits'],
                    ge['fresh_modes'], ge['reused_modes'], 'T')
        return cache, ev
    o = dict(opt, geometry_epoch={'dir': str(ep), 'max_reuse': 3})
    run(tmp_path / 'c1', o)
    v.routes['C'] = B; link_volumes(v)              # same keys, same ALL-link volumes, other pairs
    fast, ev2 = run(tmp_path / 'c2', o)
    assert 'C' in ev2['geometry_epoch']['reused_modes']                     # weakness: epoch accepted it
    assert not lc.is_fully_proven({'geometry_identity_basis': ev2['geometry_identity_basis']})
    full, ev3 = run(tmp_path / 'c3', dict(opt, geometry_proof='FULL'))
    assert ev3['geometry_identity_basis'] == lc.FULL_BASIS
    st = stations(v)
    pf, pt = first_last_pairs(fast, st, 'C'), first_last_pairs(full, st, 'C')
    assert sorted(p[2:] for p in pf) == [(2, 4), (7, 9)]                   # replayed A
    assert sorted(p[2:] for p in pt) == [(2, 9), (7, 4)]                   # true B
    assert pf != pt


# ------------------------------------------------------------ decision on full capture
class _Ev:
    methods = ('FIRST_LAST',)

    def __init__(self, full):
        self.full = full; self.calls = []

    def evaluate(self, visum, folder, label, *, full_geometry, keep_db, geometry_proof):
        self.calls.append((label, full_geometry, geometry_proof)); return self.full


class _Ad:
    raw_visum = None

    def __init__(self, full):
        self.evaluator = _Ev(full)

    def snapshot(self):
        return {'state_hash': 'S'}


def _diag(rows, basis):
    return {'valid': True, 'geometry_identity_basis': basis, 'full_geometry_check': True,
            'methods': {'FIRST_LAST': {'model': rows, 'objective': float(sum(rows))}}}


def _decide(d):
    good = d['methods']['FIRST_LAST']['objective'] < 50
    return {'total': d['methods']['FIRST_LAST']['objective']}, {'accepted': good, 'reasons': [] if good else ['WORSE']}


def test_wrong_fast_matrix_is_rejected_on_full_capture(tmp_path):
    fast = _diag([10.0, 10.0], 'EPOCH_REPLAY_ALL_LINK_VOLUME_CROSSCHECKED_THIS_CAPTURE')
    true = _diag([40.0, 40.0], lc.FULL_BASIS)
    a = _Ad(true)
    _, dec_fast = _decide(fast); assert dec_fast['accepted']                 # the fast matrix would accept
    d, v, dec, audit = lc.confirm_before_accept(a, tmp_path / 'T' / 'DIAGNOSTICS_CONFIRM', fast, {'state_hash': 'S'},
                                                _decide, True)
    assert a.evaluator.calls == [('ACCEPTANCE_CONFIRM', True, 'FULL')]
    assert d is true and not dec['accepted'] and audit['status'] == 'REJECTED_ON_FULL_CAPTURE'
    assert audit['rows']['identical'] is False and audit['decision_basis'] == 'FULL_CAPTURE'
    assert json.loads((tmp_path / 'T' / 'ACCEPTANCE_CONFIRM.json').read_text())['full_decision_accepted'] is False


def test_correct_fast_matrix_is_confirmed_and_full_diag_becomes_state(tmp_path):
    fast = _diag([10.0, 10.0], 'STATION_LINK_VOLUME_CROSSCHECKED_THIS_CAPTURE')
    true = _diag([10.0, 10.0], lc.FULL_BASIS)
    d, v, dec, audit = lc.confirm_before_accept(_Ad(true), tmp_path / 'T' / 'C', fast, {'state_hash': 'S'}, _decide, True)
    assert d is true and dec['accepted'] and audit['status'] == 'CONFIRMED' and audit['rows']['identical']


def test_full_capture_needs_no_confirmation(tmp_path):
    full = _diag([10.0, 10.0], lc.FULL_BASIS); a = _Ad(full)
    d, v, dec, audit = lc.confirm_before_accept(a, tmp_path / 'C', full, {'state_hash': 'S'}, _decide, True)
    assert d is full and dec is None and a.evaluator.calls == []


def test_confirm_must_not_change_model(tmp_path):
    class Moving(_Ad):
        def snapshot(self):
            return {'state_hash': 'OTHER'}
    with pytest.raises(Exception, match='ACCEPTANCE_CONFIRM_CHANGED_MODEL'):
        lc.confirm_before_accept(Moving(_diag([1.0], lc.FULL_BASIS)), tmp_path / 'C',
                                 _diag([1.0], 'EPOCH_REPLAY_ALL_LINK_VOLUME_CROSSCHECKED_THIS_CAPTURE'),
                                 {'state_hash': 'S'}, _decide, True)


def test_every_acceptance_site_confirms_before_accepting():
    """Generation, TD_CORDON and SupplyMix: the accept branch is reached only through
    confirm_before_accept, and the full-capture decision replaces the fast one."""
    for p in ('cordon2025/live04_step1.py', 'cordon2025/live03_td.py', 'cordon2025/live04_supply.py'):
        src = (ROOT / p).read_text(encoding='utf-8')
        i = src.index('after_value, decision = decide(after_diag)')
        j = src.index('confirm_before_accept(', i)
        k = src.index('after_diag, after_value, decision = full, v2, dec2', j)
        assert i < j < k, p
        # the only diagnostics call in a trial is followed by this decision path
        assert src.count("'STEP1_TRIAL')") == 1, p


def test_rollback_and_after_captures_are_always_full():
    src = (ROOT / 'cordon2025/live02_adapter.py').read_text(encoding='utf-8')
    assert src.count("geometry_proof='FULL'") == 2


# ------------------------------------------------------------ full mock cycle (all blocks)
from fake_live04 import Live04Visum
from cordon2025.common import read_json
from cordon2025.live04_cycle import run as cycle_run
from cordon2025 import live02_evaluation as le
from cordon2025 import live02_adapter as la

OPT = {'min_free_disk_gib': 0, 'com_retry_initial_delay_seconds': 0., 'com_retry_max_delay_seconds': 0.}
RELAX = {'idp_guard': {'max_fine_cdf_rmse_degradation': 1.0, 'max_mean_error_degradation': 1.0}}
FAST = 'EPOCH_REPLAY_ALL_LINK_VOLUME_CROSSCHECKED_THIS_CAPTURE'


def _mark_trials_accelerated(monkeypatch, labels):
    orig = le.CordonEvaluator.evaluate

    def evaluate(self, visum, folder, label, **kw):
        d = orig(self, visum, folder, label, **kw)
        labels.append((str(label), kw.get('geometry_proof')))
        if str(label) == 'STEP1_TRIAL':
            d['geometry_identity_basis'] = FAST          # as if the epoch had been replayed
        return d
    monkeypatch.setattr(le.CordonEvaluator, 'evaluate', evaluate)


def _results(root):
    f = list((root / 'runs').glob('LIVE04_TGTD_*')); assert len(f) == 1
    return f[0]


def test_cycle_every_acceptance_is_decided_on_full_capture(tmp_path, monkeypatch):
    labels = []
    _mark_trials_accelerated(monkeypatch, labels)
    v = Live04Visum(tmp_path / 'model')
    r = cycle_run(v, output_root=tmp_path / 'runs', options=OPT, config_overrides=dict(RELAX, max_cycles=1))
    f = _results(tmp_path)
    confirms = list(f.rglob('ACCEPTANCE_CONFIRM.json'))
    accepted = [json.loads(p.read_text()) for p in f.rglob('ACCEPTANCE.json')
                if json.loads(p.read_text()).get('accepted')]
    # every accepted decision carries the full-capture confirmation; none was taken on the fast capture
    assert all(a.get('acceptance_confirm', {}).get('decision_basis') == 'FULL_CAPTURE' for a in accepted)
    assert len(confirms) >= len(accepted)
    assert all(lbl != 'ACCEPTANCE_CONFIRM' or proof == 'FULL' for lbl, proof in labels)
    if accepted:
        assert ('ACCEPTANCE_CONFIRM', 'FULL') in labels
    assert r['status'].startswith('MOCK_LIVE04_')


def test_cycle_fast_capture_that_would_accept_is_overruled(tmp_path, monkeypatch):
    """The gate says YES on every accelerated capture and NO on every full one: nothing may be accepted."""
    labels = []
    _mark_trials_accelerated(monkeypatch, labels)
    orig_gate = la.CordonTrialAdapter.block_gate

    def gate(self, block, before, after, rows):
        dec = dict(orig_gate(self, block, before, after, rows))
        dec['accepted'] = after.get('geometry_identity_basis') == FAST
        dec.setdefault('reasons', []).append('TEST_GATE')
        return dec
    monkeypatch.setattr(la.CordonTrialAdapter, 'block_gate', gate)
    orig_ledger = None
    v = Live04Visum(tmp_path / 'model')
    r = cycle_run(v, output_root=tmp_path / 'runs', options=OPT,
                  config_overrides=dict(RELAX, max_cycles=1, blocks_per_cycle=['GENERATION'],
                                        td_cordon={'enabled': False}, write_policy={'td_parameter_writes': False}))
    f = _results(tmp_path)
    assert r['status'] == 'MOCK_LIVE04_NO_ACCEPTED_CHANGE'
    assert not any(json.loads(p.read_text()).get('accepted') for p in f.rglob('ACCEPTANCE.json'))
    confirms = [json.loads(p.read_text()) for p in f.rglob('ACCEPTANCE_CONFIRM.json')]
    fast_yes = [c for c in confirms if c['fast_decision_accepted']]
    assert fast_yes and all(c['status'] == 'REJECTED_ON_FULL_CAPTURE' for c in fast_yes)
