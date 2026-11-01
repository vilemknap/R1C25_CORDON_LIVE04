"""SEVRELAX3 (v7 @ 7b4c681) on the cordon rows: per-row GEH limits and scoped severity budgets.

User decision 2026-11-01: the GEH limits and severity budgets that v7 applies to the
498 count profiles apply in the cordon calibrator to the rows of the acceptance
method (FIRST_LAST: 120 station pairs + 16 C17 station rows).  Definitions are the
v7 core ones (r1_15a2_core.geh_severity_metrics, protected_profile_guard in the
early-exploration mode, rebase_severity_guard_v24912), values come from the pinned
v7 run options:

* protected row   parent GEH < 5 must stay below sev_protected_after_hard_geh (40);
                  zero catastrophic protected rows allowed;
* single row      GEH increase <= sev_max_single_profile_geh_increase (+50);
* high row        a row ending above GEH 60 may increase by at most
                  sev_max_high_geh_increase (+30);
* scope budgets   relative degradation of severity20 / severity30 and the net
                  increase of rows with GEH >= 40, per block (sev_scope_budgets:
                  generation / td / supply).

Rows with observed <= 0 are skipped (as v7 skips CAL profiles without a count).  The
cordon rows carry no R1 profile Weight, so every row has weight 1.  Everything is
relative to the parent of the trial (not the run start), exactly as in v7.  The guard
is evaluated on predicted diagnostics (STEP1/TD planning gate) and on the native trial
(final gate) with the same configuration.
"""
from __future__ import annotations
import math
import numpy as np

RELEASE = 'LIVE04_SEVRELAX3_CORDON_ROWS'
SCOPES = {'GENERATION': 'generation', 'TD_CORDON': 'td', 'SUPPLY_ADDVAL1': 'supply'}
PROTECTED_BEFORE_GEH = 5.0           # v7 core early_exploration default
LEGACY_PROTECTED_AFTER_GEH = 20.0    # v7: sev_protected_after_hard_geh = 0 keeps 20
HIGH_GEH_THRESHOLD = 60.0            # v7 core high_geh_threshold
POWER = 2.0
EPS = 1.0e-12


def policy_from_options(opts, enabled=True):
    hard = float(opts['sev_protected_after_hard_geh'] or 0.0)
    return {'enabled': bool(enabled), 'release': RELEASE,
            'protected_before_geh': PROTECTED_BEFORE_GEH,
            'protected_after_hard_geh': hard if hard > 0 else LEGACY_PROTECTED_AFTER_GEH,
            'max_protected_catastrophic': 0,
            'max_single_row_geh_increase': float(opts['sev_max_single_profile_geh_increase']),
            'high_geh_threshold': HIGH_GEH_THRESHOLD,
            'max_high_geh_increase': float(opts['sev_max_high_geh_increase']),
            'scope_budgets': {k: dict(v) for k, v in opts['sev_scope_budgets'].items()},
            'row_weight': 1.0, 'rows': 'ACCEPTANCE_METHOD_ROWS_WITH_POSITIVE_OBSERVATION',
            'source': 'V7_RUN_OPTIONS_SEVRELAX3'}


def geh(model, observed):
    model = np.asarray(model, dtype=float); observed = np.asarray(observed, dtype=float)
    return np.sqrt(2.0 * (model - observed) ** 2 / np.maximum(model + observed, EPS))


def severity(model, observed, power=POWER):
    """v7 geh_severity_metrics with unit weights on rows with a positive observation."""
    model = np.asarray(model, dtype=float); observed = np.asarray(observed, dtype=float)
    sel = observed > 0
    if not np.any(sel):
        return {'n': 0, 'geh_ge20': 0, 'geh_ge30': 0, 'geh_ge40': 0, 'max_geh': 0.0,
                'severity20': 0.0, 'severity30': 0.0, 'power': power}
    g = geh(model[sel], observed[sel])
    n = int(sel.sum())
    return {'n': n, 'geh_ge20': int(np.sum(g >= 20.0)), 'geh_ge30': int(np.sum(g >= 30.0)),
            'geh_ge40': int(np.sum(g >= 40.0)), 'max_geh': float(g.max()),
            'severity20': float(np.sum(np.maximum(g - 20.0, 0.0) ** power) / n),
            'severity30': float(np.sum(np.maximum(g - 30.0, 0.0) ** power) / n), 'power': power}


