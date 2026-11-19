"""LIVE04.14 GENSTRUCT1: spatially regularized GENERATION proposal + efficiency memory.

User decision 2026-11-19 ("implementuj je, pak je budeme ladit a testovat za behu").
The donor zonal fit penalizes only the step of ONE cycle (ridge on x), so steps
accumulate in the zones whose OD pairs cross the cordon profiles until they hit
the coefficient caps.  This module adds, in log-coefficient space (y = l + x,
l = current log coefficient relative to the anchor target, x = this step):

1. PRODUCTION ANCHOR: per zone, the reference-weighted production ratio
       log R_z ~ sum_f w_zf * y_zf        (w = run-start FP shares of WORK/SERVICE)
   is pulled towards 0 (strong), plus a weak per-family anchor.
2. PRODUCTION NEIGHBOURHOOD: y_zf - sum_u K_zu y_uf (K: population x distance kernel on the
   frozen distance matrix, optionally x similarity of reference destination shares) is
   pulled towards 0, so a profile deficit spreads over the surroundings instead of one zone.
3. ATTRACTION CENTRALITY: y of an attraction coefficient is anchored with a weight that is
   small for central zones (high reference potential and many distinct inbound origins)
   and large for satellites; no hard centre / catchment assignment.
4. EFFICIENCY MEMORY: low-dimensional factors eta_g (g = family x role) scale the columns
   of the linear effect operator; after every validly measured GENERATION trial they are
   updated by a regularized secant (Broyden) fit of measured vs predicted profile change
   (never one factor per zone).

All reference quantities are captured ONCE at run start (RUN_ANCHORS.json carries them to
continuations, verified by hash).  The native acceptance (fresh assignment, cordon, IDP,
mobility, rollback) is unchanged - this only changes which step is proposed.  Pure numpy,
read-only COM at capture.
"""
from __future__ import annotations
import copy
import math
import numpy as np
from .common import require, canonical_hash, parent_module

SCHEMA = 'LIVE04_GENSTRUCT1_REFERENCE_V1'
MEMORY_SCHEMA = 'LIVE04_GENSTRUCT1_EFFICIENCY_V1'
FAMILIES = ('WORK', 'SERVICE')
ROLES = ('PROD', 'ATT')
GROUPS = tuple((f, r) for f in FAMILIES for r in ROLES)
COEF = {('WORK', 'PROD'): 'ADD_PROD_W', ('WORK', 'ATT'): 'ADD_ATT_W',
        ('SERVICE', 'PROD'): 'ADD_PROD_S', ('SERVICE', 'ATT'): 'ADD_ATT_S'}
FP_PREFIX = {'WORK': 'FP_1_WORK_', 'SERVICE': 'FP_2_SERVICE_'}
FIELDS = {'enabled', 'anchor_target', 'production_anchor_relative', 'production_family_anchor_relative',
          'attraction_anchor_min_relative', 'attraction_anchor_max_relative', 'attraction_centrality_power',
          'neighbour_relative', 'neighbour_distance_matrix', 'neighbour_radius_km', 'neighbour_decay_km',
          'neighbour_max', 'neighbour_destination_similarity_weight', 'work_potential_attributes',
          'service_potential_attributes', 'efficiency_memory', 'reference_start_policy'}
START_POLICIES = ('REQUIRE_UNIT_WS_ON_ACTUATABLE_DOMESTIC_ZONES', 'ACCEPT_CURRENT_MODEL')
MEMORY_FIELDS = {'enabled', 'eta_min', 'eta_max', 'prior_weight', 'smoothing', 'min_predicted_norm'}
# Only these define the captured reference; penalty weights may be tuned between continuations.
CAPTURE_PARAMS = ('anchor_target', 'reference_start_policy', 'neighbour_distance_matrix', 'neighbour_radius_km', 'neighbour_decay_km',
                  'neighbour_max', 'neighbour_destination_similarity_weight', 'work_potential_attributes',
                  'service_potential_attributes')


def capture_parameters(g):
    return {k: copy.deepcopy(g[k]) for k in CAPTURE_PARAMS}


