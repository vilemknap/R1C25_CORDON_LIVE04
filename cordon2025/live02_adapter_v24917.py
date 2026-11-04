"""LIVE02 adapter + V24917 targeted Generation (port of r1_15a2_trial_adapter_v24917).

generation_design: the certified LIVE02 design (FISTA guidance on the whole cordon
matrix -> donor projection) runs first; its proposal is then replaced by the V24917
zonal fit.  Any fit error keeps the parent proposal (V24917_FIT_FALLBACK.json).
generation_preview / apply_generation: V24917 phase overlay (CATCH_UP / REFINE) and
TARGETED_ZONE_DIRECT design mode; LSGEN/BNDGEN rows are written in the same trial
(one native recompute) and are part of the snapshot/rollback state.
PERF3 timing wraps procedure execution, capture, snapshot, design and rollback.
"""
from __future__ import annotations
import contextlib
from pathlib import Path
from .common import parent_module
from .io import write_json
from .live02_adapter import CordonTrialAdapter
from . import live02_v24917 as v17

_tg = parent_module('r1_15a2_targeted_generation_v24917')
_rt = parent_module('r1_15a2_runtime_v1')
_supply = parent_module('r1_15a2_supply_visum')
_perf = parent_module('r1_15a2_perf_v24917')

TIMED = (('assign_for_block', 'procedure_sequence'), ('snapshot', 'snapshot'),
         ('diagnostics', 'cordon_capture_and_evaluation'), ('generation_design', 'design'),
         ('rollback_diagnostic_equivalence', 'rollback_proof'))


class CordonV24917Adapter(CordonTrialAdapter):
    runtime_backend = 'CORDON_LIVE02_V24917_TARGETED_STEP1'

    def __init__(self, *args, v24917_status=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.v24917_status = dict(v24917_status or {})
        self.v24917_counts = {'designs': 0, 'fit_fallbacks': 0, 'extra_rows_written': 0}
        for name, label in TIMED:
            setattr(self, name, _perf.timed(label, getattr(self, name)))

    @contextlib.contextmanager
    def v24917_overlay(self, phase):
        old = self.cfg
        self.cfg = _tg.overlay_cfg(old, phase) if phase else old
        try:
            yield self.cfg
        finally:
            self.cfg = old

    @staticmethod
    def _phase(context):
        return ((context or {}).get('v24917') or {}).get('overlay_phase')

    def generation_design(self, diag, folder):
        context = super().generation_design(diag, folder)
        context = v17.targeted_design(self, diag, folder, context)
        self.v24917_counts['designs'] += 1
        if (context.get('v24917') or {}).get('status') == 'FIT_FALLBACK_PARENT_PROPOSAL':
            self.v24917_counts['fit_fallbacks'] += 1
        return context

    def generation_preview(self, context, scale):
        with self.v24917_overlay(self._phase(context)):
            design = super().generation_preview(context, scale)
        extra = v17.extra_rows(context, scale)
        if extra and isinstance(design, dict):
            design = dict(design)
            design['candidate_rows'] = list(design.get('candidate_rows') or []) + extra
            design['v24917_long_school_boundary_rows'] = len(extra)
        return design

    def apply_generation(self, context, scale, folder):
        with self.v24917_overlay(self._phase(context)):
            rows = super().apply_generation(context, scale, folder)
        extra = v17.extra_rows(context, scale)
        if extra:
            audit = _rt.apply_add_candidate(self.visum, extra, self.zones, zone_indices=self.zone_write_index_by_no,
                                            retry_policy=self.com_retry_policy,
                                            readback_tolerance=self.zone_readback_tolerance)
            if not audit or any(x.get('status') != 'OK' for x in audit):
                raise _supply.SupplyContractError('V24917_LONG_SCHOOL_BOUNDARY_READBACK_FAILED')
            write_json(Path(folder) / 'V24917_LONG_SCHOOL_BOUNDARY_ROWS.json',
                       {'scale': scale, 'rows': extra, 'readback': audit})
            self.v24917_counts['extra_rows_written'] += len(extra)
            rows = list(rows) + extra
        return rows

    def diagnostics(self, folder, label='CURRENT'):
        if str(label) == 'STEP1_TRIAL':
            # An eligible STEP1 trial becomes the accepted state: full geometry, keep
            # the capture until the decision (PERF3 removes it for a rejected trial).
            proof = (getattr(self, 'live02', None) or {}).get('evaluation', {}).get('trial_geometry_proof', 'FULL')
            return self.evaluator.evaluate_candidate(self.raw_visum, folder, label, full_geometry=True, keep_db=True,
                                                     geometry_proof=proof)
        return super().diagnostics(folder, label)
