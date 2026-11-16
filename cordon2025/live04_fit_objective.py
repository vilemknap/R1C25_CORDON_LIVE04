"""Use the captured acceptance objective in the zonal proposal and measured refit.

The donor assembles the OD effect operator and balance constraints unchanged.
Its profile GEH weights are replaced by the exact captured cordon row weights.
"""
from __future__ import annotations
import copy
import numpy as np
from .common import require, canonical_hash, parent_module

PARENT_ATOL = 1e-9
PARENT_RTOL = 1e-12


def parent_row_check(profile_rows, index, parent_model):
    """Detailed identity check with the existing same-capture tolerances."""
    rows, missing, duplicates, seen = [], [], [], set()
    values = np.asarray(parent_model, dtype=float)
    require(values.ndim == 1, 'V24917_REFIT_INVALID_MEASUREMENT')
    for row in profile_rows:
        key = int(row['countlocation_no'])
        if key in seen:
            duplicates.append(key)
        seen.add(key)
        pos = index.get(key)
        if not isinstance(pos, (int, np.integer)) or isinstance(pos, bool) or not 0 <= pos < len(values):
            missing.append(key)
            continue
        try:
            fit, parent = float(row['model']), float(values[pos])
            finite = bool(np.isfinite([fit, parent]).all())
        except (TypeError, ValueError):
            fit = parent = None; finite = False
        difference = abs(parent-fit) if finite else None
        # np.isclose(parent, fit, rtol=1e-12, atol=1e-9), as before.
        tolerance = PARENT_ATOL + PARENT_RTOL * abs(fit) if finite else None
        rows.append({'key': key, 'fit_model': fit if finite else None,
                     'parent_model': parent if finite else None, 'abs_difference': difference,
                     'allowed_difference': tolerance, 'outside': not finite or difference > tolerance,
                     'reason': 'NONFINITE_OR_INVALID_VALUE' if not finite else None})
    finite_rows = [r for r in rows if r['abs_difference'] is not None]
    worst = max(finite_rows, key=lambda r:r['abs_difference'], default=None)
    outside = [r for r in rows if r['outside']]
    return {'schema': 'LIVE04_REFIT_PARENT_ROW_CHECK_V2', 'atol': PARENT_ATOL, 'rtol': PARENT_RTOL,
            'policy': 'SAME_CAPTURED_PARENT_IDENTITY', 'rows': rows, 'rows_checked': len(rows),
            'rows_outside': len(outside), 'missing_keys': missing, 'duplicate_keys': duplicates,
            'rows_exact': sum(r['abs_difference'] == 0 for r in finite_rows),
            'max_abs_difference': worst['abs_difference'] if worst else 0.,
            'worst_key': worst['key'] if worst else None,
            'passes': bool(profile_rows) and not outside and not missing and not duplicates}


def check_parent_rows(profile_rows, index, parent_model, *, method, comparison, folder=None):
    audit = parent_row_check(profile_rows, index, parent_model)
    audit.update(method=method, comparison=comparison)
    if not audit['passes']:
        if folder is not None:
            from pathlib import Path
            from .io import write_json
            write_json(Path(folder) / 'MEASURED_ZONAL_REFIT_PARENT_MISMATCH.json', audit)
        raise ValueError('V24917_REFIT_PARENT_DIAGNOSTICS_MISMATCH:method=%s,comparison=%s,'
                         'rows_outside=%d,max_abs=%r,worst=%r,missing=%d,duplicates=%d'
                         % (method, comparison, audit['rows_outside'], audit['max_abs_difference'],
                            audit['worst_key'], len(audit['missing_keys']), len(audit['duplicate_keys'])))
    return audit


def row_ids(rows):
    ids = [int(r['countlocation_no']) for r in rows]
    require(len(ids) == len(set(ids)), 'LIVE04_FIT_DUPLICATE_OBSERVATION_ID')
    return ids


def captured_terms(diag, method):
    terms = (diag.get('_terms') or {}).get(method)
    require(terms is not None, 'LIVE04_FIT_ACCEPTANCE_TERMS_MISSING:' + method)
    inc = diag['_incidence'][method]
    out = validated_terms(terms, len(inc.rows))
    require(np.array_equal(out['y'], np.asarray([r['observed'] for r in inc.rows], dtype=float)),
            'LIVE04_FIT_ACCEPTANCE_TARGETS_CHANGED')
    return out


def validated_terms(terms, n):
    out = {k: np.asarray(terms[k], dtype=float) for k in ('w', 'y', 'eps')}
    require(all(v.shape == (n,) and np.isfinite(v).all() for v in out.values()),
            'LIVE04_FIT_ACCEPTANCE_TERMS_INVALID')
    require(np.all(out['w'] > 0) and np.all(out['y'] >= 0) and np.all(out['eps'] == 0),
            'LIVE04_FIT_REQUIRES_POSITIVE_WEIGHTS_AND_ZERO_DEADBAND')
    return out