# ------------------------------------------------------------------ config
def validate(cfg):
    g = cfg.get('generation_structure')
    require(isinstance(g, dict) and set(g) - {'note'} == FIELDS, 'LIVE04_GENSTRUCT_FIELDS')
    require(isinstance(g['enabled'], bool), 'LIVE04_GENSTRUCT_ENABLED')
    require(g['anchor_target'] in ('UNIT', 'RUN_START'), 'LIVE04_GENSTRUCT_ANCHOR_TARGET')
    require(g['reference_start_policy'] in START_POLICIES, 'LIVE04_GENSTRUCT_REFERENCE_START_POLICY')
    for key in ('production_anchor_relative', 'production_family_anchor_relative', 'attraction_anchor_min_relative',
                'attraction_anchor_max_relative', 'neighbour_relative', 'neighbour_destination_similarity_weight'):
        v = g[key]
        require(isinstance(v, (int, float)) and not isinstance(v, bool) and 0.0 <= float(v) <= 1000.0,
                'LIVE04_GENSTRUCT_WEIGHT:' + key)
    require(g['attraction_anchor_min_relative'] <= g['attraction_anchor_max_relative'], 'LIVE04_GENSTRUCT_ATT_ORDER')
    require(g['neighbour_destination_similarity_weight'] <= 1.0, 'LIVE04_GENSTRUCT_SIMILARITY_WEIGHT')
    require(isinstance(g['attraction_centrality_power'], (int, float)) and 0.0 < g['attraction_centrality_power'] <= 10.0,
            'LIVE04_GENSTRUCT_CENTRALITY_POWER')
    require(isinstance(g['neighbour_distance_matrix'], int) and g['neighbour_distance_matrix'] > 0,
            'LIVE04_GENSTRUCT_DISTANCE_MATRIX')
    for key in ('neighbour_radius_km', 'neighbour_decay_km'):
        require(isinstance(g[key], (int, float)) and 0.0 < float(g[key]) <= 200.0, 'LIVE04_GENSTRUCT_KM:' + key)
    require(isinstance(g['neighbour_max'], int) and 1 <= g['neighbour_max'] <= 100, 'LIVE04_GENSTRUCT_NEIGHBOUR_MAX')
    for key in ('work_potential_attributes', 'service_potential_attributes'):
        require(isinstance(g[key], list) and g[key] and all(isinstance(a, str) and a for a in g[key]),
                'LIVE04_GENSTRUCT_POTENTIAL:' + key)
    m = g['efficiency_memory']
    require(isinstance(m, dict) and set(m) - {'note'} == MEMORY_FIELDS and isinstance(m['enabled'], bool),
            'LIVE04_GENSTRUCT_MEMORY_FIELDS')
    require(0.0 < m['eta_min'] <= 1.0 <= m['eta_max'] <= 5.0, 'LIVE04_GENSTRUCT_MEMORY_ETA')
    require(0.0 <= m['prior_weight'] <= 100.0 and 0.0 < m['smoothing'] <= 1.0 and m['min_predicted_norm'] >= 0.0,
            'LIVE04_GENSTRUCT_MEMORY_VALUES')
    return g


# ------------------------------------------------------------------ capture (run start)
def _zone_values(visum, attr, n, zones=None, zone_indices=None, retry_policy=None):
    """All zones in the order of ``zones``; finite and non-negative - otherwise fail closed.

    With ``zones`` the existing indexed reader is used (review N11): COM row keys are joined
    with Zone.NO, bounded COM retry, blanks are errors (no silent 0)."""
    if zones is not None:
        com = parent_module('r1_15a2_com_compat')
        vals = np.asarray(com.indexed_zone_values(visum, attr, list(zones), retry_policy=retry_policy,
                                                  zone_indices=zone_indices), dtype=float)
    else:
        rows = visum.Net.Zones.GetMultiAttValues(attr, False)
        raw = [r[1] for r in rows]
        require(all(v not in (None, '') for v in raw), 'LIVE04_GENSTRUCT_ZONE_VALUES_BLANK:' + attr)
        vals = np.asarray([float(v) for v in raw], dtype=float)
    require(len(vals) == n, 'LIVE04_GENSTRUCT_ZONE_COUNT:' + attr)
    require(np.isfinite(vals).all() and (vals >= 0).all(), 'LIVE04_GENSTRUCT_ZONE_VALUES_INVALID:' + attr)
    return vals


MISSING_ATTRIBUTE_TOKENS = ('COULD NOT FIND ATTRIBUTE', 'UNKNOWN ATTRIBUTE', 'ATTRIBUTE NOT FOUND',
                            'INVALID ATTRIBUTE')


def _attribute_missing(exc):
    """Only a missing attribute may fall back to the next candidate; a COM/read failure of an
    existing attribute (busy, wrong shape, invalid values) is never mistaken for it."""
    if isinstance(exc, KeyError):            # synthetic hosts
        return True
    text = str(exc).upper()
    return any(t in text for t in MISSING_ATTRIBUTE_TOKENS)


def _first_readable(visum, attrs, n, **kw):
    missing = []
    for a in attrs:
        try:
            return a, _zone_values(visum, a, n, **kw)
        except Exception as exc:
            if not _attribute_missing(exc):
                raise
            missing.append('%s:%s' % (a, str(exc)[:80]))
    raise ValueError('LIVE04_GENSTRUCT_NO_POTENTIAL_ATTRIBUTE:' + ';'.join(missing))


def _fp_sum(visum, prefix, n, **kw):
    """Run-start FP production of one family (the MOBILITYZONE1 person groups)."""
    groups = parent_module('r1_15a2_mobility_zone_v24917').GROUPS
    names = [prefix + gname for gname in groups]
    return sum(_zone_values(visum, a, n, **kw) for a in names), names


def _pct_rank(v):
    """Percentile rank in [0, 1]; ties share their average rank (no zone-number bias)."""
    v = np.asarray(v, dtype=float)
    if len(v) <= 1:
        return np.zeros(len(v))
    uniq, inv = np.unique(v, return_inverse=True)
    order = np.argsort(v, kind='mergesort')
    ranks = np.empty(len(v)); ranks[order] = np.arange(len(v), dtype=float)
    mean_rank = np.bincount(inv, weights=ranks) / np.bincount(inv)
    return mean_rank[inv] / (len(v) - 1)


