"""LIVE03 native prediction on frozen paths (replaces the linear step prediction).

A candidate (TG rows at a scale, or TD b/c rows) is written to Visum and ONLY the
demand part of the phase plan is executed natively: the PERF1 operation slice of
the block truncated before the first approved assignment (assignments of any
kind are never run here, so saved paths and link volumes stay those of the
accepted state).  The 12 OA demand-segment matrices are read and multiplied by
the frozen share operator of the accepted saved paths (all dsegs, all OD pairs),
which gives the predicted cordon rows of every method:

    m_row(candidate) = sum_k share_k(accepted paths) * Q_k(candidate, native TG/TD)

The only approximation left is route choice (congestion); demand responds
exactly (native TG/TD/matrix operations, including non-linear gravity and
balancing).  OD cells with positive new demand but no accepted path are
reported as unsupported volume.  Restoring after a probe = parameter restore
by COM + the same demand-only slice, verified by snapshot equality.

ANCHORING (LIVE04.5.1).  Visum stores path volumes on a 0.001 lattice while
the OD matrices are full precision, so share * Q of the parent matrices is not
bit-identical to the captured rows (live run 2026-11-03: max 0.59 % on a small
row).  The predictor is therefore anchored on the captured rows:

    m_row(candidate) = m_row(captured) + F(Q_candidate) - F(Q_parent)

which reproduces the parent exactly and carries only the native demand change.
The raw deviation F(Q_parent) - m_row(captured) is reported and bounded by a
sanity limit (a larger value means the paths do not belong to the matrices).
The parent model state itself is proven separately by snapshot equality.
"""
from __future__ import annotations
import hashlib
import time
from pathlib import Path
import numpy as np
from .common import require, parent_module
from .io import write_json, mkdir

SCHEMA = 'LIVE03_NATIVE_FROZEN_PATH_PREDICTION_V1'
ASSIGNMENT_TYPES = (100, 101)
# Raw base deviation allowed by path-volume quantization (relative with a 10 vehicle
# floor, and a 0.25 % bound on each method total).  Above it the frozen shares
# do not describe the parent matrices and prediction stops.
RAW_ROW_RELATIVE_LIMIT = 0.05
RAW_ROW_FLOOR = 10.0
RAW_TOTAL_RELATIVE_LIMIT = 0.0025


class PredictionError(RuntimeError):
    pass


def demand_plan(visum, cfg, block):
    """PERF1 plan of the block, truncated before the first approved assignment."""
    perf1 = parent_module('r1_15a2_acceleration_v24915p1')
    com = parent_module('r1_15a2_com_compat')
    plan = perf1.phase_recompute_plan(visum, cfg, block)
    inventory = plan['inventory']
    approved = sorted(int(r['no']) for r in (cfg.get('supply', {}).get('assignment_operations') or []))
    require(approved, 'LIVE03_DEMAND_PLAN_NO_APPROVED_ASSIGNMENT')
    first = min(approved)
    types = {int(r['no']): int(r['type']) for r in inventory}
    selected = [int(p) for p in plan['selected_operation_positions']]
    groups = [p for p in selected if types.get(p) == com.GROUP]
    other_assign = [p for p in selected if p < first and types.get(p) in ASSIGNMENT_TYPES]
    demand = sorted({p for p in selected if p < first and types.get(p) not in ASSIGNMENT_TYPES} | set(groups))
    require(any(types.get(p) in (com.TG, com.TD) for p in demand), 'LIVE03_DEMAND_PLAN_HAS_NO_TG_TD_OPERATION')
    out = dict(plan, schema=SCHEMA + '_PLAN', block='DEMAND_ONLY:' + str(block), mode='DEMAND_PREFIX_BEFORE_FIRST_ASSIGNMENT',
               selected_operation_positions=demand, source_plan_mode=plan.get('mode'),
               first_approved_assignment=first, excluded_assignment_positions=sorted(set(selected) - set(demand)),
               skipped_other_assignments_in_prefix=other_assign,
               approved_assignment_positions=[])
    out['exact_demand_of_full_trial'] = not other_assign and len(approved) == 1
    return out


