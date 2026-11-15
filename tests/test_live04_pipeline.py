"""Offline threading/parity contracts. These tests never use native Visum."""
import hashlib
import json
import sqlite3
import threading

import pytest

from cordon2025 import live04_fastgeom as fg, live04_pipeline as pipe
from cordon2025.common import ContractError
from cordon2025.live04_capture import capture
from cordon2025.live04_config import load_config
from cordon2025.visum_startup import preflight
from test_live04_10_4 import _collector, _keys, _rows, _dump, _mutate
from test_live04_7 import setup, crossing_network, equal_od_volumes, link_volumes  # noqa: F401


def _build(path, keys, rows, *, pipeline, batch_size=17, fast=True):
    c = _collector(path)
    c.add_parents('NATIVE_CW', 'C', [(o, d, ix, 1.0) for o, d, ix in keys],
                  {'matrix_interzonal': float(len(keys)), 'matrix_no': 1})
    try:
        if pipeline:
            audit, stats = pipe.add_geometry(c, 'C', rows, batch_size=batch_size, fast_parser=fast)
            assert stats['worker_joined_before_return']
        else:
            audit = fg.add_geometry(c, 'C', rows) if fast else c.add_geometry('C', rows)
            stats = None
        return _dump(c), audit, stats
    finally:
        c.close()


@pytest.mark.parametrize('batch_size', [1, 2, 17, 1024])
@pytest.mark.parametrize('fast', [False, True])
def test_store_bytes_hash_audits_and_commit_chunks_are_identical(tmp_path, batch_size, fast):
    keys = _keys(600)
    rows = _rows(keys, flat_every=5)
    a, b = tmp_path / 'a.sqlite', tmp_path / 'b.sqlite'
    old, ao, _ = _build(a, keys, rows, pipeline=False, fast=fast)
    new, an, stats = _build(b, keys, rows, pipeline=True, batch_size=batch_size, fast=fast)
    assert old == new and ao == an
    assert hashlib.sha256(a.read_bytes()).digest() == hashlib.sha256(b.read_bytes()).digest()
    assert stats['rows'] == len(rows) and stats['max_live_batches'] == 2
    assert stats['batches'] == (len(rows) + batch_size - 1) // batch_size
    assert not any(t.name == 'R1C25-geometry-parser' for t in threading.enumerate())


@pytest.mark.parametrize('kind', ['gap', 'unknown_edge', 'disconnected', 'non_integer', 'string_number',
                                  'incomplete_child', 'partial_parent', 'width', 'orphan',
                                  'repeat_parent', 'missing_route'])
def test_parser_errors_match_sequential_and_leave_no_worker(tmp_path, kind):
    keys = _keys(120)
    errors = []
    for pipeline in (False, True):
        try:
            _build(tmp_path / ('x%d.sqlite' % pipeline), keys, _mutate(_rows(keys), kind), pipeline=pipeline)
        except Exception as exc:
            errors.append((type(exc), str(exc)))
        else:
            errors.append(None)
    assert errors[0] == errors[1]
    assert not any(t.name == 'R1C25-geometry-parser' for t in threading.enumerate())


def test_reads_control_and_original_connection_stay_on_owner(tmp_path, monkeypatch):
    owner = threading.get_ident()
    threads = []
    original_parse = fg.add_geometry
    original_connect = sqlite3.connect

    def connect(*args, **kwargs):
        threads.append(threading.get_ident())
        return original_connect(*args, **kwargs)

    def parse(c, mode, rows):
        assert threading.get_ident() != owner
        c.db.execute('SELECT 1')  # default check_same_thread=True remains enabled
        return original_parse(c, mode, rows)

    class Control:
        def checkpoint(self, *args, **kwargs):
            assert threading.get_ident() == owner

    monkeypatch.setattr(pipe.sqlite3, 'connect', connect)
    monkeypatch.setattr(fg, 'add_geometry', parse)
    keys = _keys(120)
    c = _collector(tmp_path / 'threads.sqlite')
    c.control = Control()
    c.add_parents('NATIVE_CW', 'C', [(o, d, ix, 1.0) for o, d, ix in keys],
                  {'matrix_interzonal': float(len(keys)), 'matrix_no': 1})

    def rows():
        for row in _rows(keys):
            assert threading.get_ident() == owner
            yield row

    try:
        pipe.add_geometry(c, 'C', rows(), batch_size=17)
        assert c.db.execute('SELECT count(*) FROM geometry').fetchone()[0] == len(keys)
        assert threads[0] == owner and threads[1] != owner and len(threads) == 2
    finally:
        c.close()