def _effective_origins(M, volume_weighted=False):
    """exp(entropy) of the inbound shares of each destination (diagonal excluded).

    volume_weighted (review N12): the diversity is multiplied by the reliability of the inbound
    volume, 1 - exp(-V / V50) with V50 = median positive inbound volume, so 0.001 trips from each
    of 100 zones no longer looks like a centre of 100 origins."""
    M = np.array(M, dtype=float, copy=True)
    np.fill_diagonal(M, 0.0)
    col = M.sum(axis=0)
    with np.errstate(divide='ignore', invalid='ignore'):
        P = np.where(col > 0, M / np.where(col > 0, col, 1.0), 0.0)
        H = -np.nansum(np.where(P > 0, P * np.log(P), 0.0), axis=0)
    out = np.exp(H) * (col > 0)
    if volume_weighted:
        pos = col[col > 0]
        v50 = float(np.median(pos)) if pos.size else 1.0
        out = out * (1.0 - np.exp(-col / max(v50, 1e-12)))
    return out


def _domestic_mask(visum, n, kw):
    try:
        return _zone_values(visum, 'NOT_ZAHR', n, **kw) >= 0.5
    except Exception as exc:
        if not _attribute_missing(exc):
            raise
        return np.ones(n, dtype=bool)


UNIT_TOL = 1e-9


def structural_zero_mask(pop, fp, coef):
    """Zones without any W/S generation: no population, no WORK/SERVICE FP production and all four
    W/S coefficients exactly 0 (e.g. 646-649 in the 2025 model: NOT_ZAHR = 1 but auxiliary
    AMDY external zones).  Their 0 is structural - kept, never reset to 1, never a failure."""
    m = (np.asarray(pop, dtype=float) == 0)
    for f in FAMILIES:
        m &= (np.asarray(fp[f], dtype=float) == 0)
    for k in GROUPS:
        m &= (np.asarray(coef[k], dtype=float) == 0)
    return m


def unit_start_check(zones, coef, actuatable, domestic, policy, structural=None):
    """Review N10: with REQUIRE_UNIT_WS... the reference (centrality, OD links, production shares)
    may only be captured from a model whose W/S coefficients are 1 on every actuatable domestic
    zone - otherwise a still-calibrated .ver would be frozen as the run reference.  Structural
    zero zones (structural_zero_mask) are reported and exempt."""
    act = set(int(z) for z in (actuatable if actuatable is not None else zones))
    struct = [False] * len(zones) if structural is None else [bool(x) for x in structural]
    dom_act = [i for i, z in enumerate(zones) if int(z) in act and bool(domestic[i])]
    idx = [i for i in dom_act if not struct[i]]
    structural_zero = [int(zones[i]) for i in dom_act if struct[i]]
    off = {}
    for k, vals in coef.items():
        bad = [int(zones[i]) for i in idx if abs(float(vals[i]) - 1.0) > UNIT_TOL]
        if bad:
            off['%s|%s' % k] = {'zones': len(bad), 'examples': bad[:5]}
    out = {'policy': policy, 'checked_zones': len(idx), 'non_unit': off, 'structural_zero_zones': structural_zero,
           'status': 'PROVEN_UNIT_BASE' if not off else 'NOT_UNIT_BASE'}
    if policy == 'REQUIRE_UNIT_WS_ON_ACTUATABLE_DOMESTIC_ZONES':
        require(not off, 'LIVE04_GENSTRUCT_REFERENCE_NOT_A_UNIT_BASE:%s' % ';'.join(
            '%s=%d zones (e.g. %s)' % (k, v['zones'], v['examples']) for k, v in sorted(off.items())))
    return out


