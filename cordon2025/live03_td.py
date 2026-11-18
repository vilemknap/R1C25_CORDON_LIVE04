"""LIVE03 TD_CORDON block: shape of the trip distribution (gravity b/c) on the cordon.

Objective = the cordon objective only (FIRST_LAST pairs + C17 stations, primary
method); the IDP fine-CDF (donor FineCDF v1.9) is a degradation guard.

Parameters (FineCDF v1.9 parameter space, grouped): for every group g of TD
components (default families WORK, SERVICE, SCHOOL)
    b_n' = b_n + db_g            c_n' = c_n * exp(dl_g)      (b>=0, c<0 kept)
with the v1.9 envelopes b in [0, max(4,b)], |c| in [min(0.001,|c|), max(8,|c|)]
and a trust region (v1.9 trust radii).

Inner search (no assignment): native TD + downstream demand operations on the
accepted saved paths (live03_predictor).  Jacobian by one native probe per
parameter, box-constrained Gauss-Newton on the weighted cordon residuals,
native verification of each step (+ Broyden update), IDP guard on the native
TD output.  Outer trial: donor apply_td -> PERF1 TD_TO_ASSIGNMENT recompute ->
fresh full cordon capture -> cordon gate + IDP guard -> kept in place, or the
donor verified rollback (parameter restore + recompute + diagnostic proof).
"""
from __future__ import annotations
import math
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from .common import require, parent_module, ContractError
from .io import write_json, write_csv, mkdir, exception_text
from .optimizer import deadzone
from .live03_predictor import FrozenPathPredictor, objective_vector, same_parameters

BLOCK = 'TD_CORDON'
RELEASE = 'LIVE03_TD_CORDON_V1'


class TDSpace:
    def __init__(self, td_values, groups, tdc):
        by = {r['component']: r for r in td_values}
        self.groups = []; self.audit = []
        self.grouping = str(tdc.get('grouping', 'FAMILY'))
        if self.grouping == 'COMPONENT':
            # LIVE04.11: every TD component gets its own b and log(c) step (v7 TDJOINT1 granularity);
            # the family lists only define which components take part.
            groups = {c: [c] for comps in groups.values() for c in comps}
        for name, comps in groups.items():
            comps = [c for c in comps]
            missing = [c for c in comps if c not in by]
            require(not missing, 'LIVE03_TD_COMPONENT_MISSING:' + ','.join(missing))
            b = np.array([float(by[c]['current_b']) for c in comps]); c = np.array([float(by[c]['current_c']) for c in comps])
            if not (np.all(b >= 0) and np.all(c < 0)):
                self.audit.append({'group': name, 'status': 'EXCLUDED_REQUIRES_B_GE_0_AND_C_LT_0'}); continue
            b_hi = np.maximum(4.0, b); cmin = np.minimum(0.001, -c); cmax = np.maximum(8.0, -c)
            lo = np.array([float(np.max(-b)), float(np.max(np.log(cmin / -c)))])
            hi = np.array([float(np.min(b_hi - b)), float(np.min(np.log(cmax / -c)))])
            self.groups.append({'name': name, 'components': comps, 'b': b, 'c': c, 'lo': lo, 'hi': hi})
            self.audit.append({'group': name, 'status': 'ACTIVE', 'components': comps, 'b': b.tolist(), 'c': c.tolist(),
                               'delta_lower': lo.tolist(), 'delta_upper': hi.tolist()})
        require(self.groups, 'LIVE03_TD_NO_ACTIVE_GROUP')
        self.n = 2 * len(self.groups)
        self.lo = np.concatenate([g['lo'] for g in self.groups]); self.hi = np.concatenate([g['hi'] for g in self.groups])
        self.trust = np.array([float(tdc['trust_b']), float(tdc['trust_logc'])] * len(self.groups))
        self.probe = np.array([float(tdc['probe_b']), float(tdc['probe_logc'])] * len(self.groups))

    def names(self):
        return [g['name'] + suffix for g in self.groups for suffix in ('.db', '.dlog_c')]

    def rows(self, x):
        out = []
        for k, g in enumerate(self.groups):
            db, dl = float(x[2 * k]), float(x[2 * k + 1])
            for comp, b, c in zip(g['components'], g['b'], g['c']):
                out.append({'component': comp, 'group': g['name'], 'current_b': float(b), 'current_c': float(c),
                            'candidate_b': float(b + db), 'candidate_c': float(c * math.exp(dl))})
        return out


def box_least_squares(A, r, lo, hi, scale, damping, iterations=4000):
    """Levenberg-Marquardt step in trust-scaled variables z = x/scale:
    min 0.5||A x + r||^2 + 0.5*lambda*mean(diag(H_s))*||z||^2  s.t. lo<=x<=hi (projected FISTA)."""
    A = A * scale[None, :]
    lo = lo / scale; hi = hi / scale
    n = A.shape[1]
    H = A.T @ A
    H = H + float(damping) * max(float(np.mean(np.diag(H))), 1e-300) * np.eye(n)
    g0 = A.T @ r
    L = max(float(np.linalg.eigvalsh(H).max()), 1e-12)
    x = np.clip(np.zeros(n), lo, hi); y = x.copy(); t = 1.0
    for _ in range(iterations):
        xn = np.clip(y - (H @ y + g0) / L, lo, hi)
        tn = 0.5 * (1 + math.sqrt(1 + 4 * t * t))
        y = xn + ((t - 1) / tn) * (xn - x); x, t = xn, tn
    return x * scale


