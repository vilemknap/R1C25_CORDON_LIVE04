"""LIVE04.13 IDP run reference: cumulative FineCDF protection for GENERATION and TD_CORDON.

User decision 2026-11-19.  The local IDP guard compares a candidate with its block
parent; small accepted degradations could therefore add up over many cycles.  The
run reference is the MEASURED FineCDF v1.9 state of the model at the start of a new
run (it is not the IDP target curve).  It is captured once, stored in RUN_ANCHORS.json
and carried unchanged by every continuation; a continuation without a verifiable
reference stops instead of silently re-capturing the current model.

Per guarded component k (no mean-error floor):

    RMSE_k(new)  <= RMSE_k(start) + cumulative fine_cdf_rmse_degradation      (0.01)
    |e_k(new)|   <= |e_k(start)|  + cumulative mean_relative_error_degradation (0.02)

with e_k the relative mean-distance error (model - IDP) / IDP.  An improvement in one
component never compensates another.  The local guard (with its mean_error_floor) is
unchanged; a candidate must pass both.  Read-only: no COM write.
"""
from __future__ import annotations
import copy
import hashlib
import numpy as np
from .common import require, canonical_hash

SCHEMA = 'LIVE04_IDP_RUN_REFERENCE_V1'
POLICY = 'RUN_START_MEASURED_IDP_IMMUTABLE_PER_COMPONENT_NO_FLOOR'
BLOCKS = ('GENERATION', 'TD_CORDON')
TOLERANCE_KEYS = ('fine_cdf_rmse_degradation', 'mean_relative_error_degradation', 'mean_error_floor')


def policy(idp_cfg):
    """The validated cumulative section of idp_guard (None when disabled)."""
    c = (idp_cfg or {}).get('cumulative')
    if not c or not c.get('enabled'):
        return None
    return c


def validate(idp_cfg):
    c = (idp_cfg or {}).get('cumulative')
    require(isinstance(c, dict), 'LIVE04_IDP_CUMULATIVE_MISSING')
    require(set(c) - {'note'} == {'enabled', 'blocks', 'reference'} | set(TOLERANCE_KEYS),
            'LIVE04_IDP_CUMULATIVE_FIELDS')
    require(isinstance(c['enabled'], bool), 'LIVE04_IDP_CUMULATIVE_ENABLED')
    require(c['reference'] == POLICY, 'LIVE04_IDP_CUMULATIVE_REFERENCE_POLICY')
    require(isinstance(c['blocks'], list) and c['blocks'] and set(c['blocks']) <= set(BLOCKS)
            and len(set(c['blocks'])) == len(c['blocks']), 'LIVE04_IDP_CUMULATIVE_BLOCKS')
    for key in TOLERANCE_KEYS:
        v = c[key]
        require(isinstance(v, (int, float)) and not isinstance(v, bool) and 0.0 <= float(v) <= 1.0,
                'LIVE04_IDP_CUMULATIVE_TOLERANCE:' + key)
    require(not c['enabled'] or idp_cfg.get('enabled') is True, 'LIVE04_IDP_CUMULATIVE_NEEDS_IDP_GUARD')
    # The cumulative check runs on the IDP evaluation of the local guard of the same block.
    require(not c['enabled'] or set(c['blocks']) <= set(idp_cfg.get('blocks') or []),
            'LIVE04_IDP_CUMULATIVE_BLOCK_WITHOUT_LOCAL_GUARD')
    validate_prediction(idp_cfg)
    return c


def _tolerances(c):
    return {k: float(c[k]) for k in TOLERANCE_KEYS}


def matrices_sha256(guard):
    """Identity of the person matrices the reference was measured on (audit; read-only)."""
    from .live03_idp import _read
    h = hashlib.sha256()
    for no in guard.matrix_nos:
        arr = _read(guard.visum, no, guard.n)
        h.update(str(int(no)).encode('ascii'))
        h.update(np.ascontiguousarray(arr, dtype='<f8').tobytes())
    return h.hexdigest()


