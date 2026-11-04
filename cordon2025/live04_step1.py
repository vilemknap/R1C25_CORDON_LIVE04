"""STEP1 with the v7 GENFIX2 semantics on the cordon objective (LIVE04).

Control flow = r1_15a2_step_search_v24917._generation_block_impl (v7 @ 7b4c681);
cordon specifics kept from LIVE03 (live02_step1):
  * the gate is the cordon block_gate on BOTH enumeration methods;
  * native demand on frozen paths (LIVE03 nodes) when enabled, otherwise the
    GENFIX2 linear operator of the FINAL implemented rows at each scale;
  * a trial is a full native recompute + full cordon capture, kept in place when
    eligible.
v7 semantics added against LIVE03:
  * model.final_prediction(s): every grid scale is previewed (pure, no COM write)
    and must pass the pre-apply gate INCLUDING the final MOBILITY2/MOBILITYZONE1
    envelope (donor choose_scale reads it);
  * pre-apply gate failure shrinks the step x0.75 before any write;
  * GENERATION_GATE raised at apply (before the first zone write) restores the
    parameters, proves the parent and continues with a smaller step;
  * recovery ownership: the planned rows are owned BEFORE the first COM write, so
    a partial write and every exceptional exit (including stops) end in the
    verified rollback;
  * stationarity is certified only for a converged proposal whose complete
    configured real search was rejected (not for a truncated or fallback search).
LIVE04.4 (v7 @ 7b4c681):
  * the actually applied preview (including an off-grid pre-apply shrink) is
    recorded as the prediction of that scale;
  * after the first fully measured, rejected trial the zonal direction may be
    re-solved ONCE (adapter.refine_generation_design); the new direction starts a
    fresh step model (origin MEASURED_ZONAL_REFIT) and shares the trial budget;
  * every trial writes STEP1_PRED_AUDIT.json: the planner forecast vs the measured
    cordon rows (no COM reads, never an acceptance authority).
"""
from __future__ import annotations
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import math
from .common import parent_module, ContractError
from .live02_step1 import CordonStepModel, _drop_capture

RELEASE = 'LIVE04_V7_GENFIX2_CORDON_STEP1'