def relative_degradation(before, after):
    """v7 _v24912_relative_degradation."""
    b = float(before or 0.0); a = float(after or 0.0)
    if b <= EPS:
        return 0.0 if a <= b + EPS else float('inf')
    return max(0.0, (a - b) / b)


def evaluate(before_model, after_model, observed, labels, block, policy):
    """Decision of one transition parent -> candidate (predicted or measured)."""
    scope = SCOPES.get(str(block).upper())
    out = {'release': RELEASE, 'block': str(block), 'scope': scope, 'passes': True, 'reasons': []}
    if not policy.get('enabled', True) or scope is None:
        out['status'] = 'NOT_APPLIED'
        return out
    b = np.asarray(before_model, dtype=float); a = np.asarray(after_model, dtype=float)
    y = np.asarray(observed, dtype=float)
    if not (b.shape == a.shape == y.shape) or not (np.isfinite(a).all() and np.isfinite(b).all()):
        out.update(passes=False, reasons=['SEVRELAX3_CORDON_ROW_VECTOR_INVALID'])
        return out
    sel = y > 0
    gb = geh(b, y); ga = geh(a, y); inc = ga - gb
    lab = [str(x) for x in labels] if labels is not None else [str(i) for i in range(len(y))]

    def rows(mask):
        return [{'row': lab[i], 'observed': float(y[i]), 'before_model': float(b[i]), 'after_model': float(a[i]),
                 'before_geh': float(gb[i]), 'after_geh': float(ga[i]), 'geh_increase': float(inc[i])}
                for i in np.flatnonzero(mask)]
    protected = rows(sel & (gb < policy['protected_before_geh']) & (ga >= policy['protected_after_hard_geh']))
    single = rows(sel & (inc > policy['max_single_row_geh_increase'] + EPS))
    high = rows(sel & (ga > policy['high_geh_threshold'] + EPS) & (inc > policy['max_high_geh_increase'] + EPS))
    sb = severity(b, y); sa = severity(a, y)
    budget = policy['scope_budgets'][scope]
    s20 = relative_degradation(sb['severity20'], sa['severity20'])
    s30 = relative_degradation(sb['severity30'], sa['severity30'])
    g40 = max(0, sa['geh_ge40'] - sb['geh_ge40'])
    reasons = []
    if len(protected) > int(policy['max_protected_catastrophic']):
        reasons.append('PROTECTED_CORDON_ROW_GUARD_FAILED')
    if single:
        reasons.append('SINGLE_CORDON_ROW_GEH_INCREASE_EXCEEDED')
    if high:
        reasons.append('HIGH_GEH_CORDON_ROW_DELTA_BUDGET_EXCEEDED')
    if s20 > float(budget['max_severity20_relative_degradation']) + EPS:
        reasons.append('CORDON_SEVERITY20_BUDGET_EXCEEDED')
    if s30 > float(budget['max_severity30_relative_degradation']) + EPS:
        reasons.append('CORDON_SEVERITY30_BUDGET_EXCEEDED')
    if g40 > int(budget['max_geh40_net_count_increase']):
        reasons.append('CORDON_GEH40_NET_COUNT_BUDGET_EXCEEDED')
    out.update(passes=not reasons, reasons=reasons, status='EVALUATED',
               protected_rows_to_hard=protected, single_row_violations=single, high_geh_delta_violations=high,
               before_severity=sb, after_severity=sa,
               severity20_relative_degradation=None if math.isinf(s20) else s20,
               severity30_relative_degradation=None if math.isinf(s30) else s30,
               severity20_degradation_infinite=math.isinf(s20), severity30_degradation_infinite=math.isinf(s30),
               geh40_net_count_increase=int(g40), budget=dict(budget),
               limits={k: policy[k] for k in ('protected_before_geh', 'protected_after_hard_geh',
                                              'max_single_row_geh_increase', 'high_geh_threshold',
                                              'max_high_geh_increase')},
               max_row_geh_increase=float(inc[sel].max()) if np.any(sel) else 0.0)
    return out


def gate(before_diag, after_diag, block, method, policy):
    """Guard of one block transition on cordon diagnostics (measured or predicted)."""
    mb = before_diag['methods'][method]; ma = after_diag['methods'][method]
    observed = mb.get('observed')
    if observed is None:
        observed = before_diag['_terms'][method]['y']
    labels = ['%s-%s' % tuple(p) for p in mb.get('pairs', [])] or None
    return evaluate(mb['model'], ma['model'], observed, labels, block, policy)