def test_overlap_is_real_and_two_batches_bound_input(tmp_path, monkeypatch):
    entered, next_read = threading.Event(), threading.Event()
    original = fg.add_geometry
    counts = {'read': 0, 'used': 0, 'max_ahead': 0}
    batch_size = 17
    keys = _keys(120)

    def parse(c, mode, rows):
        def traced():
            for row in rows:
                counts['used'] += 1
                if counts['used'] == 1:
                    entered.set()
                    assert next_read.wait(2), 'owner did not overlap next read with parsing'
                yield row
        return original(c, mode, traced())

    def rows():
        for row in _rows(keys):
            if counts['read'] == batch_size:
                assert entered.wait(2)
                next_read.set()
            counts['read'] += 1
            counts['max_ahead'] = max(counts['max_ahead'], counts['read'] - counts['used'])
            yield row

    monkeypatch.setattr(fg, 'add_geometry', parse)
    _build(tmp_path / 'bounded.sqlite', keys, rows(), pipeline=True, batch_size=batch_size)
    assert counts['read'] == counts['used']
    assert counts['max_ahead'] <= 2 * batch_size


@pytest.mark.parametrize('where', ['read', 'checkpoint', 'resource', 'sqlite'])
def test_stop_and_failures_close_worker_and_allow_database_cleanup(tmp_path, monkeypatch, where):
    class Stop(Exception):
        pass

    keys = _keys(120)
    c = _collector(tmp_path / 'failed.sqlite')
    c.add_parents('NATIVE_CW', 'C', [(o, d, ix, 1.0) for o, d, ix in keys],
                  {'matrix_interzonal': float(len(keys)), 'matrix_no': 1})

    class Control:
        def checkpoint(self, phase=None, **kwargs):
            if where == 'checkpoint' and phase == 'GEOMETRY_STORE_COMMIT':
                raise Stop('USER_STOP_REQUESTED')
    c.control = Control()
    if where == 'resource':
        def check(*args, **kwargs):
            raise Stop('LOW_FREE_DISK_SPACE')
        c.check_resources = check
    if where == 'sqlite':
        c.db.execute('DROP TABLE edge_postings'); c.db.commit()

    def rows():
        for i, row in enumerate(_rows(keys)):
            if where == 'read' and i == 123:
                raise Stop('read failed')
            yield row
    try:
        with pytest.raises((Stop, sqlite3.OperationalError)):
            pipe.add_geometry(c, 'C', rows(), batch_size=17)
        assert not any(t.name == 'R1C25-geometry-parser' for t in threading.enumerate())
        assert c.db.execute('PRAGMA quick_check').fetchone() == ('ok',)
        assert c.db.execute('PRAGMA foreign_key_check').fetchall() == []
    finally:
        c.close()
    # Rename after close also matters on Windows where live handles prevent it.
    (tmp_path / 'failed.sqlite').rename(tmp_path / 'closed.sqlite')


def test_nonprimitive_provider_values_never_reach_worker(tmp_path):
    keys = _keys(120)
    rows = _rows(keys)
    rows[2] = (*rows[2][:-1], object())
    with pytest.raises(ContractError, match='NONSCALAR_CELL'):
        _build(tmp_path / 'bad.sqlite', keys, rows, pipeline=True)


def test_repeated_link_occurrences_profile_hits_and_multiplicity_match(tmp_path):
    from cordon2025.common import parent_module
    two = parent_module('r1_15a2_two_mode_v238')
    supply = parent_module('r1_15a2_supply')
    links = {(1, 1, 2): {'eligible': False}, (2, 2, 1): {'eligible': False}}
    results = []
    for enabled in (False, True):
        c = two.TwoModeRouteCollector([], supply.SupplyPolicy(), 'h', links,
              tmp_path / ('repeat%d.sqlite' % enabled), dict(two.DEFAULT_SETTINGS), None, geometry_only=True)
        c.profile_index_by_key = {(1, 1, 2): [0], (2, 2, 1): [1]}
        c.cal_indices = {0, 1}
        c.add_parents('NATIVE_CW', 'C', [(10, 20, 1, 3.)], {'matrix_interzonal': 3., 'matrix_no': 1})
        rows = [(10, 20, 1, '', '', '', ''), ('', '', '', 1, 1, 1, 2),
                ('', '', '', 2, 2, 2, 1), ('', '', '', 3, 1, 1, 2)]
        try:
            if enabled:
                pipe.add_geometry(c, 'C', iter(rows), batch_size=2)
            else:
                fg.add_geometry(c, 'C', rows)
            assert c.db.execute('SELECT multiplicity FROM profile_hits ORDER BY profile_index').fetchall() == [(2,), (1,)]
            results.append(_dump(c))
        finally:
            c.close()
    assert results[0] == results[1]


def test_failed_source_retains_original_exception_and_closes_on_owner(tmp_path):
    owner = threading.get_ident()
    closed = []
    failure = OSError('provider failed')

    def source():
        try:
            yield from _rows(_keys(120))[:123]
            raise failure
        finally:
            closed.append(threading.get_ident())

    with pytest.raises(OSError) as caught:
        _build(tmp_path / 'provider.sqlite', _keys(120), source(), pipeline=True)
    assert caught.value is failure and closed == [owner]