def capture(adapter, cfg, run_folder):
    """Run-start structure (read-only COM)."""
    from .live03_idp import reference as idp_reference, _read
    g = cfg['generation_structure']
    visum, zones = adapter.visum, list(adapter.zones)
    n = len(zones)
    kw = {'zones': zones, 'zone_indices': getattr(adapter, 'zone_write_index_by_no', None),
          'retry_policy': getattr(adapter, 'com_retry_policy', None)}
    pop = _zone_values(visum, 'POP_ZP', n, **kw)
    coef = {k: _zone_values(visum, a, n, **kw) for k, a in COEF.items()}
    fp, fp_names = {}, {}
    for f in FAMILIES:
        fp[f], fp_names[f] = _fp_sum(visum, FP_PREFIX[f], n, **kw)
    structural = structural_zero_mask(pop, fp, coef)
    start = unit_start_check(zones, coef, getattr(adapter, 'actuatable_zones', None),
                             _domestic_mask(visum, n, kw), g['reference_start_policy'], structural=structural)
    if g['reference_start_policy'] == 'REQUIRE_UNIT_WS_ON_ACTUATABLE_DOMESTIC_ZONES':
        # review cc3c3c4 N2: unit VALUES are not enough - the demand must come from a native
        # recompute after them (sealed receipt of RUN_R1_2025_RECOMPUTE_FOR_LIVE04_BASE.py)
        from . import live04_base_receipt as base_receipt
        ws_now = {COEF[k]: {str(int(z)): float(coef[k][i]) for i, z in enumerate(zones)} for k in GROUPS}
        start['base_receipt'] = base_receipt.verify(visum, zones, ws_now, zone_indices=kw['zone_indices'],
                                                    retry_policy=kw['retry_policy'])
    wattr, wpot = _first_readable(visum, g['work_potential_attributes'], n, **kw)
    sattr, spot = _first_readable(visum, g['service_potential_attributes'], n, **kw)
    # potentials at the anchor target: divide out the run-start attraction coefficient when the
    # attribute is a coefficient-scaled attraction weight (FA_*), never for exogenous NUM_PM
    if wattr.upper().startswith('FA_'):
        wpot = np.where(coef[('WORK', 'ATT')] > 0, wpot / np.where(coef[('WORK', 'ATT')] > 0, coef[('WORK', 'ATT')], 1), 0)
    if sattr.upper().startswith('FA_'):
        spot = np.where(coef[('SERVICE', 'ATT')] > 0, spot / np.where(coef[('SERVICE', 'ATT')] > 0, coef[('SERVICE', 'ATT')], 1), 0)
    ref = idp_reference()
    od = {}
    for f, prefix in (('WORK', 'WORK_'), ('SERVICE', 'SERV_')):
        nos = sorted({no for k, t in ref.TARGETS.items() if k.startswith(prefix) for no in t['matrix_nos']})
        od[f] = sum(_read(visum, no, n) for no in nos)
    D = _read(visum, int(g['neighbour_distance_matrix']), n)
    import hashlib
    dist_sha = hashlib.sha256(np.ascontiguousarray(D, dtype='<f8').tobytes()).hexdigest()
    centrality = {}
    for f, pot in (('WORK', wpot), ('SERVICE', spot)):
        inbound = _effective_origins(od[f], volume_weighted=True)
        centrality[f] = (0.5 * _pct_rank(np.log1p(np.maximum(pot, 0))) + 0.5 * _pct_rank(inbound)).tolist()
    # neighbour kernel for production (population x distance [x destination similarity])
    sim_w = float(g['neighbour_destination_similarity_weight'])
    shares = {}
    for f in FAMILIES:
        M = np.array(od[f], copy=True); np.fill_diagonal(M, 0.0)
        rs = M.sum(axis=1, keepdims=True)
        S = np.where(rs > 0, M / np.where(rs > 0, rs, 1.0), 0.0)
        nrm = np.linalg.norm(S, axis=1, keepdims=True)
        shares[f] = np.where(nrm > 0, S / np.where(nrm > 0, nrm, 1.0), 0.0)
    radius, decay, kmax = float(g['neighbour_radius_km']), float(g['neighbour_decay_km']), int(g['neighbour_max'])
    neighbours = {}
    for f in FAMILIES:
        lists = []
        for i in range(n):
            d = D[i]
            cand = [j for j in np.argsort(d) if j != i and d[j] <= radius and pop[j] > 0][:kmax]
            if pop[i] <= 0 or not cand:
                lists.append([]); continue
            w = np.array([pop[j] * math.exp(-float(d[j]) / decay) for j in cand])
            if sim_w > 0:
                sim = np.array([max(0.0, float(shares[f][i] @ shares[f][j])) for j in cand])
                w = w * ((1.0 - sim_w) + sim_w * sim)
            s = float(w.sum())
            lists.append([[int(zones[j]), float(x / s)] for j, x in zip(cand, w)] if s > 0 else [])
        neighbours[f] = lists
    tot = fp['WORK'] + fp['SERVICE']
    prod_share = {f: np.where(tot > 0, fp[f] / np.where(tot > 0, tot, 1.0), 0.0).tolist() for f in FAMILIES}
    target = {('%s|%s' % k): (np.where(structural, coef[k], 1.0) if g['anchor_target'] == 'UNIT' else coef[k]).tolist()
              for k in GROUPS}
    rec = {'schema': SCHEMA, 'zones': [int(z) for z in zones], 'population': pop.tolist(),
           'production_share': prod_share, 'centrality': centrality, 'neighbours': neighbours,
           'anchor_target': g['anchor_target'], 'target_coefficients': target,
           'run_start_coefficients': {('%s|%s' % k): v.tolist() for k, v in coef.items()},
           'potential_attributes': {'WORK': wattr, 'SERVICE': sattr}, 'fp_attributes': fp_names,
           'distance_matrix': int(g['neighbour_distance_matrix']), 'distance_fingerprint': dist_sha,
           'od_matrices': {f: sorted({no for k, t in ref.TARGETS.items()
                                      if k.startswith('WORK_' if f == 'WORK' else 'SERV_') for no in t['matrix_nos']})
                           for f in FAMILIES},
           'parameters': capture_parameters(g), 'reference_start': start,
           'origin_run_folder': str(run_folder)}
    rec['record_sha256'] = canonical_hash(rec)
    return rec


