"""LIVE03 observation contract: survey semantics of the 2026 ANPR cordon (OA, RPDI).

Authority: data/audited/AUDITED_MATRICES.npz (18x18 per category/trip type/stage,
row = VYSTUP (O), column = VSTUP (D), index 16 = C17 "bez paru", index 17 =
"vjazd-vyjazd").  Decisions taken from the survey report (Sprievodna sprava,
kap. 6 a 7) and recorded in OBSERVATION_CONTRACT.json of every run:

* pair semantics  FIRST_LAST: an ANPR trip is (first station, last station);
* pair targets    Transit RPDI (the model represents a transit trip as ONE path;
                  a NonTransit trip stops inside the cordon = TWO model trips);
* C17 targets     per station, in crossing units:
                  isolated detections  T[s,C17] + T[C17,s]
                + cyclic trips        k_cyc * (T[s,RET] + T[RET,s])   (k_cyc = 2)
                + NonTransit ends     sum_b N[s,b] + N[b,s]
                  model: saved paths crossing the cordon once (or entering and
                  leaving through the same station, counted twice);
* year bridge     2026 survey -> 2025 model, factor 1.0 (no conversion, user
                  decision 2026-10-25).
The secondary/diagnostic methods (EXACT_TWO_HITS, ALL_ORDERED_UNIQUE_PAIRS) are
compared with the same Transit pair targets (pairs only).
"""
from __future__ import annotations
import numpy as np
from .common import ROOT, require, canonical_hash, sha256
from .live03_incidence import aggregate_observations, FIRST_LAST, C17_STATION, PROFILE_STATION, PROFILE_STATION_B, PROFILE_IDS, DIRECTIONAL
import json
from .state import observation_roster

SCHEMA = 'LIVE03_OBSERVATION_CONTRACT_V1'
C17_INDEX, RETURN_INDEX = 16, 17
STATIONS = tuple(range(1, 17))
PAIR_MATRICES = ('Transit', 'ALL')
C17_POLICIES = ('STATION_MARGINS', 'DISABLED')
ROLES = ('PRIMARY', 'SECONDARY', 'DIAGNOSTIC')
PROFILE_SOURCES = ('D3_ALL_ROW_PLUS_COLUMN_SUM', 'E41_RAW_DETECTIONS_DIRECTIONAL')
RAW_SOURCE = 'E41_RAW_DETECTIONS_DIRECTIONAL'
EVIDENCE_SCHEMA = 'LIVE04_10_STATION_PROFILE_EVIDENCE_V1'
SIGN_EDGES_SCHEMA = 'LIVE04_10_STATION_PROFILE_SIGN_EDGES_V1'


def validate_profiles(obs):
    """Optional station profiles.

    LIVE04.9  D3_ALL_ROW_PLUS_COLUMN_SUM: 16 bidirectional rows, target = D3 row + column sum.
    LIVE04.10 E41_RAW_DETECTIONS_DIRECTIONAL: 32 rows (one per directed station edge),
              target = raw ANPR detections OA per sign x D3 zone coefficient OA_RPDI;
              which edge is '+' and which '-' is fixed by the report maps (sign_edges, user decision
              2026-11-05); the agreement of the model paths with it is recorded as a diagnostic."""
    sp = obs.get('station_profiles')
    if sp is None:
        return None
    require(isinstance(sp, dict) and isinstance(sp.get('enabled'), bool) and sp.get('source') in PROFILE_SOURCES,
            'LIVE04_STATION_PROFILES')
    keys = {'enabled', 'source', 'row_weight'}
    if sp['source'] == RAW_SOURCE:
        keys |= {'evidence', 'evidence_sha256', 'sign_edges', 'sign_edges_sha256'}
    require(set(sp) - {'note'} == keys, 'LIVE04_STATION_PROFILES')
    w = sp['row_weight']
    require(not isinstance(w, bool) and isinstance(w, (int, float)) and np.isfinite(float(w)) and 0 < float(w) <= 10,
            'LIVE04_STATION_PROFILE_WEIGHT')
    if sp['source'] == RAW_SOURCE:
        require(all(isinstance(sp[k], str) for k in ('evidence', 'evidence_sha256', 'sign_edges', 'sign_edges_sha256')),
                'LIVE04_STATION_PROFILE_EVIDENCE')
    return sp


