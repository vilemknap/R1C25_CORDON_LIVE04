"""LIVE04.10.4: faster ingestion of the representative path-link hierarchy.

Behaviour-identical re-implementation of ``r1_15a2_two_mode_v238.TwoModeRouteCollector.add_geometry``
(donor parent file, not edited).  The donor parses each of the ~52 million rows per capture with
generic helpers (generator expressions over 7 fields, ``_id`` per value); on the native model this is
roughly 40 % of the geometry phase.  Here the two row shapes Visum actually delivers - a pure route
parent (keys, blank link fields) and a pure link child (blank keys, numeric link fields) - take a fast
path with the same checks in the same order; every other row (flat rows, partial keys, strings,
blanks) goes through a verbatim copy of the donor logic.  Stored rows, audits, error codes and
commit cadence are identical (tests/test_live04_10_4.py compares the stores of both implementations).
"""
from __future__ import annotations
import hashlib
import struct
import zlib
from array import array
from collections import Counter, defaultdict

from .common import parent_module


def add_geometry(self, mode, raw_rows):
    two = parent_module('r1_15a2_two_mode_v238')
    SupplyContractError = two.SupplyContractError
    _filled, _id, _packed = two._filled, two._id, two._packed
    if mode not in self.mode_audits or self.mode_audits[mode].get('geometry_complete'):
        raise SupplyContractError('INVALID_OR_DUPLICATE_GEOMETRY_MODE')
    key_map = {tuple(r[1:]): r[0] for r in self.db.execute(
        'SELECT gid,orig,dest,path_index FROM geometry WHERE mode=?', (mode,))}
    seen = set()
    parent = None
    seq_ids = []
    updates = []
    hits_batch = []
    market_batch = set()
    postings = defaultdict(lambda: array('I'))
    raw_count = child_count = 0
    last_end = None
    mode_max_mult = Counter()
    zero = {'inter': 0, 'intra': 0}
    max_rows = int(self.settings['max_geometry_rows_per_mode'])
    max_links = int(self.settings['max_links_per_path'])
    commit_routes = int(self.settings['commit_routes'])
    edge_ids = self.edge_ids
    edge_keys = self.edge_keys
    profile_index_by_key = self.profile_index_by_key
    cal_indices = self.cal_indices

    def flush():
        if not updates:
            return
        self.control.checkpoint('GEOMETRY_STORE_COMMIT', mode=mode,
                                geometry_routes=len(seen), raw_rows=raw_count, link_children=child_count)
        self.db.executemany('UPDATE geometry SET edge_ids=?,edge_count=?,sequence_sha256=?,geometry_kind=? WHERE gid=?', updates)
        self.db.executemany('INSERT INTO profile_hits VALUES(?,?,?)', hits_batch)
        self.db.executemany('INSERT OR IGNORE INTO driver_markets VALUES(?,?,?)', market_batch)
        self._posting_chunk += 1
        self.db.executemany('INSERT INTO edge_postings VALUES(?,?,?)',
                            ((eid, self._posting_chunk, zlib.compress(_packed(ids), 1)) for eid, ids in postings.items()))
        self.db.commit()
        updates.clear(); hits_batch.clear(); market_batch.clear(); postings.clear()
        self.check_resources()

    def finish_route():
        if parent is None:
            return
        if parent not in key_map or parent in seen:
            raise SupplyContractError('ORPHAN_OR_REPEATED_GEOMETRY_PARENT:%r' % (parent,))
        gid = key_map[parent]
        kind = 'LINK_SEQUENCE'
        if not seq_ids:
            if parent[0] != parent[1]:
                zero['inter'] += 1
                kind = 'ZERO_LINK_INTERZONAL_NO_ADDVAL1_EFFECT'
            else:
                zero['intra'] += 1
                kind = 'ZERO_LINK_INTRAZONAL_NO_ADDVAL1_EFFECT'
        seen.add(parent)
        blob = _packed(seq_ids)
        updates.append((blob, len(seq_ids), hashlib.sha256(blob).hexdigest(), kind, gid))
        mult = Counter(seq_ids)
        hit = Counter()
        for eid, n in mult.items():
            postings[eid].extend((gid, n))
            key = edge_keys[eid]
            if n > mode_max_mult[key]:
                mode_max_mult[key] = n
            else:
                mode_max_mult[key] = max(mode_max_mult[key], n)
            for i in profile_index_by_key.get(key, ()):
                hit[i] += n
        hits_batch.extend((gid, i, n) for i, n in hit.items())
        if any(i in hit for i in cal_indices):
            market_batch.add((mode, parent[0], parent[1]))
        if len(updates) >= commit_routes:
            flush()

    def fid(x):
        t = type(x)
        if t is float:
            if x.is_integer():
                return int(x)
            return _id(x)
        if t is int:
            return x
        return _id(x)

    for raw in raw_rows:
        raw_count += 1
        if raw_count > max_rows:
            raise SupplyContractError('GEOMETRY_ROW_BUDGET_EXCEEDED')
        if len(raw) != 7:
            raise SupplyContractError('GEOMETRY_ROW_SCHEMA_MISMATCH')
        r0, r1, r2, r3, r4, r5, r6 = raw
        t3, t4, t5, t6 = type(r3), type(r4), type(r5), type(r6)
        # ---------------- fast path: pure link child (blank keys, numeric link fields)
        if (r0 == '' or r0 is None) and (r1 == '' or r1 is None) and (r2 == '' or r2 is None) \
                and (t3 is float or t3 is int) and (t4 is float or t4 is int) \
                and (t5 is float or t5 is int) and (t6 is float or t6 is int):
            if parent is None:
                raise SupplyContractError('ORPHAN_GEOMETRY_CHILD')
            idx = fid(r3); key = (fid(r4), fid(r5), fid(r6))
            if idx != len(seq_ids) + 1:
                raise SupplyContractError('GEOMETRY_LINK_INDEX_NOT_CONTIGUOUS')
            if last_end is not None and last_end != key[1]:
                raise SupplyContractError('DISCONNECTED_OFFICIAL_PATH_LINK_SEQUENCE')
            e = edge_ids.get(key)
            if e is None:
                raise SupplyContractError('PATH_EDGE_NOT_IN_LIVE_NETWORK:%r' % (key,))
            seq_ids.append(e); last_end = key[2]; child_count += 1
            if len(seq_ids) > max_links:
                raise SupplyContractError('SINGLE_ROUTE_LENGTH_BUDGET_EXCEEDED')
            continue
        # ---------------- fast path: pure route parent (numeric keys, blank link fields)
        t0, t1, t2 = type(r0), type(r1), type(r2)
        if (t0 is float or t0 is int) and (t1 is float or t1 is int) and (t2 is float or t2 is int) \
                and (r3 == '' or r3 is None) and (r4 == '' or r4 is None) and (r5 == '' or r5 is None) \
                and (r6 == '' or r6 is None):
            next_parent = (fid(r0), fid(r1), fid(r2))
            finish_route()
            parent = next_parent; seq_ids = []; last_end = None
            if parent not in key_map or parent in seen:
                raise SupplyContractError('UNKNOWN_OR_REOPENED_GEOMETRY_PARENT')
            continue
        # ---------------- verbatim donor logic for every other row shape
        supplied_parent = tuple(_filled(x) for x in raw[:3])
        supplied_link = tuple(_filled(x) for x in raw[3:])
        if not any(supplied_link):
            if not all(supplied_parent):
                raise SupplyContractError('INCOMPLETE_GEOMETRY_PARENT')
            next_parent = tuple(_id(x) for x in raw[:3])
            finish_route()
            parent = next_parent; seq_ids = []; last_end = None
            if parent not in key_map or parent in seen:
                raise SupplyContractError('UNKNOWN_OR_REOPENED_GEOMETRY_PARENT')
            continue
        if not all(supplied_link):
            raise SupplyContractError('INCOMPLETE_GEOMETRY_CHILD')
        if all(supplied_parent):
            k = tuple(_id(x) for x in raw[:3])
            if k != parent:
                finish_route()
                parent = k; seq_ids = []; last_end = None
                if parent not in key_map or parent in seen:
                    raise SupplyContractError('UNKNOWN_OR_REOPENED_FLAT_PARENT')
        elif any(supplied_parent):
            if parent is None or any(s and _id(raw[j]) != parent[j] for j, s in enumerate(supplied_parent)):
                raise SupplyContractError('CONFLICTING_PARTIAL_GEOMETRY_PARENT')
        if parent is None:
            raise SupplyContractError('ORPHAN_GEOMETRY_CHILD')
        idx = _id(raw[3]); key = tuple(_id(x) for x in raw[4:])
        if idx != len(seq_ids) + 1:
            raise SupplyContractError('GEOMETRY_LINK_INDEX_NOT_CONTIGUOUS')
        if last_end is not None and last_end != key[1]:
            raise SupplyContractError('DISCONNECTED_OFFICIAL_PATH_LINK_SEQUENCE')
        if key not in edge_ids:
            raise SupplyContractError('PATH_EDGE_NOT_IN_LIVE_NETWORK:%r' % (key,))
        seq_ids.append(edge_ids[key]); last_end = key[2]; child_count += 1
        if len(seq_ids) > max_links:
            raise SupplyContractError('SINGLE_ROUTE_LENGTH_BUDGET_EXCEEDED')
    finish_route(); flush()
    if seen != set(key_map):
        raise SupplyContractError('GEOMETRY_PARENT_COVERAGE_INCOMPLETE')
    for key, n in mode_max_mult.items():
        self.edge_max_multiplicity[key] = max(self.edge_max_multiplicity[key], n)
    h = hashlib.sha256()
    for o, d, ix, digest in self.db.execute('SELECT orig,dest,path_index,sequence_sha256 FROM geometry WHERE mode=? '
                                            'ORDER BY orig,dest,path_index', (mode,)):
        h.update(struct.pack('<III', o, d, ix)); h.update(digest.encode('ascii'))
    self.mode_audits[mode].update(geometry_complete=True, geometry_routes=len(seen),
                                  geometry_link_children=child_count, geometry_raw_rows=raw_count,
                                  zero_link_interzonal_paths=zero['inter'],
                                  zero_link_intrazonal_paths=zero['intra'],
                                  representative_geometry_sha256=h.hexdigest(), geometry_reads=1)
    self.geometry_count += len(seen)
    self.control.checkpoint('MODE_GEOMETRY_COMPLETE', force=True, mode=mode,
                            geometry_routes=len(seen), link_children=child_count)
    return self.mode_audits[mode]