class SparseSym:
    """Symmetric penalty matrix in coordinate form (LIVE04.14 review: no dense nv x nv matrix).

    Every term couples only a zone, its family partner and <= neighbour_max neighbours, so the
    number of non-zeros grows linearly with the zones; Q @ x is one bincount per call."""

    def __init__(self, n):
        self.n = int(n)
        self._acc = {}
        self.rows = self.cols = self.vals = None

    def add(self, i, j, v):
        self._acc[(i, j)] = self._acc.get((i, j), 0.0) + v

    def freeze(self):
        keys = list(self._acc)
        self.rows = np.array([k[0] for k in keys], dtype=np.int64)
        self.cols = np.array([k[1] for k in keys], dtype=np.int64)
        self.vals = np.array([self._acc[k] for k in keys], dtype=float)
        return self

    @property
    def nnz(self):
        return 0 if self.vals is None else int(len(self.vals))

    def __matmul__(self, x):
        x = np.asarray(x, dtype=float)
        if not self.nnz:
            return np.zeros(self.n)
        return np.bincount(self.rows, weights=self.vals * x[self.cols], minlength=self.n)

    def trace(self):
        return float(self.vals[self.rows == self.cols].sum()) if self.nnz else 0.0

    def dense(self):
        D = np.zeros((self.n, self.n))
        if self.nnz:
            np.add.at(D, (self.rows, self.cols), self.vals)
        return D


