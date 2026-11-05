"""SUPPLYMIX on the cordon rows (LIVE04.4): the v7 @ 7b4c681 ADDVAL1 route-choice block.

User decision 2026-11-01: port the v7 SupplyMix (24 profile groups, 240 directed
links, four integer-safe trials, steps 8/6/4/2 x 0.5 ADDVAL1) to the cordon
calibrator, driven by the cordon rows instead of the count profiles.

What is the v7 donor, unchanged (parent/r1_15a2_supply_mix_v24917.py and
parent/r1_15a2_sequence_v23.py, byte-pinned):
  * propose_sequence_supply  - per driver the exact contiguous ON / OFF branches of
    the saved paths, the complete descending step ladder, the all-path impedance
    budget and impact audit;
  * select_groups / cost_safe_merged_candidate / snap_integer - one proved branch per
    driver, highest GEH first, disjoint links, <= 24 groups and <= 240 edges, every
    final integer ADDVAL1 legal (positive generalized cost, step/cumulative bounds);
  * worsened_profiles - drivers that got worse are excluded from smaller steps;
  * cold_supply_plan - reset (op 15) .. joint assignment, demand untouched, so the
    rollback recompute is deterministic;
  * the supply policy (lattice 0.5, max step 8, cumulative 15, bundle 360 s, ...) and
    the sequence settings come from the donor effective configuration.

What is cordon-specific (this module):
  * the drivers are the rows of the acceptance method (FIRST_LAST pairs and C17
    station rows) with a positive observation; a saved path is ON for a row when its
    FIRST_LAST contribution goes to that row (exactly the incidence rule of the
    cordon diagnostic), OFF when another path of the same (DSeg, origin, destination)
    does not contribute to it;
  * the "counted link" around which ON/OFF branches diverge and rejoin is the station
    link of the ON path (first, then last station) - the donor branch_pair is used;
  * the path authority is the SQLite path store of the cordon diagnostic of the
    parent (hash-bound to the capture), not a second Visum path export;
  * acceptance = the cordon block gate of SUPPLY_ADDVAL1 (cordon objective, secondary
    method, SEVRELAX3 supply budgets on the cordon rows, LONG support) + the shared
    objective; the first eligible trial is kept in place, otherwise the verified
    donor rollback restores the parent (cordon diagnostic hash identity).
"""
from __future__ import annotations
import copy
import json
import math
import sqlite3
import struct
import time
import traceback
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from .common import ROOT, require, parent_module, read_json, sha256
from .io import write_json, mkdir

RELEASE = 'LIVE04_SUPPLYMIX_CORDON_ROWS'
BLOCK = 'SUPPLY_ADDVAL1'
POLICY_SOURCE = 'provenance/live01/DONOR_EFFECTIVE_CONFIG_FORENSIC_ONLY.json'


# ------------------------------------------------------------------ options
def options(cfg):
    """v7 SupplyMix options from the pinned run options (sp_*)."""
    from .live04_v7 import run_options
    o = run_options(cfg)
    return {'enabled': bool(o['sp_enabled']) and bool(cfg['supply_mix']['enabled']),
            'every_n': int(o['sp_every_n_cycles']), 'start_cycle': int(o['sp_start_cycle']),
            'max_trials': int(o['sp_max_trials']), 'step_units': [int(x) for x in o['sp_step_units']],
            'max_groups': int(o['sp_max_groups']), 'max_edges': int(o['sp_max_edges']),
            'min_driver_geh': float(o['sp_min_driver_geh']), 'drivers': str(o['sp_drivers']).upper(),
            'reset_position': int(o['sp_cold_reset_position']),
            'min_attribution_coverage': float(o['sp_min_attribution_coverage'])}


def due(outer_cycle, opts):
    return parent_module('r1_15a2_supply_mix_v24917').due(outer_cycle, opts)


def donor_supply_config():
    """The v7/donor supply policy + sequence settings (forensic donor effective config)."""
    supply = read_json(ROOT / POLICY_SOURCE)['supply']
    return {k: copy.deepcopy(v) for k, v in supply.items()}


