"""LIVE03 cordon diagnostics: survey observation contract (FIRST_LAST + C17 rows).

Same capture/parity/objective machinery as LIVE02 (CordonEvaluator); only the
enumeration methods, the observation aggregation (live03_observations) and the
authorized blocks differ.  The frozen share operator of every method is kept
on the incidence for the native frozen-path predictor.
"""
from __future__ import annotations
from .live02_evaluation import CordonEvaluator
from .live03_observations import aggregate

BLOCKS = ('GENERATION', 'TD_CORDON')


class Live03Evaluator(CordonEvaluator):
    def __init__(self, live03, mathcfg, contract, opt, control, baseline_pre):
        super().__init__(live03, mathcfg, None, opt, control, baseline_pre)
        self.contract = contract
        self.methods = tuple(contract.enumeration)
        self.extra_mathcfg = contract.mathcfg_extension()
        self.method = contract.primary
        self.secondary = contract.secondary
        from .live03_incidence import build_from_snapshot
        self.build_incidence = build_from_snapshot

    def aggregate_method(self, directed, method):
        return aggregate(directed, self.contract, method)

    def authorized_blocks(self):
        return BLOCKS