def capture(guard, idp_cfg, measured, state_hash, run_folder):
    """Record of the run-start IDP metrics (fresh run only)."""
    from .live03_idp import REFERENCE_SHA256, REFERENCE_ID
    c = policy(idp_cfg)
    require(c is not None, 'LIVE04_IDP_CUMULATIVE_DISABLED')
    missing = [k for k in guard.guarded if k not in measured or 'fine_cdf_rmse' not in measured[k]]
    require(not missing, 'LIVE04_IDP_RUN_REFERENCE_INCOMPLETE:' + ','.join(missing))
    comps = {k: {'fine_cdf_rmse': float(measured[k]['fine_cdf_rmse']),
                 'mean_relative_error': float(measured[k]['mean_relative_error']),
                 'mean_model_km': float(measured[k]['mean_model_km']),
                 'mean_target_km': float(measured[k]['mean_target_km'])} for k in guard.guarded}
    for k, r in comps.items():
        require(all(np.isfinite(v) for v in r.values()), 'LIVE04_IDP_RUN_REFERENCE_NONFINITE:' + k)
    rec = {'schema': SCHEMA, 'policy': POLICY, 'finecdf_reference_sha256': REFERENCE_SHA256,
           'finecdf_reference_id': REFERENCE_ID, 'components': comps, 'guarded': list(guard.guarded),
           'distance_matrix_by_component': dict(guard.distance_by_component),
           'distance_sha256': {str(k): v for k, v in sorted(guard.fixed_distance_hashes.items())},
           'matrix_nos': list(guard.matrix_nos), 'input_matrices_sha256': matrices_sha256(guard),
           'state_hash': state_hash, 'origin_run_folder': str(run_folder), 'tolerances': _tolerances(c),
           'blocks': list(c['blocks'])}
    rec['record_sha256'] = canonical_hash(rec)
    return rec


class RunReference:
    """Immutable run reference; decide() is the cumulative IDP check."""

    def __init__(self, record):
        require(isinstance(record, dict) and record.get('schema') == SCHEMA and record.get('policy') == POLICY,
                'LIVE04_IDP_RUN_REFERENCE_SCHEMA')
        body = {k: v for k, v in record.items() if k != 'record_sha256'}
        require(record.get('record_sha256') == canonical_hash(body), 'LIVE04_IDP_RUN_REFERENCE_RECORD_CHANGED')
        self.record = copy.deepcopy(record)
        self.components = self.record['components']
        self.guarded = list(self.record['guarded'])
        self.tol = dict(self.record['tolerances'])
        self.blocks = tuple(self.record['blocks'])

    def verify(self, guard, idp_cfg):
        """The reference must describe THIS evaluation: same FineCDF, distances, components, policy."""
        from .live03_idp import REFERENCE_SHA256
        r = self.record
        c = policy(idp_cfg)
        checks = {
            'FINECDF_REFERENCE': r['finecdf_reference_sha256'] == REFERENCE_SHA256,
            'COMPONENTS': self.guarded == list(guard.guarded) and set(self.components) == set(guard.guarded),
            'DISTANCE_MAP': r['distance_matrix_by_component'] == dict(guard.distance_by_component),
            'DISTANCE_SHA256': r['distance_sha256'] == {str(k): v for k, v in sorted(guard.fixed_distance_hashes.items())},
            'MATRIX_NOS': list(r['matrix_nos']) == list(guard.matrix_nos),
            'TOLERANCES': c is not None and self.tol == _tolerances(c),
            'BLOCKS': c is not None and list(self.blocks) == list(c['blocks']),
        }
        bad = sorted(k for k, ok in checks.items() if not ok)
        require(not bad, 'LIVE04_IDP_RUN_REFERENCE_MISMATCH:' + ','.join(bad))
        return {'schema': SCHEMA + '_VERIFY', 'passes': True, 'checks': checks,
                'record_sha256': r['record_sha256'], 'origin_run_folder': r['origin_run_folder']}

    def applies(self, block):
        return str(block).upper() in self.blocks

    def decide(self, after):
        if after is None or 'error' in after:
            return {'schema': SCHEMA + '_DECISION', 'passes': False,
                    'reasons': ['IDP_CUMULATIVE_EVALUATION_FAILED:' + str((after or {}).get('error'))]}
        rows, reasons = [], []
        floor = self.tol['mean_error_floor']
        for k in self.guarded:
            s = self.components[k]
            if k not in after or 'fine_cdf_rmse' not in after[k]:
                reasons.append('IDP_CUMULATIVE_COMPONENT_MISSING:' + k)
                continue
            a = after[k]
            rmse_allowed = s['fine_cdf_rmse'] + self.tol['fine_cdf_rmse_degradation']
            mean_allowed = max(abs(s['mean_relative_error']), floor) + self.tol['mean_relative_error_degradation']
            ok_rmse = float(a['fine_cdf_rmse']) <= rmse_allowed
            ok_mean = abs(float(a['mean_relative_error'])) <= mean_allowed
            rows.append({'component': k, 'rmse_start': s['fine_cdf_rmse'], 'rmse_after': float(a['fine_cdf_rmse']),
                         'rmse_allowed': rmse_allowed, 'mean_rel_start': s['mean_relative_error'],
                         'mean_rel_after': float(a['mean_relative_error']), 'mean_rel_allowed_abs': mean_allowed,
                         'mean_model_km_after': a.get('mean_model_km'), 'passes': ok_rmse and ok_mean})
            if not ok_rmse:
                reasons.append('IDP_CUMULATIVE_FINE_CDF_RMSE_DEGRADED:' + k)
            if not ok_mean:
                reasons.append('IDP_CUMULATIVE_MEAN_DISTANCE_DEGRADED:' + k)
        return {'schema': SCHEMA + '_DECISION', 'passes': not reasons, 'reasons': reasons, 'components': rows,
                'record_sha256': self.record['record_sha256'], 'policy': POLICY, 'tolerances': dict(self.tol)}