def sealed_supply_policy():
    """The donor SupplyPolicy (write/readback contract of apply_supply)."""
    return parent_module('r1_15a2_supply').SupplyPolicy.from_config({'supply': donor_supply_config()})


def supply_policy(opts):
    """SupplyPolicy of the donor with the v7 SupplyMix design overrides (coverage, candidates)."""
    import dataclasses
    raw = donor_supply_config()
    policy = sealed_supply_policy()
    seq = raw.get('sequence') or {}
    trial_steps = list(opts['step_units'])[:int(opts['max_trials'])]
    design_steps = sorted(set(seq.get('step_units_schedule', [1])) | set(trial_steps), reverse=True)
    repl = {}
    if float(opts['min_attribution_coverage']) < float(policy.min_attribution_coverage):
        repl['min_attribution_coverage'] = float(opts['min_attribution_coverage'])
    want = min(200, len(design_steps) * int(opts['max_groups']))
    if int(policy.max_candidates) < want:
        repl['max_candidates'] = want
    if repl:
        policy = dataclasses.replace(policy, **repl)
    return policy, seq, design_steps, repl


# ------------------------------------------------------------- row semantics
def row_semantics(evaluator, diag):
    """Directed station keys -> aggregated acceptance rows, and the driver profiles."""
    from .live03_incidence import C17_STATION, PROFILE_STATION
    method = evaluator.method
    inc = diag['_incidence'][method]
    stations = sorted(set(evaluator.station_map.values()))
    keys = [(a, b) for a in stations for b in stations if a != b]
    station_rows = bool(evaluator.contract.station_rows(method))
    if station_rows:
        keys += [(s, C17_STATION) for s in stations]
    profile_rows = bool(getattr(evaluator.contract, 'profile_rows', lambda m: False)(method))
    if profile_rows:
        keys += [(s, PROFILE_STATION) for s in stations]
    directed_to_row = list(inc.audit['directed_to_row'])
    require(len(directed_to_row) == len(keys), 'LIVE04_SUPPLY_DIRECTED_ROW_MAP_MISMATCH')
    key_row = {k: int(directed_to_row[i]) for i, k in enumerate(keys)}
    m = diag['methods'][method]
    profiles = []
    from .live02_v24917 import pair_key
    for i, (pair, model, observed) in enumerate(zip(m['pairs'], m['model'], m['observed'])):
        profiles.append({'countlocation_no': str(pair_key(pair[0], pair[1])), 'role': 'CALIBRATION',
                         'observed': float(observed), 'model': float(model), 'profile_weight': 1.0,
                         'row_index': i, 'origin_station': int(pair[0]), 'destination_station': int(pair[1])})
    return {'method': method, 'key_row': key_row, 'station_rows': station_rows, 'profile_rows': profile_rows,
            'profiles': profiles,
            'selected_dsegs': list(inc.audit['selected_dsegs'])}


def path_contributions(hits, sem):
    from .live03_incidence import first_last_contributions
    out = defaultdict(float)
    for key, w in first_last_contributions(hits, sem['station_rows'], sem.get('profile_rows', False)):
        out[sem['key_row'][key]] += float(w)
    return out


# ------------------------------------------------------------------ evidence
def _collector_base():
    return parent_module('r1_15a2_sequence_v23').ActualSequenceRouteCollector


