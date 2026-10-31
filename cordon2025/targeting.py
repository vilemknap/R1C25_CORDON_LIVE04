"""Read-only targeting context; exact cordon incidence remains count authority."""
from __future__ import annotations
from collections import defaultdict
import numpy as np
from .common import require, parent_module, canonical_hash
from .incidence import validate_roles


def path_targeting_report(inc, *, max_zones=128):
    """Signed, CAL-only search hints; no volume changes, no threshold relaxation.

    PROFILE488 FlowBundle targets are deliberately not imported. The same
    donor architecture (support + optional DIST_KM context separate from
    acceptance) is fed from the actual cordon operator instead.
    """
    validate_roles(inc.rows)
    require(isinstance(max_zones, int) and max_zones >= 0, 'INVALID_TARGET_ZONE_LIMIT')
    under = np.zeros(len(inc.rows)); over = np.zeros(len(inc.rows))
    for i, row in enumerate(inc.rows):
        if row['role'] != 'CALIBRATION':
            continue
        observed = float(row['observed'])
        require(np.isfinite(observed) and observed >= 0, 'INVALID_CAL_TARGET')
        residual = observed - float(inc.model[i])
        scale = max(1.0, observed)
        under[i] = max(residual, 0.0) / scale
        over[i] = max(-residual, 0.0) / scale
    upward = inc.operator.transpose(under)
    downward = inc.operator.transpose(over)
    zones = defaultdict(lambda: [0.0, 0.0]); families = defaultdict(lambda: [0.0, 0.0])
    for variable, up, down in zip(inc.variables, upward, downward):
        for key in ('origin', 'destination'):
            zones[int(variable[key])][0] += float(up) / 2
            zones[int(variable[key])][1] += float(down) / 2
        family = variable['family']
        families[family][0] += float(up); families[family][1] += float(down)
    ranked = sorted(zones.items(), key=lambda x: (-sum(x[1]), x[0]))
    rows = [{'zone': z, 'upward_pressure': p[0], 'downward_pressure': p[1],
             'signed_pressure': p[0] - p[1]} for z, p in ranked if sum(p) > 0][:max_zones]
    result = {'status': 'READ_ONLY_PATH_TARGETING_CONTEXT', 'zone_rankings': rows,
              'family_pressures': dict(families), 'uses_validation': False,
              'authority': 'ACTUAL_CORDON_INCIDENCE', 'flowbundle_used_as_count_authority': False,
              'changes_candidate_order': False, 'changes_objective': False,
              'applies_to_fixed_segments': False, 'apply_permitted': False}
    result['context_sha256'] = canonical_hash(result)
    return result


def seal_distance_context(*, values, zone_nos, matrix_no, matrix_code, unit='km'):
    """Reuse V24916 sealed skim identity exactly, without invoking COM."""
    module = parent_module('r1_15a2_skim_v24916p2c')
    return module.seal_dist_km(values=values, zone_nos=zone_nos, matrix_no=matrix_no,
                               matrix_code=matrix_code, unit=unit, exact_expected_code=matrix_code)


def td_component_context(family_pressure, idp_errors, component_family, *, diagnostic_only=()):
    module = parent_module('r1_15a2_demand_support_v24916p2c')
    return module.build_td_component_pressure(family_pressure, idp_errors, component_family,
                                               diagnostic_only_components=diagnostic_only)
