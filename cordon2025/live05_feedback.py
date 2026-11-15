"""LIVE05.8 procedure feedback: the R1 TD utility step and the 20D vignette split stay ACTIVE.

The 2025 procedure contains state that is carried from one procedure run to the next:

* the Run-script operation between the native TG and TD ("R1 TD utility step",
  R1_TD_UTILITY_PROCSEQ_COLD_START_20261110) updates the TD utility matrices
  9700..9715 by MSA:  U_new = (1-lambda) U_old + lambda M9002 * ratio(TTC/TT0, OD flows).
  The congestion ratio comes from the TTC/TT0 skims of the previous assignment;
* the 20D vignette split reads the tCur skims when DT_MODE = 'LIVE' (FROZEN reads
  the data matrices 9235/9236 and is deterministic).  LIVE cannot be reproduced even at
  the baseline: the saved demand was split with the skims of the run BEFORE the saved
  one, which no longer exist in the version.  The run therefore requires FROZEN
  (formula references only in formula_allowed_reference_nos) and stops before the
  first write otherwise.

The user decision (2026-11-15): the feedback keeps running, so a trial includes the
congestion effect; acceptance and reproducibility need not be exact.

How the calibrator treats it (no tolerance needed where the state must be reproduced):

* FEEDBACK STATE = the utility matrices + the TTC/TT0 skims of the native person
  segments (inputs of the utility step).  It is read
  at the baseline and after every accepted block (= the accepted feedback state).
* Every procedure execution (probe, trial, rollback, repair) starts from the
  accepted feedback state (the matrices are written back by SetValues when a
  previous execution changed them; exact readback).
* Probes and trials run the feedback operation (a trial = one model iteration from
  the accepted state, congestion included; probes predict that trial).
* Reproducing executions (restore after probes, rollback of a rejected trial,
  assignment repair) skip the feedback operation, so the accepted state is
  recomputed exactly: same parameters + same utilities -> same demand -> same
  assignment.  The existing exact snapshot proofs stay valid.

Write permission (audited, Live04 guard): SetValues on the resolved feedback state
matrices only; demand-segment OD matrices and component matrices stay forbidden.
"""
from __future__ import annotations
import contextlib
import hashlib
import re
from pathlib import Path
import numpy as np
from .common import require, parent_module
from .io import write_json, mkdir

SCHEMA = 'LIVE05_PROCEDURE_FEEDBACK_V1'
_MREF = re.compile(r'Matrix\(\s*(\d+)\s*\)', re.IGNORECASE)
DEFAULTS = {
    'enabled': False,
    'utility_matrix_nos': [],
    'time_skim_codes': ['TTC', 'TT0'],
    'time_skim_dsegs': [],
    'formula_matrix_nos': [],
    'formula_allowed_reference_nos': [],
    'expected_feedback_operations': 1,
}
KEYS = set(DEFAULTS) | {'note'}


def options(cfg):
    f = cfg.get('procedure_feedback')
    if f is None:
        return dict(DEFAULTS)
    require(isinstance(f, dict) and set(f) <= KEYS, 'LIVE05_FEEDBACK_CONFIG_FIELDS')
    out = dict(DEFAULTS, **{k: v for k, v in f.items() if k != 'note'})
    require(isinstance(out['enabled'], bool), 'LIVE05_FEEDBACK_ENABLED_BOOL')
    for k in ('utility_matrix_nos', 'formula_matrix_nos', 'formula_allowed_reference_nos'):
        require(isinstance(out[k], list) and all(isinstance(v, int) and not isinstance(v, bool) and v > 0
                                                 for v in out[k]), 'LIVE05_FEEDBACK_MATRIX_LIST:' + k)
    for k in ('time_skim_codes', 'time_skim_dsegs'):
        require(isinstance(out[k], list) and all(isinstance(v, str) and v.strip() for v in out[k]),
                'LIVE05_FEEDBACK_CODE_LIST:' + k)
    n = out['expected_feedback_operations']
    require(isinstance(n, int) and not isinstance(n, bool) and 1 <= n <= 3, 'LIVE05_FEEDBACK_EXPECTED_OPERATIONS')
    if out['enabled']:
        require(out['utility_matrix_nos'], 'LIVE05_FEEDBACK_UTILITY_MATRICES_REQUIRED')
    return out


def validate(cfg):
    o = options(cfg)
    wp = cfg.get('write_policy') or {}
    require(wp.get('procedure_feedback_state_matrix_writes', False) is o['enabled'],
            'LIVE05_FEEDBACK_WRITE_POLICY_MUST_MATCH')
    return o