def make_collector(*args, **kwargs):
    base = _collector_base()

    class CordonRouteEvidence(base):
        """Donor sequence evidence on the cordon path store (ON = contributes to the row)."""

        def __init__(self, profiles, policy, parent_hash, editable_keys, store, station_map, sem, folder, *,
                     max_unique_sequences, max_pairs_per_market, store_sha256):
            core = parent_module('r1_15a2_core')
            self.policy = policy
            self.parent_hash = parent_hash
            self.profiles = [dict(p) for p in profiles]
            self.editable = set(editable_keys)
            self.station_map = dict(station_map)
            self.sem = sem
            by_station = defaultdict(set)
            for key, s in self.station_map.items():
                by_station[int(s)].add(tuple(int(x) for x in key))
            from .live03_incidence import C17_STATION, PROFILE_STATION
            self.key_groups = []
            for p in self.profiles:
                a, b = p['origin_station'], p['destination_station']
                group = set(by_station.get(a, ()))
                if b not in (C17_STATION, PROFILE_STATION):
                    group |= by_station.get(b, set())
                self.key_groups.append(tuple(sorted(group)))
            self.drivers = []
            for i, p in enumerate(self.profiles):
                obs, model = float(p['observed']), float(p['model'])
                if obs <= 0 or abs(model - obs) < policy.min_residual or core.geh(model, obs) < policy.min_geh:
                    continue
                self.drivers.append(i)
            self.drivers.sort(key=lambda i: (-core.geh(self.profiles[i]['model'], self.profiles[i]['observed']), i))
            self.drivers = self.drivers[:policy.max_driver_profiles]
            self.driver_set = set(self.drivers)
            self.support = {i: 0.0 for i in self.drivers}
            self.market_counts = {i: 0 for i in self.drivers}
            self.probe_only_counts = {i: 0 for i in self.drivers}
            self.evidence = defaultdict(dict)
            self.skipped_branches = Counter()
            self.max_unique_sequences = int(max_unique_sequences)
            self.max_pairs_per_market = int(max_pairs_per_market)
            self.protected = {i for i, p in enumerate(self.profiles) if p['observed'] > 0 and
                              core.geh(p['model'], p['observed']) < 5.0}
            self.cal_indices = set(range(len(self.profiles)))
            self.route_db_path = str(Path(folder) / 'SUPPLY_CORDON_ROUTE_STORE.sqlite')
            require(not Path(self.route_db_path).exists(), 'ROUTE_STORE_WOULD_REPLACE_EXISTING_EVIDENCE')
            self.db = sqlite3.connect(self.route_db_path)
            self.db.execute('PRAGMA journal_mode=DELETE')
            self.db.execute('''CREATE TABLE routes (
               route_id INTEGER PRIMARY KEY, dseg TEXT NOT NULL, orig INTEGER NOT NULL,
               dest INTEGER NOT NULL, path_index INTEGER NOT NULL, volume REAL NOT NULL,
               sequence_json TEXT NOT NULL, cal_profile_ids TEXT NOT NULL,
               UNIQUE(dseg,orig,dest,path_index))''')
            self.db.execute('''CREATE TABLE route_edges (
               link_no INTEGER, from_no INTEGER, to_no INTEGER,
               route_id INTEGER, multiplicity INTEGER,
               UNIQUE(link_no,from_no,to_no,route_id))''')
            self._indexed = False
            self.route_count = 0
            self.store = Path(store)
            self.store_sha256 = store_sha256
            self.stats = Counter()
            self._consume()

        # ----------------------------------------------------------- stream
        def _consume(self):
            core = parent_module('r1_15a2_core')
            require(self.store.is_file(), 'LIVE04_SUPPLY_PATH_STORE_MISSING')
            require(sha256(self.store) == self.store_sha256, 'LIVE04_SUPPLY_PATH_STORE_HASH_CHANGED')
            con = sqlite3.connect('file:' + self.store.as_posix() + '?mode=ro', uri=True)
            try:
                edges = {int(i): (int(ln), int(fr), int(to)) for i, ln, fr, to in
                         con.execute('SELECT eid,link_no,from_no,to_no FROM edges')}
                codes = {core.norm_code(c) for c in self.sem['selected_dsegs']}
                query = ('SELECT g.orig,g.dest,v.dseg,g.path_index,g.edge_ids,g.edge_count,v.volume '
                         'FROM geometry g JOIN volumes v ON v.gid=g.gid ORDER BY g.orig,g.dest,v.dseg,g.path_index')
                market, routes = None, []
                for o, d, dseg, pi, blob, count, vol in con.execute(query):
                    code = core.norm_code(dseg)
                    if code not in codes:
                        continue
                    vol = float(vol)
                    require(math.isfinite(vol) and vol >= 0, 'LIVE04_SUPPLY_INVALID_PATH_VOLUME')
                    if vol <= 0:
                        continue
                    key = (code, int(o), int(d))
                    if key != market:
                        self._market(market, routes)
                        market, routes = key, []
                    eids = struct.unpack('<%dI' % count, blob) if count else ()
                    seq = tuple(edges[e] for e in eids)
                    hits = [self.station_map[e] for e in seq if e in self.station_map]
                    contrib = path_contributions(hits, self.sem)
                    multiplicity = Counter(seq)
                    rid = self._store(key, int(pi), vol, seq, multiplicity, contrib)
                    routes.append({'pk': (*key, int(pi)), 'route_id': rid, 'volume': vol, 'seq': seq,
                                   'multiplicity': multiplicity, 'contrib': contrib})
                self._market(market, routes)
                self.db.commit()
            finally:
                con.close()

        def _store(self, key, pi, vol, seq, multiplicity, contrib):
            self.db.execute('INSERT INTO routes(dseg,orig,dest,path_index,volume,sequence_json,cal_profile_ids) '
                            'VALUES(?,?,?,?,?,?,?)', (*key, pi, vol, json.dumps(seq, separators=(',', ':')),
                                                      json.dumps(sorted(contrib))))
            rid = self.db.execute('SELECT last_insert_rowid()').fetchone()[0]
            self.db.executemany('INSERT INTO route_edges(link_no,from_no,to_no,route_id,multiplicity) VALUES(?,?,?,?,?)',
                                [(*e, rid, n) for e, n in multiplicity.items()])
            self.route_count += 1
            self.stats['routes'] += 1
            return rid

        def _market(self, market, routes):
            if market is None or not routes:
                return
            seq_mod = parent_module('r1_15a2_sequence_v23')
            touched = set()
            for r in routes:
                touched |= set(r['contrib']) & self.driver_set
            for i in sorted(touched):
                on = [r for r in routes if i in r['contrib']]
                off = [r for r in routes if i not in r['contrib']]
                self.support[i] += sum(r['volume'] * r['contrib'][i] for r in on)
                self.market_counts[i] += 1
                group = set(self.key_groups[i])
                on.sort(key=lambda r: (-r['volume'], r['pk'])); off.sort(key=lambda r: (-r['volume'], r['pk']))

                def anchors(route):
                    # station links of the ON path that make it count for this row (first, then last)
                    links = [e for e in route['seq'] if e in group]
                    return list(dict.fromkeys(links[:1] + links[-1:]))
                if not off:
                    self.probe_only_counts[i] += 1
                    for o in on:
                        for profile in anchors(o)[:1]:
                            w = seq_mod.actual_on_probe_window(o['seq'], profile)
                            self._track(i, 'ON_ONLY_PROBE', w, (w[0][1], w[-1][2]), o['volume'], o['volume'], 0.,
                                        market, (o['pk'],), True)
                    continue
                pairs = [(o, f) for o in on for f in off]
                pairs.sort(key=lambda p: (-p[0]['volume'] * p[1]['volume'], p[0]['pk'], p[1]['pk']))
                if len(pairs) > self.max_pairs_per_market:
                    self.skipped_branches['PAIRS_TRUNCATED_REQUIRE_AUTHORITY_REVIEW'] += len(pairs) - self.max_pairs_per_market
                matched = False
                on_market = sum(r['volume'] for r in on); off_market = sum(r['volume'] for r in off)
                for o, f in pairs[:self.max_pairs_per_market]:
                    split = None
                    for profile in anchors(o):
                        if profile in f['multiplicity']:
                            continue
                        split = seq_mod.branch_pair(o['seq'], f['seq'], profile)
                        if split is not None:
                            break
                    if split is None:
                        self.skipped_branches['NO_COMMON_DIVERGE_REJOIN_ANCHORS'] += 1
                        continue
                    matched = True
                    v_on, v_off = o['volume'], f['volume']
                    ex = (o['pk'], f['pk'])
                    self._track(i, 'ON', split['on'], split['anchors'], v_on * v_off / max(off_market, 1e-30),
                                v_on, v_off, market, ex, opposing=split['off'])
                    self._track(i, 'OFF', split['off'], split['anchors'], v_off * v_on / max(on_market, 1e-30),
                                v_on, v_off, market, ex, opposing=split['on'])
                if not matched:
                    for o in on:
                        for profile in anchors(o)[:1]:
                            w = seq_mod.actual_on_probe_window(o['seq'], profile)
                            self._track(i, 'ON_ONLY_PROBE', w, (w[0][1], w[-1][2]), o['volume'], o['volume'], 0.,
                                        market, (o['pk'],), True)
                    self.skipped_branches['NO_BRANCHED_PAIR_ON_ONLY_PROBE'] += 1

        def finish(self):
            if not self._indexed:
                self.db.execute('CREATE INDEX route_edges_lookup ON route_edges(link_no,from_no,to_no)')
                self.db.execute('CREATE INDEX route_edges_path ON route_edges(route_id)')
                self.db.commit()
                self._indexed = True
            return {'schema': 'LIVE04_CORDON_ROUTE_EVIDENCE_V1', 'parent_hash': self.parent_hash,
                    'assignment_path_hash': self.store_sha256, 'path_store_route_count': self.route_count,
                    'path_store_type': 'SQLITE_ON_DISK', 'drivers': len(self.drivers),
                    'driver_support': {self.profiles[i]['countlocation_no']: self.support[i] for i in self.drivers},
                    'unique_sequence_bundles': sum(len(x) for x in self.evidence.values()),
                    'skipped_branch_cases': dict(self.skipped_branches),
                    'probe_only_markets': {self.profiles[i]['countlocation_no']: self.probe_only_counts[i]
                                           for i in self.drivers},
                    'authority': 'CORDON_DIAGNOSTIC_PATH_STORE_OF_THE_PARENT'}

    return CordonRouteEvidence(*args, **kwargs)


