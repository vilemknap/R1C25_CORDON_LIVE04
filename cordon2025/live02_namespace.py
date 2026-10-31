"""Run the ORIGINAL donor TG transaction code with the cordon objective.

No donor file is modified and no module global is patched.  Each donor
function is re-created from its own code object in a private copy of its module
namespace in which only the profile-specific names are replaced:

* ``ledger``          -> cordon whole-matrix objective (live assignment result)
* ``diagnostic_hash`` -> cordon diagnostic identity (120 pairs x 2 methods)

``_evaluate_candidate`` is additionally wrapped by the unchanged DIAGFAST_V2
TGFIX ``wrap_evaluate`` (pre-apply GENERATION_GATE -> rejected candidate).
"""
from __future__ import annotations
import types
from .common import parent_module, require, canonical_hash

CONTROLLER = 'r1_15a2_overnight_controller_v24915p2'
COUPLED = 'r1_15a2_overnight_controller_coupled_v24915p2_force100'
TGFIX = 'r1_15a2_generation_gate_nonfatal_v1'
TGFIX_SHA256 = '2ca13966ae4cdedcfee6f5076236ea4c2db97fc04d6cb2f612ffe899cadb6244'
REPLACED = ('ledger', 'diagnostic_hash')


def rebind_module(module, overrides):
    """Return a namespace whose module-level functions use ``overrides``.

    Every plain function defined in ``module`` is cloned onto the new
    namespace so intra-module calls resolve to the cloned versions too.
    """
    ns = dict(module.__dict__)
    ns.update(overrides)
    cloned = {}
    for name, value in module.__dict__.items():
        if isinstance(value, types.FunctionType) and value.__globals__ is module.__dict__ and name not in overrides:
            fn = types.FunctionType(value.__code__, ns, value.__name__, value.__defaults__, value.__closure__)
            fn.__kwdefaults__ = value.__kwdefaults__
            fn.__dict__.update(value.__dict__)
            fn.__wrapped_donor__ = value
            cloned[name] = fn
    ns.update(cloned)
    return ns


def code_identity(fn):
    """Bytecode identity proves the clone runs exactly the donor instructions."""
    code = fn.__code__
    return canonical_hash({'co_code': code.co_code.hex(), 'consts': repr(code.co_consts),
                           'names': list(code.co_names), 'file': code.co_filename.replace('\\', '/').rsplit('/', 1)[-1]})


class DonorTransaction:
    """Bound donor TG search: _generation_update_once with cordon ledger."""

    def __init__(self, ledger, diagnostic_hash, *, gate_nonfatal=True, outer_wrap=None):
        from .io import sha256
        from .common import PARENT
        require(sha256(PARENT / (TGFIX + '.py')) == TGFIX_SHA256, 'LIVE02_TGFIX_SOURCE_HASH_MISMATCH')
        self.controller = parent_module(CONTROLLER)
        self.coupled = parent_module(COUPLED)
        self.tgfix = parent_module(TGFIX)
        over = {'ledger': ledger, 'diagnostic_hash': diagnostic_hash}
        self.ctrl_ns = rebind_module(self.controller, over)
        self.gate_events = []
        evaluate = self.ctrl_ns['_evaluate_candidate']
        if gate_nonfatal:
            evaluate = self.tgfix.wrap_evaluate(evaluate, self.gate_events)
        if outer_wrap is not None:
            evaluate = outer_wrap(evaluate, self)
        self.evaluate = evaluate
        self.adopt = self.ctrl_ns['_adopt_candidate']
        coupled_over = dict(over, _evaluate_candidate=self.evaluate, _adopt_candidate=self.adopt,
                            _planned_generation_rows=self.ctrl_ns['_planned_generation_rows'],
                            _first_sufficient_candidate=self.ctrl_ns['_first_sufficient_candidate'])
        self.coupled_ns = rebind_module(self.coupled, coupled_over)
        self.generation_update_once = self.coupled_ns['_generation_update_once']
        self.UserStopRequested = self.controller.UserStopRequested
        self.TimeBudgetReached = self.controller.TimeBudgetReached

    def identity(self):
        """Evidence that the executed functions are the donor code objects."""
        rows = {}
        for ns, mod, names in ((self.ctrl_ns, self.controller,
                                ('_evaluate_candidate', '_adopt_candidate', '_apply_candidate',
                                 '_assign_candidate', '_rollback_candidate', '_planned_generation_rows',
                                 '_first_sufficient_candidate', '_candidate_signature')),
                               (self.coupled_ns, self.coupled,
                                ('_generation_update_once', '_generation_update_once_impl', '_generation_counts_cfg'))):
            for name in names:
                clone = ns[name]
                original = getattr(mod, name)
                require(clone.__code__ is original.__code__, 'LIVE02_DONOR_CODE_NOT_IDENTICAL:' + name)
                rows[mod.__name__ + '.' + name] = code_identity(original)
        for name in REPLACED:
            require(self.ctrl_ns[name] is not getattr(self.controller, name), 'LIVE02_PROFILE_NAME_NOT_REPLACED:' + name)
        tx = parent_module('r1_15a2_inplace_transaction_v24915p2')
        v22 = parent_module('r1_15a2_controller_v22')
        rows['rollback_and_verify'] = code_identity(tx.rollback_and_verify)
        rows['assert_freeze'] = code_identity(v22.assert_freeze)
        require(self.ctrl_ns['rollback_and_verify'] is tx.rollback_and_verify, 'LIVE02_ROLLBACK_NOT_DONOR')
        require(self.ctrl_ns['assert_freeze'] is v22.assert_freeze, 'LIVE02_FREEZE_NOT_DONOR')
        rows['tgfix_wrap_evaluate'] = code_identity(self.tgfix.wrap_evaluate)
        return {'schema': 'LIVE02_DONOR_TRANSACTION_IDENTITY_V1', 'functions': rows,
                'replaced_names': list(REPLACED), 'tgfix_sha256': TGFIX_SHA256,
                'donor_files_modified': False, 'module_globals_patched': False}
