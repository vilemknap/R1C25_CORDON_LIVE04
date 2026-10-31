"""v7 LONG post-TD mask (>= 80 km on R1_OSRM_DIST_KM 9697) inside every cordon execution.

v7 (r1_15a2_long_post_td_mask_v24917) pauses every procedure run after the
unified TD operation, multiplies the LONG person matrices 9111..9115 by the
support mask, pauses again before the first assignment, multiplies the LONG
vehicle components 9291..9295 and verifies the FORMULA aggregate 9305.  The
cordon calibrator must see exactly the same demand, so:

* full executions (trial, rollback, restore) go through the unchanged donor
  ``execute_sequence`` - this module installs the same rt.execute_procseq hook
  as the donor ``install`` but only for the lifetime of one cordon run and
  WITHOUT the FineCDF-bridge patch (the cordon TD block does not use it);
* demand-only executions of the native predictor (no assignment at all, which
  the donor sequence deliberately rejects) use ``execute_demand_only``: the
  same THROUGH_TD / REALIZATION phases and the same donor ``apply_group``
  writes, then the donor support verification;
* ``support_report`` is a read-only audit (donor ``measure`` on 9697), used to
  require an already-masked baseline and to verify every accepted state.

No P/A repair, no renormalization, volume loss accepted (v7 user decision).
"""
from __future__ import annotations
import functools
from pathlib import Path
from .common import require, parent_module
from .io import write_json, mkdir

SCHEMA = 'LIVE04_LONG_POST_TD_MASK_V1'


def _mask_module():
    return parent_module('r1_15a2_long_post_td_mask_v24917')


def install_scoped(rt):
    """Install the donor execute_procseq hook; returns (status, restore)."""
    mask = _mask_module()
    old = rt.execute_procseq
    if getattr(old, '_long_post_td_mask', False):
        return {'installed': True, 'already': True}, (lambda: None)

    @functools.wraps(old)
    def execute(visum, folder):
        adapter = mask._SCOPE.get()
        if adapter is None or adapter.visum is not visum:
            return old(visum, folder)
        return mask.execute_sequence(adapter, folder, old)
    execute._long_post_td_mask = True
    execute._live04_scoped = True
    rt.execute_procseq = execute

    def restore():
        if rt.execute_procseq is execute:
            rt.execute_procseq = old
    lg = parent_module('r1_15a2_long_distance_guard_v24917')
    status = {'installed': True, 'already': False, 'method': 'POST_TD_MULTIPLICATION_ACCEPT_VOLUME_LOSS',
              'minimum_km': lg.MIN_KM, 'maximum_km': None, 'distance_matrix': 9697,
              'person_matrices': list(lg.MATRIX_NOS),
              'vehicle_matrices': list(parent_module('r1_15a2_long_profile_incidence_v24917').COMPONENT_MATRICES),
              'vehicle_aggregate': parent_module('r1_15a2_long_profile_incidence_v24917').FINAL_MATRIX,
              'finecdf_bridge_patched': False, 'scope': 'ONE_CORDON_RUN_RESTORED_ON_EXIT'}
    return status, restore


