"""Donor supply_visum.VisumAdapter on the actual 2025 zone axis + cordon diagnostics.

Inherited unchanged (donor HOTFIX2 code, within the COMBUSY snapshot hotfix scope):
snapshot, read_links, gap, generation_preview, apply_generation (GENERATION_GATE +
rt.apply_add_candidate readback), parameter_persistence.
Borrowed unchanged from PERF1: _execute_perf1_plan (phase-specific ProcSeq with
exact ACTIVE restore).  Replaced: __init__ (real Zone.NO axis instead of literal
1..681), diagnostics/block_gate/generation_design/rollback_diagnostic_equivalence
(cordon whole-matrix authority instead of 498-profile 12D/11D).
"""
from __future__ import annotations
from pathlib import Path
from types import SimpleNamespace
from .common import require, parent_module, canonical_hash
from .io import write_json, mkdir

_supply = parent_module('r1_15a2_supply_visum')
_perf1 = parent_module('r1_15a2_acceleration_v24915p1')
_p1 = parent_module('r1_15a2_trial_adapter_v24915p1')
_com = parent_module('r1_15a2_com_compat')
_rt = parent_module('r1_15a2_runtime_v1')

# LIVE04.5.2 rollback equivalence after an EXACT snapshot match (parameters and every
# demand matrix bit-identical).  The only remaining difference can come from the PrT
# assignment itself (path set / 0.001 path-volume lattice); a fresh full capture of
# the cordon rows within these limits proves the parent state.
ROLLBACK_ROW_ATOL = 1.0          # vehicles per cordon row
ROLLBACK_ROW_RTOL = 1.0e-3
ROLLBACK_OBJECTIVE_RTOL = 1.0e-3


def rows_equivalent(baseline_diag, diag, methods):
    """Per method: |m - m0| <= ATOL + RTOL * max(|m|, |m0|) on every row, objective within RTOL."""
    out = {'atol': ROLLBACK_ROW_ATOL, 'rtol': ROLLBACK_ROW_RTOL, 'objective_rtol': ROLLBACK_OBJECTIVE_RTOL,
           'methods': {}, 'passes': bool(diag.get('valid', True))}
    if not out['passes']:
        out['reason'] = 'ROLLBACK_CAPTURE_INVALID'
        return out
    for m in methods:
        a = [float(x) for x in baseline_diag['methods'][m]['model']]
        b = [float(x) for x in diag['methods'][m]['model']]
        if len(a) != len(b):
            out['methods'][m] = {'passes': False, 'reason': 'ROW_COUNT_CHANGED'}
            out['passes'] = False
            continue
        excess = [abs(x - y) - (ROLLBACK_ROW_ATOL + ROLLBACK_ROW_RTOL * max(abs(x), abs(y))) for x, y in zip(a, b)]
        j0 = float(baseline_diag['methods'][m]['objective']); j1 = float(diag['methods'][m]['objective'])
        obj_rel = abs(j1 - j0) / max(abs(j0), 1.0)
        ok = (max(excess, default=-1.0) <= 0.0) and obj_rel <= ROLLBACK_OBJECTIVE_RTOL
        out['methods'][m] = {'passes': ok, 'max_abs_row_difference': max((abs(x - y) for x, y in zip(a, b)), default=0.0),
                             'rows_outside': sum(1 for e in excess if e > 0.0), 'objective_relative_difference': obj_rel}
        out['passes'] = out['passes'] and ok
    return out


