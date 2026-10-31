"""Cordon diagnostics from the CURRENT Visum assignment (replaces profile 12D/11D).

Every evaluation re-runs the unchanged LIVE01 preflight and the original LEGACY
saved-path capture (per-OD path/matrix parity, geometry), rebuilds incidence and
aggregates the whole 16x16 RPDI matrix into 120 unordered pairs for both
enumeration methods.  The objective is exactly the cordon data term minimized
by FISTA: 0.5*sum((w*deadzone(m-y, eps))**2) with w = weight/sqrt(max(1,y)).
"""
from __future__ import annotations
import hashlib
import struct
from pathlib import Path
import numpy as np
from .common import ROOT, require, canonical_hash, parent_module, ContractError
from .io import write_json, write_csv, mkdir, exception_text
from .visum_startup import preflight, capture, _new_list, _bounded_rows, retry_policy
from .incidence import build_from_snapshot
from .live01_observations import aggregate_whole
from .optimizer import build_problem, deadzone
from .authority import mapping
from .live02_config import METHODS

SCHEMA = 'LIVE02_CORDON_DIAGNOSTIC_V1'
CANDIDATE_CAPTURE_FAILURES = ('PER_OD_PATH_MATRIX_PARITY_FAIL', 'NO_SAVED_PRT_PATHS_FOR_POSITIVE_DEMAND',
                              'PROOF_STORE_PER_OD_PARITY_FAIL')
INVALID_OBJECTIVE = 1.0e300


def objective_terms(inc, mathcfg):
    """Fixed objective constants of one method: the optimizer's own weights and deadband."""
    problem, selected, y, base, eps = build_problem(inc, mathcfg)
    n = len(inc.rows)
    require(n >= 120 and len(selected) == n and np.array_equal(selected, np.arange(n)), 'LIVE02_OBJECTIVE_MUST_USE_ALL_ROWS')
    return {'w': np.asarray(problem.row_weight, dtype=float), 'y': np.asarray(y, dtype=float),
            'eps': np.asarray(eps, dtype=float)}


def objective_from_model(terms, model):
    """J = 0.5*sum((w*deadzone(m-y,eps))**2) plus reporting metrics for a model vector."""
    w, y, eps = terms['w'], terms['y'], terms['eps']
    model = np.asarray(model, dtype=float)
    r = deadzone(model - y, eps)
    term = 0.5 * (w * r) ** 2
    total = float(np.sum(term))
    geh = np.sqrt(2.0 * (model - y) ** 2 / np.maximum(model + y, 1e-12))
    ss_res = float(np.sum((model - y) ** 2)); ss_tot = float(np.sum((y - y.mean()) ** 2))
    metrics = {'objective': total, 'pairs': int(len(y)), 'rmse': float(np.sqrt(np.mean((model - y) ** 2))),
               'r2': 1.0 - ss_res / ss_tot if ss_tot > 0 else None,
               'geh_mean': float(geh.mean()), 'geh_max': float(geh.max()),
               'geh_le_5_share': float(np.mean(geh <= 5)), 'geh_le_10_share': float(np.mean(geh <= 10)),
               'model_total': float(model.sum()), 'observed_total': float(y.sum()),
               'model_obs_ratio': float(model.sum() / y.sum()) if y.sum() > 0 else None}
    return total, term, geh, metrics


def objective(inc, mathcfg):
    """Return (J, rows, metrics) for the current assignment of one method."""
    terms = objective_terms(inc, mathcfg)
    model = np.asarray(inc.model, dtype=float)
    total, term, geh, metrics = objective_from_model(terms, model)
    y, w, eps = terms['y'], terms['w'], terms['eps']
    rows = []
    for i, row in enumerate(inc.rows):
        rows.append({'origin_station': row['origin_station'], 'destination_station': row['destination_station'],
                     'observed': float(y[i]), 'model': float(model[i]), 'residual': float(model[i] - y[i]),
                     'weight': float(w[i]), 'epsilon_abs': float(eps[i]), 'objective_term': float(term[i]),
                     'geh': float(geh[i]), 'fixed': float(inc.fixed[i]), 'mutable': float(inc.mutable[i])})
    return total, rows, metrics