class Live04StepModel(CordonStepModel):
    def __init__(self, evaluator, diag, linear, rho, predictor=None, memory_correction=None):
        super().__init__(evaluator, diag, linear, rho)
        self.predictor = predictor
        self.preview_cache = {}
        # LIVE04.1: route-choice correction per unit scale remembered from the previous cycle.
        self.memory_correction = ({m: np.asarray(memory_correction[m], dtype=float) for m in self.methods}
                                  if memory_correction else None)

    def final_prediction(self, s):
        """(delta by method or None, candidate_ok, reasons) of the FINAL candidate at s."""
        if self.predictor is None or s == 0:
            return ({m: s * self.delta[m] for m in self.methods}, True, [])
        key = float(s)
        if key not in self.preview_cache:
            self.record_preview(key, self.predictor(key))
        return self.preview_cache[key]

    def record_preview(self, scale, preview):
        """v7 record_preview: retain the ACTUAL pre-write preview (off-grid shrinks included)."""
        pred = preview.get('genfix2_prediction') or {}
        proof = preview.get('genfix2_mobility') or {}
        pgate = preview.get('_genfix2_pre_gate') or {'passes': True, 'reasons': []}
        ok = proof.get('passes') is True and pgate.get('passes') is True
        reasons = list(pgate.get('reasons', []))
        if proof.get('passes') is not True:
            reasons.append('MOBILITY2_FINAL_ENVELOPE')
        delta = None
        if pred.get('available'):
            delta = {m: np.asarray(pred['delta'][m], dtype=float) for m in self.methods}
            if any(not np.isfinite(v).all() or len(v) != len(self.m0[m]) for m, v in delta.items()):
                raise ValueError('GENFIX2_PREDICTION_IDENTITY_MISMATCH')
        self.preview_cache[float(scale)] = (delta, ok, reasons)

    def prediction_audit(self, scale, after_diag, labels=None):
        """v7 prediction_audit on the cordon rows of the acceptance method (no COM reads)."""
        m = self.method
        if not after_diag.get('valid', True):
            return {'status': 'UNAVAILABLE', 'reason': 'CANDIDATE_CAPTURE_INVALID'}
        measured = np.asarray(after_diag['methods'][m]['model'], dtype=float)
        observed = np.asarray(after_diag['methods'][m].get('observed') or self.terms[m]['y'], dtype=float)
        if measured.shape != self.m0[m].shape or not np.allclose(observed, self.terms[m]['y'], rtol=1e-7, atol=1e-7):
            return {'status': 'UNAVAILABLE', 'reason': 'OBSERVATION_AUTHORITY_CHANGED'}
        if not np.isfinite(measured).all() or np.any(measured < 0):
            return {'status': 'UNAVAILABLE', 'reason': 'INVALID_MEASURED_MODEL'}
        raw, _, _ = self.final_prediction(float(scale)) if self.predictor is not None else (None, True, [])
        planned = self.volumes(float(scale), m)

        def geh(v, o):
            return math.sqrt(2.0 * (v - o) ** 2 / max(v + o, 1e-12))
        rows = []
        for i in range(len(measured)):
            o = float(observed[i])
            rows.append({'row': labels[i] if labels else i, 'observed': o, 'parent_model': float(self.m0[m][i]),
                         'parent_geh': geh(float(self.m0[m][i]), o),
                         'raw_proposal_delta': None if raw is None else float(raw[m][i]),
                         'planner_model': float(planned[i]), 'planner_geh': geh(float(planned[i]), o),
                         'measured_model': float(measured[i]), 'measured_geh': geh(float(measured[i]), o),
                         'flow_prediction_error': float(measured[i] - planned[i]),
                         'measured_delta': float(measured[i] - self.m0[m][i])})
        ranked = sorted(rows, key=lambda r: abs(r['flow_prediction_error']), reverse=True)
        return {'status': 'MEASURED_PREDICTION_COMPARISON', 'scale': float(scale), 'method': m,
                'mode': 'SECANT_MEASURED' if self.measured is not None else getattr(self, 'origin_mode', 'LINEAR_FIT'),
                'proposal_origin_mode': getattr(self, 'origin_mode', 'LINEAR_FIT'),
                'prediction': 'NATIVE_FROZEN_PATHS' if self.nodes else 'GENFIX2_FINAL_EFFECT_LINEAR',
                'previous_measurement_scale': None if self.measured is None else float(self.measured[0]),
                'rho': self.rho, 'rows': rows, 'largest_errors': ranked[:10],
                'acceptance_authority': False, 'new_com_reads': 0,
                'native_stage_attribution': 'UNIDENTIFIED_REQUIRES_STAGE_EVIDENCE'}

    def prior(self, s, m, *, with_memory=True):
        """Prediction before the in-block secant: native nodes or the GENFIX2 operator
        (rho before the first measurement, as v7), plus the remembered route correction."""
        s = float(s)
        if self.nodes:
            v = self._native(s, m)
        else:
            delta, _, _ = self.final_prediction(s)
            if delta is None:
                v = self.m0[m].copy()
            else:
                v = self.m0[m] + (1.0 if self.measured is not None else self.rho) * delta[m]
        if with_memory and self.memory_correction is not None:
            v = v + s * self.memory_correction[m]
        return v

    def volumes(self, s, m, *, with_memory=True):
        v = self.prior(s, m, with_memory=with_memory)
        if self.measured is not None:
            # Secant on the remaining model error measured by the full trial of this block.
            sk, mk = self.measured
            v = v + (float(s) / sk) * (mk[m] - self.prior(sk, m, with_memory=with_memory))
        return np.maximum(v, 0.0)

    def objective_without_memory(self, s):
        from .live02_evaluation import objective_from_model
        return objective_from_model(self.terms[self.method], self.volumes(s, self.method, with_memory=False))[0]

    def learn_rho(self, s, after_diag, bounds=(0.2, 1.5)):
        delta, _, _ = self.final_prediction(s)
        if s <= 0 or delta is None:
            return None
        m = np.asarray(after_diag['methods'][self.method]['model'], dtype=float)
        d = delta[self.method]
        sel = np.abs(d) > 1e-9
        if sel.sum() < 5:
            return None
        dp = d[sel]; dm = m[sel] - self.m0[self.method][sel]
        den = float(dp @ dp)
        if den <= 1e-9:
            return None
        return float(min(bounds[1], max(bounds[0], float(dp @ dm) / den)))