def constrained_least_squares(A, r, lo, hi, scale, damping, C, d, iterations=6000):
    """LIVE04.10.5: the box_least_squares step with extra linear constraints C x <= d.

    Same objective as ``box_least_squares`` (trust-scaled LM), solved by ADMM on
    l <= [I; C] z <= u.  Requires d >= 0 (x = 0 is feasible: the trust-region centre
    already passed the guard).  The ADMM point is clipped to the box and then pulled
    back along the ray towards 0 until every constraint holds exactly, so the returned
    step is always feasible for the linear model."""
    A = A * scale[None, :]
    los = lo / scale; his = hi / scale
    Cs = np.asarray(C, dtype=float) * scale[None, :]
    d = np.maximum(np.asarray(d, dtype=float), 0.0)
    n = A.shape[1]
    H = A.T @ A
    H = H + float(damping) * max(float(np.mean(np.diag(H))), 1e-300) * np.eye(n)
    g = A.T @ r
    norm = max(float(np.mean(np.diag(H))), 1e-300)
    H = H / norm; g = g / norm
    rn = np.linalg.norm(Cs, axis=1)
    keep = rn > 1e-14
    Cs = Cs[keep] / rn[keep, None]; dn = d[keep] / rn[keep]
    M = np.vstack([np.eye(n), Cs])
    l = np.concatenate([los, np.full(len(dn), -np.inf)]); u = np.concatenate([his, dn])
    sigma, rho, alpha = 1e-6, 0.1, 1.6
    K = np.linalg.inv(H + sigma * np.eye(n) + rho * M.T @ M)
    x = np.zeros(n); z = np.clip(M @ x, l, u); y = np.zeros(len(l))
    for _ in range(iterations):
        xt = K @ (sigma * x - g + M.T @ (rho * z - y))
        zt = M @ xt
        zr = alpha * zt + (1 - alpha) * z
        zn = np.clip(zr + y / rho, l, u)
        y = y + rho * (zr - zn)
        x, z = xt, zn
    x = np.clip(x, los, his)
    t = 1.0
    if len(dn):
        cx = Cs @ x
        over = cx > dn
        if np.any(over):
            t = float(min(1.0, np.min(dn[over] / cx[over])))
    return x * t * scale


class IdpStepModel:
    """LIVE04.10.5: linear model of the IDP guard quantities around the trust-region centre.

    Features per guarded component: mean relative distance error and fine-CDF RMSE.
    The Jacobian F (features x TD parameters) comes from the same native Jacobian
    probes as the cordon Jacobian (the IDP of every probe is already evaluated), and is
    Broyden-updated by every verified inner step.  ``constraints`` turns the guard of
    ``IdpGuard.decide`` (always relative to IDP_BEFORE) into C s <= d for the step s,
    using only ``slack_use`` of the remaining slack (safety for the non-linearity).
    The native IDP guard still decides every step; the model only aims the step."""

    def __init__(self, guard, before, F, slack_use):
        self.guard = guard; self.before = before; self.F = np.array(F, dtype=float)
        self.slack_use = float(slack_use)
        self.features = [(k, 'mean_relative_error') for k in guard.guarded] + [(k, 'fine_cdf_rmse') for k in guard.guarded]

    @staticmethod
    def vector(guard, idp):
        return np.array([float(idp[k]['mean_relative_error']) for k in guard.guarded]
                        + [float(idp[k]['fine_cdf_rmse']) for k in guard.guarded])

    @classmethod
    def from_probes(cls, guard, before, probes, n, slack_use):
        """probes: [(j, h, idp_after)] for the active parameters; None if any IDP failed."""
        if guard is None or before is None:
            return None
        f0 = cls.vector(guard, before)
        F = np.zeros((len(f0), n))
        for j, h, idp in probes:
            if idp is None or 'error' in idp:
                return None
            F[:, j] = (cls.vector(guard, idp) - f0) / h
        return cls(guard, before, F, slack_use)

    def constraints(self, center_idp):
        g = self.guard; K = len(g.guarded)
        fc = self.vector(g, center_idp)
        rows, rhs = [], []
        for i, k in enumerate(g.guarded):
            b = self.before[k]
            allowed = max(abs(float(b['mean_relative_error'])), g.mean_floor) + g.mean_tol
            rows.append(self.F[i]); rhs.append(self.slack_use * (allowed - fc[i]))
            rows.append(-self.F[i]); rhs.append(self.slack_use * (allowed + fc[i]))
            rows.append(self.F[K + i])
            rhs.append(self.slack_use * (float(b['fine_cdf_rmse']) + g.rmse_tol - fc[K + i]))
        return np.array(rows), np.maximum(np.array(rhs), 0.0)

    def predict(self, center_idp, step):
        f = self.vector(self.guard, center_idp) + self.F @ step
        K = len(self.guard.guarded)
        return {k: {'mean_relative_error': float(f[i]), 'fine_cdf_rmse': float(f[K + i])}
                for i, k in enumerate(self.guard.guarded)}

    def update(self, center_idp, idp_x, step):
        dd = float(step @ step)
        if dd <= 0 or idp_x is None or 'error' in idp_x:
            return False
        fc = self.vector(self.guard, center_idp); fx = self.vector(self.guard, idp_x)
        self.F += np.outer(fx - fc - self.F @ step, step) / dd
        return True