class CordonTrialAdapter(_supply.VisumAdapter):
    runtime_backend = 'CORDON_LIVE02_DONOR_SUPPLY_VISUM_ACTUAL_ZONE_AXIS'
    # Exact PERF1 function object (no zero-argument super inside).
    _execute_perf1_plan = _p1.VisumAdapter.__dict__['_execute_perf1_plan']

    def __init__(self, visum, cfg, *, evaluator, raw_visum, expected_zones, actuatable_zones,
                 folder, live02):
        self.visum = visum
        self.raw_visum = raw_visum
        self.cfg = cfg
        self.policy = None  # supply actuator is not part of LIVE02
        self.com_retry_policy = dict(cfg.get('com_resilience', {}) or {})
        self.zones, self.zone_write_index_by_no = _com.zone_identity(visum, None, self.com_retry_policy)
        require(self.zones == list(expected_zones) and len(self.zones) == int(cfg['expected_zones']),
                'LIVE02_ZONE_AXIS_CHANGED_SINCE_BASELINE')
        self.zone_readback_tolerance = float(self.com_retry_policy.get('zone_readback_tolerance', 1.0e-7))
        self.actuatable_zones = list(actuatable_zones)
        self.baseline_addval = None
        self.supply_path_proof = None
        self.generation_reference_values = None
        self.generation_reference_hash = None
        self.evaluator = evaluator
        self.live02 = live02
        self.folder = Path(folder)
        self.design_count = 0
        # Same module-global binding as the donor constructor.
        _rt.Visum = visum
        _supply.base.Visum = visum

    # ------------------------------------------------------------ run start
    def set_generation_reference(self, snapshot, folder):
        """Donor preflight rule: signed refinement reference fixed at run start."""
        import copy
        if self.cfg.get('generation_signed_refinement', {}).get('enabled') is True:
            self.generation_reference_values = copy.deepcopy(snapshot.get('generation_values', {}))
            self.generation_reference_hash = canonical_hash(self.generation_reference_values)
            write_json(Path(folder) / '00_GENERATION_COEFFICIENT_REFERENCE.json', {
                'schema': 'R1_15A2_GENERATION_COEFFICIENT_REFERENCE_V2492',
                'policy': 'RUN_START_REFERENCE_FIXED_FOR_SIGNED_REFINEMENT',
                'state_hash': snapshot.get('state_hash'),
                'generation_reference_hash': self.generation_reference_hash,
                'values': self.generation_reference_values})

    # ---------------------------------------------------- procedure execution
    def assign_for_block(self, folder, block):
        folder = Path(folder); mkdir(folder)
        if not _perf1.enabled(self.cfg, 'phase_specific_procseq'):
            return self.assign(folder, supply_only=False)
        plan = _perf1.phase_recompute_plan(self.visum, self.cfg, block)
        return self._execute_perf1_plan(folder, block, plan)

    # -------------------------------------------------------------- disabled
    def apply_supply(self, *args, **kwargs):
        raise PermissionError('LIVE02_SUPPLY_WRITES_DISABLED')

    def apply_td(self, rows):
        if self.live02['write_policy']['td_parameter_writes'] is not True:
            raise PermissionError('LIVE02_TD_WRITES_DISABLED')
        return super().apply_td(rows)

    def restore(self, *args, **kwargs):
        raise PermissionError('LIVE02_LOADVERSION_FORBIDDEN')

    def save(self, path):
        raise PermissionError('LIVE02_SAVE_ONLY_AT_VERIFIED_END')

    # ------------------------------------------------------ cordon authority
    def diagnostics(self, folder, label='CURRENT'):
        ev = self.live02['evaluation']
        label = str(label)
        cached = self.__dict__.pop('_rollback_capture_cache', None)
        if label == 'ROLLBACK' and cached is not None and self.snapshot().get('state_hash') == cached[0]:
            # The tolerant rollback proof already captured THIS state; do not capture it twice.
            return cached[1]
        if label in ('AFTER',):
            return self.evaluator.evaluate_candidate(
                self.raw_visum, folder, label, full_geometry=ev['trial_full_geometry_check'],
                keep_db=ev['keep_trial_capture_db'])
        return self.evaluator.evaluate(self.raw_visum, folder, label, full_geometry=True, keep_db=True)

    def block_gate(self, block, before, after, rows):
        return self.evaluator.block_gate(block, before, after, rows)

    def generation_design(self, diag, folder):
        """FISTA on the current whole matrix -> donor P/A projection (LIVE01 path)."""
        from .live01_generation import propose_generation
        from .live02_config import live01_view
        from .live01_donor_scope import zone_state_rows
        folder = Path(folder); mkdir(folder)
        self.design_count += 1
        require(diag.get('valid', True) and '_incidence' in diag, 'LIVE02_DESIGN_REQUIRES_VALID_CURRENT_DIAGNOSTIC')
        method = self.evaluator.method
        inc = diag['_incidence'][method]
        view = live01_view(self.live02, int(self.cfg['live02']['outer_cycle']))
        zone_rows, _ = zone_state_rows(self.visum, self.zones, self.cfg, zone_indices=self.zone_write_index_by_no,
                                       retry_policy=self.com_retry_policy)
        snap = self.snapshot()
        state = {'actuatable_zones': self.actuatable_zones, 'zone_rows': zone_rows,
                 'network_sha256': diag['network_sha256'], 'current_model_fingerprint': snap['state_hash']}
        solution, proposal = propose_generation(
            inc, view, state, solver_ladder=self.live02['generation_search']['solver_tolerance_ladder'])
        solution.save(folder, inc)
        write_json(folder / 'PROPOSED_TG_CANDIDATES_SCALE_1.json', proposal)
        projection = proposal['projection']
        context = {'result': solution.guidance,
                   'projection': SimpleNamespace(rows=projection['projection_rows'],
                                                 family_summaries=projection['family_summaries']),
                   'proposal_sha256': proposal['proposal_sha256'], 'method': method,
                   'solver_status': solution.report['status']}
        write_json(folder / 'GENERATION_DESIGN_CONTEXT.json', {
            'method': method, 'solver_status': solution.report['status'],
            'numeric_converged': solution.report['numeric_converged'],
            'kkt_x': solution.report['kkt_x'],
            'solver_tolerance_ladder': solution.report.get('solver_tolerance_ladder'),
            'family_summaries': projection['family_summaries'],
            'projection_rows': len(projection['projection_rows']),
            'candidate_count_scale_1': proposal['candidate_count'],
            'proposal_sha256': proposal['proposal_sha256'], 'parent_state_hash': snap['state_hash']})
        return context

    def rollback_diagnostic_equivalence(self, baseline_diag, before_snapshot, folder):
        """Reuse baseline cordon diagnostics only with exact state + path proof."""
        from .live02_evaluation import path_volume_signature
        folder = Path(folder); mkdir(folder)
        if self.live02['evaluation']['rollback_proof'] != 'PATH_VOLUME_SIGNATURE_THEN_FULL_CAPTURE':
            return {'passes': False, 'reason': 'FULL_CAPTURE_POLICY'}
        pre = self.snapshot()
        dsegs = baseline_diag['_pre'][4]
        signature = path_volume_signature(self.raw_visum, dsegs, self.evaluator.control, self.evaluator.opt)
        post = self.snapshot()
        passes = bool(pre == before_snapshot and post == before_snapshot and
                      signature == baseline_diag.get('path_signature'))
        result = {'schema': 'LIVE02_ROLLBACK_DIAGNOSTIC_REUSE_PROOF_V1', 'passes': passes,
                  'snapshot_equal_before_signature': pre == before_snapshot,
                  'snapshot_equal_after_signature': post == before_snapshot,
                  'matrix_hash_equal': pre.get('matrix_hash') == before_snapshot.get('matrix_hash'),
                  'generation_hash_equal': pre.get('generation_hash') == before_snapshot.get('generation_hash'),
                  'td_hash_equal': pre.get('td_hash') == before_snapshot.get('td_hash'),
                  'path_signature_equal': signature == baseline_diag.get('path_signature'),
                  'basis': 'EXACT_DONOR_SNAPSHOT_PLUS_12_DSEG_PATH_KEYS_AND_VOLUMES',
                  'full_capture_fallback_required': not passes, 'signature': signature,
                  'reason': None if passes else 'SNAPSHOT_OR_PATH_SIGNATURE_DIFFER'}
        if not passes and result['snapshot_equal_before_signature'] and result['snapshot_equal_after_signature']:
            result = self._tolerant_rollback_equivalence(baseline_diag, before_snapshot, folder, signature, result)
        write_json(folder / 'ROLLBACK_DIAGNOSTIC_REUSE_PROOF.json', result)
        return result

    def _tolerant_rollback_equivalence(self, baseline_diag, before_snapshot, folder, signature, result):
        """Exact parameters + matrices, different path signature: compare the cordon rows."""
        key = before_snapshot.get('state_hash')
        known = self.__dict__.setdefault('_equivalent_path_signatures', {})
        sig_hash = canonical_hash(signature)
        result = dict(result, exact_signature_equal=False, tolerant_policy={
            'row_atol': ROLLBACK_ROW_ATOL, 'row_rtol': ROLLBACK_ROW_RTOL, 'objective_rtol': ROLLBACK_OBJECTIVE_RTOL,
            'requires': 'EXACT_SNAPSHOT_PARAMETERS_AND_ALL_DEMAND_MATRICES'})
        if sig_hash in known.get(key, ()):
            return dict(result, passes=True, reason=None, full_capture_fallback_required=False,
                        basis='EXACT_SNAPSHOT_PLUS_PATH_SIGNATURE_ALREADY_PROVEN_EQUIVALENT_FOR_THIS_STATE')
        diag = self.evaluator.evaluate(self.raw_visum, Path(folder) / 'TOLERANT_CAPTURE', 'ROLLBACK',
                                       full_geometry=True, keep_db=False)
        same = self.snapshot() == before_snapshot
        cmp = rows_equivalent(baseline_diag, diag, self.evaluator.methods)
        result.update(tolerant_capture_snapshot_equal=same, tolerant_rows=cmp)
        if same and cmp['passes']:
            known.setdefault(key, set()).add(sig_hash)
            return dict(result, passes=True, reason=None, full_capture_fallback_required=False,
                        basis='EXACT_SNAPSHOT_PLUS_FULL_CAPTURE_ROWS_WITHIN_TOLERANCE')
        if same:
            self._rollback_capture_cache = (key, diag)   # donor fallback reuses this capture
        return dict(result, passes=False, reason='ROLLBACK_CORDON_ROWS_OUTSIDE_TOLERANCE' if same
                    else 'SNAPSHOT_CHANGED_DURING_TOLERANT_CAPTURE')