def design(adapter, diag, folder, state, opts):
    """Donor sequence design on the cordon rows; returns (design, policy audit)."""
    seq_mod = parent_module('r1_15a2_sequence_v23')
    folder = Path(folder); mkdir(folder)
    require(diag.get('valid', True) and diag.get('capture_db_retained', True) is not False,
            'LIVE04_SUPPLY_PARENT_PATH_STORE_NOT_RETAINED')
    store = Path(diag['folder']) / 'p.sqlite'
    policy, seq, design_steps, overrides = supply_policy(opts)
    links = adapter.read_links()
    require(adapter.baseline_addval is not None, 'LIVE04_SUPPLY_BASELINE_ADDVAL_MISSING')
    sem = row_semantics(adapter.evaluator, diag)
    collector = make_collector(sem['profiles'], policy, state['state_hash'],
                               [k for k, r in links.items() if r['eligible']], store, adapter.evaluator.station_map,
                               sem, folder, max_unique_sequences=seq.get('max_unique_sequences', 100000),
                               max_pairs_per_market=seq.get('max_pairs_per_market', 64),
                               store_sha256=diag['capture_cache_sha256'])
    try:
        out = seq_mod.propose_sequence_supply(collector, links, adapter.baseline_addval, policy,
                                              sequence_caps=seq.get('sequence_cap_schedule', [4, 2, 1]),
                                              max_collateral_ratio=seq.get('max_collateral_volume_to_driver_ratio'),
                                              step_units=design_steps)
    finally:
        collector.close()
    out['design_step_units'] = design_steps
    out['design_policy_override'] = overrides
    out['drivers'] = [sem['profiles'][i]['countlocation_no'] for i in collector.drivers]
    adapter.supply_path_proof = {'parent_hash': state['state_hash'],
                                 'assignment_path_hash': out['authority']['assignment_path_hash']}
    write_json(folder / 'SUPPLY_PATH_SEQUENCE_DESIGN.json', out)
    return out, policy, sem


