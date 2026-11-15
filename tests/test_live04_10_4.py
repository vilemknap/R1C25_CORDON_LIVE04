"""LIVE04.10.4: faster geometry ingestion (identical store) and the COM page size from the config.
Synthetic mock only - NOT native PTV Visum evidence."""
import json
import random
import sqlite3
import time

import pytest

from cordon2025.common import parent_module, ContractError
from cordon2025 import live04_fastgeom as fg
from cordon2025.live04_config import load_config
from cordon2025.visum_startup import preflight
from cordon2025.live04_capture import capture
from test_live04_7 import setup, crossing_network, equal_od_volumes, link_volumes  # noqa: F401

two = parent_module('r1_15a2_two_mode_v238')
supply = parent_module('r1_15a2_supply')
N_LINKS = 400


def _collector(path, n_links=N_LINKS):
    links = {(i, i, i + 1): {'eligible': False} for i in range(1, n_links)}
    st = dict(two.DEFAULT_SETTINGS, max_geometry_rows_per_mode=10 ** 9, max_parent_rows_per_dseg=10 ** 7, commit_routes=37)
    return two.TwoModeRouteCollector([], supply.SupplyPolicy(), 'h', links, path, st, None, geometry_only=True)


def _keys(n):
    return sorted({(1 + r // 20, 1 + (r // 2) % 10 + 30, 1 + r % 2) for r in range(n)} | {(7, 7, 1), (8, 9, 3)})


def _rows(keys, seed=3, flat_every=0, ints=False):
    rnd = random.Random(seed); rows = []
    cast = (lambda x: x) if ints else float
    for n, (o, d, ix) in enumerate(keys):
        if (o, d, ix) in ((7, 7, 1), (8, 9, 3)):          # zero-link intrazonal / interzonal routes
            rows.append((cast(o), cast(d), cast(ix), '', '', '', '')); continue
        length = rnd.randint(1, 30); s = rnd.randint(1, N_LINKS - length - 1)
        flat = flat_every and n % flat_every == 0
        if not flat:
            rows.append((cast(o), cast(d), cast(ix), None, '', None, ''))
        for i in range(length):
            a = s + i
            keyfields = (cast(o), cast(d), cast(ix)) if flat else ('', None, '')
            rows.append(keyfields + (cast(i + 1), cast(a), cast(a), cast(a + 1)))
    return rows


def _dump(c):
    db = c.db
    out = {t: sorted(db.execute('SELECT * FROM %s' % t).fetchall(), key=repr)
           for t in ('geometry', 'profile_hits', 'driver_markets', 'edge_postings', 'metadata', 'segments')}
    out['audits'] = json.dumps(c.mode_audits, sort_keys=True, default=str)
    out['mult'] = sorted(c.edge_max_multiplicity.items())
    out['count'] = c.geometry_count
    return out


def _both(tmp_path, keys, rows):
    res = []
    for name, fn in (('donor', None), ('fast', fg.add_geometry)):
        c = _collector(tmp_path / (name + '.sqlite'))
        c.add_parents('NATIVE_CW', 'C', [(float(o), float(d), float(ix), 1.0) for o, d, ix in keys],
                      {'matrix_interzonal': float(len(keys)), 'matrix_no': 1})
        err = None
        try:
            (c.add_geometry('C', rows) if fn is None else fn(c, 'C', rows))
        except Exception as exc:
            err = (type(exc).__name__, str(exc))
        res.append((err, None if err else _dump(c)))
        c.db.close()
    return res


@pytest.mark.parametrize('flat_every, ints', [(0, False), (5, False), (0, True), (3, True)])
def test_fast_parser_builds_the_identical_store(tmp_path, flat_every, ints):
    keys = _keys(600)
    (e1, d1), (e2, d2) = _both(tmp_path, keys, _rows(keys, flat_every=flat_every, ints=ints))
    assert e1 is None and e2 is None
    assert d1 == d2


def _mutate(rows, kind):
    rows = list(rows)
    child = next(i for i, r in enumerate(rows) if r[0] in ('', None) and r[3] not in ('', None) and i > 5)
    r = list(rows[child])
    if kind == 'gap':
        r[3] = r[3] + 1
    elif kind == 'unknown_edge':
        r[4], r[5], r[6] = 99999.0, 99999.0, 100000.0
    elif kind == 'disconnected':
        r[5] = r[5] + 3; r[4] = r[5]; r[6] = r[5] + 1
    elif kind == 'non_integer':
        r[4] = 3.5
    elif kind == 'string_number':
        r[3] = str(int(r[3]))
    elif kind == 'incomplete_child':
        r[6] = ''
    elif kind == 'partial_parent':
        r[0] = 1.0
    elif kind == 'width':
        r = r[:6]
    rows[child] = tuple(r)
    if kind == 'orphan':
        rows = rows[1:]
    if kind == 'repeat_parent':
        rows = rows + [rows[0]]
    if kind == 'missing_route':
        last = max(i for i, r in enumerate(rows) if r[3] in ('', None))
        rows = rows[:last]
    return rows


@pytest.mark.parametrize('kind', ['gap', 'unknown_edge', 'disconnected', 'non_integer', 'string_number',
                                  'incomplete_child', 'partial_parent', 'width', 'orphan', 'repeat_parent',
                                  'missing_route'])
def test_fast_parser_fails_exactly_like_the_donor(tmp_path, kind):
    keys = _keys(120)
    (e1, d1), (e2, d2) = _both(tmp_path, keys, _mutate(_rows(keys), kind))
    assert e1 == e2
    if e1 is None:
        assert d1 == d2


def test_fast_parser_is_faster(tmp_path):
    keys = sorted({(1 + r // 100, 1 + (r // 2) % 50 + 200, 1 + r % 2) for r in range(8000)})
    rnd = random.Random(1); rows = []
    for o, d, ix in keys:
        rows.append((float(o), float(d), float(ix), '', '', '', ''))
        s = rnd.randint(1, 8000 - 51)
        rows.extend(('', '', '', float(i + 1), float(s + i), float(s + i), float(s + i + 1)) for i in range(50))
    # Whole add_geometry incl. the identical per-route SQLite/posting work (which dilutes the row-parser
    # gain); best of 3 runs each, interleaved, so machine load does not decide the result.
    times = {'donor': [], 'fast': []}
    for rep in range(3):
        for name, fn in (('donor', None), ('fast', fg.add_geometry)):
            c = _collector(tmp_path / ('%s_%d.sqlite' % (name, rep)), n_links=8000)
            c.add_parents('NATIVE_CW', 'C', [(float(o), float(d), float(ix), 1.0) for o, d, ix in keys],
                          {'matrix_interzonal': float(len(keys)), 'matrix_no': 1})
            t = time.perf_counter()
            (c.add_geometry('C', rows) if fn is None else fn(c, 'C', rows))
            times[name].append(time.perf_counter() - t)
            c.db.close()
    assert min(times['fast']) < 0.9 * min(times['donor']), times


def test_capture_with_fast_parser_equals_donor_capture(setup, tmp_path):
    v, c, out, ctl, opt = setup
    A, B, _ = crossing_network(v)
    v.routes['C'] = A; equal_od_volumes(v, 'C'); link_volumes(v)
    full = dict(opt, geometry_proof='FULL', full_proof_method='ALL_LINK_VOLUMES', final_readback='ALL_LINK_VOLUMES')
    stores = {}
    for flag in (False, True):
        f = tmp_path / ('c%d' % flag); f.mkdir()
        cache, evidence = capture(v, c, f, ctl, dict(full, fast_geometry_parser=flag), preflight(v, c, f, ctl, full))
        ev = json.loads(evidence.read_text())
        assert ev['fast_geometry_parser'] is flag
        with sqlite3.connect(cache) as db:
            stores[flag] = {t: sorted(db.execute('SELECT * FROM %s' % t).fetchall(), key=repr)
                            for t in ('geometry', 'volumes', 'edge_postings', 'profile_hits')}
        stores[flag]['sig'] = ev['final_path_volume_signature']
    assert stores[False] == stores[True]


def test_release_config_and_page_size():
    ev = load_config()['evaluation']
    assert ev['fast_geometry_parser'] is True and ev['com_page_size'] == 1024
    for bad in ({'com_page_size': 50}, {'com_page_size': 5000}, {'fast_geometry_parser': 'yes'}):
        with pytest.raises(ContractError, match='LIVE02_INVALID'):
            load_config(overrides={'evaluation': bad})
