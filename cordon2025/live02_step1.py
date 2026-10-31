"""STEP1 (V24917) on the cordon objective: computed TG step, eligible trial kept in place.

Control flow is a port of r1_15a2_step_search_v24917.generation_block; the donor
``choose_scale`` (grid, robustness margin, best predicted gain) is used unchanged.
Profile specifics are replaced:
  * the step model predicts the 120 pair volumes of BOTH enumeration methods
    (linear m(s) = m0 + s*rho*d from the zonal fit, secant after a measurement);
  * the predicted gate is the cordon block_gate (primary objective improvement,
    secondary method not degraded) on the predicted volumes;
  * a trial is a full native recompute + fresh full cordon capture; an eligible
    trial stays as the accepted state (no rollback, no re-apply, no extra
    assignment).  A rejected trial restores the parent parameters (COM only); the
    full verified rollback runs only when the block ends without an eligible trial.
"""
from __future__ import annotations
import shutil
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from .common import parent_module
from .live02_config import METHODS
from .live02_evaluation import objective_from_model

RELEASE = 'LIVE02_V24917_CORDON_STEP1'


class CordonStepModel:
    def __init__(self, evaluator, diag, linear, rho):
        self.evaluator = evaluator
        self.method = evaluator.method
        self.base_rows = diag                     # passed through to the gate unchanged
        self.terms = diag['_terms']
        self.methods = tuple(getattr(evaluator, 'methods', METHODS))
        self.m0 = {m: np.asarray(diag['methods'][m]['model'], dtype=float) for m in self.methods}
        delta = (linear or {}).get('delta_full') or {}
        self.delta = {m: np.asarray(delta.get(m, np.zeros(len(self.m0[m]))), dtype=float) for m in self.methods}
        self.mapped = int(np.count_nonzero(self.delta[self.method]))
        self.rho = float(rho)
        self.measured = None                      # (s_k, {method: m_k})
        self.nodes = {}                           # LIVE03: {s: {method: native frozen-path rows}}

    def set_nodes(self, nodes):
        self.nodes = {float(s): {m: np.asarray(v[m], dtype=float) for m in self.methods} for s, v in nodes.items()}
        if self.nodes:
            self.mapped = int(np.count_nonzero(np.abs(self.nodes[max(self.nodes)][self.method] - self.m0[self.method]) > 1e-9))

    def _native(self, s, m):
        """Piecewise-linear interpolation through (0, m0) and the native nodes;
        linear extrapolation with the last segment beyond the largest node."""
        xs = [0.0] + sorted(self.nodes)
        ys = [self.m0[m]] + [self.nodes[x][m] for x in xs[1:]]
        s = float(s)
        for k in range(1, len(xs)):
            if s <= xs[k] or k == len(xs) - 1:
                x0, x1 = xs[k - 1], xs[k]
                t = (s - x0) / (x1 - x0)
                return ys[k - 1] + t * (ys[k] - ys[k - 1])
        return ys[-1]

    def set_measured(self, scale, after_diag):
        self.measured = (float(scale), {m: np.asarray(after_diag['methods'][m]['model'], dtype=float) for m in self.methods})

    def volumes(self, s, m):
        if self.nodes:
            v = self._native(s, m)
            if self.measured is not None:
                # Route-choice correction measured by the full trial, scaled with the step.
                sk, mk = self.measured
                v = v + (s / sk) * (mk[m] - self._native(sk, m))
            return np.maximum(v, 0.0)
        if self.measured is not None:
            sk, mk = self.measured
            v = self.m0[m] + (s / sk) * (mk[m] - self.m0[m])
        else:
            v = self.m0[m] + s * self.rho * self.delta[m]
        return np.maximum(v, 0.0)

    def rows(self, s):
        """Predicted cordon diagnostic (same schema the gate reads)."""
        out = {'valid': True, 'methods': {}, 'predicted_scale': float(s)}
        for m in self.methods:
            v = self.volumes(s, m)
            total, _, _, metrics = objective_from_model(self.terms[m], v)
            out['methods'][m] = {'objective': total, 'metrics': metrics, 'model': v.tolist()}
        return out

    def objective(self, s):
        v = self.volumes(s, self.method)
        return objective_from_model(self.terms[self.method], v)[0]

    def learn_rho(self, s, after_diag, bounds=(0.2, 1.5)):
        m = np.asarray(after_diag['methods'][self.method]['model'], dtype=float)
        d = self.delta[self.method]
        sel = np.abs(d) > 1e-9
        if s <= 0 or sel.sum() < 5:
            return None
        dp = s * d[sel]; dm = m[sel] - self.m0[self.method][sel]
        den = float(dp @ dp)
        if den <= 1e-9:
            return None
        return float(min(bounds[1], max(bounds[0], float(dp @ dm) / den)))


