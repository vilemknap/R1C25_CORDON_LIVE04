"""Auditable practical numerical controls, separate from data identity/physics.

PRACTICAL_V1 relaxes numerical accuracy and resource quotas, NOT observations,
C17 budgets, fixed demand, path identities or unimplemented live actions.
"""
import math
from .common import require

NUMERICAL = {
    'internal_sum_atol': 1e-6, 'internal_sum_rtol': 1e-8,
    'c17_solver_tolerance': 1e-7, 'c17_projection_tolerance': 1e-8,
    'feasibility_atol': 0.001, 'feasibility_rtol': 1e-6,
    'feasibility_solver_tolerance': 1e-10, 'feasibility_kkt_tolerance': 1e-5,
    'objective_comparison_atol': 1e-8, 'objective_comparison_rtol': 1e-10,
    'generation_min_relative_improvement': 1e-6,
    'td_min_relative_improvement': 5e-5,
}
LEGACY = dict(NUMERICAL, internal_sum_atol=1e-8, internal_sum_rtol=1e-10,
    c17_solver_tolerance=1e-9, c17_projection_tolerance=1e-11,
    feasibility_atol=1e-5, feasibility_rtol=0., feasibility_solver_tolerance=1e-14,
    feasibility_kkt_tolerance=1e-6, objective_comparison_atol=1e-10,
    objective_comparison_rtol=0., generation_min_relative_improvement=1e-5,
    td_min_relative_improvement=5e-4)


def numerical(cfg=None):
    cfg = cfg or {}
    profile = cfg.get('limit_profile', 'LEGACY_STRICT')
    require(profile in ('LEGACY_STRICT', 'PRACTICAL_V1'), 'UNKNOWN_LIMIT_PROFILE')
    result = dict(NUMERICAL if profile == 'PRACTICAL_V1' else LEGACY)
    overrides = cfg.get('numerical_limits', {})
    require(isinstance(overrides, dict) and not set(overrides)-set(result), 'UNKNOWN_NUMERICAL_LIMIT')
    result.update(overrides)
    for key, value in result.items():
        require(type(value) in (int,float) and math.isfinite(value) and value>=0,
                'INVALID_NUMERICAL_LIMIT:' + key)
    require(all(result[key]>0 for key in ('c17_solver_tolerance','c17_projection_tolerance',
            'feasibility_atol','feasibility_solver_tolerance','feasibility_kkt_tolerance')),
            'ZERO_CONVERGENCE_TOLERANCE')
    return result
