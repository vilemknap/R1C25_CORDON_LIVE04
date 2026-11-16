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
        # LIVE05: extra observation links join the trial-capture station cross-check
        from . import live04_capture
        live04_capture.EXTRA_CROSSCHECK_LINKS.clear()
        extra = getattr(self.contract, 'extra_links', None)
        if extra is not None:
            live04_capture.EXTRA_CROSSCHECK_LINKS.update({k: True for k in extra()})

    def authorized_blocks(self):
        return BLOCKS

    def block_gate(self, block, before, after, rows):
        decision = super().block_gate(block, before, after, rows)
        acc = self.live02['acceptance']
        if block == 'GENERATION' and 'generation_secondary_max_relative_degradation' in acc:
            limit = float(acc['generation_secondary_max_relative_degradation'])
            decision['secondary_max_relative_degradation'] = limit
            degradation = decision.get('secondary_relative_degradation')
            if degradation is not None:
                reasons = [r for r in decision['reasons'] if r != 'SECONDARY_METHOD_DEGRADED']
                if degradation > limit:
                    reasons.append('SECONDARY_METHOD_DEGRADED')
                decision['reasons'] = reasons
                decision['accepted'] = not reasons
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