def _items(collection):
    member = collection.GetAll
    return list(member() if callable(member) else member)


def _array(matrix):
    return np.array(matrix.GetValues(), dtype=float, copy=True)


def _hash(a):
    return hashlib.sha256(np.ascontiguousarray(a, dtype='<f8').tobytes()).hexdigest()


def feedback_positions(visum):
    """Active Run-script operations strictly between the active native TG and TD."""
    com = parent_module('r1_15a2_com_compat')
    rows = com.operation_rows(visum)
    active = [r for r in rows if int(r['active'])]
    tg = [int(r['no']) for r in active if int(r['type']) == com.TG]
    td = [int(r['no']) for r in active if int(r['type']) == com.TD]
    require(len(tg) == 1 and len(td) == 1 and tg[0] < td[0], 'LIVE05_FEEDBACK_TG_TD_LAYOUT')
    return [int(r['no']) for r in active if int(r['type']) == com.EXECUTE_SCRIPT and tg[0] < int(r['no']) < td[0]]


def resolve_state_matrices(visum, o):
    """utility matrices + TTC/TT0 skims of the configured segments; vignette formulas must be FROZEN."""
    mats = visum.Net.Matrices
    out = {}
    for no in o['utility_matrix_nos']:
        try:
            mats.ItemByKey(no)
        except Exception:
            require(False, 'LIVE05_FEEDBACK_UTILITY_MATRIX_MISSING:%d' % no)
        out[int(no)] = 'TD_UTILITY'
    codes = {c.strip().upper() for c in o['time_skim_codes']}
    dsegs = {d.strip().upper() for d in o['time_skim_dsegs']}
    skims = {}
    if codes and dsegs:
        for m in _items(mats):
            code = str(m.AttValue('CODE')).strip().upper()
            dseg = str(m.AttValue('DSEGCODE')).strip().upper()
            if code in codes and dseg in dsegs:
                require((dseg, code) not in skims, 'LIVE05_FEEDBACK_DUPLICATE_TIME_SKIM:%s:%s' % (dseg, code))
                skims[(dseg, code)] = int(m.AttValue('NO'))
    for (dseg, code), no in sorted(skims.items()):
        out.setdefault(no, 'TIME_SKIM_%s_%s' % (code, dseg))
    formulas = {}
    for no in o['formula_matrix_nos']:
        try:
            m = mats.ItemByKey(no)
        except Exception:
            formulas[str(no)] = None
            continue
        text = str(m.AttValue('FORMULA') or '')
        refs = sorted({int(x) for x in _MREF.findall(text)} - set(o['formula_matrix_nos']))
        formulas[str(no)] = {'formula': text, 'references': refs}
        bad = sorted(set(refs) - set(o['formula_allowed_reference_nos']))
        require(not bad, 'LIVE05_VIGNETTE_SPLIT_NOT_FROZEN_NOT_REPRODUCIBLE:matrix=%d,references=%s'
                ' (DT_MODE=FROZEN + R1_20D_FREEZE_DT.py)' % (no, bad))
    return out, {'time_skims': {'%s:%s' % k: v for k, v in sorted(skims.items())}, 'formulas': formulas}