def _raw_evidence(sp):
    p = ROOT / sp['evidence']
    require(p.is_file(), 'LIVE04_STATION_PROFILE_EVIDENCE_MISSING')
    require(sha256(p) == sp['evidence_sha256'], 'LIVE04_STATION_PROFILE_EVIDENCE_HASH_CHANGED')
    doc = json.loads(p.read_text(encoding='utf-8'))
    require(doc.get('schema') == EVIDENCE_SCHEMA, 'LIVE04_STATION_PROFILE_EVIDENCE_SCHEMA')
    d3 = ROOT / 'data/source/D3.xlsx'
    require(d3.is_file() and sha256(d3) == doc['source_d3_sha256'], 'LIVE04_STATION_PROFILE_D3_MISMATCH')
    by = {int(st['station']): st for st in doc['stations']}
    require(sorted(by) == list(STATIONS), 'LIVE04_STATION_PROFILE_EVIDENCE_STATIONS')
    for st in by.values():
        require(set(st['signs']) == {'+', '-'}, 'LIVE04_STATION_PROFILE_EVIDENCE_SIGNS')
        for g in st['signs'].values():
            t = float(g['target_rpdi'])
            require(np.isfinite(t) and t >= 0, 'LIVE04_STATION_PROFILE_EVIDENCE_TARGET')
            require(abs(t - float(g['oa_12h_with_unrecognized_share']) * float(st['zone_coefficient_oa_rpdi'])) <= 1e-6 * max(1.0, t),
                    'LIVE04_STATION_PROFILE_EVIDENCE_ARITHMETIC')
    return p, doc, by


def _sign_edges(sp):
    p = ROOT / sp['sign_edges']
    require(p.is_file(), 'LIVE04_STATION_PROFILE_SIGN_EDGES_MISSING')
    require(sha256(p) == sp['sign_edges_sha256'], 'LIVE04_STATION_PROFILE_SIGN_EDGES_HASH_CHANGED')
    doc = json.loads(p.read_text(encoding='utf-8'))
    require(doc.get('schema') == SIGN_EDGES_SCHEMA, 'LIVE04_STATION_PROFILE_SIGN_EDGES_SCHEMA')
    out = {}
    for st in doc['stations']:
        plus, minus = tuple(int(x) for x in st['plus_edge']), tuple(int(x) for x in st['minus_edge'])
        require(len(plus) == 3 and len(minus) == 3 and plus != minus, 'LIVE04_STATION_PROFILE_SIGN_EDGES_INVALID')
        out[int(st['station'])] = {'plus': plus, 'minus': minus, 'source': st['source']}
    require(sorted(out) == list(STATIONS), 'LIVE04_STATION_PROFILE_SIGN_EDGES_STATIONS')
    # LIVE04.10.1: static check against the station mapping, without any path capture.
    import csv
    mapped = {}
    with open(ROOT / 'data/audited/STATION_MAPPING.csv', encoding='utf-8-sig') as f:
        for r in csv.DictReader(f, delimiter=';'):
            mapped.setdefault(int(r['station_id']), set()).add((int(r['link_no']), int(r['from_node_no']), int(r['to_node_no'])))
    for s, e in out.items():
        require(mapped.get(s) == {e['plus'], e['minus']}, 'LIVE04_PROFILE_SIGN_EDGE_NOT_A_STATION_EDGE:SDP%d' % s)
    return doc, out


def resolve_sign_sides(raw_contexts, model_contexts):
    """Agreement of the sign '+' with side A (0) of one station.

    raw_contexts:   {'+': {'DEP:t': n, ...}, '-': {...}} (survey, consecutive detections)
    model_contexts: {0: {'DEP:t': v, ...}, 1: {...}}     (model paths, consecutive station hits)
    score = sum_c sqrt(w_raw w_mod) r_c m_c / sum_c sqrt(w_raw w_mod), r_c = (n+ - n-)/(n+ + n-),
    m_c = (vA - vB)/(vA + vB); score > 0: '+' = side A, score < 0: '+' = side B; |score| = agreement."""
    num = den = 0.0
    for c in set(raw_contexts['+']) | set(raw_contexts['-']):
        p, m = float(raw_contexts['+'].get(c, 0)), float(raw_contexts['-'].get(c, 0))
        a, b = float(model_contexts[0].get(c, 0)), float(model_contexts[1].get(c, 0))
        if p + m <= 0 or a + b <= 0:
            continue
        w = np.sqrt((p + m) * (a + b))
        num += w * (p - m) / (p + m) * (a - b) / (a + b)
        den += w
    return (num / den) if den > 0 else 0.0


