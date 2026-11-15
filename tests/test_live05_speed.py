"""LIVE05.6 speed-ups. Synthetic mock only - not native PTV Visum evidence."""
from pathlib import Path

from fake_live04 import Live04Visum
from cordon2025.common import read_json
from cordon2025 import live04_cycle
from cordon2025.live04_config import load_config

OPT = {'min_free_disk_gib': 0, 'com_retry_initial_delay_seconds': 0., 'com_retry_max_delay_seconds': 0.}


def _fake(name, calls, changed_in=()):
    def make(tx, cfg):
        def block(adapter, cfg_, bdir, ctl, state, diag, anchors, reference, policy, outer_cycle=None):
            Path(bdir).mkdir(parents=True, exist_ok=True)
            calls.append((outer_cycle, name))
            return False, state, diag, None, {'status': 'NO_TD_CANDIDATE' if name == 'TD_CORDON' else 'EXHAUSTED'}
        return block
    return make


def test_td_is_skipped_for_one_cycle_after_an_unchanged_td(tmp_path, monkeypatch):
    assert load_config()['td_cordon']['skip_cycles_after_unchanged'] == 1
    calls = []
    monkeypatch.setattr(live04_cycle, 'make_generation_block', _fake('GENERATION', calls))
    monkeypatch.setattr(live04_cycle, 'make_td_block', _fake('TD_CORDON', calls))
    monkeypatch.setattr(live04_cycle, 'make_supply_block', _fake('SUPPLY_ADDVAL1', calls))
    v = Live04Visum(tmp_path / 'model')
    live04_cycle.run(v, output_root=tmp_path / 'runs', options=OPT,
                     config_overrides={'max_cycles': 5, 'stop_after_cycle_without_change': False})
    td = [o for o, n in calls if n == 'TD_CORDON']
    assert td == [1, 3, 5]
    prog = read_json(next((tmp_path / 'runs').glob('LIVE04_TGTD_*')) / 'CYCLE_PROGRESS.json')
    assert [c.get('skipped_blocks', [{}])[0].get('block') for c in prog['cycles']] == [None, 'TD_CORDON', None,
                                                                                     'TD_CORDON', None]


