"""LIVE04.4 cordon evaluator: LIVE03 diagnostics + SEVRELAX3 on the cordon rows + SupplyMix scope.

The evaluator gate is used by the STEP1 / TD planning gates (predicted
diagnostics) and by every native trial (through the adapter), so the per-row GEH
limits and the scoped severity budgets apply with ONE configuration to the
prediction and to the final acceptance, as in v7 (SEVRELAX3).
"""
from __future__ import annotations
from .live03_evaluation import Live03Evaluator, BLOCKS as LIVE03_BLOCKS
from . import live04_severity as sev

BLOCKS = LIVE03_BLOCKS + ('SUPPLY_ADDVAL1',)


class Live04Evaluator(Live03Evaluator):
    def __init__(self, *args, row_guard_policy=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.row_guard_policy = row_guard_policy

    def authorized_blocks(self):
        return BLOCKS

    def block_gate(self, block, before, after, rows):
        decision = super().block_gate(block, before, after, rows)
        policy = self.row_guard_policy
        if policy is None or not policy.get('enabled'):
            return decision
        if not (before.get('valid', True) and after.get('valid', True)):
            return decision
        guard = sev.gate(before, after, block, self.method, policy)
        decision['row_geh_guard'] = guard
        if not guard['passes']:
            decision['accepted'] = False
            decision['reasons'] = list(decision.get('reasons') or []) + list(guard['reasons'])
        return decision
