"""Read-only COM retry port from the supplied Aggressive 24915 HOTFIX1.

No routing, assignment, TG/TD, matrix setters, ROT attachment or model saves.
The original parent hotfix is kept byte-identical. This bridge also protects
cordon's own startup reads (which do NOT call the profile snapshot adapter).
Retry is bounded per read transaction, never a whole partially-written export.
"""
from __future__ import annotations
from contextlib import contextmanager
from collections import Counter
from pathlib import Path
import time
from .common import parent_module, require, PARENT
from .io import sha256, exception_text

SOURCE = 'r1_15a2_com_busy_snapshot_hotfix_v1.py'
SOURCE_SHA256 = '2488191e97c17a072fd161c5645e17fa1fe0ac8c35412b92282d9737f0f76366'
RELEASE = 'CORDON_2025_STARTUP_FIX3_PRACTICAL_20261023'
# Literal defaults audited against the delivered source; checked by tests and
# parent_hotfix_scope before real startup. No silent enable of a disabled policy.
DEFAULTS = {'com_retry_enabled': True, 'com_retry_attempts': 64,
    'com_retry_initial_delay_seconds': .15, 'com_retry_backoff_factor': 1.5,
    'com_retry_max_delay_seconds': 1.5, 'com_retry_max_elapsed_seconds': 75.}
NO_RETRY = {'enabled': False, 'max_attempts': 1,
            'initial_delay_seconds': 0., 'max_delay_seconds': 0.}


def policy(options):
    return {'enabled': options['com_retry_enabled'],
            'max_attempts': options['com_retry_attempts'],
            'initial_delay_seconds': options['com_retry_initial_delay_seconds'],
            'backoff_factor': options['com_retry_backoff_factor'],
            'max_delay_seconds': options['com_retry_max_delay_seconds'],
            'max_elapsed_seconds': options['com_retry_max_elapsed_seconds']}


def record_event(control, event):
    """Telemetry is bounded and cannot replace a COM error; STOP is elsewhere."""
    try:
        if not hasattr(control, 'com_retry_events'):
            control.com_retry_events = []
            control.com_retry_event_counts = Counter()
        kind = 'EXHAUSTED' if event.get('exhausted') else 'RETRY'
        control.com_retry_event_counts[kind] += 1
        if len(control.com_retry_events) < 1000:
            control.com_retry_events.append(dict(event, event=kind))
    except Exception:
        pass


def telemetry(control, options):
    return {'release': RELEASE, 'parent_hotfix_sha256': SOURCE_SHA256,
            'policy': policy(options), 'scope': 'ONE_READ_OR_ONE_BOUNDED_PAGE',
            'not_a_whole_run_deadline': True,
            'cannot_interrupt_an_inflight_native_COM_call': True,
            'event_counts': dict(getattr(control, 'com_retry_event_counts', {})),
            'events': list(getattr(control, 'com_retry_events', [])),
            'events_retained_limit': 1000,
            'apply_permitted': False, 'native_visum_tested_here': False}


def read_call(call, control, options, label):
    """Use the parent's exact RPC classifier/backoff, with one owner per read.

    All helpers called inside this closure must use NO_RETRY to avoid separate
    nested budgets. Nested calls to read_call share this outer transaction.
    A successful COM call is not time-limited or asynchronously cancelled.
    """
    control.checkpoint(label)
    depth = getattr(control, '_cordon_combusy_depth', 0)
    if depth:
        return call()
    com = parent_module('r1_15a2_com_compat')
    control._cordon_combusy_depth = depth + 1
    def observer(event):
        record_event(control, event)
        # This may raise USER_STOP_REQUESTED or COM_THREAD_CHANGED deliberately.
        control.checkpoint(label, force=True, com_read_retry=event)
    def attempt():
        # Check again after sleeping/message pumping, before any new COM call.
        control.checkpoint(label)
        return call()
    try:
        return com.com_call_with_retry(attempt, label='CORDON_READ:' + label,
            retry_policy=policy(options), sleep_fn=time.sleep, clock_fn=time.monotonic,
            on_retry=observer, on_exhausted=observer)
    finally:
        control._cordon_combusy_depth = depth