def combine(local, cumulative):
    """Both must pass; reasons of both are kept (local first)."""
    parts = {}
    if local is not None:
        parts['local'] = local
    if cumulative is not None:
        parts['cumulative'] = cumulative
    reasons = [r for d in parts.values() for r in (d.get('reasons') or [])]
    out = dict(local or {})
    out.update(passes=all(d.get('passes') for d in parts.values()), reasons=reasons)
    if cumulative is not None:
        out['cumulative'] = cumulative
    return out


def component_summary(measured):
    """Per-component FineCDF RMSE and mean distance for the trial records."""
    if measured is None or 'error' in measured:
        return {'error': (measured or {}).get('error', 'NOT_EVALUATED')}
    return {k: {'fine_cdf_rmse': v.get('fine_cdf_rmse'), 'mean_model_km': v.get('mean_model_km'),
                'mean_target_km': v.get('mean_target_km'), 'mean_relative_error': v.get('mean_relative_error')}
            for k, v in measured.items()}


def establish(adapter, idp_cfg, anchors, *, continuation, state_hash, folder, write_json):
    """Fresh run: capture and put into the anchors.  Continuation: carried record, verified.

    Returns the RunReference (also set as adapter.idp_run_reference) or None when disabled."""
    from .live03_idp import IdpGuard
    c = policy(idp_cfg)
    adapter.idp_run_reference = None
    if c is None:
        return None
    guard = IdpGuard(adapter.visum, len(adapter.zones), idp_cfg)
    if continuation:
        record = anchors.get('idp_run_reference')
        require(record is not None, 'LIVE04_IDP_RUN_REFERENCE_MISSING_IN_CONTINUATION')
        ref = RunReference(record)
        audit = ref.verify(guard, idp_cfg)
        audit['source'] = 'CARRIED_FROM_ORIGIN_RUN'
    else:
        measured = guard.evaluate('RUN_REFERENCE')
        record = capture(guard, idp_cfg, measured, state_hash, folder)
        ref = RunReference(record)
        audit = ref.verify(guard, idp_cfg)
        audit['source'] = 'MEASURED_AT_RUN_START'
        anchors['idp_run_reference'] = record
    write_json(folder / 'IDP_RUN_REFERENCE.json', dict(ref.record, verification=audit))
    adapter.idp_run_reference = ref
    return ref


# ------------------------------------------------------------------ LIVE04.14 stage B
PRED_FIELDS = {'enabled', 'slack_use', 'min_direction_norm'}


def validate_prediction(idp_cfg):
    p = (idp_cfg or {}).get('generation_prediction')
    require(isinstance(p, dict) and set(p) - {'note'} == PRED_FIELDS and isinstance(p['enabled'], bool),
            'LIVE04_IDP_GENERATION_PREDICTION_FIELDS')
    require(isinstance(p['slack_use'], (int, float)) and 0.0 < float(p['slack_use']) <= 1.0,
            'LIVE04_IDP_GENERATION_PREDICTION_SLACK')
    require(isinstance(p['min_direction_norm'], (int, float)) and float(p['min_direction_norm']) >= 0.0,
            'LIVE04_IDP_GENERATION_PREDICTION_NORM')
    return p


def direction(rows):
    """Low-dimensional GENERATION direction: mean log step per family x role (scale 1)."""
    acc = {}
    for r in rows or []:
        key = '%s|%s' % (r.get('family'), r.get('role'))
        acc.setdefault(key, []).append(float(r.get('log_step', 0.0) or 0.0))
    return {k: float(np.mean(v)) for k, v in sorted(acc.items())}


