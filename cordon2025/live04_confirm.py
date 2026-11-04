"""LIVE04.7.1 - no candidate is accepted on an accelerated capture.

The accelerated trial captures (LIVE04.6 station-link cross-check, LIVE04.7 geometry
epoch) prove link VOLUMES, not path identity.  Link volumes do not identify the
cordon FIRST_LAST matrix: paths 1->2 and 3->4 give exactly the same station (and
even all-link) volumes as 1->4 and 3->2 when they share links, but a different
FIRST_LAST matrix.  Therefore an accelerated capture may only REJECT a candidate
(or steer the search).  Before a candidate is accepted, an independent full
capture of the same assignment state is taken: every DSeg's complete path-link
hierarchy is read from Visum (no epoch, full same-mode proof), the cordon rows
are rebuilt from it and the acceptance decision is taken again ON THE FULL
CAPTURE.  The accelerated rows are only compared and reported.
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
from .common import require
from .io import write_json

FULL_BASIS = 'FULL_SAME_MODE_GEOMETRY_COMPARED_THIS_CAPTURE'
CONFIRM_LABEL = 'ACCEPTANCE_CONFIRM'


def is_fully_proven(diag):
    return diag.get('geometry_identity_basis', FULL_BASIS) == FULL_BASIS and bool(diag.get('full_geometry_check', True))


def compare_rows(fast, full, methods):
    out = {'identical': True, 'methods': {}}
    for m in methods:
        a = np.asarray(fast['methods'][m]['model'], dtype=float)
        b = np.asarray(full['methods'][m]['model'], dtype=float)
        same = a.shape == b.shape and np.array_equal(a, b)
        diff = float(np.max(np.abs(a - b))) if a.shape == b.shape and a.size else (0.0 if same else float('inf'))
        out['methods'][m] = {'identical': bool(same), 'max_abs_row_difference': diff,
                             'objective_fast': float(fast['methods'][m]['objective']),
                             'objective_full': float(full['methods'][m]['objective'])}
        out['identical'] = out['identical'] and same
    return out


def confirm_before_accept(adapter, folder, fast_diag, after_snapshot, decide, accepted_fast):
    """Return (diag, after_value, decision, audit) for the final decision.

    ``decide(diag) -> (after_value, decision)`` is the block's complete acceptance
    logic.  Called only when the decision on ``fast_diag`` is to accept.
    """
    folder = Path(folder)
    if is_fully_proven(fast_diag) or not fast_diag.get('valid', True):
        return fast_diag, None, None, {'status': 'NOT_REQUIRED_FULL_GEOMETRY_CAPTURE'}
    full = adapter.evaluator.evaluate(adapter.raw_visum, folder, CONFIRM_LABEL, full_geometry=True, keep_db=True,
                                      geometry_proof='FULL')
    require(adapter.snapshot() == after_snapshot, 'ACCEPTANCE_CONFIRM_CHANGED_MODEL')
    require(full.get('geometry_identity_basis', FULL_BASIS) == FULL_BASIS, 'ACCEPTANCE_CONFIRM_NOT_FULL')
    cmp = compare_rows(fast_diag, full, adapter.evaluator.methods)
    after_value, decision = decide(full)
    audit = {'schema': 'LIVE04_ACCEPTANCE_CONFIRM_V1', 'status': 'CONFIRMED' if decision.get('accepted') else
             'REJECTED_ON_FULL_CAPTURE', 'fast_geometry_basis': fast_diag.get('geometry_identity_basis'),
             'full_geometry_basis': full.get('geometry_identity_basis'), 'rows': cmp,
             'fast_decision_accepted': bool(accepted_fast), 'full_decision_accepted': bool(decision.get('accepted')),
             'decision_basis': 'FULL_CAPTURE', 'full_capture_folder': str(folder)}
    decision['acceptance_confirm'] = {k: audit[k] for k in ('status', 'fast_geometry_basis', 'decision_basis')}
    decision['acceptance_confirm']['rows_identical'] = cmp['identical']
    write_json(folder.parent / 'ACCEPTANCE_CONFIRM.json', audit)
    return full, after_value, decision, audit
