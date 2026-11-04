"""LIVE04 adapter = LIVE03 cordon adapter on the v7 @ 7b4c681 Generation, SupplyMix and LONG rules.

Changes against LIVE03 (each mirrors r1_15a2_trial_adapter_v24917 of v7):
* generation_design: live04_generation.design (MOBILITY2 + MOBILITYZONE1 parent
  authority, role envelopes, BDPA1 joint fit, guarded projection, GENFIX2
  effect operator).  A blocked authority yields BLOCKED_MOBILITY_DATA, which
  STEP1 turns into a stop before any write (never a plateau).
* generation_preview: pure preview from the verified parent zone rows, boundary
  rows appended, final MOBILITY2/MOBILITYZONE1 check and the GENFIX2 final
  prediction for BOTH cordon methods.
* apply_generation: the complete plan (inherited rows + boundary rows) is checked
  again immediately before the first COM write, the MOBILITYZONE1 parent must be
  unchanged and the plan must be byte-identical to the preview.
* block_gate (GENERATION): live MOBILITY2/MOBILITYZONE1 readback after the trial.
  Every block: the LONG support (>= 80 km on 9697) of the trial must be clean
  and LONGGUARD1 must pass against the last accepted state.
* assign_for_block runs inside the v7 LONG post-TD mask scope; the native
  predictor's demand-only runs use execute_demand_only (same mask phases).
LIVE04.4:
* refine_generation_design: the v7 measured zonal refit (live04_generation.refine);
* SupplyMix: apply_supply is the donor write (path proof, complete validation
  before the first write, readback) under the donor supply policy; the
  SUPPLY_ADDVAL1 recompute is the v7 cold chain (reset op .. joint assignment),
  demand untouched, so the rollback recompute is deterministic.
"""
from __future__ import annotations
import copy
import math
from pathlib import Path
from .common import require, parent_module
from .io import write_json, mkdir
from .live02_adapter import CordonTrialAdapter
from .live03_adapter import CordonLive03Adapter
from . import live04_generation as gen
from . import live04_long_mask as longmask

_rt = parent_module('r1_15a2_runtime_v1')
_supply = parent_module('r1_15a2_supply_visum')
_mb = parent_module('r1_15a2_multiblock')
_bdgen = parent_module('r1_15a2_boundary_generation_v24917')
_bdpa = parent_module('r1_15a2_boundary_pa_v24917')
_mguard = parent_module('r1_15a2_mobility_guard_v24917')
_zguard = parent_module('r1_15a2_mobility_zone_v24917')
_mask = parent_module('r1_15a2_long_post_td_mask_v24917')


def _parent_coefficients_unchanged(authority, rows):
    """MOBILITYZONE1 coefficient part of parent_unchanged (raw FP_* not compared)."""
    by = _zguard.zone_map(rows)
    violations = []
    for e in authority['entries'].values():
        value = _zguard.finite(by[e['zone_no']].get(e['attr']), e['attr'])
        if not _zguard.close(value, e['current']):
            violations.append({'zone_no': e['zone_no'], 'family': e['family'], 'reasons': ['PARENT_CHANGED_BEFORE_WRITE']})
    for fam in authority['unavailable']:
        attrs = (_zguard.SPECS[fam][0],) + tuple(a for a, f in _zguard.ATT_FAMILY.items() if f == fam)
        old = _zguard.zone_map(authority['parent_zone_rows'])
        for z, row in old.items():
            for attr in attrs:
                if attr in row and not _zguard.close(_zguard.finite(row[attr], attr), _zguard.finite(by[z].get(attr), attr)):
                    violations.append({'zone_no': z, 'family': fam, 'reasons': ['DEFERRED_FAMILY_PARAMETER_CHANGED']})
    return {'passes': not violations, 'violations': violations, 'scope': 'COEFFICIENTS_AFTER_REJECTED_TRIAL'}


