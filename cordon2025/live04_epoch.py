"""LIVE04.7 geometry epoch for trial captures (cordon analogue of the v7 V2.4.7 path epoch).

The most expensive part of a cordon capture is the COM read of the PrT path-link
hierarchy (~31 million rows per mode).  Inside a calibration run the assignment
usually returns the very same path set after a trial.  An epoch keeps the link
sequences of the last capture that read them from Visum; a later trial capture may
replay them INSTEAD of the COM read only if ALL of the following hold for the mode:

* same network hash and same edge dictionary as when the epoch was written;
* the current saved-path key set (orig, dest, PathIndex) of the mode is identical
  to the epoch key set (``parent_keys_sha256`` of the representative DSeg; all
  same-mode DSegs share that set, enforced by the donor collector);
* for EVERY DSeg of the mode (representative included) and EVERY network link, the
  Visum link volume ``VOLVEH_DSEG(<code>,AP)`` equals the volume implied by the
  epoch link sequences and the CURRENT path volumes (tolerance 1 veh + 0.0005 per
  positive path on the link + 0.1 %);
* the epoch has been reused fewer than ``max_reuse`` times in a row for the mode
  (afterwards the next capture reads the geometry from Visum again).

Otherwise the capture reads the geometry from Visum exactly as in LIVE04.6.  The
replayed rows go through the unmodified donor geometry parser (contiguity, network
membership, coverage).  BASELINE never replays.  Every candidate is still accepted
or rejected only on a fresh native assignment and fresh path volumes.
"""
from __future__ import annotations
from pathlib import Path
import os
import sqlite3
import sys
import numpy as np
from .common import require
from .io import write_json, read_json

SCHEMA = 'LIVE04_GEOMETRY_EPOCH_V1'
ATOL = 1.0
PATH_ROUNDING = 0.0005          # Visum path volumes are on a 0.001 lattice
RTOL = 1e-3
CHUNK_ROUTES = 50000


def _connect(path):
    db = sqlite3.connect(str(path))
    db.execute('PRAGMA query_only=ON')
    return db


def meta(epoch_dir):
    p = Path(epoch_dir) / 'EPOCH.json'
    if not p.is_file() or not (Path(epoch_dir) / 'epoch.sqlite').is_file():
        return None
    m = read_json(p)
    return m if m.get('schema') == SCHEMA else None


def usable(epoch_dir, mode, network_sha256, edge_dictionary, keys_sha256, max_reuse):
    m = meta(epoch_dir)
    if m is None:
        return False, 'NO_EPOCH'
    if m['network_sha256'] != network_sha256:
        return False, 'NETWORK_CHANGED'
    if m['edge_dictionary_sha256'] != edge_dictionary:
        return False, 'EDGE_DICTIONARY_CHANGED'
    mm = (m.get('modes') or {}).get(mode)
    if not mm:
        return False, 'MODE_NOT_IN_EPOCH'
    if mm['parent_keys_sha256'] != keys_sha256:
        return False, 'PATH_KEY_SET_CHANGED'
    if int(mm.get('reuses', 0)) >= int(max_reuse):
        return False, 'MAX_REUSE_REACHED'
    return True, None


def _edge_keys(db):
    return {int(e): (int(n), int(f), int(t)) for e, n, f, t in db.execute('SELECT eid,link_no,from_no,to_no FROM edges')}


def _unpack(blob):
    if not blob:
        return np.zeros(0, dtype=np.uint32)
    a = np.frombuffer(blob, dtype='<u4')
    return a.astype(np.uint32, copy=False)


def replay_rows(epoch_dir, mode):
    """Donor GEOMETRY_COLUMNS rows rebuilt from the epoch (parent row + child rows)."""
    db = _connect(Path(epoch_dir) / 'epoch.sqlite')
    try:
        keys = _edge_keys(db)
        for o, d, ix, blob in db.execute('SELECT orig,dest,path_index,edge_ids FROM routes WHERE mode=? '
                                         'ORDER BY orig,dest,path_index', (mode,)):
            yield [int(o), int(d), int(ix), None, None, None, None]
            for i, eid in enumerate(_unpack(blob).tolist(), 1):
                yield [None, None, None, i, *keys[eid]]
    finally:
        db.close()


def implied_link_volumes(epoch_dir, store_db, mode, dseg_codes):
    """Per-DSeg link volumes from epoch sequences x CURRENT path volumes (same key order)."""
    ep = _connect(Path(epoch_dir) / 'epoch.sqlite')
    try:
        n_edges = int(ep.execute('SELECT COALESCE(MAX(eid),0) FROM edges').fetchone()[0]) + 1
        cur_keys = store_db.execute('SELECT orig,dest,path_index,gid FROM geometry WHERE mode=? '
                                    'ORDER BY orig,dest,path_index', (mode,)).fetchall()
        gid_order = np.asarray([r[3] for r in cur_keys], dtype=np.int64)
        vol = np.zeros((len(cur_keys), len(dseg_codes)))
        pos = {int(g): i for i, g in enumerate(gid_order)}
        for j, code in enumerate(dseg_codes):
            for g, v in store_db.execute('SELECT gid,volume FROM volumes WHERE dseg=?', (code,)):
                i = pos.get(int(g))
                if i is not None:
                    vol[i, j] = float(v)
        pred = np.zeros((n_edges, len(dseg_codes)))
        npos = np.zeros((n_edges, len(dseg_codes)))
        cursor = ep.execute('SELECT orig,dest,path_index,edge_ids FROM routes WHERE mode=? '
                            'ORDER BY orig,dest,path_index', (mode,))
        i = 0
        while True:
            batch = cursor.fetchmany(CHUNK_ROUTES)
            if not batch:
                break
            seqs = []
            for o, d, ix, blob in batch:
                require(tuple(cur_keys[i][:3]) == (int(o), int(d), int(ix)), 'EPOCH_KEY_ORDER_MISMATCH')
                seqs.append(_unpack(blob)); i += 1
            lens = np.fromiter((len(s) for s in seqs), dtype=np.int64, count=len(seqs))
            if lens.sum() == 0:
                continue
            eids = np.concatenate(seqs).astype(np.int64)
            rows = np.repeat(np.arange(i - len(batch), i, dtype=np.int64), lens)
            for j in range(len(dseg_codes)):
                w = vol[rows, j]
                pred[:, j] += np.bincount(eids, weights=w, minlength=n_edges)
                npos[:, j] += np.bincount(eids, weights=(w > 0).astype(float), minlength=n_edges)
        require(i == len(cur_keys), 'EPOCH_ROUTE_COUNT_MISMATCH')
        return pred, npos, _edge_keys(ep)
    finally:
        ep.close()


