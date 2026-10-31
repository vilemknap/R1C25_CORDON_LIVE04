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
from .live03_incidence import aggregate_observations, FIRST_LAST, C17_STATION
from .state import observation_roster

SCHEMA = 'LIVE03_OBSERVATION_CONTRACT_V1'
C17_INDEX, RETURN_INDEX = 16, 17
STATIONS = tuple(range(1, 17))
PAIR_MATRICES = ('Transit', 'ALL')
C17_POLICIES = ('STATION_MARGINS', 'DISABLED')
ROLES = ('PRIMARY', 'SECONDARY', 'DIAGNOSTIC')


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
            'rows': {m: self.row_count(m) for m in self.methods},
            'production_ready': False,
            'observation_status': 'APPROVED_BY_SURVEY_REPORT_AND_USER_FOR_LIVE03_TECHNICAL_CALIBRATION'}
        self.audit['contract_sha256'] = canonical_hash({k: v for k, v in self.audit.items() if k != 'c17_station_parts'})

    def station_rows(self, method):
        return method == FIRST_LAST and bool(self.station_cells)

    def row_count(self, method):
        return 120 + (16 if self.station_rows(method) else 0)

    def targets(self, method):
        out = dict(self.pair_cells)
        if self.station_rows(method):
            out.update(self.station_cells)
        return out

    def mathcfg_extension(self):
        return {'enumeration_methods': list(self.enumeration),
                'first_last_station_rows': bool(self.station_cells),
                'full_share_methods': list(self.enumeration)}


def aggregate(inc, contract, method):
    """Bidirectional aggregation of one method; rows = 120 pairs (+16 C17 for FIRST_LAST)."""
    targets = contract.targets(method)
    roles = {}
    for (a, b) in targets:
        roles[tuple(sorted((a, b)))] = 'CALIBRATION'
    expected = contract.row_count(method)
    keys = [(int(r['origin_station']), int(r['destination_station'])) for r in inc.rows]
    require(len(keys) == (240 + (16 if contract.station_rows(method) else 0)), 'LIVE03_DIRECTED_ROW_COUNT:' + method)
    result = aggregate_observations(inc, targets, bidirectional=True, roles=roles)
    roster = observation_roster(result.rows)
    require((roster['rows'], roster['calibration'], roster['validation']) == (expected, expected, 0),
            'LIVE03_ROSTER_OMISSION:' + method)
    w = float(contract.obs.get('c17_row_weight', 1.0))
    for r in result.rows:
        if r['destination_station'] == C17_STATION:
            r['observation_type'] = 'KORDON_C17_STATION'; r['weight'] = w
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
    result.audit.update(observation_policy=SCHEMA, contract_sha256=contract.audit['contract_sha256'],
                        whole_matrix_roster=roster, directed_to_row=mapping.tolist())
    return result, trace, roster