class FrozenPathPredictor:
    def __init__(self, adapter, diag, folder, *, tolerance=1.0e-6):
        self.adapter = adapter
        self.evaluator = adapter.evaluator
        self.methods = tuple(self.evaluator.methods)
        self.folder = Path(folder); mkdir(self.folder)
        require(diag.get('valid', True) and '_incidence' in diag, 'LIVE03_PREDICTOR_NEEDS_VALID_DIAGNOSTIC')
        self.frozen = {m: diag['_incidence'][m].frozen for m in self.methods}
        require(all(f is not None for f in self.frozen.values()), 'LIVE03_FROZEN_SHARE_NOT_CAPTURED')
        pre = diag['_pre']
        self.zone_nos = list(pre[2]); self.dsegs = list(pre[4])
        self.m0 = {m: np.asarray(diag['methods'][m]['model'], dtype=float) for m in self.methods}
        self.tolerance = float(tolerance)
        self.offset = None              # m_row(captured) - F(Q_parent), set by base_parity()
        self.calls = 0; self.seconds = 0.0; self.records = []
        n = len(self.zone_nos)
        pos = {z: i for i, z in enumerate(self.zone_nos)}
        any_frozen = next(iter(self.frozen.values()))
        self.support = {}
        for code, keys in any_frozen.supported_od.items():
            mask = np.zeros((n, n), dtype=bool)
            if keys:
                ij = np.array([(pos[o], pos[d]) for o, d in keys], dtype=np.int64)
                mask[ij[:, 0], ij[:, 1]] = True
            self.support[code] = mask

    # ------------------------------------------------------------- reading
    def read_matrices(self):
        from .visum_startup import _matrix
        ev = self.evaluator
        out = {}
        for ds in self.dsegs:
            arr, _ = _matrix(ds, len(self.zone_nos), ev.control, ev.opt)
            out[ds['norm_code']] = arr
        return out

    def raw_rows(self, matrices):
        return {m: self.frozen[m].predict(matrices, self.zone_nos) for m in self.methods}

    def predict_from(self, matrices, label):
        require(self.offset is not None, 'LIVE03_PREDICTOR_BASE_PARITY_NOT_RUN')
        raw = self.raw_rows(matrices)
        rows = {m: raw[m] + self.offset[m] for m in self.methods}
        unsupported = {}
        for code, arr in matrices.items():
            mask = self.support.get(code)
            if mask is None:
                continue
            unsupported[code] = float(arr[(~mask) & (arr > 0)].sum())
        total = float(sum(float(a.sum()) for a in matrices.values()))
        audit = {'label': label, 'unsupported_volume': float(sum(unsupported.values())),
                 'unsupported_by_dseg': unsupported, 'total_volume': total,
                 'unsupported_share': float(sum(unsupported.values()) / total) if total > 0 else 0.0}
        return rows, audit

    def base_parity(self):
        """Anchor on the captured rows (parent matrices, before any write) and prove it.

        The anchored prediction of the parent must equal the captured rows within
        ``tolerance``; the raw share * Q deviation (path-volume quantization) must
        stay inside the RAW_* sanity limits."""
        matrices = self.read_matrices()
        raw = self.raw_rows(matrices)
        dev = {m: raw[m] - self.m0[m] for m in self.methods}
        raw_row = {m: float(np.max(np.abs(dev[m]) / np.maximum(RAW_ROW_FLOOR, np.abs(self.m0[m])), initial=0.0))
                   for m in self.methods}
        raw_total = {m: float(abs(dev[m].sum()) / max(1.0, float(np.abs(self.m0[m]).sum()))) for m in self.methods}
        raw_abs = {m: float(np.max(np.abs(dev[m]), initial=0.0)) for m in self.methods}
        raw_err = {m: float(np.max(np.abs(dev[m]) / np.maximum(1.0, np.abs(self.m0[m])), initial=0.0))
                   for m in self.methods}
        self.offset = {m: self.m0[m] - raw[m] for m in self.methods}
        rows, audit = self.predict_from(matrices, 'BASE_PARITY')
        err = {m: float(np.max(np.abs(rows[m] - self.m0[m]) / np.maximum(1.0, np.abs(self.m0[m])), initial=0.0))
               for m in self.methods}
        raw_ok = all(raw_row[m] <= RAW_ROW_RELATIVE_LIMIT and raw_total[m] <= RAW_TOTAL_RELATIVE_LIMIT
                     for m in self.methods)
        audit.update(mode='ANCHORED_ON_CAPTURED_ROWS', max_relative_error=err,
                     raw_share_times_matrix_deviation={
                         'max_relative_error_floor_1': raw_err, 'max_relative_error_floor_10': raw_row,
                         'max_abs_vehicles': raw_abs, 'total_relative': raw_total,
                         'limits': {'row_relative': RAW_ROW_RELATIVE_LIMIT, 'row_floor': RAW_ROW_FLOOR,
                                    'total_relative': RAW_TOTAL_RELATIVE_LIMIT},
                         'cause': 'PATH_VOLUME_LATTICE_0.001_VS_FULL_PRECISION_MATRIX', 'passes': raw_ok},
                     passes=raw_ok and all(v <= self.tolerance for v in err.values()))
        write_json(self.folder / 'PREDICTOR_BASE_PARITY.json', audit)
        if not raw_ok:
            self.offset = None
        require(raw_ok, 'LIVE03_PREDICTOR_RAW_SHARE_DEVIATION_TOO_LARGE:' + str({'row': raw_row, 'total': raw_total}))
        require(audit['passes'], 'LIVE03_PREDICTOR_BASE_PARITY_FAIL:' + str(err))
        return audit

    # ------------------------------------------------------------ execution
    def run_demand(self, block, folder):
        perf1 = parent_module('r1_15a2_acceleration_v24915p1')
        rt = parent_module('r1_15a2_runtime_v1')
        folder = Path(folder); mkdir(folder)
        plan = demand_plan(self.adapter.visum, self.adapter.cfg, block)
        write_json(folder / 'DEMAND_ONLY_PLAN.json', plan)
        t0 = time.monotonic()
        hook = getattr(self.adapter, 'execute_demand_only', None)
        if hook is not None:
            # LIVE04: the adapter owns phased execution (v7 LONG post-TD mask).
            write_json(folder / 'DEMAND_ONLY_EXECUTION.json', hook(plan, folder))
        else:
            with perf1.activate_operation_plan(self.adapter.visum, plan) as active:
                write_json(folder / 'DEMAND_ONLY_PLAN_ACTIVE.json', active)
                rt.execute_procseq(self.adapter.visum, folder)
        self.seconds += time.monotonic() - t0
        self.calls += 1
        return plan

    def probe(self, block, label, folder):
        """Native demand for the parameters currently written + frozen-path prediction."""
        folder = Path(folder); mkdir(folder)
        plan = self.run_demand(block, folder)
        matrices = self.read_matrices()
        rows, audit = self.predict_from(matrices, label)
        audit.update(exact_demand_of_full_trial=plan['exact_demand_of_full_trial'],
                     matrix_sha256={c: hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()
                                    for c, a in matrices.items()})
        self.records.append(dict(audit, block=block))
        write_json(folder / 'NATIVE_PREDICTION.json', dict(audit, rows={m: rows[m].tolist() for m in self.methods}))
        return rows, matrices, audit

    def restore_demand(self, block, state, folder):
        """After parameters are restored by COM: same demand slice, prove the parent state."""
        self.run_demand(block, folder)
        snap = self.adapter.snapshot()
        same = snap == state
        write_json(Path(folder) / 'DEMAND_RESTORE_PROOF.json', {
            'schema': SCHEMA + '_RESTORE', 'snapshot_equal': same, 'state_hash': snap.get('state_hash'),
            'expected_state_hash': state.get('state_hash'),
            'matrix_hash_equal': snap.get('matrix_hash') == state.get('matrix_hash')})
        require(same, 'LIVE03_DEMAND_RESTORE_SNAPSHOT_DIFFERS')
        return snap

    def summary(self):
        return {'schema': SCHEMA, 'demand_only_executions': self.calls, 'seconds': self.seconds,
                'probes': [{k: r.get(k) for k in ('label', 'block', 'unsupported_share', 'exact_demand_of_full_trial')}
                           for r in self.records]}