# --------------------------------------------------------------------- block
def supply_block(tx, adapter, cfg, folder, control, state, diag, anchors, reference, policy, *, outer_cycle, opts):
    """One SupplyMix block: verified state (changed or parent) or an exception after recovery."""
    sm = parent_module('r1_15a2_supply_mix_v24917')
    txm = parent_module('r1_15a2_inplace_transaction_v24915p2')
    SupplyContractError = parent_module('r1_15a2_supply').SupplyContractError
    base = SimpleNamespace(**tx.ctrl_ns)
    ctrl = SimpleNamespace(**tx.coupled_ns)
    folder = Path(folder); mkdir(folder)
    t0 = time.time()
    sup_cfg = ctrl._generation_counts_cfg(cfg)
    rec = {'release': RELEASE, 'donor_release': sm.RELEASE, 'outer_cycle': outer_cycle, 'status': 'DESIGNING',
           'attempts': [], 'options': dict(opts), 'search_complete': False, 'stationarity_confirmed': False}
    baseline_value = base.ledger(diag, state, anchors, policy, reference, sup_cfg)
    rec['objective_before'] = baseline_value
    baseline_diag_hash = base.diagnostic_hash(diag)
    own = {'candidate': None, 'applied': None}

    def save():
        rec['elapsed_s'] = round(time.time() - t0, 1)
        try:
            write_json(folder / 'SUPPLYMIX_BLOCK_RESULT.json', rec)
        except Exception as io_exc:
            rec.setdefault('evidence_write_errors', []).append(repr(io_exc)[:300])

    def remember(candidate):
        changes = {tuple(r['key']): dict(r) for r in (own['candidate'] or {}).get('changes', [])}
        for row in candidate.get('changes', []):
            changes.setdefault(tuple(row['key']), dict(row))
        own['candidate'] = dict(candidate, changes=list(changes.values()))

    def rollback(reason):
        with base.recovery_scope(control, 'LIVE04_SUPPLYMIX_ROLLBACK'):
            rb, rolled = base._rollback_candidate(adapter, BLOCK, state, baseline_diag_hash, folder / 'ROLLBACK', [],
                                                  own['candidate'], diag)
        write_json(folder / 'ROLLBACK_SUMMARY.json', dict(rb, reason=reason))
        if base.diagnostic_hash(rolled) != baseline_diag_hash or adapter.snapshot() != state:
            raise SupplyContractError('LIVE04_SUPPLYMIX_ROLLBACK_NOT_EQUIVALENT')
        own.update(candidate=None, applied=None)

    # ---------------------------------------------------------- design (no write)
    try:
        control.checkpoint('LIVE04_SUPPLYMIX_DESIGN', force=True)
        design_, spolicy, sem = design(adapter, diag, folder / 'DESIGN', state, opts)
        link_cost_basis = adapter.read_links()
        if adapter.snapshot() != state:
            raise SupplyContractError('COSTFIX1_LINK_READ_CHANGED_PARENT')
        rec['design_step_units'] = design_['design_step_units']
        rec['design_policy_override'] = design_['design_policy_override']
        rec['design_candidates'] = len(design_.get('candidates') or [])
        rec['drivers'] = design_['drivers']
        skipped = Counter(str(r.get('reason')) for r in design_.get('skipped') or [])
        rec['design_skipped_reasons'] = dict(skipped)
    except BaseException as exc:
        if not isinstance(exc, Exception) or isinstance(exc, (base.UserStopRequested, base.TimeBudgetReached)):
            raise
        if adapter.snapshot() != state:
            raise SupplyContractError('LIVE04_SUPPLYMIX_DESIGN_CHANGED_MODEL') from exc
        rec.update(status='DESIGN_FAILED_NO_WRITE', error=str(exc)[:2000], traceback=traceback.format_exc()[-4000:])
        save()
        return False, state, diag, baseline_value, rec
    table = sm.profile_table(sem['profiles'])
    mode = sm.driver_mode(opts, (adapter.v24917_status or {}).get('last_phase'))
    rec['driver_mode'] = mode
    groups = sm.select_groups(design_, table, opts, mode)
    rec['selected_groups'] = [{k: v for k, v in g.items() if k not in ('keys', 'ladder')} for g in groups]
    if not groups:
        rec.update(status='NO_DRIVER_BRANCH', search_complete=True)
        save()
        return False, state, diag, baseline_value, rec
    av_type = sm.addval_integer(adapter)
    rec['addval1_value_type'] = av_type
    rec['costfix1'] = {'enabled': True, 'trials': [], 'basis': 'LIVE_T0_C_PLUS_FINAL_INTEGER_ADDVAL1',
                       'alternate_proved_branches_allowed': True}
    excluded = set()
    attempted = set()
    units = list(opts['step_units'])[:int(opts['max_trials'])]
    from .live02_step1 import _drop_capture
    attempt = None
    try:
        for ordinal, unit in enumerate(units, start=1):
            attempt = None
            cand, cost_audit = sm.cost_safe_merged_candidate(design_, table, opts, mode, unit, state['state_hash'],
                                                             link_cost_basis, adapter.baseline_addval, spolicy,
                                                             av_type['integer'], excluded_profiles=excluded)
            rec['costfix1']['trials'].append(cost_audit)
            if cand is None:
                rec['stop_reason'] = 'NO_COST_SAFE_PROVED_BRANCH'
                break
            if cand['candidate_id'] in attempted:
                rec['stop_reason'] = 'DUPLICATE_COST_SAFE_CANDIDATE'
                cost_audit['skip_reason'] = 'DUPLICATE_COST_SAFE_CANDIDATE'
                continue          # a smaller limit may still produce a new candidate (v7)
            rec.pop('stop_reason', None)
            attempted.add(cand['candidate_id'])
            tfolder = folder / ('TRY_%02d' % ordinal); mkdir(tfolder)
            write_json(tfolder / 'SUPPLYMIX_CANDIDATE.json', cand)
            attempt = {'trial': ordinal, 'step_units': unit, 'addval1_step': unit * 0.5,
                       'generalized_seconds_step': unit * 5.0, 'candidate_id': cand['candidate_id'],
                       'edges': len(cand['changes']), 'positive_edges': cand['positive_edges'],
                       'negative_edges': cand['negative_edges'], 'members': cand['members']}
            if own['applied'] is not None:
                txm.restore_supply_parameters(adapter, state, own['applied']['changes'], tfolder / 'RESTORE_PARENT')
                own['applied'] = None
            require(adapter.snapshot() == state, 'LIVE04_SUPPLYMIX_PARENT_CHANGED')
            adapter.supply_path_proof = dict(adapter.supply_path_proof or {}, parent_hash=state['state_hash'])
            control.checkpoint('TRIAL_APPLY', block=BLOCK, candidate=base._candidate_signature(BLOCK, cand, []))
            remember(cand)                          # owned before the first COM write
            own['applied'] = cand
            adapter.apply_supply(cand, state, tfolder)
            control.checkpoint('TRIAL_ASSIGNMENT', block=BLOCK)
            gap = base._assign_candidate(adapter, tfolder / 'ASSIGNMENT', BLOCK)
            after = adapter.snapshot()
            base.assert_freeze(state, after, BLOCK, rows=[], candidate=cand, cfg=sup_cfg)
            control.checkpoint('TRIAL_DIAGNOSTICS', block=BLOCK)
            after_diag = adapter.diagnostics(tfolder / 'DIAGNOSTICS', 'STEP1_TRIAL')
            if adapter.snapshot() != after:
                raise SupplyContractError('TRIAL_DIAGNOSTICS_CHANGED_MODEL')
            def decide(d, _after=after):
                v = base.ledger(d, _after, anchors, policy, reference, sup_cfg)
                dec = adapter.block_gate(BLOCK, diag, d, [])
                imp = baseline_value['total'] - v['total']
                dec.update(shared_ledger_before=baseline_value, shared_ledger_after=v,
                           shared_objective_improvement=imp)
                minimum = base.number(sup_cfg.get('shared_objective', {}).get('minimum_improvement', 1e-8))
                if imp <= minimum:
                    dec['accepted'] = False
                    dec.setdefault('reasons', []).append('SHARED_OBJECTIVE_NOT_IMPROVED')
                return v, dec
            after_value, decision = decide(after_diag)
            if decision.get('accepted'):
                from .live04_confirm import confirm_before_accept
                full, v2, dec2, caudit = confirm_before_accept(adapter, tfolder / 'DIAGNOSTICS_CONFIRM', after_diag,
                                                               after, decide, True)
                attempt['acceptance_confirm'] = caudit.get('status')
                if dec2 is not None:
                    _drop_capture(tfolder / 'DIAGNOSTICS')
                    after_diag, after_value, decision = full, v2, dec2
            write_json(tfolder / 'ACCEPTANCE.json', decision)
            valid = bool(after_diag.get('valid', True))
            after_table = sm.profile_table(row_semantics(adapter.evaluator, after_diag)['profiles']) if valid else {}
            drivers = []
            for m in cand['members']:
                p = m['driver_profile']; b = table.get(p, {}); a = after_table.get(p, {})
                drivers.append({'row': p, 'geh_before': round(b.get('geh', 0.0), 3), 'geh_after': round(a.get('geh', 0.0), 3),
                                'model_before': round(b.get('model', 0.0), 3), 'model_after': round(a.get('model', 0.0), 3),
                                'observed': round(b.get('observed', 0.0), 3)})
            attempt.update(status='ELIGIBLE' if decision.get('accepted') else 'REJECTED', gap=gap,
                           decision_reasons=list(decision.get('reasons') or []), objective_after=after_value,
                           drivers=drivers)
            rec['attempts'].append(attempt)
            attempt = None
            save()
            if decision.get('accepted'):
                rec.update(status='ACCEPTED', accepted_trial=ordinal, adopted_in_place=True, objective_after=after_value,
                           search_complete=True, addval1_changes=len(cand['changes']))
                own.update(candidate=None, applied=None)
                save()
                return True, after, after_diag, after_value, rec
            if not adapter.evaluator.live02['evaluation']['keep_trial_capture_db']:
                rec['attempts'][-1]['rejected_capture_removed'] = _drop_capture(tfolder / 'DIAGNOSTICS')
            excluded |= set(sm.worsened_profiles(cand['members'], table, after_table))
            rec['attempts'][-1]['excluded_after_trial'] = sorted(excluded)
        if own['candidate'] is not None:
            rollback('SEARCH_EXHAUSTED')
        rec['status'] = ('NO_COST_SAFE_CANDIDATE' if rec.get('stop_reason') == 'NO_COST_SAFE_PROVED_BRANCH'
                         and not rec['attempts'] else 'NO_ACCEPTED_TRIAL')
        # exhausting this legal lattice is not a stationarity proof (v7)
        rec['search_complete'] = rec['status'] != 'NO_COST_SAFE_CANDIDATE'
        save()
        return False, state, diag, baseline_value, rec
    except BaseException as exc:
        if attempt is not None:
            attempt.update(status='FAILED', error=str(exc)[:2000])
            rec['attempts'].append(attempt)
        rec.update(status='FAILED', error=str(exc)[:2000], search_complete=False)
        save()
        stop = not isinstance(exc, Exception) or isinstance(exc, (base.UserStopRequested, base.TimeBudgetReached))
        if own['candidate'] is not None:
            rollback('TRIAL_ERROR')            # a failed rollback raises: the run stops with a state readback
            rec['status'] = 'TRIAL_FAILED_ROLLBACK_VERIFIED'
            save()
            if stop or isinstance(exc, OSError):
                raise
            return False, state, diag, baseline_value, rec
        if stop:
            raise
        rec['status'] = 'TRIAL_FAILED_BEFORE_WRITE'
        save()
        return False, state, diag, baseline_value, rec