def _parent_unchanged(snap, state, probe_dirty):
    if not probe_dirty:
        return snap == state
    from .live03_predictor import same_parameters
    return same_parameters(snap, state)


def _drop_capture(folder):
    folder = Path(folder)
    removed = []
    for p in (folder / 'p.sqlite', folder / 'p.sqlite-wal', folder / 'p.sqlite-journal'):
        try:
            if p.exists():
                p.unlink(); removed.append(p.name)
        except OSError:
            pass
    if (folder / 'matrix_authority').exists():
        shutil.rmtree(folder / 'matrix_authority', ignore_errors=True); removed.append('matrix_authority')
    return removed


def step1_block(tx, adapter, cfg, folder, control, state, diag, anchors, reference, policy, *, write_json):
    step = parent_module('r1_15a2_step_search_v24917')
    txm = parent_module('r1_15a2_inplace_transaction_v24915p2')
    SupplyContractError = parent_module('r1_15a2_supply').SupplyContractError
    base = SimpleNamespace(**tx.ctrl_ns)
    ctrl = SimpleNamespace(**tx.coupled_ns)
    evaluator = adapter.evaluator
    opts = step.options()
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    gen_cfg = ctrl._generation_counts_cfg(cfg)
    baseline_value = base.ledger(diag, state, anchors, policy, reference, gen_cfg)
    rec = {'status': 'DESIGNING', 'attempts': [], 'objective_before': baseline_value,
           'search_mode': 'V24917_STEP1_COMPUTED_STEP_ADOPT_IN_PLACE_CORDON', 'release': RELEASE}
    context = adapter.generation_design(diag, folder / 'DESIGN')
    if context.get('result') is not None and not context['result'].converged:
        raise SupplyContractError('V245_GENERATION_SOLVER_NOT_CONVERGED_NOT_A_PLATEAU')
    if context.get('projection') is not None:
        fams = context['projection'].family_summaries
        if not fams or not all(row.get('converged') for row in fams):
            raise SupplyContractError('V245_GENERATION_PROJECTION_NOT_CONVERGED_NOT_A_PLATEAU')
    rec['design'] = {k: (context.get('v24917') or {}).get(k) for k in ('status', 'phase', 'model_obs_ratio', 'error')}
    max_trials = max(1, len(gen_cfg.get('backtracking_scales') or [1.0, 0.5, 0.25]))
    limit = int(gen_cfg.get('trial_calibration', {}).get('max_trials_per_block', {}).get('GENERATION', max_trials))
    max_trials = max(1, min(max_trials, limit))
    min_rel = float(((gen_cfg.get('performance', {}) or {}).get('first_sufficient', {}) or {})
                    .get('generation_min_relative_improvement', 0.0) or 0.0)
    rec.update(planned_trials=max_trials, search_complete=False, stationarity_confirmed=False)
    rho = step._STATE['rho'] if step._STATE['rho'] is not None else 1.0
    model = CordonStepModel(evaluator, diag, context.get('v24917_step_model'), rho)
    # LIVE03: native demand on frozen paths replaces the linear prediction.
    ncfg = getattr(adapter, 'native_prediction', None) or {}
    probe = {'dirty': False, 'predictor': None}
    if ncfg.get('enabled') and ncfg.get('tg_step1'):
        from .live03_predictor import probe_generation_nodes
        try:
            nodes, info = probe_generation_nodes(base, adapter, context, state, diag, folder / 'NATIVE_PREDICTION',
                                                 ncfg, opts, control)
        except BaseException:
            # Parameters are restored by the probe itself; demand must follow.
            from .live03_predictor import FrozenPathPredictor
            with base.recovery_scope(control, 'LIVE03_TG_PROBE_DEMAND_RESTORE'):
                FrozenPathPredictor(adapter, diag, folder / 'NATIVE_PREDICTION').restore_demand(
                    'GENERATION', state, folder / 'NATIVE_PREDICTION' / 'RESTORE_AFTER_ERROR')
            raise
        probe['dirty'] = bool(info.get('model_mutated'))
        probe['predictor'] = info.pop('_predictor', None)
        rec['native_prediction'] = info
        if nodes:
            model.set_nodes(nodes)

    def gate(before_rows, predicted):
        return evaluator.block_gate('GENERATION', before_rows, predicted, [])
    baseline_diag_hash = base.diagnostic_hash(diag)
    applied_rows = None
    applied_candidate = None
    # FIX vs donor: rows of the last trial that reached Visum.  Restoring the parent
    # parameters by COM only does NOT restore the demand/assignment of that trial,
    # so the final verified rollback (restore + recompute) must still run.
    dirty = {'rows': None, 'candidate': None}
    upper = float(opts['max_scale'])
    step._STATE['blocks'] += 1

    def rollback_full(reason):
        rows_ = applied_rows if applied_rows is not None else dirty['rows']
        cand_ = applied_candidate if applied_rows is not None else dirty['candidate']
        if rows_ is None:
            if probe['dirty']:
                with base.recovery_scope(control, 'LIVE03_TG_PROBE_DEMAND_RESTORE'):
                    probe['predictor'].restore_demand('GENERATION', state, folder / 'NATIVE_PREDICTION' / 'RESTORE')
                probe['dirty'] = False
            return
        with base.recovery_scope(control, 'STEP1_FINAL_ROLLBACK'):
            rb, rolled = base._rollback_candidate(adapter, 'GENERATION', state, baseline_diag_hash,
                                                  folder / 'ROLLBACK', rows_, cand_, diag)
        base.atomic_json(folder / 'ROLLBACK_SUMMARY.json', dict(rb, reason=reason))
        if base.diagnostic_hash(rolled) != baseline_diag_hash:
            raise SupplyContractError('V242_GENERATION_ROLLBACK_DIAGNOSTIC_CHANGED')

    for ordinal in range(1, max_trials + 1):
        plan = step.choose_scale(model, gate, min_rel, opts, upper)
        scale = plan['scale']
        if scale is None and model.measured is None and model.nodes:
            # LIVE03: the native frozen-path prediction (not a linear model) finds no
            # robust improving step -> no blind full trial.
            plan['prediction'] = 'NATIVE_FROZEN_PATHS'
            write_json(folder / ('STEP1_PLAN_%02d.json' % ordinal), plan)
            rec['stop_reason'] = 'NATIVE_PREDICTION_NO_ROBUST_IMPROVING_SCALE'
            break
        if scale is None and model.measured is None:
            scale = upper
            plan['fallback'] = 'LINEAR_MODEL_NO_ROBUST_STEP_MEASURE_FULL'
        plan['prediction'] = 'NATIVE_FROZEN_PATHS' if model.nodes else 'LINEAR_V24917'
        write_json(folder / ('STEP1_PLAN_%02d.json' % ordinal), plan)
        if scale is None:
            rec['stop_reason'] = 'NO_ROBUST_FEASIBLE_SCALE_BELOW_MEASURED_TRIAL'
            break
        candidate = {'scale': float(scale)}
        trial_folder = folder / ('TRY_%02d' % ordinal); trial_folder.mkdir(parents=True, exist_ok=True)
        control.checkpoint('COUPLED_DEMAND_GENERATION_TRIAL', force=True, trial=ordinal)
        attempt = {'trial': ordinal, 'candidate': candidate, 'plan_mode': plan['mode'],
                   'predicted_rel_improvement': plan.get('predicted_rel_improvement'), 'rho': plan.get('rho')}
        mutated = applied_rows is not None or dirty['rows'] is not None or probe['dirty']
        try:
            if applied_rows is not None:
                txm.restore_generation_parameters(adapter, state, list(applied_rows),
                                                  trial_folder / 'RESTORE_PARENT_PARAMETERS')
                applied_rows = None
            elif dirty['rows'] is None and not _parent_unchanged(adapter.snapshot(), state, probe['dirty']):
                # Only before the first write: afterwards the model legitimately holds
                # the last trial's demand until the next recompute or final rollback.
                raise SupplyContractError('V242_GENERATION_TRIAL_PARENT_CHANGED')
            preview, rows = base._planned_generation_rows(adapter, context, float(scale))
            base.atomic_json(trial_folder / ('GENERATION_PREVIEW_%s.json' % str(round(scale, 6)).replace('.', '_')), preview)
            rows = list(rows or [])
            if not rows:
                attempt['status'] = 'NO_PARAMETER_CANDIDATE'
                rec['attempts'].append(attempt)
                rec['stop_reason'] = 'NO_PARAMETER_CANDIDATE'
                break
            # FIX vs donor: TGFIX semantics also in STEP1 - the pre-apply
            # GENERATION_GATE is decided on the identical preview BEFORE a write,
            # the candidate is rejected and a smaller computed step is tried.
            gate_pre = parent_module('r1_15a2_supply_visum').base.generation_apply_gate(preview, adapter.cfg)
            if not gate_pre['passes']:
                attempt.update(status='REJECTED', error='GENERATION_GATE:' + ';'.join(gate_pre['reasons']),
                               pre_apply_gate_rejected=True, model_mutated=False)
                base.atomic_json(trial_folder / 'TRIAL_RESULT.json', {'status': 'REJECTED_PRE_APPLY_GATE',
                                 'gate': gate_pre, 'scale': float(scale), 'model_mutated': False})
                rec['attempts'].append(attempt)
                base.atomic_json(folder / 'GENERATION_BLOCK_RESULT.json', rec)
                upper = float(scale) * 0.95
                if upper < float(opts['min_scale']):
                    rec['stop_reason'] = 'SCALE_BELOW_MINIMUM'
                    break
                continue
            signature = base._candidate_signature('GENERATION', candidate, rows)
            control.checkpoint('TRIAL_APPLY', block='GENERATION', candidate=signature)
            mutated = True
            applied_candidate = candidate
            applied_rows = rows
            dirty.update(rows=rows, candidate=candidate)
            actual = base._apply_candidate(adapter, 'GENERATION', candidate, rows, context, state, trial_folder)
            applied_rows = list(actual)
            dirty.update(rows=list(actual))
            control.checkpoint('TRIAL_ASSIGNMENT', block='GENERATION')
            gap = base._assign_candidate(adapter, trial_folder / 'ASSIGNMENT', 'GENERATION')
            adapter.parameter_persistence('GENERATION', actual)
            after = adapter.snapshot()
            base.assert_freeze(state, after, 'GENERATION', rows=actual, candidate=candidate, cfg=gen_cfg)
            control.checkpoint('TRIAL_DIAGNOSTICS', block='GENERATION')
            after_diag = adapter.diagnostics(trial_folder / 'DIAGNOSTICS', 'STEP1_TRIAL')
            if adapter.snapshot() != after:
                raise SupplyContractError('TRIAL_DIAGNOSTICS_CHANGED_MODEL')
            after_value = base.ledger(after_diag, after, anchors, policy, reference, gen_cfg)
            decision = adapter.block_gate('GENERATION', diag, after_diag, actual)
            improvement = baseline_value['total'] - after_value['total']
            decision['shared_ledger_before'] = baseline_value
            decision['shared_ledger_after'] = after_value
            decision['shared_objective_improvement'] = improvement
            minimum = base.number(gen_cfg.get('shared_objective', {}).get('minimum_improvement', 1e-8))
            if improvement <= minimum:
                decision['accepted'] = False
                decision.setdefault('reasons', []).append('SHARED_OBJECTIVE_NOT_IMPROVED')
            base._write_acceptance(trial_folder / 'ACCEPTANCE.json', decision)
            if not decision.get('accepted') and not evaluator.live02['evaluation']['keep_trial_capture_db']:
                attempt['rejected_capture_removed'] = _drop_capture(trial_folder / 'DIAGNOSTICS')
        except BaseException as exc:
            attempt['status'] = 'FAILED'; attempt['error'] = str(exc)
            rec['attempts'].append(attempt)
            base.atomic_json(folder / 'GENERATION_BLOCK_RESULT.json', rec)
            if mutated:
                rollback_full('TRIAL_ERROR')
            if not isinstance(exc, Exception) or isinstance(exc, (base.UserStopRequested, base.TimeBudgetReached)):
                raise
            raise SupplyContractError('V245_GENERATION_TRIAL_ERROR_NOT_A_PLATEAU:' + str(exc)) from exc
        step._STATE['trials'] += 1
        attempt.update(status='ELIGIBLE' if decision.get('accepted') else 'REJECTED', gap=gap, decision=decision,
                       counts_objective=after_value, predicted_objective=model.objective(float(scale)),
                       measured_objective=float(after_value['total']))
        valid_capture = bool(after_diag.get('valid', True))
        if plan['mode'] == 'LINEAR_FIT' and valid_capture and not model.nodes:
            r = model.learn_rho(float(scale), after_diag, opts['rho_bounds'])
            if r is not None:
                old = step._STATE['rho']
                step._STATE['rho'] = r if old is None else 0.5 * old + 0.5 * r
                step._STATE['rho_history'].append({'measured': r, 'used_next': step._STATE['rho']})
                attempt['rho_measured'] = r
        rec['attempts'].append(attempt)
        base.atomic_json(folder / 'GENERATION_BLOCK_RESULT.json', rec)
        if decision.get('accepted'):
            step._STATE['kept'] += 1
            rec.update(status='ACCEPTED', gap=gap, candidate=candidate, rows=len(actual), objective_after=after_value,
                       search_complete=True, adopted_in_place=True, early_stop_trial=ordinal,
                       early_stop_policy='STEP1_FIRST_ELIGIBLE_KEPT')
            base.atomic_json(folder / 'GENERATION_BLOCK_RESULT.json', rec)
            return True, after, after_diag, after_value, rec
        if valid_capture:
            model.set_measured(float(scale), after_diag)
        upper = float(scale) * 0.95
        if upper < float(opts['min_scale']):
            rec['stop_reason'] = 'SCALE_BELOW_MINIMUM'
            break
    rollback_full('SEARCH_EXHAUSTED')
    step._STATE['exhausted'] += 1
    rec.update(search_complete=True, stationarity_confirmed=True, status='CONFIGURED_GENERATION_SEARCH_EXHAUSTED')
    base.atomic_json(folder / 'GENERATION_BLOCK_RESULT.json', rec)
    return False, state, diag, baseline_value, rec
