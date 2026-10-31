"""One precision-aware OD/path contract for capture AND sealed-cache replay.

Observed quantization is not physical missing traffic. No matrix or path volume
is rounded, scaled, clipped, imputed or changed here. Per-OD support checks and
independent gross/net/unsupported-volume caps prevent cancellation of losses.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass
import math
import numpy as np
from .common import require, canonical_hash

SCHEMA = 'CORDON_PATH_MATRIX_PARITY_V3'

@dataclass(frozen=True)
class ParityPolicy:
    atol: float = 1e-5
    rtol: float = 1e-5
    path_volume_quantum: float = 0.001
    lattice_atol: float = 1e-9
    missing_path_cell_atol: float = 0.0005
    aggregate_abs_floor: float = 0.01
    max_net_relative_error: float = 1e-4
    max_l1_relative_error: float = 1e-3
    max_zero_flow_relative_mass: float = 1e-4

    def __post_init__(self):
        for key, value in asdict(self).items():
            require(type(value) in (int, float) and math.isfinite(value) and value >= 0,
                    'INVALID_PARITY_POLICY:' + key)

    def record(self):
        return {'schema': SCHEMA, **asdict(self)}

    @classmethod
    def from_record(cls, record):
        require(isinstance(record, dict) and record.get('schema') == SCHEMA, 'PARITY_POLICY_SCHEMA')
        require(set(record) == {'schema', *cls.__dataclass_fields__}, 'PARITY_POLICY_FIELDS')
        return cls(**{k: v for k, v in record.items() if k != 'schema'})

    @classmethod
    def legacy(cls):
        # Older captures used a strict cell-wise comparison. Do not silently
        # reinterpret an existing sealed snapshot under a new numerical policy.
        return cls(atol=1e-6, rtol=1e-6, path_volume_quantum=0.,
                   missing_path_cell_atol=0., aggregate_abs_floor=1e-5,
                   max_net_relative_error=1e-6, max_l1_relative_error=1e-5,
                   max_zero_flow_relative_mass=1e-6)


def from_options(options):
    names = {'atol': 'od_parity_atol', 'rtol': 'od_parity_rtol',
             'path_volume_quantum': 'path_volume_quantum',
             'lattice_atol': 'path_volume_lattice_atol',
             'missing_path_cell_atol': 'missing_path_cell_atol',
             'aggregate_abs_floor': 'parity_aggregate_abs_floor',
             'max_net_relative_error': 'parity_max_net_relative_error',
             'max_l1_relative_error': 'parity_max_l1_relative_error',
             'max_zero_flow_relative_mass': 'parity_max_zero_flow_relative_mass'}
    defaults = asdict(ParityPolicy())
    return ParityPolicy(**{key: options.get(name, defaults[key]) for key, name in names.items()})


def lattice_error(db, code, policy):
    q = policy.path_volume_quantum
    if not q:
        return None
    # Sqlite ROUND is used only to MEASURE the source resolution, never to
    # rewrite stored volumes. A nonlattice export gets NO rounding allowance.
    r = db.execute('SELECT MAX(ABS(volume - ROUND(volume / ?, 0) * ?)) '
                   'FROM volumes WHERE dseg=?', (q, q, code)).fetchone()
    return float(r[0] or 0.)


def reconstruct(db, code, zone_nos, values):
    zones = np.asarray(zone_nos)
    require(zones.ndim == 1 and np.issubdtype(zones.dtype, np.integer)
            and (zones > 0).all() and len(zones) == len(set(zones.tolist())), 'PARITY_ZONE_IDENTITY')
    index = {int(z): i for i, z in enumerate(zones)}
    expected = np.asarray(values, dtype=float)
    require(expected.shape == (len(zones), len(zones)), 'PARITY_MATRIX_SHAPE')
    flows = np.zeros_like(expected)
    counts = np.zeros_like(expected, dtype=np.int64)
    rows = []
    query = ('SELECT g.orig,g.dest,SUM(v.volume),COUNT(*) FROM geometry g '
             'JOIN volumes v ON v.gid=g.gid WHERE v.dseg=? GROUP BY g.orig,g.dest')
    for o, d, volume, count in db.execute(query, (code,)):
        require(o in index and d in index, 'PATH_ZONE_NOT_IN_LIVE_MATRIX')
        flows[index[o], index[d]] = volume
        counts[index[o], index[d]] = count
        rows.append((o, d, volume))
    return flows, counts, rows


def compare(values, reconstructed, counts, zone_nos, code, policy, *, max_lattice_error=None, enforce_aggregate_checks=True):
    """Return diagnostics, not an optimistic pass from an aggregate total alone."""
    values = np.asarray(values, dtype=float)
    reconstructed = np.asarray(reconstructed, dtype=float)
    counts = np.asarray(counts)
    require(values.shape == reconstructed.shape == counts.shape == (len(zone_nos), len(zone_nos)), 'PARITY_SHAPE')
    require(np.isfinite(values).all() and (values >= 0).all(), 'PARITY_INVALID_MATRIX')
    require(np.isfinite(reconstructed).all() and (reconstructed >= 0).all(), 'PARITY_INVALID_PATH_VOLUME')
    require(np.issubdtype(counts.dtype, np.integer) and (counts >= 0).all(), 'PARITY_INVALID_PATH_COUNTS')
    require(not np.any((counts == 0) & (reconstructed > 0)), 'PARITY_VOLUME_WITHOUT_ROWS')
    if max_lattice_error is not None:
        require(math.isfinite(max_lattice_error) and max_lattice_error >= 0, 'PARITY_INVALID_LATTICE_EVIDENCE')
    quantized = bool(policy.path_volume_quantum and max_lattice_error is not None
                     and max_lattice_error <= policy.lattice_atol)
    quantum = policy.path_volume_quantum if quantized else 0.
    mask = ~np.eye(len(zone_nos), dtype=bool)
    delta = reconstructed - values
    err = np.abs(delta)
    # One half-quantum per ACTUALLY EXPORTED route, including zero-volume rows.
    rounding_bound = (0.5 * quantum) * counts
    allowed = policy.atol + policy.rtol * np.abs(values) + rounding_bound
    unsupported = counts == 0
    allowed[unsupported] = policy.atol + policy.rtol * values[unsupported] + policy.missing_path_cell_atol
    bad = np.argwhere(mask & (err > allowed))
    total = float(values[mask].sum(dtype=np.float64))
    saved = float(reconstructed[mask].sum(dtype=np.float64))
    l1 = float(err[mask].sum(dtype=np.float64))
    net = float(delta[mask].sum(dtype=np.float64))
    zero = mask & (reconstructed == 0) & (values > 0)
    no_rows = mask & unsupported & (values > 0)
    zero_mass = float(values[zero].sum(dtype=np.float64))
    # Aggregate only the UNEXPLAINED remainder against the residual caps.
    # Otherwise a low-volume segment is rejected again for entirely compatible
    # route-level rounding. Raw totals and the full uncertainty are still shown.
    excess = np.maximum(err - rounding_bound, 0.)
    excess_l1 = float(excess[mask].sum(dtype=np.float64))
    excess_net = float((np.sign(delta)*excess)[mask].sum(dtype=np.float64))
    unexplained_zero_mass = float(np.maximum(values-rounding_bound,0.)[zero].sum(dtype=np.float64))
    cap = lambda relative: max(policy.aggregate_abs_floor, relative * total)
    caps = {'net_absolute': cap(policy.max_net_relative_error),
            'l1_absolute': cap(policy.max_l1_relative_error),
            'zero_flow_mass': cap(policy.max_zero_flow_relative_mass)}
    failures = []
    if len(bad): failures.append('LOCAL_OD_RESIDUAL_EXCEEDS_PRECISION_ENVELOPE')
    if enforce_aggregate_checks and abs(excess_net) > caps['net_absolute']: failures.append('AGGREGATE_NET_VOLUME_MISMATCH')
    if enforce_aggregate_checks and excess_l1 > caps['l1_absolute']: failures.append('AGGREGATE_GROSS_VOLUME_MISMATCH')
    if enforce_aggregate_checks and unexplained_zero_mass > caps['zero_flow_mass']: failures.append('ZERO_FLOW_DEMAND_BUDGET_EXCEEDED')
    strict_bad = int(np.count_nonzero(mask & (err > 1e-6 + 1e-6 * values)))
    return {'dseg': code, 'status': 'FAIL' if failures else 'PASS', 'failures': failures,
        'basis': 'EACH_INTERZONAL_OD_MATRIX_CELL_VS_SUM_SAVED_PATH_VOLUMES',
        'policy': policy.record(), 'policy_sha256': canonical_hash(policy.record()),
        'quantization_compatible': quantized, 'observed_lattice_max_abs_error': max_lattice_error,
        'effective_path_volume_quantum': quantum, 'quantum_is_export_resolution_not_survey_tolerance': True,
        'max_abs_interzonal_error': float(err[mask].max(initial=0.)),
        'diagonal_error_not_hidden': float(np.diag(err).sum()),
        'matrix_interzonal_sum': total, 'saved_path_interzonal_sum': saved,
        'net_path_minus_matrix': net, 'sum_absolute_od_error': l1,
        'aggregate_check_basis':'RESIDUAL_BEYOND_VERIFIED_PATH_QUANTIZATION_ENVELOPE',
        'quantization_absolute_error_bound_sum':float(rounding_bound[mask].sum()),
        'rounding_explained_l1_error':l1-excess_l1,
        'unexplained_l1_error':excess_l1, 'unexplained_signed_net_error':excess_net,
        'unexplained_zero_flow_demand_mass':unexplained_zero_mass,
        'raw_errors_above_residual_limits':bool(abs(net)>caps['net_absolute'] or l1>caps['l1_absolute'] or zero_mass>caps['zero_flow_mass']),
        'aggregate_limits': caps, 'aggregate_checks_applied':bool(enforce_aggregate_checks), 'strict_legacy_inconsistent_od_count': strict_bad,
        'missing_or_inconsistent_od_count': len(bad),
        'positive_matrix_zero_path_flow_count': int(np.count_nonzero(zero)),
        'positive_matrix_zero_path_flow_mass': zero_mass,
        'positive_matrix_no_path_rows_count': int(np.count_nonzero(no_rows)),
        'positive_matrix_no_path_rows_mass': float(values[no_rows].sum()),
        'rounding_only_cells_accepted': max(0, strict_bad-len(bad)),
        'warnings': (['NUMERIC_EXPORT_RESIDUAL_WITHIN_BUDGET'] if not failures and strict_bad else [])
                    + (['TINY_OD_WITHOUT_PATH_ROWS'] if np.any(no_rows) else []),
        'sample_errors': [{'origin': int(zone_nos[i]), 'destination': int(zone_nos[j]),
            'matrix': float(values[i,j]), 'paths': float(reconstructed[i,j]),
            'path_count': int(counts[i,j]), 'allowed_abs_error': float(allowed[i,j])}
            for i,j in bad[:20]],
        'raw_matrix_and_paths_modified': False, 'apply_permitted': False}


def compare_database(db, code, values, zone_nos, policy):
    flows, counts, rows = reconstruct(db, code, zone_nos, values)
    report = compare(values, flows, counts, zone_nos, code, policy,
                     max_lattice_error=lattice_error(db, code, policy))
    return report, rows