class Structure:
    """Run reference + the quadratic penalty builder + the efficiency memory."""

    def __init__(self, record, cfg):
        require(isinstance(record, dict) and record.get('schema') == SCHEMA, 'LIVE04_GENSTRUCT_REFERENCE_SCHEMA')
        body = {k: v for k, v in record.items() if k != 'record_sha256'}
        require(record.get('record_sha256') == canonical_hash(body), 'LIVE04_GENSTRUCT_REFERENCE_RECORD_CHANGED')
        g = cfg['generation_structure']
        changed = sorted(k for k, v in capture_parameters(g).items() if record['parameters'].get(k) != v)
        require(not changed, 'LIVE04_GENSTRUCT_REFERENCE_PARAMETERS_CHANGED:' + ','.join(changed))
        self.record = record
        self.cfg = g
        self.zones = list(record['zones'])
        self.index = {z: i for i, z in enumerate(self.zones)}
        self.mem_cfg = dict(g['efficiency_memory'])
        self.eta = {k: 1.0 for k in GROUPS}
        self.history = []
        self.updates_total = 0
        self.history_digest = ''
        self.last_penalty_constant = 0.0

    # -------------------------------------------------------------- penalty
    def _logs(self, zone_rows):
        """y0 = log(current / target) for every zone and group (zone rows of the design)."""
        mb = parent_module('r1_15a2_multiblock')
        lookup = mb._zone_lookup(zone_rows)
        out = {}
        for k in GROUPS:
            tgt = self.record['target_coefficients']['%s|%s' % k]
            vals = np.zeros(len(self.zones))
            for i, z in enumerate(self.zones):
                row = lookup.get(int(z))
                cur = float(mb.fval((row or {}).get(COEF[k]), 0.0) or 0.0) if row else 0.0
                vals[i] = math.log(cur / tgt[i]) if cur > 0 and tgt[i] > 0 else 0.0
            out[k] = vals
        return out

    def penalty(self, problem, zone_rows, scale):
        """(Q, q) with penalty 0.5 x'Qx + q'x (+ const) on the problem variables."""
        keys = [tuple(k) for k in problem.var_keys]
        nv = len(keys)
        Q = SparseSym(nv); q = np.zeros(nv)
        self.last_penalty_constant = 0.0
        if not self.cfg['enabled'] or nv == 0:
            return Q.freeze(), q, {'status': 'DISABLED', 'constant': 0.0}
        y0 = self._logs(zone_rows)
        pos = {k: j for j, k in enumerate(keys)}
        rel = lambda key: float(self.cfg[key]) * scale
        audit = {'variables': nv, 'scale': scale}

        const_total = [0.0]

        def add_quadratic(entries, weight, const=None):
            """weight * 0.5 * (const + sum_c a_c * x_c)^2; const defaults to sum_c a_c * y0_c
            for entries [(var_or_None, a, y0)].  The constant term is tracked for the audit."""
            idx = [(pos.get(v), a) for v, a, _ in entries]
            if const is None:
                const = sum(a * y for (_, a, y) in entries)
            const_total[0] += 0.5 * weight * const * const
            for j, a in idx:
                if j is None:
                    continue
                q[j] += weight * a * const
                for k2, b in idx:
                    if k2 is not None:
                        Q.add(j, k2, weight * a * b)
        # 1. production anchor on the EXACT reference-weighted production ratio
        #    R = sum_f w_f * c_f / t_f = sum_f w_f exp(y_f), linearized at the current state:
        #    R - 1 ~ (R0 - 1) + sum_f w_f exp(y0_f) x_f      (+ a weak per-family log anchor)
        lp, lpf = rel('production_anchor_relative'), rel('production_family_anchor_relative')
        for i, z in enumerate(self.zones):
            ent, r0 = [], 0.0
            for f in FAMILIES:
                w = float(self.record['production_share'][f][i])
                e = math.exp(float(y0[(f, 'PROD')][i]))
                r0 += w * e
                ent.append(((f, 'PROD', z), w * e, float(y0[(f, 'PROD')][i])))
                if lpf > 0 and (f, 'PROD', z) in pos:
                    add_quadratic([((f, 'PROD', z), 1.0, float(y0[(f, 'PROD')][i]))], lpf)
            if lp > 0 and r0 > 0 and any(v in pos for v, a, _ in ent if a > 0):
                add_quadratic(ent, lp, const=r0 - 1.0)
        # 2. production neighbourhood
        ln = rel('neighbour_relative')
        if ln > 0:
            for f in FAMILIES:
                for i, z in enumerate(self.zones):
                    nb = self.record['neighbours'][f][i]
                    if not nb:
                        continue
                    ent = [((f, 'PROD', z), 1.0, float(y0[(f, 'PROD')][i]))]
                    for u, w in nb:
                        ent.append(((f, 'PROD', int(u)), -float(w), float(y0[(f, 'PROD')][self.index[int(u)]])))
                    # review cc3c3c4: the term exists whenever ANY of its zones is a variable;
                    # fixed zones (centre or neighbours) enter as constants, never drop the link
                    if any(v in pos and a != 0.0 for v, a, _ in ent):
                        add_quadratic(ent, ln)
        # 3. attraction anchor by centrality
        amin, amax = rel('attraction_anchor_min_relative'), rel('attraction_anchor_max_relative')
        p = float(self.cfg['attraction_centrality_power'])
        for f in FAMILIES:
            cent = self.record['centrality'][f]
            for i, z in enumerate(self.zones):
                if (f, 'ATT', z) not in pos:
                    continue
                w = amin + (amax - amin) * (1.0 - float(cent[i])) ** p
                if w > 0:
                    add_quadratic([((f, 'ATT', z), 1.0, float(y0[(f, 'ATT')][i]))], w)
        Q.freeze()
        audit.update(status='ACTIVE', q_norm=float(np.linalg.norm(q)), Q_trace=Q.trace(), Q_nnz=Q.nnz,
                     constant=const_total[0])
        self.last_penalty_constant = const_total[0]
        return Q, q, audit

    # -------------------------------------------------------------- efficiency
    def group_of(self, key):
        key = tuple(key)
        return (key[0], key[1]) if (key[0], key[1]) in self.eta else None

    def column_factors(self, var_keys):
        if not self.mem_cfg.get('enabled'):
            return np.ones(len(var_keys))
        return np.array([self.eta.get(self.group_of(k), 1.0) for k in var_keys], dtype=float)

    def learn(self, G, var_keys, x, measured_delta, weight):
        """Regularized secant update of eta_g from ONE measured trial (all profile rows)."""
        if not self.mem_cfg.get('enabled'):
            return {'status': 'DISABLED'}
        G = np.asarray(G, dtype=float); x = np.asarray(x, dtype=float)
        d = np.asarray(measured_delta, dtype=float); w = np.asarray(weight, dtype=float)
        contrib, groups = [], []
        for gk in GROUPS:
            mask = np.array([self.group_of(k) == gk for k in var_keys])
            if mask.any():
                c = G[:, mask] @ x[mask]
                if np.linalg.norm(c) > float(self.mem_cfg['min_predicted_norm']):
                    contrib.append(c); groups.append(gk)
        if not groups:
            return {'status': 'NO_PREDICTED_EFFECT'}
        C = np.column_stack(contrib) * w[:, None]
        b = d * w
        prior = np.array([self.eta[gk] for gk in groups])
        curv = max(1e-12, float(np.median(np.sum(C * C, axis=0))))
        # numerical floor: prior_weight = 0 with collinear groups must not make A singular
        mu = max(float(self.mem_cfg['prior_weight']) * curv, 1e-9 * curv)
        A = C.T @ C + mu * np.eye(len(groups))
        est = np.linalg.lstsq(A, C.T @ b + mu * prior, rcond=None)[0]
        if not np.isfinite(est).all():
            return {'status': 'NONFINITE_ESTIMATE_NOT_APPLIED'}
        est = np.clip(est, float(self.mem_cfg['eta_min']), float(self.mem_cfg['eta_max']))
        a = float(self.mem_cfg['smoothing'])
        new = (1.0 - a) * prior + a * est
        before = dict(self.eta)
        for gk, v in zip(groups, new):
            self.eta[gk] = float(v)
        pred_before = C @ prior; pred_after = C @ new
        rec = {'status': 'UPDATED', 'groups': ['%s|%s' % g for g in groups],
               'eta_before': {'%s|%s' % k: v for k, v in before.items()},
               'eta_after': {'%s|%s' % k: v for k, v in self.eta.items()},
               'estimate_clipped': {'%s|%s' % g: float(v) for g, v in zip(groups, est)},
               'weighted_error_before': float(np.linalg.norm(b - pred_before)),
               'weighted_error_after': float(np.linalg.norm(b - pred_after))}
        self.history.append(rec)
        self.updates_total += 1
        self.history_digest = canonical_hash([self.history_digest, rec])
        return rec

    def snapshot(self):
        """In-memory copy for a transactional update (restore on a failed persist)."""
        return (dict(self.eta), len(self.history), self.updates_total, self.history_digest)

    def restore(self, snap):
        eta, n, total, digest = snap
        self.eta = dict(eta); del self.history[n:]
        self.updates_total, self.history_digest = total, digest

    def memory_state(self):
        return {'schema': MEMORY_SCHEMA, 'reference_sha256': self.record['record_sha256'],
                'eta': {'%s|%s' % k: v for k, v in self.eta.items()}, 'updates': self.updates_total,
                'history_digest': self.history_digest, 'history': self.history[-20:]}

    def load_memory(self, state):
        """Factors of a previous run: same reference, exactly the four groups, finite; values are
        clipped to the CURRENT eta bounds (recorded).  Returns (loaded, reason)."""
        if not isinstance(state, dict) or state.get('schema') != MEMORY_SCHEMA:
            return False, 'SCHEMA'
        if state.get('reference_sha256') != self.record['record_sha256']:
            return False, 'OTHER_REFERENCE'
        eta = state.get('eta')
        expected = {'%s|%s' % k for k in GROUPS}
        if not isinstance(eta, dict) or set(eta) != expected:
            return False, 'GROUPS'
        try:
            vals = {k: float(v) for k, v in eta.items()}
        except (TypeError, ValueError):
            return False, 'NOT_NUMERIC'
        if not all(math.isfinite(v) for v in vals.values()):
            return False, 'NONFINITE'
        lo, hi = float(self.mem_cfg['eta_min']), float(self.mem_cfg['eta_max'])
        clipped = sorted(k for k, v in vals.items() if not lo <= v <= hi)
        for key, v in vals.items():
            f, r = key.split('|')
            self.eta[(f, r)] = min(hi, max(lo, v))
        self.updates_total = int(state.get('updates') or 0)
        self.history_digest = str(state.get('history_digest') or '')
        return True, ('CLIPPED_TO_CURRENT_BOUNDS:' + ','.join(clipped)) if clipped else 'LOADED'