def all_link_crosscheck(pred, npos, edge_keys, visum_volumes, dseg_codes):
    """visum_volumes[code][link_key] for every network link."""
    bad = []; compared = 0; worst = 0.0; positive = 0.0
    for j, code in enumerate(dseg_codes):
        vv = visum_volumes[code]
        require(set(vv) >= set(edge_keys.values()), 'EPOCH_VISUM_LINK_COVERAGE')
        for eid, key in edge_keys.items():
            p = float(pred[eid, j]); a = float(vv[key])
            if p == 0.0 and a == 0.0:
                continue
            compared += 1; positive += abs(a)
            tol = ATOL + PATH_ROUNDING * float(npos[eid, j]) + RTOL * max(abs(p), abs(a))
            diff = abs(p - a); worst = max(worst, diff / tol)
            if diff > tol:
                bad.append({'dseg': code, 'link': list(key), 'implied': round(p, 4), 'visum': round(a, 4),
                            'abs_diff': round(diff, 4), 'tolerance': round(tol, 4)})
    status = 'PASS' if not bad and positive > 0 else ('MISMATCH' if bad else 'NO_LINK_VOLUME')
    return {'status': status, 'compared_link_values': compared, 'failed': len(bad),
            'worst_diff_to_tolerance': round(worst, 6), 'failures': bad[:40],
            'atol': ATOL, 'path_rounding_per_positive_path': PATH_ROUNDING, 'rtol': RTOL,
            'attribute': 'VOLVEH_DSEG(<code>,AP)', 'scope': 'ALL_NETWORK_LINKS_ALL_DSEGS_OF_MODE'}


def write_epoch(epoch_dir, store_path, network_sha256, edge_dictionary, mode_audits, fresh_modes, reused_modes,
                label):
    """Rebuild the epoch from a completed capture store (atomic replace)."""
    epoch_dir = Path(epoch_dir); epoch_dir.mkdir(parents=True, exist_ok=True)
    old = meta(epoch_dir) or {}
    if not fresh_modes and old and old.get('network_sha256') == network_sha256:
        modes = dict(old.get('modes') or {})
        for mode in reused_modes:
            modes[mode] = dict(modes[mode], reuses=int(modes[mode].get('reuses', 0)) + 1)
        m = dict(old, modes=modes, last_reuse_label=str(label))
        write_json(epoch_dir / 'EPOCH.json', m)
        return m
    tmp = epoch_dir / ('epoch.%d.tmp' % os.getpid())
    if tmp.exists():
        tmp.unlink()
    db = sqlite3.connect(str(tmp))
    try:
        db.executescript('PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;'
                         'CREATE TABLE edges(eid INTEGER PRIMARY KEY, link_no INTEGER, from_no INTEGER, to_no INTEGER);'
                         'CREATE TABLE routes(mode TEXT, orig INTEGER, dest INTEGER, path_index INTEGER, edge_ids BLOB,'
                         ' PRIMARY KEY(mode,orig,dest,path_index)) WITHOUT ROWID;')
        db.execute('ATTACH DATABASE ? AS src', (str(store_path),))
        db.execute('INSERT INTO edges SELECT eid,link_no,from_no,to_no FROM src.edges')
        db.execute('INSERT INTO routes SELECT mode,orig,dest,path_index,edge_ids FROM src.geometry')
        db.commit()
        db.execute('DETACH DATABASE src')
    finally:
        db.close()
    os.replace(tmp, epoch_dir / 'epoch.sqlite')
    modes = {}
    for mode, audit in mode_audits.items():
        prev = (old.get('modes') or {}).get(mode, {})
        same_set = prev.get('parent_keys_sha256') == audit['parent_keys_sha256']
        modes[mode] = {'parent_keys_sha256': audit['parent_keys_sha256'],
                       'reuses': (int(prev.get('reuses', 0)) + 1) if (mode in reused_modes and same_set) else 0,
                       'source': 'COM_READ' if mode in fresh_modes else 'EPOCH_REPLAY_VERIFIED'}
    m = {'schema': SCHEMA, 'network_sha256': network_sha256, 'edge_dictionary_sha256': edge_dictionary,
         'modes': modes, 'written_from_label': str(label), 'store': str(store_path)}
    write_json(epoch_dir / 'EPOCH.json', m)
    return m
