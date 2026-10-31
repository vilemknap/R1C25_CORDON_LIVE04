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
        write_json(folder / 'ROLLBACK_DIAGNOSTIC_REUSE_PROOF.json', result)
        return result