# ------------------------------------------------------------------ regularized solver
def solve(problem, fit_cfg, structure, zone_rows):
    """Donor FISTA (box + hard P/A hyperplanes) with the GENSTRUCT1 penalty and
    efficiency-scaled effect columns.  structure None/disabled -> donor solve unchanged."""
    zf = parent_module('r1_15a2_zonal_count_fit_v24917')
    if structure is None or not structure.cfg['enabled']:
        return zf.solve(problem, fit_cfg), {'status': 'DONOR_SOLVE'}
    # A measured-refit problem already carries the EFFECTIVE (eta-scaled, secant-corrected)
    # operator; scaling it again would break G_new @ x_trial = measured delta.
    effective = getattr(problem, 'genstruct_operator', 'RAW') == 'EFFECTIVE'
    eta = np.ones(len(problem.var_keys)) if effective else structure.column_factors(problem.var_keys)
    G = np.asarray(problem.G, dtype=float) * eta[None, :]
    W2 = np.asarray(problem.weight, dtype=float) ** 2
    nv = G.shape[1]
    diag_h = np.einsum('ij,i,ij->j', G, W2, G)
    positive = diag_h[diag_h > zf.EPS]
    scale = float(np.median(positive)) if positive.size else 1.0
    ridge = float(fit_cfg.get('ridge_relative', 0.02)) * scale
    Q, q, paudit = structure.penalty(problem, zone_rows, scale)
    hard = str(fit_cfg.get('balance_mode', 'HARD')).upper() == 'HARD'
    require(hard, 'LIVE04_GENSTRUCT_REQUIRES_HARD_BALANCE')
    hard_vecs = [np.asarray(vec, dtype=float) for vec, _ in problem.balance_vectors.values()]

    def project(z):
        return zf.project_box_hyperplanes(z, problem.lower, problem.upper, hard_vecs)

    def grad(x):
        return G.T @ (W2 * (G @ x - problem.target)) + ridge * x + Q @ x + q

    const = float(getattr(structure, 'last_penalty_constant', 0.0))

    def parts(x):
        r = G @ x - problem.target
        return (0.5 * float(r @ (W2 * r)), 0.5 * ridge * float(x @ x),
                0.5 * float(x @ (Q @ x)) + float(q @ x) + const)

    def objective(x):
        return sum(parts(x))

    rng = np.random.default_rng(17)
    v = rng.random(nv) + 0.1
    v /= np.linalg.norm(v) if nv else 1.0
    lip = 1.0
    for _ in range(60):
        hv = G.T @ (W2 * (G @ v)) + ridge * v + Q @ v
        nrm = float(np.linalg.norm(hv))
        if nrm <= zf.EPS:
            break
        v = hv / nrm
        lip = nrm
    step = 1.0 / max(lip * 1.05, zf.EPS)
    x = np.zeros(nv); y = x.copy(); t = 1.0
    obj0 = objective(x); prev = obj0
    max_iter = int(fit_cfg.get('max_iter', 4000)); tol = float(fit_cfg.get('tolerance', 1.0e-9))
    converged = False; it = 0
    for it in range(1, max_iter + 1):
        x_new = project(y - step * grad(y))
        t_new = 0.5 * (1.0 + math.sqrt(1.0 + 4.0 * t * t))
        y = x_new + ((t - 1.0) / t_new) * (x_new - x)
        x, t = x_new, t_new
        if it % 20 == 0 or it == max_iter:
            obj = objective(x)
            if obj > prev * (1.0 + 1.0e-10) if prev > 0 else obj > prev + 1e-12:
                y, t = x.copy(), 1.0
            if abs(prev - obj) <= tol * max(1.0, abs(prev)):
                converged = True; prev = obj; break
            prev = obj
    nonlinear_pa = {}
    if fit_cfg.get('nonlinear_pa_repair', False):
        x, nonlinear_pa = zf.repair_nonlinear_pa(problem, x, tolerance=float(fit_cfg.get('nonlinear_pa_tolerance', 1.0e-10)))
    pred = G @ x
    balance = {fam: {'linear_pa_gap': float(np.asarray(vec) @ x), 'margin_total': float(tot),
                     'relative_to_total': float(np.asarray(vec) @ x) / max(zf.EPS, float(tot))}
               for fam, (vec, tot) in problem.balance_vectors.items()}
    sol = {'x': x, 'predicted_change': pred, 'objective_initial': obj0, 'objective_final': objective(x),
           'iterations': it, 'converged': converged, 'ridge': ridge, 'balance_weight': 0.0, 'lipschitz': lip,
           'balance_mode': 'HARD', 'balance': balance, 'nonlinear_pa_repair': nonlinear_pa}
    audit = {'status': 'GENSTRUCT1_SOLVE', 'penalty': paudit,
             'operator': 'EFFECTIVE_FROM_MEASURED_REFIT' if effective else 'RAW_TIMES_ETA',
             'eta': {'%s|%s' % k: v for k, v in structure.eta.items()},
             'objective_initial': obj0, 'objective_final': sol['objective_final'], 'iterations': it,
             'converged': converged,
             'objective_parts_final': dict(zip(('data', 'step_ridge', 'structure_penalty_full'), parts(x))),
             'objective_parts_initial': dict(zip(('data', 'step_ridge', 'structure_penalty_full'),
                                                 parts(np.zeros(nv))))}
    return sol, audit