def test_stop_rule_still_waits_for_a_skipped_td(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(live04_cycle, 'make_generation_block', _fake('GENERATION', calls))
    monkeypatch.setattr(live04_cycle, 'make_td_block', _fake('TD_CORDON', calls))
    monkeypatch.setattr(live04_cycle, 'make_supply_block', _fake('SUPPLY_ADDVAL1', calls))
    v = Live04Visum(tmp_path / 'model')
    live04_cycle.run(v, output_root=tmp_path / 'runs', options=OPT, config_overrides={'max_cycles': 6})
    prog = read_json(next((tmp_path / 'runs').glob('LIVE04_TGTD_*')) / 'CYCLE_PROGRESS.json')
    assert prog['stop_reason'] == 'NO_CHANGE_IN_ANY_BLOCK_SINCE_LAST_ACCEPTED_CHANGE'
    assert set(prog['unchanged_since_last_change']) == {'GENERATION', 'TD_CORDON', 'SUPPLY_ADDVAL1'}


def test_skip_can_be_switched_off():
    cfg = load_config(overrides={'td_cordon': {'skip_cycles_after_unchanged': 0}})
    assert cfg['td_cordon']['skip_cycles_after_unchanged'] == 0


# ------------------------------------------------------------- LIVE05.6 pipelined geometry ingestion
import json
import sqlite3
import threading

import pytest

from cordon2025 import live04_fastgeom as fg
from cordon2025 import live05_pipeline as pl
from test_live04_10_4 import _collector, _keys, _rows, _dump, _mutate
from test_live04_7 import setup  # noqa: F401


class _ThreadBoundControl:
    """Like LiveControl: checkpoint only on the COM thread; optional stop after n calls."""
    def __init__(self, stop_after=None):
        self.thread = threading.get_ident(); self.calls = []; self.stop_after = stop_after

    def checkpoint(self, phase=None, force=False, **details):
        assert threading.get_ident() == self.thread, 'COM_THREAD_CHANGED'
        self.calls.append(phase)
        if self.stop_after is not None and self.calls.count('GEOMETRY_STORE_COMMIT') >= self.stop_after:
            raise RuntimeError('USER_STOP_REQUESTED')


def _run(tmp_path, name, keys, rows, piped, control=None):
    c = _collector(tmp_path / (name + '.sqlite'))
    c.control = control or _ThreadBoundControl()
    c.add_parents('NATIVE_CW', 'C', [(float(o), float(d), float(ix), 1.0) for o, d, ix in keys],
                  {'matrix_interzonal': float(len(keys)), 'matrix_no': 1})
    err = None
    try:
        if piped:
            pl.shareable_connection(c)
            pl.add_geometry(c, 'C', iter(rows), lambda m, r: fg.add_geometry(c, m, r))
        else:
            fg.add_geometry(c, 'C', rows)
    except Exception as exc:
        err = (type(exc).__name__, str(exc))
    out = (err, None if err else _dump(c))
    c.db.close()
    return out


@pytest.mark.parametrize('flat_every, ints', [(0, False), (5, False), (3, True)])
def test_pipelined_ingestion_builds_the_identical_store(tmp_path, flat_every, ints, monkeypatch):
    monkeypatch.setattr(pl, 'BATCH_ROWS', 7)          # many small batches, queue often full
    monkeypatch.setattr(pl, 'QUEUE_BATCHES', 2)
    keys = _keys(600)
    rows = _rows(keys, flat_every=flat_every, ints=ints)
    assert _run(tmp_path, 'serial', keys, rows, False) == _run(tmp_path, 'piped', keys, rows, True)


@pytest.mark.parametrize('kind', ['gap', 'unknown_edge', 'disconnected', 'orphan', 'missing_route'])
def test_pipelined_ingestion_fails_like_the_serial_one(tmp_path, kind, monkeypatch):
    monkeypatch.setattr(pl, 'BATCH_ROWS', 5)
    keys = _keys(120)
    rows = _mutate(_rows(keys), kind)
    assert _run(tmp_path, 'serial', keys, rows, False)[0] == _run(tmp_path, 'piped', keys, rows, True)[0]


def test_com_failure_stops_the_parser_and_is_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(pl, 'BATCH_ROWS', 5)
    keys = _keys(300); rows = _rows(keys)

    def com_rows():
        for i, r in enumerate(rows):
            if i == len(rows) // 2:
                raise OSError('RPC_E_CALL_REJECTED')
            yield r
    c = _collector(tmp_path / 'x.sqlite'); c.control = _ThreadBoundControl()
    c.add_parents('NATIVE_CW', 'C', [(float(o), float(d), float(ix), 1.0) for o, d, ix in keys],
                  {'matrix_interzonal': float(len(keys)), 'matrix_no': 1})
    pl.shareable_connection(c)
    with pytest.raises(OSError, match='RPC_E_CALL_REJECTED'):
        pl.add_geometry(c, 'C', com_rows(), lambda m, r: fg.add_geometry(c, m, r))
    assert not [t for t in threading.enumerate() if t.name == 'LIVE05_GEOMETRY_PARSER']
    assert isinstance(c.control, _ThreadBoundControl)       # real control restored
    c.db.close()


def test_stop_request_is_honoured_on_the_com_thread(tmp_path, monkeypatch):
    monkeypatch.setattr(pl, 'BATCH_ROWS', 3)
    keys = _keys(600); rows = _rows(keys)
    err, _ = _run(tmp_path, 'stop', keys, rows, True, control=_ThreadBoundControl(stop_after=1))
    assert err == ('RuntimeError', 'USER_STOP_REQUESTED')


def test_capture_pipelined_equals_serial_capture(setup, tmp_path):
    from cordon2025.visum_startup import preflight
    from cordon2025.live04_capture import capture
    from test_live04_7 import crossing_network, equal_od_volumes, link_volumes
    v, c, out, ctl, opt = setup
    A, B, _ = crossing_network(v)
    v.routes['C'] = A; equal_od_volumes(v, 'C'); link_volumes(v)
    full = dict(opt, geometry_proof='FULL', full_proof_method='ALL_LINK_VOLUMES', final_readback='ALL_LINK_VOLUMES',
                fast_geometry_parser=True)
    stores = {}
    for flag in (False, True):
        f = tmp_path / ('p%d' % flag); f.mkdir()
        cache, evidence = capture(v, c, f, ctl, dict(full, pipelined_geometry=flag), preflight(v, c, f, ctl, full))
        ev = json.loads(evidence.read_text())
        assert ev['pipelined_geometry'] is flag
        with sqlite3.connect(cache) as db:
            stores[flag] = {t: sorted(db.execute('SELECT * FROM %s' % t).fetchall(), key=repr)
                            for t in ('geometry', 'volumes', 'edge_postings', 'profile_hits')}
        stores[flag]['sig'] = ev['final_path_volume_signature']
    assert stores[False] == stores[True]


def test_release_config_enables_pipelined_geometry():
    assert load_config()['evaluation']['pipelined_geometry'] is True


def test_flowbundle_probe_helpers():
    import importlib.util
    from cordon2025.common import ROOT
    spec = importlib.util.spec_from_file_location('fbprobe', ROOT / 'RUN_R1_2025_FLOWBUNDLE_PROBE.py')
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    obs = m._observed_links()
    assert sum(1 for k in obs.values() if k == 'STATION') == 32 and 32 < len(obs) <= 32 + 120   # K arms may be station links
    rows = [(1.0, 2.0, 1.0, '', '', '', ''), ('', '', '', 1.0, 5.0, 10.0, 11.0), ('', '', '', 2.0, 6.0, 11.0, 12.0),
            (3.0, 4.0, 2.0, '', '', '', ''), ('', '', '', 1.0, 6.0, 11.0, 12.0)]
    assert m._routes(rows) == {(1, 2, 1): [(5, 10, 11), (6, 11, 12)], (3, 4, 2): [(6, 11, 12)]}