def _settings(opt):
    two = parent_module('r1_15a2_two_mode_v238')
    return dict(two.DEFAULT_SETTINGS, page_size=opt['page_size'], min_free_disk_gib=opt['min_free_disk_gib'],
                max_store_gib=opt['max_store_gib'] or 1024., max_parent_rows_per_dseg=opt['max_parent_rows_per_dseg'],
                max_geometry_rows_per_mode=opt['max_geometry_rows_per_mode'], com_retry_policy=retry_policy(opt))


def path_volume_signature(visum, dsegs, control, opt):
    """Same keys+Vol(AP) digest as the original capture FINAL_PATH_READBACK."""
    two = parent_module('r1_15a2_two_mode_v238'); com = parent_module('r1_15a2_com_compat')
    st = _settings(opt); out = {}
    for ds in dsegs:
        obj = _new_list(visum, 'CreatePrTPathList', ds['code'], control, opt)
        returned = {}
        for row in _bounded_rows(obj, two.PARENT_COLUMNS, st, control, opt, 'LIVE02_PATH_SIGNATURE', dseg=ds['code']):
            key = tuple(com.exact_int(v, 'path key') for v in row[:3]); vol = com.finite_float(row[3], 'Vol(AP)')
            require(key not in returned and vol >= 0, 'LIVE02_SIGNATURE_PATH_KEYS_OR_VOLUMES_INVALID')
            returned[key] = vol
        h = hashlib.sha256()
        for key, vol in sorted(returned.items()):
            h.update(struct.pack('<IIId', *key, vol))
        out[ds['norm_code']] = {'paths': len(returned), 'volume_sum': float(sum(returned.values())),
                                'keys_and_volumes_sha256': h.hexdigest()}
    return out