def _parent_check(adapter, state, probe_dirty, folder, phase):
    """v7 genstate.require_parent; after native probes only the parameters must match
    (the demand holds the last probe until the next recompute or the final rollback)."""
    if not probe_dirty:
        return parent_module('r1_15a2_generation_state_v24917').require_parent(adapter, state, folder, phase=phase)
    from .live03_predictor import same_parameters
    snap = adapter.snapshot()
    if not same_parameters(snap, state):
        raise parent_module('r1_15a2_supply').SupplyContractError('V242_GENERATION_TRIAL_PARENT_CHANGED')
    return snap


def step1_block(tx, adapter, cfg, folder, control, state, diag, anchors, reference, policy, *, write_json):
    step = parent_module('r1_15a2_step_search_v24917')
    SupplyContractError = parent_module('r1_15a2_supply').SupplyContractError
    base = SimpleNamespace(**tx.ctrl_ns)
    ctrl = SimpleNamespace(**tx.coupled_ns)
    evaluator = adapter.evaluator
    opts = step.options()
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    gen_cfg = ctrl._generation_counts_cfg(cfg)
    baseline_value = base.ledger(diag, state, anchors, policy, reference, gen_cfg)
    rec = {'status': 'DESIGNING', 'attempts': [], 'objective_before': baseline_value,
           'search_mode': 'V7_GENFIX2_STEP1_COMPUTED_STEP_ADOPT_IN_PLACE_CORDON', 'release': RELEASE}

    def save_rec():
        try:
            base.atomic_json(folder / 'GENERATION_BLOCK_RESULT.json', rec)
        except Exception as io_exc:   # never replace the primary model/stop exception
            rec.setdefault('failure_record_write_errors', []).append(repr(io_exc)[:500])

    design_phase = 'BEFORE_DESIGN'
    try:
        parent_module('r1_15a2_generation_state_v24917').require_parent(
            adapter, state, folder / 'DESIGN_PARENT_CHECK', phase=design_phase)
        design_phase = 'GENERATION_DESIGN'
        context = adapter.generation_design(diag, folder / 'DESIGN')
        blocked = context.get('v24917') or {}
        if blocked.get('status') == 'BLOCKED_MOBILITY_DATA':
            rec['mobility_block'] = {k: blocked.get(k) for k in
                                     ('failure_stage', 'exception_type', 'error', 'detail_path', 'status')}
            raise SupplyContractError('MOBILITY2_BLOCKED_DATA_NOT_A_PLATEAU:' + str(blocked.get('failure_stage'))
                                      + ':' + str(blocked.get('error'))[:1000])
        design_phase = 'GENERATION_SOLVER_CHECK'
        if context.get('result') is not None and not context['result'].converged:
            raise SupplyContractError('V245_GENERATION_SOLVER_NOT_CONVERGED_NOT_A_PLATEAU')
        design_phase = 'GENERATION_PROJECTION_CHECK'
        fams = context['projection'].family_summaries
        if not fams or not all(row.get('converged') for row in fams):
            raise SupplyContractError('V245_GENERATION_PROJECTION_NOT_CONVERGED_NOT_A_PLATEAU')
    except BaseException as exc:
        rec.update(status='FAILED', failure_phase=design_phase, error=str(exc), search_complete=False,
                   stationarity_confirmed=False)
        save_rec()
        raise
    v7 = context.get('v24917') or {}
    rec['design'] = {k: v7.get(k) for k in ('status', 'phase', 'model_obs_ratio', 'error', 'solver_converged',
                                             'proposal_usable', 'mobility_target_satisfied', 'search_incomplete')}
    max_trials = max(1, len(gen_cfg.get('backtracking_scales') or [1.0, 0.5, 0.25]))
    limit = int(gen_cfg.get('trial_calibration', {}).get('max_trials_per_block', {}).get('GENERATION', max_trials))
    max_trials = max(1, min(max_trials, limit))
    min_rel = float(((gen_cfg.get('performance', {}) or {}).get('first_sufficient', {}) or {})
                    .get('generation_min_relative_improvement', 0.0) or 0.0)
    rec.update(planned_trials=max_trials, search_complete=False, stationarity_confirmed=False,
               solver_converged=v7.get('solver_converged') is True)
    rho = step._STATE['rho'] if step._STATE['rho'] is not None else 1.0

    def final_preview(scale):
        preview = adapter.generation_preview(context, scale)
        preview['_genfix2_pre_gate'] = step._pre_apply_gate(preview, adapter)
        return preview
    memory = getattr(adapter, 'run_memory', None)
    direction = None
    correction = None
    if memory is not None:
        from .live04_memory import direction_from_rows
        direction = direction_from_rows(context['projection'].rows, context.get('v24917_bd'))
        correction, rec['memory_route_correction'] = memory.tg_correction(direction)
    model = Live04StepModel(evaluator, diag, context.get('v24917_step_model'), rho,
                            predictor=final_preview if context.get('_genfix2_mobility') else None,
                            memory_correction=correction)
    rec['prediction_authority'] = 'FINAL_IMPLEMENTED_EFFECT_ROWS' if model.predictor else 'LEGACY_OR_UNAVAILABLE'
    ncfg = getattr(adapter, 'native_prediction', None) or {}
    probe = {'dirty': False, 'predictor': None}
    if ncfg.get('enabled') and ncfg.get('tg_step1') and context['projection'].rows:
        from .live03_predictor import probe_generation_nodes, FrozenPathPredictor
        if memory is not None:
            ncfg = dict(ncfg, tg_node_fractions=memory.node_fractions(ncfg.get('tg_node_fractions')))
        nodes, info = None, None
        try:
            nodes, info = probe_generation_nodes(base, adapter, context, state, diag, folder / 'NATIVE_PREDICTION',
                                                 ncfg, opts, control, restore_each=True)
        except BaseException as exc:
            # LIVE04.5.2: the predictor's base parity runs BEFORE any write.  If it fails,
            # STEP1 continues with the GENFIX2 final-effect prediction (the measured trial
            # decides anyway); the model has not been touched, so nothing is restored.
            before_write = isinstance(exc, ContractError) and str(exc).startswith('LIVE03_PREDICTOR_')
            if not before_write:
                with base.recovery_scope(control, 'LIVE04_TG_PROBE_DEMAND_RESTORE'):
                    FrozenPathPredictor(adapter, diag, folder / 'NATIVE_PREDICTION').restore_demand(
                        'GENERATION', state, folder / 'NATIVE_PREDICTION' / 'RESTORE_AFTER_ERROR')
                raise
            rec['native_prediction'] = {'status': 'UNAVAILABLE_FALLBACK_GENFIX2_FINAL_EFFECT',
                                        'reason': str(exc)[:1000], 'model_mutated': False}
        if info is None:
            nodes, info = {}, dict(rec['native_prediction'])
        probe['dirty'] = bool(info.get('model_mutated'))
        probe['predictor'] = info.pop('_predictor', None)
        rec['native_prediction'] = info
        if nodes:
            model.set_nodes(nodes)
            if memory is not None:
                info['memory_curvature'] = memory.record_curvature(model.nodes, model.m0, model.method)
        rec['native_node_fractions'] = list(ncfg.get('tg_node_fractions') or [])

    def gate(before_rows, predicted):
        return evaluator.block_gate('GENERATION', before_rows, predicted, [])
    baseline_diag_hash = base.diagnostic_hash(diag)
    own = {'rows': None, 'candidate': None, 'applied': None, 'demand_dirty': False, 'rollback_started': False}
    upper = float(opts['max_scale'])
    refit_attempted = False
    labels = ['%s-%s' % tuple(p) for p in diag['methods'][evaluator.method].get('pairs', [])] or None
    step._STATE['blocks'] += 1

    def own_recovery(rows, candidate):
        retained = {(r['attr'], r['zone_no']): r for r in (own['rows'] or [])}
        for row in rows:
            retained.setdefault((row['attr'], row['zone_no']), dict(row))
        own['rows'] = list(retained.values())
        own['candidate'] = dict(candidate)

    def restore_probe_demand():
        if probe['dirty']:
            with base.recovery_scope(control, 'LIVE04_TG_PROBE_DEMAND_RESTORE'):
                probe['predictor'].restore_demand('GENERATION', state, folder / 'NATIVE_PREDICTION' / 'RESTORE')
            probe['dirty'] = False

    def rollback_full(reason):
        if own['rows'] is None:
            restore_probe_demand()
            return
        own['rollback_started'] = True
        with base.recovery_scope(control, 'STEP1_FINAL_ROLLBACK'):
            rb, rolled = base._rollback_candidate(adapter, 'GENERATION', state, baseline_diag_hash,
                                                  folder / 'ROLLBACK', own['rows'], own['candidate'], diag)
        base.atomic_json(folder / 'ROLLBACK_SUMMARY.json', dict(rb, reason=reason))
        if base.diagnostic_hash(rolled) != baseline_diag_hash:
            raise SupplyContractError('V242_GENERATION_ROLLBACK_DIAGNOSTIC_CHANGED')
        own.update(rows=None, candidate=None, applied=None, demand_dirty=False)
        probe['dirty'] = False
        adapter.tg_outputs_from_rejected_trial = False

    adapter.tg_outputs_from_rejected_trial = False
    try:
        for ordinal in range(1, max_trials + 1):
            plan = step.choose_scale(model, gate, min_rel, opts, upper)
            if plan['scale'] is None and model.measured is None and model.memory_correction is not None:
                # Memory may change WHICH step is tried, never suppress the trial LIVE04 would run.
                kept = model.memory_correction
                model.memory_correction = None
                try:
                    plan = step.choose_scale(model, gate, min_rel, opts, upper)
                finally:
                    model.memory_correction = kept
                plan['memory_fallback'] = 'NO_STEP_WITH_MEMORY_PLAN_WITHOUT_MEMORY'
            scale = plan['scale']
            if scale is None and model.measured is None and model.nodes:
                plan['prediction'] = 'NATIVE_FROZEN_PATHS'
                write_json(folder / ('STEP1_PLAN_%02d.json' % ordinal), plan)
                rec['stop_reason'] = 'NATIVE_PREDICTION_NO_ROBUST_IMPROVING_SCALE'
                break
            if scale is None and model.measured is None:
                scale = upper
                plan['fallback'] = 'LINEAR_MODEL_NO_ROBUST_STEP_MEASURE_FULL'
            plan['prediction'] = 'NATIVE_FROZEN_PATHS' if model.nodes else 'GENFIX2_FINAL_EFFECT_LINEAR'
            write_json(folder / ('STEP1_PLAN_%02d.json' % ordinal), plan)
            if scale is None:
                rec['stop_reason'] = 'NO_ROBUST_FEASIBLE_SCALE_BELOW_MEASURED_TRIAL'
                break
            candidate = {'scale': float(scale)}
            trial_folder = folder / ('TRY_%02d' % ordinal); trial_folder.mkdir(parents=True, exist_ok=True)
            control.checkpoint('COUPLED_DEMAND_GENERATION_TRIAL', force=True, trial=ordinal)
            attempt = {'trial': ordinal, 'candidate': candidate, 'plan_mode': plan['mode'],
                       'predicted_rel_improvement': plan.get('predicted_rel_improvement'), 'rho': plan.get('rho')}
            try:
                if own['applied'] is not None:
                    parent_module('r1_15a2_inplace_transaction_v24915p2').restore_generation_parameters(
                        adapter, state, list(own['applied']), trial_folder / 'RESTORE_PARENT_PARAMETERS')
                    own['applied'] = None
                elif own['rows'] is None:
                    _parent_check(adapter, state, probe['dirty'], trial_folder / 'PARENT_CHECK', 'BEFORE_TRIAL_APPLY')
                preview, rows = base._planned_generation_rows(adapter, context, float(scale))
                gate_log = []
                pgate = step._pre_apply_gate(preview, adapter)
                while pgate is not None and not pgate['passes']:
                    gate_log.append({'scale': float(scale), 'reasons': pgate['reasons'], 'pa_gaps': step._pa_gaps(preview)})
                    nxt = float(scale) * 0.75
                    if nxt < float(opts['min_scale']):
                        break
                    scale = nxt
                    candidate = {'scale': float(scale)}
                    preview, rows = base._planned_generation_rows(adapter, context, float(scale))
                    pgate = step._pre_apply_gate(preview, adapter)
                if gate_log:
                    attempt.update(pre_apply_gate_shrink=gate_log, candidate=candidate)
                    step._STATE['pre_gate_shrinks'] = step._STATE.get('pre_gate_shrinks', 0) + len(gate_log)
                if pgate is not None and not pgate['passes']:
                    attempt['status'] = 'REJECTED_PRE_APPLY_GATE_ALL_SCALES'
                    rec['attempts'].append(attempt)
                    rec['stop_reason'] = 'PRE_APPLY_GATE_NO_FEASIBLE_SCALE'
                    save_rec()
                    break
                base.atomic_json(trial_folder / ('GENERATION_PREVIEW_%s.json' % str(round(scale, 6)).replace('.', '_')),
                                 preview)
                if model.predictor is not None:
                    model.record_preview(float(scale), dict(preview, _genfix2_pre_gate=pgate))
                rows = list(rows or [])
                if not rows:
                    attempt['status'] = 'NO_PARAMETER_CANDIDATE'
                    rec['attempts'].append(attempt)
                    rec['stop_reason'] = 'NO_PARAMETER_CANDIDATE'
                    break
                signature = base._candidate_signature('GENERATION', candidate, rows)
                control.checkpoint('TRIAL_APPLY', block='GENERATION', candidate=signature)
                own['applied'] = rows
                own_recovery(rows, candidate)          # owned BEFORE the first COM write
                actual = base._apply_candidate(adapter, 'GENERATION', candidate, rows, context, state, trial_folder)
                own['applied'] = list(actual)
                own_recovery(own['applied'], candidate)
                control.checkpoint('TRIAL_ASSIGNMENT', block='GENERATION')
                own['demand_dirty'] = True
                adapter.tg_outputs_from_rejected_trial = True    # cleared on acceptance or rollback
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
                decision.update(shared_ledger_before=baseline_value, shared_ledger_after=after_value,
                                shared_objective_improvement=improvement)
                minimum = base.number(gen_cfg.get('shared_objective', {}).get('minimum_improvement', 1e-8))
                if improvement <= minimum:
                    decision['accepted'] = False
                    decision.setdefault('reasons', []).append('SHARED_OBJECTIVE_NOT_IMPROVED')
                base._write_acceptance(trial_folder / 'ACCEPTANCE.json', decision)
                if not decision.get('accepted') and not evaluator.live02['evaluation']['keep_trial_capture_db']:
                    attempt['rejected_capture_removed'] = _drop_capture(trial_folder / 'DIAGNOSTICS')
            except BaseException as exc:
                if isinstance(exc, Exception) and 'GENERATION_GATE:' in str(exc):
                    # Raised before any zone write: parameters back, prove the parent, smaller step.
                    if own['applied'] is not None:
                        parent_module('r1_15a2_inplace_transaction_v24915p2').restore_generation_parameters(
                            adapter, state, list(own['applied']), trial_folder / 'RESTORE_AFTER_PRE_APPLY_GATE')
                        own['applied'] = None
                    if not own['demand_dirty']:
                        try:
                            _parent_check(adapter, state, probe['dirty'], trial_folder / 'PRE_APPLY_GATE_PARENT_CHECK',
                                          'AFTER_PRE_APPLY_GATE_RESTORE')
                        except BaseException as restore_exc:
                            rec.update(status='FAILED', failure_phase='PRE_APPLY_GATE_RESTORE', error=str(restore_exc))
                            attempt.update(status='FAILED', error=str(restore_exc))
                            rec['attempts'].append(attempt)
                            save_rec()
                            rollback_full('PRE_APPLY_GATE_RESTORE_ERROR')
                            raise
                        own.update(rows=None, candidate=None)
                    attempt.update(status='REJECTED_PRE_APPLY_GATE', error=str(exc)[:500])
                    rec['attempts'].append(attempt)
                    save_rec()
                    upper = float(scale) * 0.75
                    if upper < float(opts['min_scale']):
                        rec['stop_reason'] = 'PRE_APPLY_GATE_NO_FEASIBLE_SCALE'
                        break
                    continue
                if isinstance(exc, Exception) and 'ASSIGNMENT_NOT_TIGHT' in str(exc) and own['rows'] is not None:
                    # LIVE04.5.2: an assignment above the gap limit is a property of this candidate,
                    # not of the run: verified rollback to the parent, then a smaller step.
                    attempt.update(status='REJECTED_ASSIGNMENT_NOT_TIGHT', error=str(exc)[:500])
                    rec['attempts'].append(attempt)
                    save_rec()
                    rollback_full('ASSIGNMENT_NOT_TIGHT')
                    rec['status'] = 'SEARCHING'
                    save_rec()
                    upper = float(scale) * 0.5
                    if upper < float(opts['min_scale']):
                        rec['stop_reason'] = 'ASSIGNMENT_NOT_TIGHT_NO_FEASIBLE_SCALE'
                        break
                    continue
                attempt.update(status='FAILED', error=str(exc))
                rec['attempts'].append(attempt)
                rec.update(status='FAILED', failure_phase='GENERATION_TRIAL', error=str(exc))
                save_rec()
                if own['rows'] is not None or probe['dirty']:
                    rollback_full('TRIAL_ERROR')
                if not isinstance(exc, Exception) or isinstance(exc, (base.UserStopRequested, base.TimeBudgetReached)):
                    raise
                raise SupplyContractError('V245_GENERATION_TRIAL_ERROR_NOT_A_PLATEAU:' + str(exc)) from exc
            step._STATE['trials'] += 1
            audit = model.prediction_audit(float(scale), after_diag, labels)
            audit.update(parent_state_hash=state.get('state_hash'), candidate_state_hash=after.get('state_hash'),
                         assignment_gap=gap)
            write_json(trial_folder / 'STEP1_PRED_AUDIT.json', audit)
            attempt['prediction_audit'] = {'path': str(trial_folder / 'STEP1_PRED_AUDIT.json'),
                                           'status': audit['status'], 'mode': audit.get('mode')}
            attempt.update(status='ELIGIBLE' if decision.get('accepted') else 'REJECTED', gap=gap, decision=decision,
                           counts_objective=after_value, predicted_objective=model.objective(float(scale)),
                           measured_objective=float(after_value['total']))
            valid_capture = bool(after_diag.get('valid', True))
            if model.memory_correction is not None:
                attempt['predicted_objective_without_memory'] = model.objective_without_memory(float(scale))
            if memory is not None and direction is not None and valid_capture and model.measured is None:
                memory.record_tg_correction(
                    direction, float(scale), {m: after_diag['methods'][m]['model'] for m in model.methods},
                    {m: model.prior(float(scale), m, with_memory=False) for m in model.methods})
            if plan['mode'] == 'LINEAR_FIT' and valid_capture and not model.nodes:
                r = model.learn_rho(float(scale), after_diag, opts['rho_bounds'])
                if r is not None:
                    old = step._STATE['rho']
                    step._STATE['rho'] = r if old is None else 0.5 * old + 0.5 * r
                    step._STATE['rho_history'].append({'measured': r, 'used_next': step._STATE['rho']})
                    attempt['rho_measured'] = r
            rec['attempts'].append(attempt)
            save_rec()
            if decision.get('accepted'):
                step._STATE['kept'] += 1
                rec.update(status='ACCEPTED', gap=gap, candidate=candidate, rows=len(actual), objective_after=after_value,
                           search_complete=True, adopted_in_place=True, early_stop_trial=ordinal,
                           early_stop_policy='STEP1_FIRST_ELIGIBLE_KEPT')
                save_rec()
                own.update(rows=None, candidate=None, applied=None, demand_dirty=False)
                probe['dirty'] = False
                adapter.tg_outputs_from_rejected_trial = False
                return True, after, after_diag, after_value, rec
            if (not refit_attempted and ordinal < max_trials and valid_capture
                    and callable(getattr(adapter, 'refine_generation_design', None))):
                refit_attempted = True
                # Full native diagnostics describe this rejected trial; only the proposal
                # operator changes, the parent and the recovery ownership stay intact (v7).
                try:
                    refined, raudit = adapter.refine_generation_design(context, float(scale), preview, diag, after_diag,
                                                                       folder / 'MEASURED_REFIT')
                except Exception as exc:
                    refined, raudit = None, {'status': 'REFIT_UNAVAILABLE', 'error': repr(exc)}
                rec['measured_zonal_refit'] = raudit
                base.atomic_json(folder / 'MEASURED_ZONAL_REFIT.json', raudit)
                if refined is not None:
                    context = refined
                    # A secant of the old direction cannot be applied to a different zonal
                    # vector: fresh model and preview cache on the corrected operator.
                    model = Live04StepModel(evaluator, diag, context.get('v24917_step_model'), 1.0,
                                            predictor=final_preview if context.get('_genfix2_mobility') else None)
                    model.origin_mode = 'MEASURED_ZONAL_REFIT'
                    direction = None
                    upper = float(opts['max_scale'])
                    continue
            if valid_capture:
                model.set_measured(float(scale), after_diag)
            upper = float(scale) * 0.95
            if upper < float(opts['min_scale']):
                rec['stop_reason'] = 'SCALE_BELOW_MINIMUM'
                break
        rollback_full('SEARCH_EXHAUSTED')
        step._STATE['exhausted'] += 1
        verified = bool(rec.get('solver_converged') is True and len(rec['attempts']) == max_trials
                        and all(a.get('status') == 'REJECTED' for a in rec['attempts'])
                        and not (context.get('v24917') or {}).get('search_incomplete'))
        rec.update(search_complete=True, configured_search_exhausted=True, stationarity_confirmed=verified,
                   stationarity_verified=verified,
                   stationarity_scope='CONVERGED_PROPOSAL_COMPLETE_CONFIGURED_REAL_SEARCH_NOT_GLOBAL_OPTIMALITY',
                   stationarity_reason=('COMPLETE_CONFIGURED_REAL_SEARCH_REJECTED' if verified
                                        else 'BOUNDED_OR_UNVERIFIED_SEARCH_NOT_A_STATIONARITY_CERTIFICATE'),
                   status='CONFIGURED_GENERATION_SEARCH_EXHAUSTED')
        save_rec()
        return False, state, diag, baseline_value, rec
    except BaseException as exc:
        rec.update(status='FAILED', search_complete=False, stationarity_confirmed=False)
        rec.setdefault('failure_phase', 'GENERATION_SEARCH')
        rec.setdefault('error', str(exc))
        try:
            save_rec()
        finally:
            if (own['rows'] is not None or probe['dirty']) and not own['rollback_started']:
                rollback_full('SEARCH_ERROR')
        raise