def validate(obs):
    require(obs.get('schema') == 'LIVE03_OBSERVATIONS_V1', 'LIVE03_OBSERVATIONS_SCHEMA')
    require(obs.get('semantics') == FIRST_LAST, 'LIVE03_SEMANTICS_MUST_BE_FIRST_LAST')
    require(obs.get('category') == 'OA' and obs.get('stage') == 'D3_RPDI', 'LIVE03_OA_RPDI_ONLY')
    require(obs.get('pair_matrix') in PAIR_MATRICES, 'LIVE03_PAIR_MATRIX')
    require(obs.get('c17_policy') in C17_POLICIES, 'LIVE03_C17_POLICY')
    comp = obs.get('c17_components') or {}
    require(set(comp) == {'isolated', 'cyclic', 'cyclic_crossings_per_trip', 'nontransit_endpoints'}, 'LIVE03_C17_COMPONENTS')
    require(float(comp['cyclic_crossings_per_trip']) in (1.0, 2.0), 'LIVE03_CYCLIC_MULTIPLICITY')
    if obs['pair_matrix'] == 'ALL':
        # ALL pairs already contain NonTransit trips: adding them to C17 counts twice.
        require(not comp['nontransit_endpoints'], 'LIVE03_NONTRANSIT_DOUBLE_COUNT')
    w = float(obs.get('c17_row_weight', 1.0))
    require(np.isfinite(w) and w > 0, 'LIVE03_C17_WEIGHT')
    yb = obs.get('year_bridge') or {}
    require(yb.get('survey_year') == 2026 and yb.get('model_year') == 2025, 'LIVE03_YEAR_BRIDGE_YEARS')
    f = float(yb.get('factor', float('nan')))
    require(np.isfinite(f) and 0.5 <= f <= 2.0, 'LIVE03_YEAR_FACTOR')
    require(bool(yb.get('approval')), 'LIVE03_YEAR_BRIDGE_APPROVAL_MISSING')
    validate_profiles(obs)
    methods = obs.get('methods') or {}
    require(methods.get(FIRST_LAST) == 'PRIMARY', 'LIVE03_FIRST_LAST_MUST_BE_PRIMARY')
    require(all(r in ROLES for r in methods.values()) and list(methods.values()).count('PRIMARY') == 1
            and list(methods.values()).count('SECONDARY') <= 1, 'LIVE03_METHOD_ROLES')
    require(set(methods) <= {FIRST_LAST, 'EXACT_TWO_HITS', 'ALL_ORDERED_UNIQUE_PAIRS'}, 'LIVE03_UNKNOWN_METHOD')
    return obs


def _npz(obs):
    p = ROOT / obs['authority_npz']
    require(p.is_file(), 'LIVE03_AUTHORITY_NPZ_MISSING')
    require(sha256(p) == obs['authority_npz_sha256'], 'LIVE03_AUTHORITY_NPZ_HASH_CHANGED')
    with np.load(p) as d:
        out = {k: np.asarray(d['%s_%s_%s' % (obs['category'], k, obs['stage'])], dtype=float)
               for k in ('Transit', 'NonTransit', 'ALL')}
    return p, out


def _check(name, m):
    require(m.shape == (18, 18) and np.all(np.isfinite(m)) and np.all(m >= 0), 'LIVE03_MATRIX_INVALID:' + name)
    require(np.array_equal(m, m.T), 'LIVE03_MATRIX_NOT_SYMMETRIC:' + name)
    require(np.all(np.diag(m)[:16] == 0), 'LIVE03_INTERIOR_DIAGONAL_NONZERO:' + name)