class IdpBlend:
    """LIVE04.11: IDP part of the blended TD inner objective.

    f = [fine_cdf_rmse_k ; 0.5 * mean_relative_error_k] for the TD components k, so that
    sum(f^2) = sum_k J_k (sealed FineCDF v1.9 component objective RMSE^2 + 0.25 mean^2).
    Normalised at the block start: weight w on J/J_ref, (1-w) on the cordon Q/Q_ref."""

    def __init__(self, guard, components, before, weight, q_ref):
        self.components = [k for k in guard.guarded if k in set(components)]
        require(self.components, 'LIVE04_TD_BLEND_NO_GUARDED_TD_COMPONENT')
        self.idx = [guard.guarded.index(k) for k in self.components]
        self.K = len(guard.guarded)
        self.weight = float(weight)
        f0 = self.features(before)
        self.j_ref = max(float(f0 @ f0), 1e-12)
        self.q_ref = max(float(q_ref), 1e-12)
        self.a_cordon = math.sqrt((1.0 - self.weight) / self.q_ref)
        self.a_idp = math.sqrt(2.0 * self.weight / self.j_ref)

    def features(self, idp):
        return np.array([float(idp[k]['fine_cdf_rmse']) for k in self.components]
                        + [0.5 * float(idp[k]['mean_relative_error']) for k in self.components])

    def jacobian(self, model):
        rmse = [self.K + i for i in self.idx]; mean = list(self.idx)
        return np.vstack([model.F[rmse], 0.5 * model.F[mean]])

    def value(self, q, idp):
        f = self.features(idp)
        return (1.0 - self.weight) * float(q) / self.q_ref + self.weight * float(f @ f) / self.j_ref

    def audit(self):
        return {'schema': 'LIVE04_11_TD_BLEND_V1', 'idp_weight': self.weight, 'cordon_weight': 1.0 - self.weight,
                'components': self.components, 'cordon_ref': self.q_ref, 'idp_ref': self.j_ref,
                'form': '(1-w) Q/Q_ref + w sum_k(RMSE_k^2 + 0.25 mean_k^2)/J_ref',
                'role': 'INNER_STEP_DIRECTION_ONLY_ACCEPTANCE_UNCHANGED'}


SOFT_CORDON_REASONS = ('CORDON_OBJECTIVE_NOT_IMPROVED', 'CORDON_RELATIVE_IMPROVEMENT_BELOW_MINIMUM',
                       'SECONDARY_METHOD_DEGRADED')


def blended_gate(dec, blend, q0, q1, idp0, idp1, tdc, q_base=None):
    """LIVE04.11 (user decision 2026-11-06, v7 TDBLEND1 outer acceptance): a TD step is accepted when
    F = (1-w) q1/q0 + w J(idp1)/J(idp0) <= 1 - min_rel, the cordon objective (and the secondary
    method) worsens by at most max_deg, and every other (hard) gate reason is absent.  The plain
    'cordon must improve' reasons of the shared gate become soft and are replaced by this rule."""
    min_rel = float(tdc.get('blended_min_relative_improvement', 0.001))
    max_deg = float(tdc.get('blended_max_cordon_degradation', 0.01))
    max_secondary_deg = float(tdc.get('blended_max_secondary_degradation', max_deg))
    hard = [r for r in (dec.get('reasons') or []) if r not in SOFT_CORDON_REASONS]
    if idp1 is None or 'error' in idp1:
        return dict(dec, accepted=False, reasons=hard + ['TD_BLENDED_IDP_UNAVAILABLE'])
    f0 = blend.features(idp0); f1 = blend.features(idp1)
    j0 = max(float(f0 @ f0), 1e-12); j1 = float(f1 @ f1)
    w = blend.weight
    value = (1.0 - w) * float(q1) / max(abs(float(q0)), 1e-12) + w * j1 / j0
    # cordon loss is always measured against the block start (q_base), so inner steps cannot
    # accumulate more than max_deg in total; F improvement is measured against q0 / idp0
    qb = float(q0 if q_base is None else q_base)
    cordon_deg = (float(q1) - qb) / max(abs(qb), 1e-12)
    sec = dec.get('secondary_relative_degradation')
    reasons = list(hard)
    if value > 1.0 - min_rel:
        reasons.append('TD_BLENDED_OBJECTIVE_NOT_IMPROVED')
    if cordon_deg > max_deg:
        reasons.append('TD_CORDON_DEGRADED_TOO_MUCH')
    if sec is not None and float(sec) > max_secondary_deg:
        reasons.append('TD_SECONDARY_DEGRADED_TOO_MUCH')
    audit = {'rule': 'V7_TDBLEND1_OUTER', 'idp_weight': w, 'blended_value': value,
             'blended_relative_improvement': 1.0 - value, 'cordon_relative_degradation': cordon_deg,
             'idp_ratio': j1 / j0, 'min_relative_improvement': min_rel, 'max_cordon_degradation': max_deg,
             'max_secondary_degradation': max_secondary_deg,
             'soft_reasons_replaced': [r for r in (dec.get('reasons') or []) if r in SOFT_CORDON_REASONS]}
    return dict(dec, accepted=not reasons, reasons=reasons, td_blended_acceptance=audit)