def execute_demand_only(adapter, plan, folder, original_execute):
    """Masked demand-only execution of a PERF1 demand prefix (no assignment).

    ``plan`` is the LIVE03 demand plan (selected positions before the first
    approved assignment).  Phases: positions <= TD, mask person LONG; positions
    after TD, mask vehicle LONG + verify the FORMULA aggregate; final support
    verification.  Without a TD leaf the prefix runs as one phase and the
    support must already hold (nothing produces new LONG person demand).
    """
    mask = _mask_module()
    lg = parent_module('r1_15a2_long_distance_guard_v24917')
    li = parent_module('r1_15a2_long_profile_incidence_v24917')
    com = parent_module('r1_15a2_com_compat')
    perf1 = parent_module('r1_15a2_acceleration_v24915p1')
    folder = Path(folder); mkdir(folder)
    distance, source = parent_module('r1_15a2_long_support_distance_v24917').read_current(adapter)
    support = distance >= lg.MIN_KM
    inventory = com.operation_rows(adapter.visum)
    types = {int(r['no']): int(r['type']) for r in inventory}
    selected = sorted(int(p) for p in plan['selected_operation_positions'])
    groups = sorted(p for p in selected if types.get(p) == com.GROUP)
    leaves = [p for p in selected if types.get(p) != com.GROUP]
    require(not any(types.get(p) == com.ASSIGNMENT_PRT for p in leaves), 'LIVE04_DEMAND_ONLY_PLAN_CONTAINS_ASSIGNMENT')
    td = [p for p in leaves if types.get(p) == com.TD]
    require(len(td) <= 1, 'LIVE04_LONGMASK_EXPECTED_ONE_UNIFIED_TD_OPERATION')
    all_long = lg.MATRIX_NOS + li.COMPONENT_MATRICES + (li.FINAL_MATRIX,)
    if td:
        phases = [('THROUGH_TD', [p for p in leaves if p <= td[0]])]
        after = [p for p in leaves if p > td[0]]
        if after:
            phases.append(('REALIZATION', after))
    else:
        phases = [('DEMAND_NO_TD', leaves)]
        mask._verify_support(adapter, support, all_long)
    write_json(folder / 'LONG_MASK_DEMAND_ONLY_PLAN.json', {
        'schema': SCHEMA + '_DEMAND_ONLY', 'source': source, 'phases': phases,
        'td_operation_position': td[0] if td else None, 'groups': groups,
        'operation_definitions_unchanged': True, 'volume_loss_accepted': True,
        'assignment_executed': False})
    for name, positions in phases:
        sub = {'selected_operation_positions': sorted(set(positions) | set(groups))}
        with perf1.activate_operation_plan(adapter.visum, sub):
            original_execute(adapter.visum, folder / name)
        parent_module('r1_15a2_long_support_distance_v24917').read_current(adapter)
        if name == 'THROUGH_TD':
            mask.apply_group(adapter, support, lg.MATRIX_NOS, folder / 'MASK_PERSON_LONG')
        elif name == 'REALIZATION':
            mask.apply_group(adapter, support, li.COMPONENT_MATRICES, folder / 'MASK_VEHICLE_LONG',
                             aggregate_no=li.FINAL_MATRIX)
    if td and len(phases) == 1:
        # TD ran but no realization operation followed in this prefix: the vehicle
        # matrices were not recomputed; person support must hold now.
        mask._verify_support(adapter, support, lg.MATRIX_NOS)
    else:
        mask._verify_support(adapter, support, all_long)
    return {'phases': [p[0] for p in phases], 'td_operation_position': td[0] if td else None}


def support_report(adapter, folder=None, label='CURRENT'):
    """Read-only LONG support audit on the fixed OSRM distance (donor measure)."""
    mask = _mask_module()
    lg = parent_module('r1_15a2_long_distance_guard_v24917')
    li = parent_module('r1_15a2_long_profile_incidence_v24917')
    hash_ = parent_module('r1_15a2_path_incidence_v24917').matrix_values_hash
    distance, source = parent_module('r1_15a2_long_support_distance_v24917').read_current(adapter)
    support = distance >= lg.MIN_KM
    person = {no: mask._read(adapter, no)[1] for no in lg.MATRIX_NOS}
    proof = lg.measure(distance, person)
    vehicle = {}
    for no in li.COMPONENT_MATRICES + (li.FINAL_MATRIX,):
        values = mask._read(adapter, no)[1]
        require(values.shape == support.shape, 'LIVE04_LONG_VEHICLE_SHAPE:%d' % no)
        vehicle[str(no)] = {'total': float(values.sum()), 'below_min_km': float(values[~support].sum()),
                            'sha256': hash_(values)}
    vehicle_clean = all(v['below_min_km'] <= lg.MASS_ATOL for v in vehicle.values())
    report = {'schema': SCHEMA + '_SUPPORT', 'label': label, 'distance_source': source,
              'person': {k: proof[k] for k in ('status', 'total_volume', 'below_min_km', 'below_min_share',
                                                'support_clean', 'by_matrix')},
              'person_sha256': {str(no): hash_(a) for no, a in person.items()},
              'vehicle': vehicle, 'vehicle_support_clean': vehicle_clean,
              'support_clean': bool(proof['support_clean'] and vehicle_clean),
              '_measure': proof}
    if folder is not None:
        write_json(Path(folder) / ('LONG_SUPPORT_%s.json' % label), {k: v for k, v in report.items() if k != '_measure'})
    return report


def decide(parent, candidate):
    """Donor LONGGUARD1 decision for a candidate that never changes LONG coefficients."""
    lg = parent_module('r1_15a2_long_distance_guard_v24917')
    out = lg.decide(parent['_measure'], candidate['_measure'], changed_long=False)
    if not candidate['vehicle_support_clean']:
        out = dict(out, passes=False, reasons=list(out.get('reasons') or []) + ['LIVE04_LONG_VEHICLE_SUPPORT_NOT_CLEAN'])
    return out