class Contract:
    """Effective targets per method (directed keys, as aggregate_observations expects)."""

    def __init__(self, obs):
        self.obs = validate(dict(obs))
        path, mats = _npz(self.obs)
        for k, m in mats.items():
            _check(k, m)
        T, N, A = mats['Transit'], mats['NonTransit'], mats['ALL']
        require(np.all(N[C17_INDEX:, :] == 0) and np.all(N[:, C17_INDEX:] == 0), 'LIVE03_NONTRANSIT_HAS_C17')
        self.factor = float(self.obs['year_bridge']['factor'])
        P = (T if self.obs['pair_matrix'] == 'Transit' else A)
        comp = self.obs['c17_components']
        self.pair_cells = {(a, b): self.factor * float(P[a - 1, b - 1]) for a in STATIONS for b in STATIONS if a != b}
        k_cyc = float(comp['cyclic_crossings_per_trip'])
        self.station_parts = []
        self.station_cells = {}
        if self.obs['c17_policy'] == 'STATION_MARGINS':
            for s in STATIONS:
                i = s - 1
                iso_out, iso_in = float(T[i, C17_INDEX]), float(T[C17_INDEX, i])
                cyc_a, cyc_b = float(T[i, RETURN_INDEX]), float(T[RETURN_INDEX, i])
                nt_out, nt_in = float(N[i, :16].sum()), float(N[:16, i].sum())
                row_part = (iso_out if comp['isolated'] else 0.) + (k_cyc * cyc_a if comp['cyclic'] else 0.) + \
                           (nt_out if comp['nontransit_endpoints'] else 0.)
                col_part = (iso_in if comp['isolated'] else 0.) + (k_cyc * cyc_b if comp['cyclic'] else 0.) + \
                           (nt_in if comp['nontransit_endpoints'] else 0.)
                # Two directed keys; only their bidirectional sum enters the objective.
                self.station_cells[(s, C17_STATION)] = self.factor * row_part
                self.station_cells[(C17_STATION, s)] = self.factor * col_part
                self.station_parts.append({'station': s, 'isolated_row_exit': iso_out, 'isolated_col_entry': iso_in,
                                           'cyclic_row': cyc_a, 'cyclic_col': cyc_b, 'cyclic_crossings_per_trip': k_cyc,
                                           'nontransit_row_sum': nt_out, 'nontransit_col_sum': nt_in,
                                           'target_crossings': self.factor * (row_part + col_part)})
        # LIVE04.9 station profiles: row + column sum of the ALL matrix (pairs, C17, vjazd-vyjazd)
        # = every vehicle crossing of station s; model = station link volume (every hit).
        # LIVE04.10 directional profiles: one row per directed station edge, target from the raw
        # ANPR detections (every pass incl. passes in the middle of a multi-station trip).
        self.profile_cells = {}
        self.profile_parts = []
        self.profile_directional = False
        self.direction_map = None
        self.direction_audit = None
        sp = self.obs.get('station_profiles')
        if sp and sp['enabled'] and sp['source'] == RAW_SOURCE:
            ev_path, _, by = _raw_evidence(sp)
            _, self.sign_edges = _sign_edges(sp)
            self.profile_directional = True
            self.profile_evidence = by
            self.profile_sign_targets = {s: {g: self.factor * float(by[s]['signs'][g]['target_rpdi']) for g in '+-'}
                                         for s in STATIONS}
            for s in STATIONS:
                self.profile_parts.append({'station': s, 'zone_coefficient_oa_rpdi': by[s]['zone_coefficient_oa_rpdi'],
                                           'target_plus': self.profile_sign_targets[s]['+'],
                                           'target_minus': self.profile_sign_targets[s]['-'],
                                           'target_crossings': sum(self.profile_sign_targets[s].values())})
                for pid in PROFILE_IDS:      # placeholders until the sign -> side map is resolved
                    self.profile_cells[(s, pid)] = None
                    self.profile_cells[(pid, s)] = 0.0
        elif sp and sp['enabled']:
            for s in STATIONS:
                i = s - 1
                rsum, csum = float(A[i, :].sum()), float(A[:, i].sum())
                self.profile_cells[(s, PROFILE_STATION)] = self.factor * rsum
                self.profile_cells[(PROFILE_STATION, s)] = self.factor * csum
                self.profile_parts.append({'station': s, 'all_row_sum': rsum, 'all_column_sum': csum,
                                           'target_crossings': self.factor * (rsum + csum)})
        self.methods = dict(self.obs['methods'])
        self.primary = next(m for m, r in self.methods.items() if r == 'PRIMARY')
        self.secondary = next((m for m, r in self.methods.items() if r == 'SECONDARY'), None)
        self.enumeration = tuple(self.methods)
        self.audit = {
            'schema': SCHEMA, 'source_path': path.relative_to(ROOT).as_posix(), 'source_sha256': sha256(path),
            'orientation': 'ROW=VYSTUP(O) COL=VSTUP(D); BIDIRECTIONAL_SUM_IN_OBJECTIVE',
            'semantics': FIRST_LAST, 'semantics_authority': 'SURVEY_REPORT_KAP6_KROK2_KROK3_FIRST_LAST_STATION',
            'pair_matrix': self.obs['pair_matrix'], 'c17_policy': self.obs['c17_policy'],
            'c17_components': comp, 'c17_row_weight': float(self.obs.get('c17_row_weight', 1.0)),
            'year_bridge': dict(self.obs['year_bridge']),
            'methods': self.methods, 'primary': self.primary, 'secondary': self.secondary,
            'transit_interior_sum': float(T[:16, :16].sum()), 'nontransit_interior_sum': float(N[:16, :16].sum()),
            'all_interior_sum': float(A[:16, :16].sum()),
            'all_minus_transit_minus_nontransit_max_abs': float(np.max(np.abs(A - T - N))),
            'pair_target_unordered_sum': float(sum(self.pair_cells.values())),
            'c17_target_crossings_sum': float(sum(self.station_cells.values())),
            'c17_station_parts': self.station_parts,
            'station_profiles': dict(sp) if sp else None,
            'station_profile_parts': self.profile_parts,
            'station_profile_target_sum': float(sum(p['target_crossings'] for p in self.profile_parts)),
            'station_profile_mode': (DIRECTIONAL if self.profile_directional else ('BIDIRECTIONAL' if self.profile_cells else None)),
            'rows': {m: self.row_count(m) for m in self.methods},
            'production_ready': False,
            'observation_status': 'APPROVED_BY_SURVEY_REPORT_AND_USER_FOR_LIVE03_TECHNICAL_CALIBRATION'}
        self.audit['contract_sha256'] = canonical_hash({k: v for k, v in self.audit.items() if k not in ('c17_station_parts', 'station_profile_parts')})

    def station_rows(self, method):
        return method == FIRST_LAST and bool(self.station_cells)

    def profile_rows(self, method):
        return method == FIRST_LAST and bool(self.profile_cells)

    def profile_row_count(self, method):
        if not self.profile_rows(method):
            return 0
        return 32 if self.profile_directional else 16

    def row_count(self, method):
        return 120 + (16 if self.station_rows(method) else 0) + self.profile_row_count(method)

    def resolve_directions(self, inc):
        """LIVE04.10: which station edge carries the '+' and which the '-' targets.

        Fixed by the report maps (sign_edges; each edge must be one of the two directed station edges
        of the capture).  The agreement of the model paths (consecutive station hits vs. consecutive
        raw detections, `resolve_sign_sides`) with the fixed assignment is recorded per station as a
        diagnostic only (+1 = the model routes agree with the report, -1 = opposite)."""
        if not self.profile_directional:
            return None
        sides = inc.audit.get('profile_sides')
        ctx = inc.audit.get('profile_side_contexts')
        require(sides is not None and ctx is not None, 'LIVE04_PROFILE_SIDES_NOT_CAPTURED')
        model = {s: {0: {}, 1: {}} for s in STATIONS}
        for s, side, role, t, v in ctx:
            k = '%s:%d' % (role, int(t))
            model[int(s)][int(side)][k] = model[int(s)][int(side)].get(k, 0.0) + float(v)
        mapping, rows = {}, []
        for s in STATIONS:
            edges = [tuple(int(x) for x in e) for e in sides[str(s)]]
            fixed = self.sign_edges[s]
            require(set(edges) == {fixed['plus'], fixed['minus']}, 'LIVE04_PROFILE_SIGN_EDGE_NOT_A_STATION_EDGE:SDP%d' % s)
            plus_side = edges.index(fixed['plus'])
            raw = {g: self.profile_evidence[s]['signs'][g]['contexts'] for g in '+-'}
            score = resolve_sign_sides(raw, model[s])
            rows.append({'station': s, 'plus_side': plus_side, 'plus_edge': list(fixed['plus']),
                         'minus_edge': list(fixed['minus']), 'source': fixed['source'],
                         'model_agreement_with_fixed': float(score if plus_side == 0 else -score),
                         'model_context_volume': float(sum(sum(model[s][k].values()) for k in (0, 1)))})
            mapping[s] = plus_side
        if self.direction_map is None:
            self.direction_map = mapping
            self.direction_audit = {'authority': 'REPORT_MAPS_SIGN_EDGES', 'resolved_from': 'FIRST_AGGREGATED_CAPTURE',
                                    'stations': rows}
            for s in STATIONS:
                for side in (0, 1):
                    g = '+' if side == mapping[s] else '-'
                    self.profile_cells[(s, PROFILE_IDS[side])] = self.profile_sign_targets[s][g]
        else:
            require(mapping == self.direction_map, 'LIVE04_PROFILE_DIRECTION_CHANGED')
        return rows

    def targets(self, method):
        out = dict(self.pair_cells)
        if self.station_rows(method):
            out.update(self.station_cells)
        if self.profile_rows(method):
            require(all(v is not None for v in self.profile_cells.values()), 'LIVE04_PROFILE_DIRECTIONS_NOT_RESOLVED')
            out.update(self.profile_cells)
        return out

    def mathcfg_extension(self):
        ext = {'enumeration_methods': list(self.enumeration),
               'first_last_station_rows': bool(self.station_cells),
               'full_share_methods': list(self.enumeration)}
        if self.profile_cells:
            ext['first_last_profile_rows'] = DIRECTIONAL if self.profile_directional else True
        return ext