def inner_blended_gate(dec, blend, parent_q, center_q, candidate_q,
                       parent_idp, center_idp, candidate_idp, tdc):
    """Use the trial's parent reference, then keep only improvements over the current inner step."""
    out = blended_gate(dec, blend, parent_q, candidate_q, parent_idp, candidate_idp,
                       tdc, q_base=parent_q)
    if out['accepted']:
        center_value = blend.value(center_q, center_idp)
        candidate_value = blend.value(candidate_q, candidate_idp)
        out['td_blended_acceptance'].update(inner_center_value=center_value,
                                            inner_candidate_value=candidate_value)
        if candidate_value >= center_value - 1e-12:
            out['accepted'] = False
            out['reasons'] = list(out['reasons']) + ['TD_INNER_BLEND_NOT_BETTER_THAN_CENTER']
    return out


def _verify_memory_jacobian(J, native, space, tdc, mcfg, m0, method, w, y, eps, methods):
    """LIVE04.1: plan the first trust-region step with the remembered Jacobian, probe it
    natively once and accept the Jacobian only if it predicts that probe."""
    r = w * deadzone(m0[method] - y, eps)
    lo = np.maximum(space.lo, -space.trust); hi = np.minimum(space.hi, space.trust)
    step = box_least_squares(w[:, None] * J[method], r, lo, hi, space.trust, float(tdc['damping']))
    out = {'step': step.tolist(), 'step_max_abs': float(np.max(np.abs(step), initial=0.0))}
    if np.max(np.abs(step) / np.maximum(space.trust, 1e-12), initial=0.0) < 1e-4:
        # No informative direction: use one standard probe size on the first active parameter.
        step = np.zeros(space.n); step[0] = space.probe[0] if space.hi[0] >= space.probe[0] else -space.probe[0]
        out['step'] = step.tolist(); out['fallback_direction'] = True
    # Verify in the linear regime: the planned DIRECTION at the per-parameter probe size
    # (a full trust-region step would test the non-linearity, not the Jacobian).
    size = float(np.max(np.abs(step) / np.maximum(space.probe, 1e-12)))
    step = step / size
    out['verify_step'] = step.tolist()
    rows, _, audit = native(step, 'MEM_VERIFY')
    actual = np.asarray(rows[method], dtype=float) - m0[method]
    predicted = J[method] @ step
    err = float(np.linalg.norm(actual - predicted)) / max(float(np.linalg.norm(actual)), 1e-12)
    out.update(relative_error=err, tolerance=float(mcfg['td_verify_tolerance']),
               unsupported_share=audit['unsupported_share'])
    if err <= float(mcfg['td_verify_tolerance']):
        dd = float(step @ step)
        for m in methods:
            J[m] += np.outer(np.asarray(rows[m], dtype=float) - m0[m] - J[m] @ step, step) / dd
        out['status'] = 'MEMORY_VERIFIED'
    else:
        out['status'] = 'MEMORY_REJECTED_FULL_PROBES'
    return out