class GenerationIdpModel:
    """Stage B: IDP features (RMSE_k, e_k) as a linear function of the low-dimensional GENERATION
    direction, learned by Broyden updates from measured trials; used ONLY to cap the trial scale
    so that the predicted IDP stays inside slack_use x the remaining local and cumulative slack.
    Never accepts anything - the measured IDP guard decides."""

    def __init__(self, components, cfg):
        self.components = list(components)
        self.cfg = dict(cfg)
        self.keys = []          # direction keys
        self.J = None           # features x keys
        self.updates = 0

    def features(self, idp):
        return np.array([float(idp[k]['fine_cdf_rmse']) for k in self.components]
                        + [float(idp[k]['mean_relative_error']) for k in self.components])

    def _vector(self, d):
        for k in d:
            if k not in self.keys:
                self.keys.append(k)
                if self.J is not None:
                    self.J = np.hstack([self.J, np.zeros((self.J.shape[0], 1))])
        return np.array([float(d.get(k, 0.0)) for k in self.keys])

    def update(self, d, scale, idp_before, idp_after):
        if idp_before is None or idp_after is None or 'error' in idp_before or 'error' in idp_after:
            return {'status': 'NO_MEASUREMENT'}
        a = float(scale) * self._vector(d)
        if float(np.linalg.norm(a)) <= float(self.cfg.get('min_direction_norm', 0.0)) or not a.any():
            return {'status': 'NO_DIRECTION'}
        df = self.features(idp_after) - self.features(idp_before)
        if self.J is None:
            self.J = np.zeros((len(df), len(a)))
        err_before = float(np.linalg.norm(df - self.J @ a))
        self.J = self.J + np.outer(df - self.J @ a, a) / float(a @ a)
        self.updates += 1
        return {'status': 'UPDATED', 'updates': self.updates, 'error_before': err_before,
                'error_after': float(np.linalg.norm(df - self.J @ a))}

    def max_scale(self, d, idp_now, idp_parent, run_reference, local_cfg):
        """Largest scale with predicted IDP inside slack_use x min(local, cumulative) slack."""
        if self.J is None or not self.updates or idp_now is None or 'error' in idp_now:
            return None, {'status': 'NO_MODEL'}
        a = self._vector(d)
        if not a.any():
            return None, {'status': 'NO_DIRECTION'}
        pred = self.J @ a                                   # change per unit scale
        n = len(self.components)
        use = float(self.cfg['slack_use'])
        rmse_tol = float(local_cfg['max_fine_cdf_rmse_degradation'])
        floor = float(local_cfg['mean_error_floor']); mean_tol = float(local_cfg['max_mean_error_degradation'])
        caps, rows = [], []
        for i, k in enumerate(self.components):
            now = idp_now[k]; par = idp_parent[k]
            slack_r = float(par['fine_cdf_rmse']) + rmse_tol - float(now['fine_cdf_rmse'])
            e = float(now['mean_relative_error'])
            slack_m = max(abs(float(par['mean_relative_error'])), floor) + mean_tol - abs(e)
            if run_reference is not None and k in run_reference.components:
                s = run_reference.components[k]
                slack_r = min(slack_r, s['fine_cdf_rmse'] + run_reference.tol['fine_cdf_rmse_degradation']
                              - float(now['fine_cdf_rmse']))
                slack_m = min(slack_m, max(abs(s['mean_relative_error']), run_reference.tol['mean_error_floor'])
                              + run_reference.tol['mean_relative_error_degradation'] - abs(e))
            dr = float(pred[i]); dm = float(pred[n + i]) * (1.0 if e >= 0 else -1.0)   # d|e| ~ sign(e) de
            for name, slack, rate in (('RMSE', slack_r, dr), ('MEAN', slack_m, dm)):
                if rate > 1e-12:                         # numerical noise is not a degradation
                    cap = max(0.0, use * slack) / rate
                    caps.append(cap)
                    rows.append({'component': k, 'feature': name, 'slack': slack, 'rate_per_scale': rate, 'cap': cap})
        cap = min(caps) if caps else None
        return cap, {'status': 'CAPPED' if cap is not None else 'NO_PREDICTED_DEGRADATION', 'cap': cap,
                     'binding': min(rows, key=lambda r: r['cap']) if rows else None, 'updates': self.updates}