class ProcedureFeedback:
    """Accepted feedback state + execution modes (see module docstring)."""

    def __init__(self, visum, cfg, folder, *, forbidden_matrix_nos=(), audit=None):
        self.visum = visum
        self.o = options(cfg)
        self.folder = Path(folder); mkdir(self.folder)
        self.positions = feedback_positions(visum)
        require(len(self.positions) == self.o['expected_feedback_operations'],
                'LIVE05_FEEDBACK_OPERATION_COUNT:found=%s,expected=%d'
                % (self.positions, self.o['expected_feedback_operations']))
        self.roles, details = resolve_state_matrices(visum, self.o)
        clash = sorted(set(self.roles) & {int(x) for x in forbidden_matrix_nos})
        require(not clash, 'LIVE05_FEEDBACK_STATE_OVERLAPS_DEMAND_OR_COMPONENT_MATRICES:%s' % clash)
        if audit is not None:
            audit.feedback_state_matrices = frozenset(self.roles)
        self.accepted = None
        self.hashes = None
        self.dirty = set()           # matrices a previous execution may have changed
        self._reproducing = 0
        self._executing = False
        self.counts = {'captures': 0, 'restores': 0, 'matrices_written': 0, 'feedback_runs': 0, 'reproducing_runs': 0}
        self.details = details
        # FROZEN vignette split: the formulas reference the frozen data matrices only.
        self.formula_references = sorted({r for f in details['formulas'].values() if f for r in f['references']})
        write_json(self.folder / 'PROCEDURE_FEEDBACK.json', self.describe())

    def describe(self):
        return {'schema': SCHEMA, 'feedback_operation_positions': self.positions,
                'state_matrices': {str(k): v for k, v in sorted(self.roles.items())},
                'resolution': self.details, 'formula_references': self.formula_references,
                'policy': {'probes_and_trials': 'START_FROM_ACCEPTED_FEEDBACK_STATE_RUN_FEEDBACK_OPERATION',
                           'restore_rollback_repair': 'START_FROM_ACCEPTED_FEEDBACK_STATE_SKIP_FEEDBACK_OPERATION',
                           'accepted_state': 'READ_AT_BASELINE_AND_AFTER_EVERY_ACCEPTED_BLOCK'},
                'counts': dict(self.counts)}

    # ------------------------------------------------------------- state
    def capture(self, label):
        mats = self.visum.Net.Matrices
        self.accepted = {no: _array(mats.ItemByKey(no)) for no in sorted(self.roles)}
        self.hashes = {no: _hash(a) for no, a in self.accepted.items()}
        self.dirty = set()
        self.counts['captures'] += 1
        write_json(self.folder / ('FEEDBACK_STATE_%s.json' % label), {
            'schema': SCHEMA + '_STATE', 'label': label, 'hashes': {str(k): v for k, v in self.hashes.items()}})
        return self.hashes

    def restore(self):
        """Write back the accepted feedback state where a previous execution changed it."""
        require(self.accepted is not None, 'LIVE05_FEEDBACK_STATE_NOT_CAPTURED')
        if not self.dirty:
            return []
        mats = self.visum.Net.Matrices
        written = []
        for no in sorted(self.dirty):
            m = mats.ItemByKey(no)
            if _hash(_array(m)) == self.hashes[no]:
                continue
            m.SetValues(np.ascontiguousarray(self.accepted[no], dtype=np.float64), False)
            require(_hash(_array(mats.ItemByKey(no))) == self.hashes[no], 'LIVE05_FEEDBACK_STATE_READBACK:%d' % no)
            written.append(no)
        self.dirty = set()
        self.counts['restores'] += 1
        self.counts['matrices_written'] += len(written)
        return written

    # --------------------------------------------------------- execution
    @property
    def reproducing(self):
        return self._reproducing > 0

    @contextlib.contextmanager
    def reproduce(self):
        self._reproducing += 1
        try:
            yield self
        finally:
            self._reproducing -= 1

    def filter_plan(self, plan):
        """Demand-only plan of a reproducing execution: the feedback operation removed."""
        if not self.reproducing:
            return plan
        sel = [p for p in plan['selected_operation_positions'] if int(p) not in self.positions]
        return dict(plan, selected_operation_positions=sel, feedback_operations_skipped=list(self.positions))

    @contextlib.contextmanager
    def execution(self, *, assignment):
        """Around one procedure execution: accepted state first; feedback skipped when reproducing."""
        if self._executing:
            yield 'NESTED'
            return
        self._executing = True
        try:
            with self._execution(assignment=assignment) as mode:
                yield mode
        finally:
            self._executing = False

    @contextlib.contextmanager
    def _execution(self, *, assignment):
        self.restore()
        if self.reproducing:
            self.counts['reproducing_runs'] += 1
            perf1 = parent_module('r1_15a2_acceleration_v24915p1')
            com = parent_module('r1_15a2_com_compat')
            keep = sorted(int(r['no']) for r in com.operation_rows(self.visum)
                          if int(r['active']) and int(r['no']) not in self.positions)
            try:
                with perf1.activate_operation_plan(self.visum, {'selected_operation_positions': keep}):
                    yield 'REPRODUCE_FEEDBACK_SKIPPED'
            finally:
                if assignment:
                    self.dirty |= {no for no, r in self.roles.items() if r != 'TD_UTILITY'}
        else:
            self.counts['feedback_runs'] += 1
            try:
                yield 'FEEDBACK_ACTIVE'
            finally:
                self.dirty |= ({no for no, r in self.roles.items() if r == 'TD_UTILITY'} if not assignment
                               else set(self.roles))

    def wrap_rollback(self, fn):
        def _rollback_candidate(*args, **kwargs):
            with self.reproduce():
                return fn(*args, **kwargs)
        _rollback_candidate.__wrapped__ = fn
        _rollback_candidate.__r1_live05_feedback__ = True
        return _rollback_candidate