class _TypeInfoRead:
    """Forward real provider TypeInfo, without manufacturing a signature."""
    def __init__(self, obj, control, options, label):
        self.obj, self.control, self.options, self.label = obj, control, options, label
    def _read(self, name, *args):
        return read_call(lambda: getattr(self.obj, name)(*args), self.control,
                         self.options, self.label + '.' + name)
    def GetTypeAttr(self): return self._read('GetTypeAttr')
    def GetFuncDesc(self, index): return self._read('GetFuncDesc', index)
    def GetNames(self, memid): return self._read('GetNames', memid)


class _OleRead:
    def __init__(self, obj, control, options, label):
        self.obj, self.control, self.options, self.label = obj, control, options, label
    def GetTypeInfo(self):
        obj = read_call(lambda: self.obj.GetTypeInfo(), self.control, self.options,
                        self.label + '.GetTypeInfo')
        return _TypeInfoRead(obj, self.control, self.options, self.label)
    def Invoke(self, *args):
        # Original 15A2 bounded_rows owns exactly ONE retry budget for each page.
        # Do not add an inner retry here or advance/rescale the requested range.
        # STOP may have appeared during the parent's message pump/backoff.
        # Check before the next native call, without introducing a second retry.
        self.control.checkpoint(self.label)
        return self.obj.Invoke(*args)


class BoundedReadTarget:
    """Minimal read facade for the existing 15A2 bounded_rows iterator.

    Only dispatch metadata is wrapped. The original parser, pagination, range
    fallback and native values are untouched. This does not proxy model writes.
    """
    def __init__(self, obj, control, options, label):
        self.obj, self.control, self.options, self.label = obj, control, options, label
    @property
    def _oleobj_(self):
        obj = read_call(lambda: getattr(self.obj, '_oleobj_', None), self.control,
                        self.options, self.label + '._oleobj_')
        # Preserve the parent's fail-closed missing-TypeInfo check.
        if obj is None: return None
        return _OleRead(obj, self.control, self.options, self.label)


@contextmanager
def parent_hotfix_scope():
    """Install the delivered three snapshot fixes, restore them on every exit.

    Called inside bootstrap's isolated_imports, never on modules belonging to a
    running 2022 release. No profile launcher is imported or executed. Even a
    direct offline test invocation restores the previous parent module state.
    """
    source = PARENT / SOURCE
    require(sha256(source) == SOURCE_SHA256, 'COMBUSY_PARENT_SOURCE_HASH_MISMATCH')
    hotfix = parent_module('r1_15a2_com_busy_snapshot_hotfix_v1')
    supply = parent_module('r1_15a2_supply_visum')
    optimized = parent_module('r1_15a2_single_pass_snapshot_v24915p2c')
    adapter = parent_module('r1_15a2_trial_adapter_v24915p2c')
    require(not hotfix._ACTIVE, 'COMBUSY_PARENT_PATCH_ALREADY_ACTIVE_OUTSIDE_SCOPE')
    originals = [(supply.VisumAdapter, 'read_links', supply.VisumAdapter.read_links),
        (supply.VisumAdapter, 'snapshot', supply.VisumAdapter.snapshot),
        (optimized, 'single_pass_exact_snapshot', optimized.single_pass_exact_snapshot),
        (adapter, 'single_pass_exact_snapshot', adapter.single_pass_exact_snapshot)]
    try:
        activated = hotfix.activate()
        yield dict(activated, source_sha256=SOURCE_SHA256,
                   activation='SCOPED_CORDON_ONLY_NO_PROFILE_LAUNCHER')
    finally:
        for owner, attr, original in originals:
            setattr(owner, attr, original)
        hotfix._ACTIVE = False