def objective_vector(evaluator, diag, rows):
    """Predicted diagnostic in the gate schema from predicted row vectors."""
    from .live02_evaluation import objective_from_model
    out = {'valid': True, 'methods': {}, 'source': 'NATIVE_FROZEN_PATH_PREDICTION'}
    for m in evaluator.methods:
        v = np.maximum(np.asarray(rows[m], dtype=float), 0.0)
        total, _, _, metrics = objective_from_model(diag['_terms'][m], v)
        out['methods'][m] = {'objective': total, 'metrics': metrics, 'model': v.tolist()}
    return out


def same_parameters(snap, state):
    return snap.get('generation_hash') == state.get('generation_hash') and snap.get('td_hash') == state.get('td_hash') \
        and snap.get('addval_hash') == state.get('addval_hash')


def probe_generation_nodes(base, adapter, context, state, diag, folder, ncfg, opts, control, *, restore_each=False):
    """Native TG nodes for STEP1: write rows at s, demand-only run, predict, restore by COM.

    Returns ({s: {method: rows}}, info).  After the call the TG/TD parameters equal
    the parent; the demand matrices hold the last probe until the next recompute
    (info['model_mutated']; the STEP1 block owns the final demand restore).
    restore_each (LIVE04): after every node the demand is recomputed with the parent
    parameters and the exact parent snapshot is proven, so the next node and the
    first trial start from the verified parent (TG outputs such as FP_* included)."""
    txm = parent_module('r1_15a2_inplace_transaction_v24915p2')
    supply = parent_module('r1_15a2_supply_visum')
    folder = Path(folder); mkdir(folder)
    pred = FrozenPathPredictor(adapter, diag, folder, tolerance=float(ncfg.get('base_parity_tolerance', 1e-6)))
    info = {'schema': SCHEMA + '_TG_NODES', 'nodes': [], 'model_mutated': False,
            'base_parity': pred.base_parity()}
    nodes = {}
    upper = float(opts['max_scale'])
    for k, frac in enumerate(ncfg.get('tg_node_fractions') or []):
        s = round(float(frac) * upper, 6)
        nf = folder / ('NODE_%02d' % (k + 1))
        preview, rows = base._planned_generation_rows(adapter, context, s)
        rows = list(rows or [])
        node = {'scale': s, 'rows': len(rows)}
        if not rows:
            node['status'] = 'NO_ROWS'; info['nodes'].append(node); continue
        gate = supply.base.generation_apply_gate(preview, adapter.cfg)
        mobility = preview.get('genfix2_mobility') if isinstance(preview, dict) else None
        if mobility is not None and mobility.get('passes') is not True:
            # LIVE04 (v7 GENFIX2): the final MOBILITY2 envelope is part of the pre-apply gate.
            gate = dict(gate, passes=False, reasons=list(gate.get('reasons') or []) + ['MOBILITY2_FINAL_ENVELOPE'])
        if not gate['passes']:
            node.update(status='PRE_APPLY_GATE_REJECTED', reasons=gate['reasons'][:6]); info['nodes'].append(node); continue
        control.checkpoint('LIVE03_NATIVE_TG_PROBE', force=True, scale=s)
        info['model_mutated'] = True
        written = rows
        try:
            written = list(adapter.apply_generation(context, s, nf) or rows)
            predicted, _, audit = pred.probe('GENERATION', 'TG_SCALE_%s' % s, nf)
        finally:
            txm.restore_generation_parameters(adapter, state, written, nf / 'RESTORE_PARAMETERS')
        if restore_each:
            pred.restore_demand('GENERATION', state, nf / 'RESTORE_DEMAND')
            info['model_mutated'] = False
        nodes[s] = predicted
        node.update(status='NATIVE', unsupported_share=audit['unsupported_share'],
                    exact_demand_of_full_trial=audit['exact_demand_of_full_trial'])
        info['nodes'].append(node)
    snap = adapter.snapshot()
    require(same_parameters(snap, state), 'LIVE03_TG_PROBE_PARAMETER_RESTORE_FAILED')
    info['demand_differs_from_parent'] = snap.get('matrix_hash') != state.get('matrix_hash')
    info['predictor'] = pred.summary()
    write_json(folder / 'TG_NATIVE_NODES.json', info)
    info['_predictor'] = pred
    return nodes, info