def aggregate(inc, contract, method):
    """Bidirectional aggregation of one method; rows = 120 pairs (+16 C17 for FIRST_LAST)."""
    if contract.profile_rows(method) and contract.profile_directional:
        contract.resolve_directions(inc)
    targets = contract.targets(method)
    roles = {}
    for (a, b) in targets:
        roles[tuple(sorted((a, b)))] = 'CALIBRATION'
    expected = contract.row_count(method)
    keys = [(int(r['origin_station']), int(r['destination_station'])) for r in inc.rows]
    require(len(keys) == (240 + (16 if contract.station_rows(method) else 0) + contract.profile_row_count(method)),
            'LIVE03_DIRECTED_ROW_COUNT:' + method)
    result = aggregate_observations(inc, targets, bidirectional=True, roles=roles)
    roster = observation_roster(result.rows)
    require((roster['rows'], roster['calibration'], roster['validation']) == (expected, expected, 0),
            'LIVE03_ROSTER_OMISSION:' + method)
    w = float(contract.obs.get('c17_row_weight', 1.0))
    for r in result.rows:
        if r['destination_station'] == C17_STATION:
            r['observation_type'] = 'KORDON_C17_STATION'; r['weight'] = w
        elif r['destination_station'] in PROFILE_IDS:
            r['observation_type'] = 'KORDON_STATION_PROFILE'
            r['weight'] = float(contract.obs['station_profiles']['row_weight'])
    # Directed -> aggregated row map, applied to the frozen share operator too.
    index = {(r['origin_station'], r['destination_station']): i for i, r in enumerate(result.rows)}
    mapping = np.array([index[tuple(sorted(k))] for k in keys], dtype=np.int64)
    frozen = None
    if inc.frozen is not None:
        import copy
        frozen = copy.copy(inc.frozen)
        frozen.__dict__.pop('_axis_cache', None)
        frozen.row = mapping[inc.frozen.row]; frozen.n_rows = len(result.rows)
    trace = []
    for i, r in enumerate(result.rows):
        a, b = r['origin_station'], r['destination_station']
        trace.append({'origin_station': a, 'destination_station': b, 'observation_type': r['observation_type'],
                      'target_ij': targets[(a, b)], 'target_ji': targets[(b, a)], 'effective_target': r['observed'],
                      'effective_model': float(result.model[i]), 'weight': r.get('weight', 1.0),
                      'residual': float(result.model[i]) - r['observed']})
    result.frozen = frozen
    if contract.direction_audit is not None:
        result.audit['station_profile_directions'] = contract.direction_audit
    result.audit.update(observation_policy=SCHEMA, contract_sha256=contract.audit['contract_sha256'],
                        whole_matrix_roster=roster, directed_to_row=mapping.tolist())
    return result, trace, roster