def td_block(tx, adapter, cfg, folder, control, state, diag, anchors, reference, policy, *, tdc, idp_cfg, memory=None):
    base = SimpleNamespace(**tx.ctrl_ns)
    SupplyContractError = parent_module('r1_15a2_supply').SupplyContractError
    txm = parent_module('r1_15a2_inplace_transaction_v24915p2')
    evaluator = adapter.evaluator
    method = evaluator.method
    folder = Path(folder); mkdir(folder)
    baseline_value = base.ledger(diag, state, anchors, policy, reference, cfg)
    baseline_hash = base.diagnostic_hash(diag)
    rec = {'release': RELEASE, 'block': BLOCK, 'status': 'DESIGNING', 'objective_before': baseline_value,
           'inner': [], 'search_mode': 'NATIVE_FROZEN_PATH_GAUSS_NEWTON_ADOPT_IN_PLACE'}
    space = TDSpace(state['td_values'], tdc['groups'], tdc)
    rec['parameter_space'] = space.audit
    from .live03_idp import IdpGuard
    guard = None; idp_before = None
    if idp_cfg.get('enabled', True):
        try:
            guard = IdpGuard(adapter.visum, len(adapter.zones), idp_cfg)
            idp_before = guard.evaluate('BEFORE')
        except Exception as exc:   # fail closed: no TD write without a valid IDP reference
            rec.update(status='NO_TD_CANDIDATE', stop_reason='IDP_BASELINE_UNAVAILABLE',
                       error=type(exc).__name__ + ':' + exception_text(exc))
            write_json(folder / 'TD_BLOCK_RESULT.json', rec)
            return False, state, diag, baseline_value, rec
        write_json(folder / 'IDP_BEFORE.json', idp_before)
    pred = FrozenPathPredictor(adapter, diag, folder / 'PREDICTOR', tolerance=float(tdc.get('base_parity_tolerance', 1e-6)))
    try:
        rec['base_parity'] = pred.base_parity()          # before any write
    except ContractError as exc:
        if not exception_text(exc).startswith('LIVE03_PREDICTOR_'):
            raise
        # LIVE04.5.2: without a valid frozen-path predictor there is no TD search; skip
        # this TD block (no write happened) instead of stopping the whole run.
        rec.update(status='NO_TD_CANDIDATE', stop_reason='PREDICTOR_UNAVAILABLE', error=exception_text(exc)[:1000])
        write_json(folder / 'TD_BLOCK_RESULT.json', rec)
        return False, state, diag, baseline_value, rec
    terms = diag['_terms'][method]
    w, y, eps = terms['w'], terms['y'], terms['eps']
    m0 = {m: np.asarray(diag['methods'][m]['model'], dtype=float) for m in evaluator.methods}
    dirty = {'demand': False}

    def native(x, label):
        rows = space.rows(x)
        nf = folder / 'NATIVE' / label
        control.checkpoint('LIVE03_TD_NATIVE_PROBE', force=True, label=label)
        dirty['demand'] = True
        try:
            audit = parent_module('r1_15a2_visum_parameters').apply_td_candidates(adapter.visum, rows)
            require(audit and all(a.get('status') == 'OK' for a in audit), 'LIVE03_TD_PROBE_READBACK_FAILED')
            predicted, _, paudit = pred.probe(BLOCK, label, nf)
            idp_after = None
            if guard:
                try:
                    idp_after = guard.evaluate(label)
                except Exception as exc:  # donor GuardError (e.g. no conditioned demand)
                    idp_after = {'error': type(exc).__name__ + ':' + exception_text(exc)}
        finally:
            txm.restore_td_parameters(adapter, state, rows, nf / 'RESTORE_PARAMETERS')
        return predicted, idp_after, paudit

    def predicted_objective(rows_by_method):
        return objective_vector(evaluator, diag, rows_by_method)

    def guard_decision(idp_after):
        if guard is None:
            return {'passes': True, 'reasons': [], 'role': 'DISABLED'}
        if idp_after is None or 'error' in idp_after:
            return {'passes': False, 'reasons': ['IDP_EVALUATION_FAILED:' + str((idp_after or {}).get('error'))]}
        return guard.decide(idp_before, idp_after)

    def finish_without_trial(reason):
        if dirty['demand']:
            with base.recovery_scope(control, 'LIVE03_TD_DEMAND_RESTORE'):
                pred.restore_demand(BLOCK, state, folder / 'DEMAND_RESTORE')
            dirty['demand'] = False
        rec.update(status='NO_TD_CANDIDATE', stop_reason=reason, predictor=pred.summary())
        write_json(folder / 'TD_BLOCK_RESULT.json', rec)
        return False, state, diag, baseline_value, rec

    try:
        J = None
        probes = []
        # ---- LIVE04.1: Jacobian from the previous cycle, verified by ONE native probe
        reused = memory.td_jacobian(space.names(), {m: len(m0[m]) for m in evaluator.methods}) if memory else None
        if reused is not None:
            rec['jacobian_memory'] = _verify_memory_jacobian(reused, native, space, tdc, memory.cfg, m0, method,
                                                             w, y, eps, evaluator.methods)
            probes.append({'parameter': 'MEMORY_VERIFY', 'step': rec['jacobian_memory'].get('step_max_abs'),
                           'unsupported_share': rec['jacobian_memory'].get('unsupported_share')})
            if rec['jacobian_memory']['status'] == 'MEMORY_VERIFIED':
                J = reused
        rec['jacobian_source'] = 'MEMORY_VERIFIED' if J is not None else (
            'NATIVE_PROBES_MEMORY_REJECTED' if reused is not None else 'NATIVE_PROBES')
    except BaseException:
        if dirty['demand']:
            with base.recovery_scope(control, 'LIVE03_TD_DEMAND_RESTORE_AFTER_ERROR'):
                pred.restore_demand(BLOCK, state, folder / 'DEMAND_RESTORE_AFTER_ERROR')
        raise
    idp_probes = []
    try:
        # ---- Jacobian: one native probe per parameter (frozen paths)
        for j in (range(space.n) if J is None else ()):
            if j == 0:
                J = {m: np.zeros((len(m0[m]), space.n)) for m in evaluator.methods}
            h = space.probe[j]
            if space.hi[j] < h:
                h = -h if space.lo[j] <= -h else (space.hi[j] if space.hi[j] >= -space.lo[j] else space.lo[j])
            require(abs(h) > 1e-12, 'LIVE03_TD_NO_ROOM_FOR_PROBE:' + space.names()[j])
            x = np.zeros(space.n); x[j] = h
            rows_j, idp_j, a = native(x, 'JAC_%02d' % (j + 1))
            idp_probes.append((j, float(h), idp_j))
            for m in evaluator.methods:
                J[m][:, j] = (rows_j[m] - m0[m]) / h
            probes.append({'parameter': space.names()[j], 'step': float(h), 'unsupported_share': a['unsupported_share'],
                           'primary_row_response_l2': float(np.linalg.norm(J[method][:, j]))})
        # Parameters without cordon response (e.g. a family absent from the OA dsegs) stay fixed.
        norms = np.linalg.norm(J[method], axis=0)
        active = norms > float(tdc.get('min_relative_column_norm', 1e-6)) * max(float(norms.max(initial=0.0)), 1e-300)
        for p, a_ in zip([p for p in probes if p['parameter'] != 'MEMORY_VERIFY'], active):
            p['active'] = bool(a_)
        require(active.any(), 'LIVE03_TD_NO_PARAMETER_WITH_CORDON_RESPONSE')
        rec['jacobian_probes'] = probes
        J_local = {m: v.copy() for m, v in J.items()}   # probe-size (local) Jacobian, before secant updates
        # ---- LIVE04.10.5: IDP-aware step (linear IDP guard model from the same probes)
        idp_model = None
        idp_mode = 'OFF'
        if guard is not None and bool(tdc.get('idp_constrained_step', False)):
            slack_use = float(tdc.get('idp_constraint_slack_use', 0.7))
            if idp_probes:
                idp_model = IdpStepModel.from_probes(guard, idp_before, idp_probes, space.n, slack_use)
                idp_mode = 'NATIVE_PROBES' if idp_model else 'UNAVAILABLE_PROBE_IDP_FAILED'
            else:
                F = memory.td_idp_jacobian(space.names(), len(guard.guarded)) if memory else None
                if F is not None:
                    idp_model = IdpStepModel(guard, idp_before, F, slack_use)
                    idp_mode = 'MEMORY'
                else:
                    idp_mode = 'UNAVAILABLE_NO_IDP_JACOBIAN'
        F_local = None if idp_model is None else idp_model.F.copy()
        rec['idp_step_model'] = {'mode': idp_mode, 'slack_use': None if idp_model is None else idp_model.slack_use,
                                 'parameters': space.names(),
                                 'jacobian': None if idp_model is None else {
                                     '%s.%s' % f: dict(zip(space.names(), idp_model.F[i].tolist()))
                                     for i, f in enumerate(idp_model.features)}}
        center_idp = idp_before
        blend = None
        bw = float(tdc.get('idp_objective_weight', 0.0))
        if idp_model is not None and bw > 0:
            td_comps = [c for g in space.groups for c in g['components']]
            blend = IdpBlend(guard, td_comps, idp_before, bw, float(diag['methods'][method]['objective']))
        rec['objective_blend'] = None if blend is None else blend.audit()
        blended_acceptance = blend is not None and str(tdc.get('acceptance', 'CORDON')) == 'BLENDED'
        rec['acceptance_mode'] = 'BLENDED' if blended_acceptance else 'CORDON'
        if str(tdc.get('acceptance', 'CORDON')) == 'BLENDED' and not blended_acceptance:
            if bw > 0 and guard is not None:
                rec['acceptance_mode_note'] = 'BLENDED_REQUESTED_BUT_IDP_MODEL_UNAVAILABLE_NO_TRIAL'
                return finish_without_trial('BLENDED_IDP_MODEL_UNAVAILABLE')
            rec['acceptance_mode_note'] = ('BLENDED_REQUESTED_BUT_IDP_WEIGHT_ZERO_CORDON_USED' if bw == 0
                                           else 'BLENDED_REQUESTED_BUT_IDP_DISABLED_CORDON_USED')
        write_csv(folder / 'TD_JACOBIAN_PRIMARY.csv', [dict(zip(['row'] + space.names(), [i] + list(J[method][i])))
                                                      for i in range(J[method].shape[0])])
        # ---- inner box Gauss-Newton with trust region, native verification
        center = np.zeros(space.n); center_rows = {m: m0[m].copy() for m in evaluator.methods}
        center_obj = float(diag['methods'][method]['objective'])
        best = None
        radius = 1.0
        evals = 0
        min_rel = float(tdc['min_predicted_relative_improvement'])
        for it in range(int(tdc['max_inner_evaluations'])):
            r = w * deadzone(center_rows[method] - y, eps)
            A = w[:, None] * J[method]
            lo = np.where(active, np.maximum(space.lo - center, -space.trust * radius), 0.0)
            hi = np.where(active, np.minimum(space.hi - center, space.trust * radius), 0.0)
            if blend is not None:
                # LIVE04.11: 0.5||[sqrt((1-w)/Q_ref) r_cordon ; sqrt(2w/J_ref) f_idp]||^2
                #          = (1-w) Q/Q_ref + w J/J_ref   (v7 TDBLEND1 form, normalised at the block start)
                fv = blend.features(center_idp)
                A = np.vstack([blend.a_cordon * A, blend.a_idp * blend.jacobian(idp_model)])
                r = np.concatenate([blend.a_cordon * r, blend.a_idp * fv])
            if idp_model is not None:
                Cm, dm = idp_model.constraints(center_idp)
                Cm = Cm * active[None, :]
                step = constrained_least_squares(A, r, lo, hi, space.trust, float(tdc['damping']), Cm, dm)
            else:
                step = box_least_squares(A, r, lo, hi, space.trust, float(tdc['damping']))
            entry = {'iteration': it + 1, 'radius': radius, 'step': step.tolist(),
                     'linear_predicted_objective': float(0.5 * np.sum((w * deadzone(center_rows[method] + J[method] @ step - y, eps)) ** 2))}
            if idp_model is not None:
                entry['idp_constrained'] = True
                entry['idp_predicted'] = idp_model.predict(center_idp, step)
            if np.max(np.abs(step) / np.maximum(space.trust, 1e-12)) < 1e-4:
                entry['status'] = 'STEP_NEGLIGIBLE'; rec['inner'].append(entry); break
            x = center + step
            rows_x, idp_after, a = native(x, 'GN_%02d' % (it + 1)); evals += 1
            if idp_model is not None:
                entry['idp_model_updated'] = idp_model.update(center_idp, idp_after, step)
            pdiag = predicted_objective(rows_x)
            gate = evaluator.block_gate(BLOCK, diag, pdiag, space.rows(x))
            obj = float(pdiag['methods'][method]['objective'])
            rel_vs_center = (center_obj - obj) / max(abs(center_obj), 1e-12)
            gd = guard_decision(idp_after)
            if blended_acceptance:
                # Apply the same block-parent acceptance as the full trial, while retaining
                # only successive inner steps that improve on the current best score.
                gate = inner_blended_gate(gate, blend, float(diag['methods'][method]['objective']),
                                          center_obj, obj, idp_before, center_idp, idp_after, tdc)
            entry.update(x=x.tolist(), native_frozen_objective=obj, relative_vs_center=rel_vs_center,
                         predicted_secondary_relative_degradation=gate.get('secondary_relative_degradation'),
                         gate_reasons=gate.get('reasons'), idp=gd, unsupported_share=a['unsupported_share'])
            if blend is not None and idp_after is not None and 'error' not in idp_after:
                entry.update(blend_center=blend.value(center_obj, center_idp), blend_measured=blend.value(obj, idp_after))
            # Broyden rank-1 correction of all method Jacobians.
            dd = float(step @ step)
            if dd > 0:
                for m in evaluator.methods:
                    J[m] += np.outer(rows_x[m] - center_rows[m] - J[m] @ step, step) / dd
            improved = gate.get('accepted') if blended_acceptance else rel_vs_center > 0
            if improved and gate.get('accepted') and gd['passes']:
                center, center_rows, center_obj = x, rows_x, obj
                if idp_after is not None and 'error' not in idp_after:
                    center_idp = idp_after
                best = {'x': x.copy(), 'objective': obj, 'idp': gd,
                        'blend': None if blend is None else blend.value(obj, idp_after)}
                entry['status'] = 'INNER_ACCEPTED'
                radius = min(float(tdc['trust_radius_max']), radius * float(tdc['trust_growth']))
            else:
                entry['status'] = 'INNER_REJECTED'
                radius *= float(tdc['trust_shrink'])
            rec['inner'].append(entry)
            write_json(folder / 'TD_BLOCK_RESULT.json', rec)
            if radius < float(tdc['trust_radius_min']):
                break
        rec['native_evaluations'] = len(probes) + evals
        if memory:
            # Local frozen-path Jacobian: the next block verifies it with a probe-size step, so
            # neither the large-step Broyden secants nor the measured trial (route choice) are
            # folded in.
            memory.store_td(space.names(), J_local, 'LOCAL_FROZEN_PATH_JACOBIAN', idp=F_local)
        if best is None:
            if idp_model is not None and rec['inner'] and rec['inner'][-1].get('status') == 'STEP_NEGLIGIBLE' \
                    and len(rec['inner']) == 1:
                return finish_without_trial('NO_IDP_FEASIBLE_IMPROVING_STEP')
            return finish_without_trial('NO_INNER_IMPROVEMENT_WITH_GUARD')
        j0 = float(diag['methods'][method]['objective'])
        rec['predicted_relative_improvement'] = (j0 - best['objective']) / max(abs(j0), 1e-12)
        if blended_acceptance:
            rec['predicted_cordon_relative_improvement'] = rec['predicted_relative_improvement']
            rec['predicted_relative_improvement'] = 1.0 - float(best['blend'])
        if rec['predicted_relative_improvement'] < min_rel:
            return finish_without_trial('PREDICTED_IMPROVEMENT_BELOW_MINIMUM')
    except BaseException:
        if dirty['demand']:
            with base.recovery_scope(control, 'LIVE03_TD_DEMAND_RESTORE_AFTER_ERROR'):
                pred.restore_demand(BLOCK, state, folder / 'DEMAND_RESTORE_AFTER_ERROR')
        raise

    # ---- full trial: donor apply -> TD_TO_ASSIGNMENT -> capture -> gate (+IDP) -> keep or rollback
    rows = space.rows(best['x'])
    candidate = {'td_cordon': True, 'x': best['x'].tolist(), 'parameters': space.names()}
    trial = folder / 'TRIAL'; mkdir(trial)
    require(same_parameters(adapter.snapshot(), state), 'LIVE03_TD_TRIAL_PARENT_PARAMETERS_CHANGED')
    try:
        control.checkpoint('TRIAL_APPLY', block=BLOCK, candidate=base._candidate_signature(BLOCK, candidate, rows))
        actual = base._apply_candidate(adapter, BLOCK, candidate, rows, {}, state, trial)
        from .live03_td_parameters import capture_write_readback, assert_trial_freeze
        actual, rec['parameter_write_readback'] = capture_write_readback(adapter, state, actual, trial)
        control.checkpoint('TRIAL_ASSIGNMENT', block=BLOCK)
        gap = base._assign_candidate(adapter, trial / 'ASSIGNMENT', BLOCK)
        dirty['demand'] = False
        adapter.parameter_persistence(BLOCK, actual)
        after = adapter.snapshot()
        assert_trial_freeze(base, state, after, BLOCK, actual, candidate, cfg, trial)
        after_diag = adapter.diagnostics(trial / 'DIAGNOSTICS', 'STEP1_TRIAL')
        require(adapter.snapshot() == after, 'TRIAL_DIAGNOSTICS_CHANGED_MODEL')
        def decide(d):
            v = base.ledger(d, after, anchors, policy, reference, cfg)
            dec = adapter.block_gate(BLOCK, diag, d, actual)
            idp_trial = None
            if guard and d.get('valid', True):
                try:
                    idp_trial = guard.evaluate('TRIAL')
                except Exception as exc:
                    idp_trial = {'error': type(exc).__name__ + ':' + exception_text(exc)}
            if blended_acceptance and d.get('valid', True):
                dec = blended_gate(dec, blend, baseline_value['total'], v['total'], idp_before, idp_trial, tdc)
            if guard and d.get('valid', True):
                gd = guard_decision(idp_trial)
                dec['idp_guard'] = gd
                if not gd['passes']:
                    dec['accepted'] = False
                    dec.setdefault('reasons', []).extend(gd['reasons'])
            imp = baseline_value['total'] - v['total']
            dec.update(shared_ledger_before=baseline_value, shared_ledger_after=v,
                       shared_objective_improvement=imp,
                       predicted_objective=best['objective'], measured_objective=v['total'])
            if imp <= 1e-8 and not blended_acceptance:
                dec['accepted'] = False
                dec.setdefault('reasons', []).append('SHARED_OBJECTIVE_NOT_IMPROVED')
            return v, dec
        after_value, decision = decide(after_diag)
        if decision.get('accepted'):
            from .live04_confirm import confirm_before_accept
            from .live02_step1 import _drop_capture
            full, v2, dec2, caudit = confirm_before_accept(adapter, trial / 'DIAGNOSTICS_CONFIRM', after_diag, after,
                                                           decide, True)
            rec['acceptance_confirm'] = caudit.get('status')
            if dec2 is not None:
                _drop_capture(trial / 'DIAGNOSTICS')
                after_diag, after_value, decision = full, v2, dec2
        write_json(trial / 'ACCEPTANCE.json', decision)
        rec.update(trial={'gap': gap, 'decision': {k: decision.get(k) for k in ('accepted', 'reasons', 'objective_before',
                                                                               'objective_after', 'relative_improvement',
                                                                               'secondary_relative_degradation')},
                          'rows': actual, 'predicted_objective': best['objective'],
                          'measured_objective': after_value['total']})
        if decision.get('accepted'):
            rec.update(status='ACCEPTED', objective_after=after_value, adopted_in_place=True, predictor=pred.summary())
            write_json(folder / 'TD_BLOCK_RESULT.json', rec)
            write_csv(folder / 'ACCEPTED_TD_PARAMETERS.csv', actual)
            return True, after, after_diag, after_value, rec
    except BaseException as exc:
        # Recovery must run before formatting/reporting the failure: COM
        # exceptions may be unprintable and the report file may be locked.
        with base.recovery_scope(control, 'LIVE03_TD_TRIAL_ROLLBACK'):
            rb, rolled = base._rollback_candidate(adapter, BLOCK, state, baseline_hash, trial / 'ROLLBACK', rows,
                                                  candidate, diag)
        text = exception_text(exc)
        rec.update(status='TRIAL_FAILED', error=text, rollback=rb)
        write_json(folder / 'TD_BLOCK_RESULT.json', rec)
        if not isinstance(exc, Exception) or isinstance(exc, (base.UserStopRequested, base.TimeBudgetReached)):
            raise
        if 'ASSIGNMENT_NOT_TIGHT' in text and base.diagnostic_hash(rolled) == baseline_hash:
            # LIVE04.5.2: gap above the limit is a candidate property -> rejected after verified rollback.
            rec.update(status='TRIAL_REJECTED_ASSIGNMENT_NOT_TIGHT', rollback=rb, predictor=pred.summary())
            write_json(folder / 'TD_BLOCK_RESULT.json', rec)
            return False, state, diag, baseline_value, rec
        raise SupplyContractError('LIVE03_TD_TRIAL_ERROR_NOT_A_PLATEAU:' + text) from exc
    with base.recovery_scope(control, 'LIVE03_TD_TRIAL_ROLLBACK'):
        rb, rolled = base._rollback_candidate(adapter, BLOCK, state, baseline_hash, trial / 'ROLLBACK', rows, candidate, diag)
    write_json(trial / 'ROLLBACK_SUMMARY.json', rb)
    require(base.diagnostic_hash(rolled) == baseline_hash, 'LIVE03_TD_ROLLBACK_DIAGNOSTIC_CHANGED')
    rec.update(status='TRIAL_REJECTED_ROLLED_BACK', predictor=pred.summary())
    write_json(folder / 'TD_BLOCK_RESULT.json', rec)
    return False, state, diag, baseline_value, rec