# ------------------------------------------------------------------ run start
def establish(adapter, cfg, anchors, *, continuation, folder, write_json, previous_run_folder=None):
    """Fresh run: capture; continuation: carried record, verified.  Sets adapter.generation_structure."""
    from .common import read_json
    from pathlib import Path
    g = cfg['generation_structure']
    adapter.generation_structure = None
    if not g['enabled']:
        return None
    if continuation:
        record = anchors.get('generation_structure_reference')
        require(record is not None, 'LIVE04_GENSTRUCT_REFERENCE_MISSING_IN_CONTINUATION')
        # the neighbour structure is only valid on the SAME distance matrix (state hashes do not cover it)
        from .live03_idp import _read
        import hashlib
        D = _read(adapter.visum, int(record['distance_matrix']), len(record['zones']))
        actual = hashlib.sha256(np.ascontiguousarray(D, dtype='<f8').tobytes()).hexdigest()
        require(actual == record['distance_fingerprint'],
                'LIVE04_GENSTRUCT_DISTANCE_MATRIX_CHANGED:%d' % int(record['distance_matrix']))
        require([int(z) for z in adapter.zones] == [int(z) for z in record['zones']],
                'LIVE04_GENSTRUCT_ZONE_ORDER_CHANGED')
        require(str(record.get('origin_run_folder')) == str(anchors.get('origin_run_folder')),
                'LIVE04_GENSTRUCT_REFERENCE_NOT_OF_THE_ORIGIN_RUN')
        source = 'CARRIED_FROM_ORIGIN_RUN'
    else:
        record = capture(adapter, cfg, folder)
        anchors['generation_structure_reference'] = record
        source = 'MEASURED_AT_RUN_START'
    st = Structure(record, cfg)
    loaded = 'NOT_LOADED_HERE_STATE_SNAPSHOTS_DECIDE'      # LIVE04.14: see live04_memory_snapshots
    write_json(Path(folder) / 'GENSTRUCT1_REFERENCE.json', {
        'source': source, 'record_sha256': record['record_sha256'], 'zones': len(record['zones']),
        'potential_attributes': record['potential_attributes'], 'distance_matrix': record['distance_matrix'],
        'anchor_target': record['anchor_target'], 'efficiency_memory_loaded': loaded,
        'reference_start': record.get('reference_start'),
        'centrality_quartiles': {f: np.percentile(record['centrality'][f], [25, 50, 75]).tolist() for f in FAMILIES},
        'zones_with_neighbours': {f: sum(1 for x in record['neighbours'][f] if x) for f in FAMILIES}})
    adapter.generation_structure = st
    adapter.generation_structure_folder = Path(folder)
    return st