class CordonLive04Adapter(CordonLive03Adapter):
    runtime_backend = 'CORDON_LIVE04_V7_7B4C681_STEP1_GENFIX2_SUPPLYMIX_TD_CORDON_LONGMASK'

    def __init__(self, *args, long_mask=True, supply_policy=None, supply_reset_position=None, **kwargs):
        super().__init__(*args, **kwargs)
        # LIVE04.4 SupplyMix: donor supply policy and the run-start ADDVAL1 anchors.
        self.supply_writes_enabled = supply_policy is not None
        if supply_policy is not None:
            self.policy = supply_policy
        self.supply_reset_position = supply_reset_position
        self._long_post_td_mask_enabled = bool(long_mask)
        # v7 adapter attribute read by MOBILITYZONE1 (enrich LONG/SCHOOL when LSGEN is active).
        self.v24917_ls = dict((self.v24917_status or {}).get('long_school') or {})
        self.long_support_accepted = None
        self.long_support_last_trial = None
        # True between a rejected, executed GENERATION trial and the next recompute/rollback.
        self.tg_outputs_from_rejected_trial = False
        self.v24917_counts.update(mobility_blocked=0, preview_mobility_rejections=0, long_gate_rejections=0)

    # ---------------------------------------------------- procedure execution
    def assign_for_block(self, folder, block):
        with _mask.execution_scope(self):
            if str(block).upper() == 'SUPPLY_ADDVAL1':
                out = self._assign_supply_cold(folder)
            else:
                out = super().assign_for_block(folder, block)
        self.assignment_invalidated = False
        return out

    def assign(self, *args, **kwargs):
        out = super().assign(*args, **kwargs)
        self.assignment_invalidated = False
        return out

    # LIVE04.8.1: a demand-only execution (frozen-path predictor probe / restore) runs the
    # procedure-sequence resets 'reset PrT assignment results' WITHOUT an assignment, so the
    # saved PrT paths and link volumes of the model are gone until the next full recompute.
    # A block that ends without a native trial (e.g. NO_TD_CANDIDATE after probes, or a stop
    # during the design) used to leave the model without paths -> the next run / capture
    # failed with NO_SAVED_PRT_PATHS_FOR_POSITIVE_DEMAND and a saved .ver had no paths.
    def repair_assignment(self, folder, state, diag):
        """Full native recompute at the unchanged accepted parameters + proof of the state."""
        folder = Path(folder); mkdir(folder)
        before = self.snapshot()
        require(before == state, 'LIVE04_ASSIGNMENT_REPAIR_PARENT_NOT_ACCEPTED_STATE')
        self.assign_for_block(folder / 'RECOMPUTE', 'GENERATION')
        proof = self.rollback_diagnostic_equivalence(diag, state, folder / 'PROOF')
        out = {'schema': 'LIVE04_ASSIGNMENT_REPAIR_V1', 'reason': 'DEMAND_ONLY_EXECUTION_RESET_ASSIGNMENT',
               'snapshot_equal': self.snapshot() == state, 'proof_passes': bool(proof.get('passes')),
               'proof_basis': proof.get('basis'), 'proof_reason': proof.get('reason')}
        out['status'] = 'REPAIRED_VERIFIED' if out['snapshot_equal'] and out['proof_passes'] else 'REPAIR_NOT_VERIFIED'
        write_json(folder / 'ASSIGNMENT_REPAIR.json', out)
        require(out['status'] == 'REPAIRED_VERIFIED', 'LIVE04_ASSIGNMENT_REPAIR_NOT_VERIFIED:' + str(out['proof_reason']))
        return out

    def _assign_supply_cold(self, folder):
        """v7 SUPPLYMIX cold chain: reset op .. joint assignment (+ active groups)."""
        perf1 = parent_module('r1_15a2_acceleration_v24915p1')
        sm = parent_module('r1_15a2_supply_mix_v24917')
        folder = Path(folder); mkdir(folder)
        require(self.supply_writes_enabled and self.supply_reset_position is not None, 'LIVE04_SUPPLYMIX_NOT_ENABLED')
        plan = perf1.phase_recompute_plan(self.visum, self.cfg, 'SUPPLY_ADDVAL1')
        if not plan.get('inventory'):
            plan = dict(plan, inventory=[{k: v for k, v in r.items() if k != 'object'}
                                         for r in parent_module('r1_15a2_com_compat').operation_rows(self.visum)])
        cold = sm.cold_supply_plan(plan, self.cfg, int(self.supply_reset_position))
        info = cold.get('v24917_supplymix_plan') or {}
        if not info.get('applied'):
            raise _supply.SupplyContractError('V24917_SUPPLYMIX_COLD_PLAN_UNAVAILABLE:' + ';'.join(info.get('reasons', [])))
        return self._execute_perf1_plan(folder, 'SUPPLY_ADDVAL1', cold)

    # ------------------------------------------------------------ SupplyMix
    def apply_supply(self, candidate, snapshot, folder):
        if not self.supply_writes_enabled:
            raise PermissionError('LIVE04_SUPPLY_WRITES_DISABLED')
        return _supply.VisumAdapter.apply_supply(self, candidate, snapshot, folder)

    def refine_generation_design(self, context, scale, preview, before, after, folder):
        return gen.refine(self, context, scale, preview, before, after, folder)

    def execute_demand_only(self, plan, folder):
        perf1 = parent_module('r1_15a2_acceleration_v24915p1')
        self.assignment_invalidated = True
        if not self._long_post_td_mask_enabled:
            with perf1.activate_operation_plan(self.visum, plan) as active:
                _rt.execute_procseq(self.visum, folder)
            return {'phases': ['UNMASKED'], 'plan': active}
        # Outside execution_scope the scoped donor hook delegates to the original
        # execute_procseq, so each phase below is one plain Procedures.Execute.
        return longmask.execute_demand_only(self, plan, folder, _rt.execute_procseq)

    # --------------------------------------------------------- LONG support
    def long_support(self, folder=None, label='CURRENT'):
        return longmask.support_report(self, folder, label)

    def accept_long_support(self, report):
        self.long_support_accepted = report

    # ---------------------------------------------------------------- design
    def generation_design(self, diag, folder):
        folder = Path(folder); mkdir(folder)
        self.design_count += 1
        require(diag.get('valid', True) and '_incidence' in diag, 'LIVE04_DESIGN_REQUIRES_VALID_CURRENT_DIAGNOSTIC')
        context = {'method': self.evaluator.method, 'parent_design': 'NONE_LIVE04_ZONAL_FIT_ONLY'}
        context = gen.design(self, diag, folder, context)
        status = (context.get('v24917') or {}).get('status')
        self.v24917_counts['designs'] += 1
        if status == 'BLOCKED_MOBILITY_DATA':
            self.v24917_counts['mobility_blocked'] += 1
        write_json(folder / 'LIVE04_GENERATION_DESIGN.json', {
            'status': status, 'rows': len(getattr(context['projection'], 'rows', []) or []),
            'boundary_rows': len(_bdgen.rows_at_scale(context.get('v24917_bd'), 1.0))})
        return context

    # ------------------------------------------------------- preview / apply
    def generation_preview(self, context, scale):
        blocked = context.get('v24917') or {}
        if blocked.get('status') == 'BLOCKED_MOBILITY_DATA':
            raise _supply.SupplyContractError('MOBILITY2_BLOCKED_DATA_NOT_A_PLATEAU:' + str(blocked.get('failure_stage'))
                                              + ':' + str(blocked.get('error'))[:1000])
        if not math.isfinite(float(scale)) or not 0 <= float(scale) <= 1:
            raise _supply.SupplyContractError('GENFIX2_INVALID_GENERATION_SCALE')
        authority = context.get('_genfix2_mobility')
        with self.v24917_overlay(self._phase(context)), _bdpa.scope(context.get('v24917_bd')):
            if authority is None:
                design = CordonTrialAdapter.generation_preview(self, context, scale)
            else:
                design = _mb.design_generation_candidates(context['projection'].rows, authority['zone_rows'], self.cfg,
                                                         scale=scale, reference_values=self.generation_reference_values)
                design['zone_attributes_read'] = authority['zone_attributes']
        extra = _bdgen.rows_at_scale(context.get('v24917_bd'), scale)
        if isinstance(design, dict):
            design = dict(design)
            design['candidate_rows'] = list(design.get('candidate_rows') or []) + extra
            design['v24917_long_school_boundary_rows'] = len(extra)
            proof = gen.validate_mobility_plan(context, design)
            if proof.get('passes') is not True:
                self.v24917_counts['preview_mobility_rejections'] += 1
            design['genfix2_prediction'] = gen.final_prediction(context, design, scale)
        return design

    def apply_generation(self, context, scale, folder):
        from r1_15a2_supply import canonical_hash
        preview = self.generation_preview(context, scale)
        proof = preview.get('genfix2_mobility') or {}
        if proof.get('passes') is not True:
            raise _supply.SupplyContractError('GENERATION_GATE:MOBILITY2_FINAL_ENVELOPE')
        extra = _bdgen.rows_at_scale(context.get('v24917_bd'), scale)
        mz = context.get('_mobilityzone1')
        if mz is not None and mz['enabled']:
            fresh, _ = _supply.base.zone_state_rows(self.visum, self.zones, self.cfg,
                                                    zone_indices=self.zone_write_index_by_no,
                                                    retry_policy=self.com_retry_policy)
            fresh, _, read_errors = _zguard.enrich(self, fresh)
            if any(f not in mz['unavailable'] for f in read_errors):
                raise _supply.SupplyContractError('GENERATION_GATE:MOBILITYZONE1_LIVE_READ_UNAVAILABLE')
            if self.tg_outputs_from_rejected_trial:
                # Parent coefficients were restored by COM after a rejected trial; its TG
                # outputs (FP_*) stay until this trial recomputes them.  Only the
                # coefficients can (and must) equal the parent here.
                check = _parent_coefficients_unchanged(mz, fresh)
            else:
                check = _zguard.parent_unchanged(mz, fresh)
            if not check['passes']:
                raise _supply.SupplyContractError('GENERATION_GATE:MOBILITYZONE1_STALE_PARENT')
        original = _supply.base.generation_candidate

        def checked_design(*args, **kwargs):
            design = original(*args, **kwargs)
            complete = dict(design, candidate_rows=list(design.get('candidate_rows') or []) + extra)
            complete['summary'] = copy.deepcopy(design.get('summary', {}))
            checked = gen.validate_mobility_plan(context, complete)
            if not checked['passes']:
                raise _supply.SupplyContractError('GENERATION_GATE:MOBILITY2_FINAL_ENVELOPE')
            if canonical_hash(complete['candidate_rows']) != canonical_hash(preview['candidate_rows']):
                raise _supply.SupplyContractError('GENFIX2_GENERATION_PLAN_CHANGED_BEFORE_WRITE')
            design['genfix2_mobility'] = checked
            return design
        _supply.base.generation_candidate = checked_design
        try:
            with self.v24917_overlay(self._phase(context)), _bdpa.scope(context.get('v24917_bd')):
                rows = CordonTrialAdapter.apply_generation(self, context, scale, folder)
        finally:
            _supply.base.generation_candidate = original
        if extra:
            audit = _rt.apply_add_candidate(self.visum, extra, self.zones, zone_indices=self.zone_write_index_by_no,
                                            retry_policy=self.com_retry_policy,
                                            readback_tolerance=self.zone_readback_tolerance)
            if not audit or any(x.get('status') != 'OK' for x in audit):
                raise _supply.SupplyContractError('V24917_BOUNDARY_READBACK_FAILED')
            write_json(Path(folder) / 'V24917_BOUNDARY_ROWS.json', {'scale': scale, 'rows': extra, 'readback': audit})
            self.v24917_counts['extra_rows_written'] += len(extra)
            rows = list(rows) + extra
        write_json(Path(folder) / 'GENFIX2_FINAL_MOBILITY_AND_PREDICTION.json',
                   {'mobility': proof, 'prediction': preview.get('genfix2_prediction')})
        return rows

    # ------------------------------------------------------------ acceptance
    def _mobility_live(self):
        authority = getattr(self, '_genfix2_mobility_parent', None)
        opts = authority['options'] if authority else _mguard.options()
        if not opts.get('enabled', True):
            return {'passes': True, 'status': 'DISABLED'}
        if authority is None:
            raise _supply.SupplyContractError('MOBILITY2_PARENT_AUTHORITY_MISSING')
        live_rows, _ = _supply.base.zone_state_rows(self.visum, self.zones, self.cfg,
                                                    zone_indices=self.zone_write_index_by_no,
                                                    retry_policy=self.com_retry_policy)
        proof = _mguard.check_live(authority['zone_rows'], live_rows, opts)
        mz = getattr(self, '_mobilityzone1_parent', None)
        if mz is not None:
            try:
                mz_live, _, read_errors = _zguard.enrich(self, live_rows)
                if any(f not in mz['unavailable'] for f in read_errors):
                    raise ValueError('MOBILITYZONE1_LIVE_READ_UNAVAILABLE:' + repr(read_errors))
                zonal = _zguard.check_live(mz, mz_live)
            except Exception as exc:
                zonal = {'release': _zguard.RELEASE, 'passes': False, 'status': 'LIVE_READ_UNVERIFIED', 'error': repr(exc)}
            proof['mobilityzone1'] = zonal
            proof['passes'] = bool(proof['passes'] and zonal['passes'])
        return proof

    def block_gate(self, block, before, after, rows):
        decision = super().block_gate(block, before, after, rows)
        if str(block).upper() == 'GENERATION':
            proof = self._mobility_live()
            decision = dict(decision, mobility_guard_live=proof)
            if not proof['passes']:
                decision['accepted'] = False
                decision['reasons'] = list(decision.get('reasons') or []) + ['MOBILITY2_LIVE_ENVELOPE_REJECTED']
        if self._long_post_td_mask_enabled:
            try:
                candidate = self.long_support()
                parent = self.long_support_accepted
                require(parent is not None, 'LIVE04_LONG_SUPPORT_PARENT_MISSING')
                proof = longmask.decide(parent, candidate)
            except Exception as exc:
                proof = {'passes': False, 'reasons': ['LIVE04_LONG_SUPPORT_UNVERIFIED:' + str(exc)[:500]]}
                candidate = None
            decision = dict(decision, longguard1=proof)
            self.long_support_last_trial = candidate
            if not proof['passes']:
                self.v24917_counts['long_gate_rejections'] += 1
                decision['accepted'] = False
                decision['reasons'] = list(decision.get('reasons') or []) + list(proof.get('reasons') or [])
        return decision