def bind_objective(problem, profiles, terms, model):
    """Apply the same row target and weight used by objective_from_model."""
    row_ids(profiles)
    n = len(profiles)
    terms = validated_terms(terms, n)
    zf = parent_module('r1_15a2_zonal_count_fit_v24917')
    model = np.asarray(model, dtype=float)
    require(model.shape == (n,) and np.isfinite(model).all() and np.all(model >= 0),
            'LIVE04_FIT_INVALID_PARENT_MODEL')
    require(len(problem.profile_rows) == n and len(row_ids(problem.profile_rows)) == n,
            'LIVE04_FIT_ACCEPTANCE_ROSTER_INCOMPLETE')
    problem.profile_rows = [dict(row) for row in problem.profile_rows]
    source = {int(r['countlocation_no']): i for i, r in enumerate(profiles)}
    order = []
    for row in problem.profile_rows:
        key = int(row['countlocation_no'])
        require(key in source, 'LIVE04_FIT_UNKNOWN_OBSERVATION_ID')
        i = source[key]; order.append(i)
        obs, old = float(terms['y'][i]), float(model[i])
        row.update(observed=obs, model=old, residual=obs-old,
                   geh=zf.geh(old, obs),
                   weight=float(terms['w'][i]))
    order = np.asarray(order, dtype=int)
    problem.weight = np.array(terms['w'][order], copy=True)
    problem.target = np.array(terms['y'][order] - model[order], copy=True)
    problem.objective_weighting = {
        'schema': 'LIVE04_FIT_ACCEPTANCE_OBJECTIVE_V1',
        'authority': 'CAPTURED_CORDON_OBJECTIVE_TERMS', 'rows': n,
        'zero_observed_rows': int(np.sum(terms['y'] == 0)),
        'protected_residual_multiplier': 1.0,
        'row_ids_sha256': canonical_hash(row_ids(problem.profile_rows)),
        'weights_sha256': canonical_hash(problem.weight.tolist()),
        'parent_data_objective': float(0.5 * np.sum((problem.weight * problem.target)**2)),
        'native_acceptance_required': True}
    return problem


def build_problem(incidence, zones, bounds, cfg, terms, model):
    """Include zero-target rows without changing the protected donor builder."""
    zf = parent_module('r1_15a2_zonal_count_fit_v24917')
    profiles = copy.deepcopy(incidence['profiles'])
    require(len(profiles) == len(terms['y']), 'LIVE04_FIT_ACCEPTANCE_ROSTER_INCOMPLETE')
    for i, row in enumerate(profiles):
        require(str(row.get('role', '')).upper() == str(cfg.get('calibration_role', 'CALIBRATION')).upper(),
                'LIVE04_FIT_NONCALIBRATION_OBSERVATION')
        # Only lets the donor assemble this row. bind_objective restores the
        # original zero target before either solve or summary uses it.
        row.update(observed=max(float(terms['y'][i]), 1e-9), model=float(model[i]))
    local = dict(incidence, profiles=profiles)
    problem = zf.build_problem(local, zones, bounds, cfg)
    return bind_objective(problem, incidence['profiles'], terms, model)


def measured_vectors(before, after, method, *, parent_check_folder=None):
    """A model vector is valid only for the same ordered observation roster."""
    from .live02_v24917 import pair_key, observation_index
    inc = before['_incidence'][method]
    observation_index(inc.rows)
    expected = [pair_key(r['origin_station'], r['destination_station']) for r in inc.rows]
    require(('pairs' in before['methods'][method]) == ('pairs' in after['methods'][method]),
            'V24917_REFIT_OBSERVATION_ROSTER_CHANGED:' + method)
    vectors = []
    for diag in (before, after):
        data = diag['methods'][method]
        model = np.asarray(data['model'], dtype=float)
        require(model.shape == (len(expected),) and np.isfinite(model).all() and np.all(model >= 0),
                'V24917_REFIT_INVALID_MEASUREMENT')
        if 'pairs' in data:
            ids = [pair_key(*p) for p in data['pairs']]
            require(ids == expected, 'V24917_REFIT_OBSERVATION_ROSTER_CHANGED:' + method)
        vectors.append(model)
    expected_model = np.asarray(inc.model, dtype=float)
    require(expected_model.shape == (len(expected),), 'V24917_REFIT_INVALID_MEASUREMENT')
    check_parent_rows([{'countlocation_no': key, 'model': value} for key, value in zip(expected, expected_model)],
                      {key:i for i,key in enumerate(expected)}, vectors[0], method=method,
                      comparison='CAPTURED_INCIDENCE_VS_PARENT_DIAGNOSTIC', folder=parent_check_folder)
    if method in (after.get('_terms') or {}):
        bterms = captured_terms(before, method)
        aterms = validated_terms(after['_terms'][method], len(expected))
        require(all(np.array_equal(bterms[k], aterms[k]) for k in bterms),
                'V24917_REFIT_OBJECTIVE_AUTHORITY_CHANGED:' + method)
    return vectors


def usable_solution(solution):
    initial, final = float(solution['objective_initial']), float(solution['objective_final'])
    return bool(np.isfinite([initial, final]).all()
                and (solution['converged'] or final < initial))