def test_sqlite_close_failure_is_reported_without_hanging(tmp_path, monkeypatch):
    connect = sqlite3.connect
    owner = threading.get_ident()

    class Connection:
        def __init__(self, *a, **kw):
            self.db = connect(*a, **kw)
        def __getattr__(self, key):
            return getattr(self.db, key)
        def close(self):
            self.db.close()
            raise OSError('worker close failed')

    def factory(*a, **kw):
        return connect(*a, **kw) if threading.get_ident() == owner else Connection(*a, **kw)

    monkeypatch.setattr(pipe.sqlite3, 'connect', factory)
    with pytest.raises(OSError, match='worker close failed'):
        _build(tmp_path / 'close.sqlite', _keys(120), _rows(_keys(120)), pipeline=True)
    assert not any(t.name == 'R1C25-geometry-parser' for t in threading.enumerate())


def test_failed_pipeline_capture_has_no_completed_evidence(setup):
    v, c, out, ctl, opt = setup
    v.sequence_gap = True
    with pytest.raises(Exception, match='GEOMETRY_LINK_INDEX_NOT_CONTIGUOUS'):
        capture(v, c, out, ctl, dict(opt, geometry_pipeline=True, fast_geometry_parser=True),
                preflight(v, c, out, ctl, opt))
    assert not (out / 'SNAPSHOT_EVIDENCE.json').exists()
    with sqlite3.connect(out / 'p.sqlite') as db:
        assert db.execute("SELECT value FROM metadata WHERE key='capture_complete'").fetchone() is None
    assert not any(t.name == 'R1C25-geometry-parser' for t in threading.enumerate())


def test_capture_pipeline_keeps_proofs_signature_and_database_exact(setup, tmp_path):
    v, c, out, ctl, opt = setup
    A, B, _ = crossing_network(v)
    v.routes['C'] = A; equal_od_volumes(v, 'C'); link_volumes(v)
    full = dict(opt, geometry_proof='FULL', full_proof_method='ALL_LINK_VOLUMES',
                final_readback='ALL_LINK_VOLUMES', fast_geometry_parser=True)
    outcomes = []
    for enabled in (False, True):
        f = tmp_path / ('capture%d' % enabled); f.mkdir()
        cache, evidence = capture(v, c, f, ctl, dict(full, geometry_pipeline=enabled), preflight(v, c, f, ctl, full))
        ev = json.loads(evidence.read_text())
        ev.pop('geometry_pipeline'); ev.pop('capture_timing_seconds')
        outcomes.append((cache.read_bytes(), ev))
    assert outcomes[0] == outcomes[1]
    assert not v.writes and not v.unbounded


def test_config_explicit_toggle_and_invalid_type():
    assert load_config()['evaluation']['geometry_pipeline'] is True
    assert load_config(overrides={'evaluation': {'geometry_pipeline': False}})['evaluation']['geometry_pipeline'] is False
    with pytest.raises(ContractError, match='INVALID_GEOMETRY_PIPELINE'):
        load_config(overrides={'evaluation': {'geometry_pipeline': 1}})


def test_epoch_replay_stays_sequential_when_pipeline_is_enabled(setup, tmp_path, monkeypatch):
    from cordon2025 import live04_epoch as epm
    v, cfg, out, ctl, opt = setup
    A, B, _ = crossing_network(v)
    v.routes['C'] = A; equal_od_volumes(v, 'C'); link_volumes(v)
    opt = dict(opt, geometry_pipeline=True, fast_geometry_parser=True, geometry_proof='FULL',
               full_proof_method='ALL_LINK_VOLUMES', final_readback='ALL_LINK_VOLUMES')
    pre = preflight(v, cfg, out, ctl, opt)
    cache, evidence = capture(v, cfg, out, ctl, opt, pre)
    ev = json.loads(evidence.read_text()); ge = ev['geometry_epoch']
    assert len(ev['geometry_pipeline']['streams']) == 2
    epoch = tmp_path / 'EPOCH'
    epm.write_epoch(epoch, cache, pre[0]['network_sha256'], ge['edge_dictionary_sha256'],
                    ge['mode_audits'], ge['fresh_modes'], ge['reused_modes'], 'TRIAL', keep_previous=True)

    def forbidden(*args, **kwargs):
        raise AssertionError('disk replay must not pay pipeline overhead')

    monkeypatch.setattr(pipe, 'add_geometry', forbidden)
    dst = tmp_path / 'replay'; dst.mkdir()
    opt['geometry_epoch'] = {'dir': str(epoch), 'max_reuse': 3, 'full_proof_replay': True}
    _, evidence = capture(v, cfg, dst, ctl, opt, preflight(v, cfg, dst, ctl, opt))
    ev = json.loads(evidence.read_text())
    assert sorted(ev['geometry_epoch']['reused_modes']) == ['C', 'C_NOT']
    assert ev['geometry_pipeline']['streams'] == []