class CordonEvaluator:
    def __init__(self, live02, mathcfg, cells, opt, control, baseline_pre):
        self.live02 = live02; self.mathcfg = mathcfg; self.cells = cells; self.opt = opt
        self.control = control; self.baseline_pre = baseline_pre
        self.station_map, _ = mapping(ROOT / 'data/audited/STATION_MAPPING.csv')
        self.method = live02['acceptance']['method']; self.secondary = live02['acceptance']['secondary_method']
        self.decimals = live02['acceptance']['diagnostic_hash_decimals']
        self.count = 0
        self.observed_hash = None
        self.methods = tuple(METHODS)
        self.build_incidence = build_from_snapshot
        self.extra_mathcfg = {}

    # LIVE03 hook: per-method observation aggregation (LIVE02: whole RPDI ALL matrix).
    def aggregate_method(self, directed, method):
        return aggregate_whole(directed, self.cells)

    def on_incidence(self, diag, directed, aggregated):
        return None

    # ---------------------------------------------------------------- capture
    def evaluate(self, visum, folder, label, *, full_geometry=True, keep_db=True):
        folder = Path(folder); mkdir(folder)
        self.count += 1
        opt = dict(self.opt, full_geometry_check=bool(full_geometry))
        self.control.checkpoint('LIVE02_EVALUATE_' + str(label), force=True)
        pre = preflight(visum, self.mathcfg, folder, self.control, opt)
        require(pre[2] == self.baseline_pre[2] and pre[0]['network_sha256'] == self.baseline_pre[0]['network_sha256'],
                'LIVE02_NETWORK_OR_ZONE_AXIS_CHANGED')
        require(str(pre[1]) == str(self.baseline_pre[1]), 'LIVE02_CURRENT_VERSION_POINTER_CHANGED')
        cache, epath = capture(visum, self.mathcfg, folder, self.control, opt, pre)
        from .io import read_json
        evidence = read_json(epath)
        directed = self.build_incidence(cache, self.station_map, dict(self.mathcfg, **self.extra_mathcfg, actual_network_sha256=pre[0]['network_sha256'],
                                       actual_demand_sha256=evidence['demand_sha256']), evidence,
                                       hits_output=folder / 'STATION_HITS.csv')
        require(set(directed) == set(self.methods), 'LIVE02_ENUMERATION_METHODS_CHANGED')
        signature = path_volume_signature(visum, pre[4], self.control, opt)
        methods = {}; incidence = {}; pair_rows = []; native_cl = {}; terms_by_method = {}
        for method in self.methods:
            cl = {}
            for r in directed[method].rows:
                a, b = sorted((int(r['origin_station']), int(r['destination_station'])))
                key = a * 100 + b
                cl[key] = cl.get(key, 0.0) + float((r.get('per_dseg') or {}).get('NATIVE_CL', 0.0))
            native_cl[method] = cl
            inc, trace, roster = self.aggregate_method(directed[method], method)
            total, rows, metrics = objective(inc, self.mathcfg)
            methods[method] = {'objective': total, 'metrics': metrics,
                               'model': [r['model'] for r in rows], 'observed': [r['observed'] for r in rows],
                               'pairs': [[r['origin_station'], r['destination_station']] for r in rows],
                               'roster': roster}
            incidence[method] = inc
            terms_by_method[method] = objective_terms(inc, self.mathcfg)
            pair_rows.extend(dict(r, method=method, label=label) for r in rows)
        obs = canonical_hash({m: methods[m]['observed'] for m in self.methods})
        if self.observed_hash is None:
            self.observed_hash = obs
        require(obs == self.observed_hash, 'LIVE02_OBSERVATION_AUTHORITY_CHANGED')
        diag = {'schema': SCHEMA, 'label': str(label), 'valid': True, 'methods': methods,
                'acceptance_method': self.method, 'secondary_method': self.secondary,
                'network_sha256': pre[0]['network_sha256'], 'demand_sha256': evidence['demand_sha256'],
                'matrix_audit': pre[0]['matrix_audit'], 'path_signature': signature,
                'capture_cache_sha256': evidence['cache_sha256'], 'folder': str(folder),
                'full_geometry_check': bool(full_geometry), 'observed_hash': obs,
                'native_cl_pair_volume': native_cl,
                'source': 'FRESH_LEGACY_CAPTURE_OF_CURRENT_ASSIGNMENT'}
        diag['diagnostic_hash'] = self.diagnostic_hash(diag)
        write_json(folder / 'CORDON_DIAGNOSTIC.json', diag)
        write_csv(folder / 'CORDON_PAIR_RESULTS.csv', pair_rows)
        diag['_incidence'] = incidence
        diag['_terms'] = terms_by_method
        diag['_pre'] = pre
        self.on_incidence(diag, directed, incidence)
        if not keep_db:
            for p in (folder / 'p.sqlite', folder / 'p.sqlite-wal', folder / 'p.sqlite-journal'):
                try:
                    if p.exists(): p.unlink()
                except OSError:
                    pass
            import shutil
            shutil.rmtree(folder / 'matrix_authority', ignore_errors=True)
            diag['capture_db_retained'] = False
        return diag

    def evaluate_candidate(self, visum, folder, label, *, full_geometry, keep_db):
        """AFTER/ADOPTED: capture parity failures are a candidate property."""
        try:
            return self.evaluate(visum, folder, label, full_geometry=full_geometry, keep_db=keep_db)
        except ContractError as exc:
            text = exception_text(exc)
            policy = self.live02['acceptance']['candidate_capture_failure_policy']
            if str(label) not in ('AFTER', 'STEP1_TRIAL') or policy != 'REJECT_CANDIDATE_AFTER_VERIFIED_ROLLBACK' or \
                    not any(token in text for token in CANDIDATE_CAPTURE_FAILURES):
                raise
            diag = {'schema': SCHEMA, 'label': str(label), 'valid': False, 'invalid_reason': text,
                    'methods': {m: {'objective': INVALID_OBJECTIVE} for m in self.methods},
                    'acceptance_method': self.method, 'secondary_method': self.secondary,
                    'source': 'CANDIDATE_CAPTURE_REJECTED'}
            diag['diagnostic_hash'] = self.diagnostic_hash(diag)
            write_json(Path(folder) / 'CORDON_DIAGNOSTIC.json', diag)
            return diag

    # ------------------------------------------------------- donor interfaces
    def _vector(self, values):
        if self.decimals is None:
            return [float(v) for v in values]
        return [round(float(v), self.decimals) for v in values]

    def diagnostic_hash(self, diag):
        if not diag.get('valid', True):
            return canonical_hash({'invalid': diag.get('invalid_reason'), 'label': diag.get('label')})
        return canonical_hash({'schema': SCHEMA, 'observed_hash': diag['observed_hash'],
                               'model': {m: self._vector(diag['methods'][m]['model']) for m in self.methods},
                               'demand_sha256': diag['demand_sha256'], 'network_sha256': diag['network_sha256']})

    def ledger(self, diag, state, anchors, policy, reference, cfg):
        """Donor ledger signature; 'total' is the acceptance-method objective."""
        if diag.get('valid', True):
            require(diag['observed_hash'] == reference['observed_hash'], 'LIVE02_OBSERVATION_AUTHORITY_CHANGED')
        total = float(diag['methods'][self.method]['objective'])
        out = {'schema': 'LIVE02_CORDON_LEDGER_V1', 'total': total, 'method': self.method,
               'objective_by_method': {m: float(diag['methods'][m]['objective']) for m in self.methods},
               'valid': bool(diag.get('valid', True)),
               'state_hash': state.get('state_hash') if isinstance(state, dict) else None}
        if diag.get('valid', True):
            out['metrics'] = {m: diag['methods'][m]['metrics'] for m in self.methods}
        return out

    def reference(self, diag):
        return {'schema': 'LIVE02_CORDON_REFERENCE_V1', 'observed_hash': diag['observed_hash'],
                'baseline_objective': {m: diag['methods'][m]['objective'] for m in self.methods},
                'method': self.method}

    def authorized_blocks(self):
        return ('GENERATION',)

    def block_gate(self, block, before, after, rows):
        acc = self.live02['acceptance']
        reasons = []
        decision = {'schema': 'LIVE02_CORDON_ACCEPTANCE_V1', 'block': block, 'method': self.method,
                    'secondary_method': self.secondary}
        if block not in self.authorized_blocks():
            reasons.append('LIVE02_ONLY_GENERATION_BLOCK_AUTHORIZED')
        if not after.get('valid', True):
            reasons.append('CANDIDATE_CAPTURE_INVALID:' + str(after.get('invalid_reason', ''))[:200])
        else:
            j0 = float(before['methods'][self.method]['objective']); j1 = float(after['methods'][self.method]['objective'])
            rel = (j0 - j1) / max(abs(j0), 1e-12)
            decision.update(objective_before=j0, objective_after=j1, relative_improvement=rel,
                            absolute_improvement=j0 - j1)
            if not (j0 - j1 > float(acc['minimum_absolute_improvement'])):
                reasons.append('CORDON_OBJECTIVE_NOT_IMPROVED')
            elif rel < float(acc['min_relative_improvement']):
                reasons.append('CORDON_RELATIVE_IMPROVEMENT_BELOW_MINIMUM')
            if self.secondary:
                s0 = float(before['methods'][self.secondary]['objective']); s1 = float(after['methods'][self.secondary]['objective'])
                srel = (s1 - s0) / max(abs(s0), 1e-12)
                decision.update(secondary_before=s0, secondary_after=s1, secondary_relative_degradation=srel)
                if srel > float(acc['secondary_max_relative_degradation']):
                    reasons.append('SECONDARY_METHOD_DEGRADED')
            decision['metrics_before'] = before['methods'][self.method]['metrics']
            decision['metrics_after'] = after['methods'][self.method]['metrics']
        decision['rows'] = len(rows or [])
        decision['reasons'] = reasons
        decision['accepted'] = not reasons
        decision['authority'] = 'FRESH_VISUM_ASSIGNMENT_PLUS_FULL_CORDON_CAPTURE'
        return decision
