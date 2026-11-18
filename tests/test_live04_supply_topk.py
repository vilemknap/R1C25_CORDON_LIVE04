"""The bounded route pair search must keep the old exhaustive ordering."""
import random
import sqlite3
import struct
import pytest

from cordon2025.common import sha256
from cordon2025.live04_supply import _top_route_pairs, make_collector, sealed_supply_policy


def _routes(prefix, volumes):
    routes = [{'pk': (prefix, i), 'volume': float(v)} for i, v in enumerate(volumes)]
    return sorted(routes, key=lambda r: (-r['volume'], r['pk']))


def _exhaustive(on, off, limit):
    return sorted(((a, b) for a in on for b in off),
                  key=lambda p: (-p[0]['volume'] * p[1]['volume'], p[0]['pk'], p[1]['pk']))[:limit]


def test_top_pairs_matches_exhaustive_with_ties_and_sparse_limits():
    rng = random.Random(20261117)
    for n_on in range(1, 17):
        for n_off in range(1, 17):
            on = _routes('on', [rng.choice((0.1, 0.5, 1.0, 2.0, 4.0)) for _ in range(n_on)])
            off = _routes('off', [rng.choice((0.1, 0.5, 1.0, 2.0, 4.0)) for _ in range(n_off)])
            for limit in (0, 1, 2, 7, 128, n_on * n_off + 1):
                assert _top_route_pairs(on, off, limit) == _exhaustive(on, off, limit)


def test_top_pairs_stays_bounded_for_large_market():
    on = _routes('on', range(10000, 0, -1))
    off = _routes('off', range(10000, 0, -1))
    result = _top_route_pairs(on, off, 128)
    assert len(result) == 128
    assert result[0] == (on[0], off[0])


def test_failed_route_store_build_does_not_block_retry(tmp_path):
    policy = sealed_supply_policy()
    args = ([], policy, 'parent', [], tmp_path / 'missing.sqlite', {}, {'selected_dsegs': []}, tmp_path)
    options = dict(max_unique_sequences=10, max_pairs_per_market=4, store_sha256='missing')
    for _ in range(2):
        with pytest.raises(Exception, match='LIVE04_SUPPLY_PATH_STORE_MISSING'):
            make_collector(*args, **options)
        assert not list(tmp_path.glob('SUPPLY_CORDON_ROUTE_STORE_*.sqlite*'))


def test_partial_route_store_is_removed_after_stream_error(tmp_path):
    source = tmp_path / 'broken_source.sqlite'
    con = sqlite3.connect(source)
    con.execute('CREATE TABLE edges(eid INTEGER, link_no INTEGER, from_no INTEGER, to_no INTEGER)')
    con.execute('CREATE TABLE geometry(gid INTEGER, orig INTEGER, dest INTEGER, path_index INTEGER, edge_ids BLOB, edge_count INTEGER)')
    con.execute('CREATE TABLE volumes(gid INTEGER, dseg TEXT, volume REAL)')
    con.execute('INSERT INTO edges VALUES(1,10,1,2)')
    con.executemany('INSERT INTO geometry VALUES(?,?,?,?,?,?)', [
        (1, 1, 2, 1, struct.pack('<I', 1), 1),
        (2, 2, 3, 1, struct.pack('<I', 999), 1)])
    con.executemany('INSERT INTO volumes VALUES(?,?,?)',
                    [(1, 'NATIVE_CL', 1.), (2, 'NATIVE_CL', 1.)])
    con.commit(); con.close()
    args = ([], sealed_supply_policy(), 'parent', [], source, {},
            {'selected_dsegs': ['NATIVE_CL'], 'station_rows': False, 'profile_rows': False,
             'key_row': {}}, tmp_path)
    options = dict(max_unique_sequences=10, max_pairs_per_market=4, store_sha256=sha256(source))
    for _ in range(2):
        with pytest.raises(KeyError, match='999'):
            make_collector(*args, **options)
        assert not list(tmp_path.glob('SUPPLY_CORDON_ROUTE_STORE_*.sqlite*'))


def test_successive_route_store_builds_keep_separate_evidence(tmp_path):
    source = tmp_path / 'source.sqlite'
    con = sqlite3.connect(source)
    con.execute('CREATE TABLE edges(eid INTEGER, link_no INTEGER, from_no INTEGER, to_no INTEGER)')
    con.execute('CREATE TABLE geometry(gid INTEGER, orig INTEGER, dest INTEGER, path_index INTEGER, edge_ids BLOB, edge_count INTEGER)')
    con.execute('CREATE TABLE volumes(gid INTEGER, dseg TEXT, volume REAL)')
    con.commit(); con.close()
    args = ([], sealed_supply_policy(), 'parent', [], source, {}, {'selected_dsegs': []}, tmp_path)
    options = dict(max_unique_sequences=10, max_pairs_per_market=4, store_sha256=sha256(source))
    stores = []
    for _ in range(2):
        collector = make_collector(*args, **options)
        try:
            collector.finish()
            stores.append(collector.route_db_path)
        finally:
            collector.close()
    assert stores[0] != stores[1]
    for path in stores:
        con = sqlite3.connect(path)
        try:
            assert con.execute('SELECT count(*) FROM routes').fetchone()[0] == 0
        finally:
            con.close()
