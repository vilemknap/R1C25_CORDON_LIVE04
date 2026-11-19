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
          'service_potential_attributes', 'efficiency_memory'}
MEMORY_FIELDS = {'enabled', 'eta_min', 'eta_max', 'prior_weight', 'smoothing', 'min_predicted_norm'}
# Only these define the captured reference; penalty weights may be tuned between continuations.
CAPTURE_PARAMS = ('anchor_target', 'neighbour_distance_matrix', 'neighbour_radius_km', 'neighbour_decay_km',
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
def _zone_values(visum, attr, n):
    rows = visum.Net.Zones.GetMultiAttValues(attr, False)       # all zones, not only active
    vals = [float(r[1]) if r[1] not in (None, '') else 0.0 for r in rows]
    require(len(vals) == n, 'LIVE04_GENSTRUCT_ZONE_COUNT:' + attr)
    return np.asarray(vals, dtype=float)


def _first_readable(visum, attrs, n):
    errors = []
    for a in attrs:
        try:
            return a, _zone_values(visum, a, n)
        except Exception as exc:     # attribute not in this model: next candidate
            errors.append('%s:%s' % (a, str(exc)[:80]))
    raise ValueError('LIVE04_GENSTRUCT_NO_POTENTIAL_ATTRIBUTE:' + ';'.join(errors))


def _fp_sum(visum, prefix, n):
    """Run-start FP production of one family (the MOBILITYZONE1 person groups)."""
    groups = parent_module('r1_15a2_mobility_zone_v24917').GROUPS
    names = [prefix + gname for gname in groups]
    return sum(_zone_values(visum, a, n) for a in names), names


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


def _effective_origins(M):
    """exp(entropy) of the inbound shares of each destination (diagonal excluded)."""
    M = np.array(M, dtype=float, copy=True)
    np.fill_diagonal(M, 0.0)
    col = M.sum(axis=0)
    with np.errstate(divide='ignore', invalid='ignore'):
        P = np.where(col > 0, M / np.where(col > 0, col, 1.0), 0.0)
        H = -np.nansum(np.where(P > 0, P * np.log(P), 0.0), axis=0)
    return np.exp(H) * (col > 0)


def capture(adapter, cfg, run_folder):
    """Run-start structure (read-only COM)."""
    from .live03_idp import reference as idp_reference, _read
    g = cfg['generation_structure']
    visum, zones = adapter.visum, list(adapter.zones)
    n = len(zones)
    pop = _zone_values(visum, 'POP_ZP', n)
    coef = {k: _zone_values(visum, a, n) for k, a in COEF.items()}
    fp, fp_names = {}, {}
    for f in FAMILIES:
        fp[f], fp_names[f] = _fp_sum(visum, FP_PREFIX[f], n)
    wattr, wpot = _first_readable(visum, g['work_potential_attributes'], n)
    sattr, spot = _first_readable(visum, g['service_potential_attributes'], n)
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
        inbound = _effective_origins(od[f])
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
    target = {('%s|%s' % k): (np.ones(n) if g['anchor_target'] == 'UNIT' else coef[k]).tolist() for k in GROUPS}
    rec = {'schema': SCHEMA, 'zones': [int(z) for z in zones], 'population': pop.tolist(),
           'production_share': prod_share, 'centrality': centrality, 'neighbours': neighbours,
           'anchor_target': g['anchor_target'], 'target_coefficients': target,
           'run_start_coefficients': {('%s|%s' % k): v.tolist() for k, v in coef.items()},
           'potential_attributes': {'WORK': wattr, 'SERVICE': sattr}, 'fp_attributes': fp_names,
           'distance_matrix': int(g['neighbour_distance_matrix']), 'distance_fingerprint': dist_sha,
           'od_matrices': {f: sorted({no for k, t in ref.TARGETS.items()
                                      if k.startswith('WORK_' if f == 'WORK' else 'SERV_') for no in t['matrix_nos']})
                           for f in FAMILIES},
           'parameters': capture_parameters(g),
           'origin_run_folder': str(run_folder)}
    rec['record_sha256'] = canonical_hash(rec)
    return rec


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
        Q = np.zeros((nv, nv)); q = np.zeros(nv)
        if not self.cfg['enabled'] or nv == 0:
            return Q, q, {'status': 'DISABLED'}
        y0 = self._logs(zone_rows)
        pos = {k: j for j, k in enumerate(keys)}
        rel = lambda key: float(self.cfg[key]) * scale
        audit = {'variables': nv, 'scale': scale}

        def add_quadratic(entries, weight):
            """weight * 0.5 * (sum_c a_c * y_c)^2 for entries [(var_or_None, a, y0)]"""
            idx = [(pos.get(v), a) for v, a, _ in entries]
            const = sum(a * y for (_, a, y) in entries)
            for j, a in idx:
                if j is None:
                    continue
                q[j] += weight * a * const
                for k2, b in idx:
                    if k2 is not None:
                        Q[j, k2] += weight * a * b
        # 1. production anchor (combined) + weak per-family anchor
        lp, lpf = rel('production_anchor_relative'), rel('production_family_anchor_relative')
        for i, z in enumerate(self.zones):
            ent = []
            for f in FAMILIES:
                w = float(self.record['production_share'][f][i])
                ent.append(((f, 'PROD', z), w, float(y0[(f, 'PROD')][i])))
                if lpf > 0 and (f, 'PROD', z) in pos:
                    add_quadratic([((f, 'PROD', z), 1.0, float(y0[(f, 'PROD')][i]))], lpf)
            if lp > 0 and any(v in pos for v, a, _ in ent if a > 0):
                add_quadratic(ent, lp)
        # 2. production neighbourhood
        ln = rel('neighbour_relative')
        if ln > 0:
            for f in FAMILIES:
                for i, z in enumerate(self.zones):
                    nb = self.record['neighbours'][f][i]
                    if not nb or (f, 'PROD', z) not in pos:
                        continue
                    ent = [((f, 'PROD', z), 1.0, float(y0[(f, 'PROD')][i]))]
                    for u, w in nb:
                        ent.append(((f, 'PROD', int(u)), -float(w), float(y0[(f, 'PROD')][self.index[int(u)]])))
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
        audit.update(status='ACTIVE', q_norm=float(np.linalg.norm(q)), Q_trace=float(np.trace(Q)))
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
        mu = float(self.mem_cfg['prior_weight']) * max(1e-12, float(np.median(np.sum(C * C, axis=0))))
        A = C.T @ C + mu * np.eye(len(groups))
        est = np.linalg.solve(A, C.T @ b + mu * prior)
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
        return rec

    def memory_state(self):
        return {'schema': MEMORY_SCHEMA, 'reference_sha256': self.record['record_sha256'],
                'eta': {'%s|%s' % k: v for k, v in self.eta.items()}, 'updates': len(self.history),
                'history': self.history[-20:]}

    def load_memory(self, state):
        """Previous run's factors: only for the same reference record."""
        if not state or state.get('schema') != MEMORY_SCHEMA or \
                state.get('reference_sha256') != self.record['record_sha256']:
            return False
        for key, v in state['eta'].items():
            f, r = key.split('|')
            if (f, r) in self.eta:
                self.eta[(f, r)] = float(v)
        return True


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

    def objective(x):
        r = G @ x - problem.target
        return 0.5 * float(r @ (W2 * r)) + 0.5 * ridge * float(x @ x) + 0.5 * float(x @ Q @ x) + float(q @ x)

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
             'converged': converged}
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
        source = 'CARRIED_FROM_ORIGIN_RUN'
    else:
        record = capture(adapter, cfg, folder)
        anchors['generation_structure_reference'] = record
        source = 'MEASURED_AT_RUN_START'
    st = Structure(record, cfg)
    loaded = False
    if continuation and previous_run_folder and g['efficiency_memory']['enabled']:
        p = Path(previous_run_folder) / 'GENSTRUCT1_EFFICIENCY.json'
        if p.is_file():
            loaded = st.load_memory(read_json(p))
    write_json(Path(folder) / 'GENSTRUCT1_REFERENCE.json', {
        'source': source, 'record_sha256': record['record_sha256'], 'zones': len(record['zones']),
        'potential_attributes': record['potential_attributes'], 'distance_matrix': record['distance_matrix'],
        'anchor_target': record['anchor_target'], 'efficiency_memory_loaded': loaded,
        'centrality_quartiles': {f: np.percentile(record['centrality'][f], [25, 50, 75]).tolist() for f in FAMILIES},
        'zones_with_neighbours': {f: sum(1 for x in record['neighbours'][f] if x) for f in FAMILIES}})
    adapter.generation_structure = st
    adapter.generation_structure_folder = Path(folder)
    return st

