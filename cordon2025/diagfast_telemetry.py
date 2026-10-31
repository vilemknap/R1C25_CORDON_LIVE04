"""Aggregated same-thread timing. No per-row files and no model interaction."""
from __future__ import annotations
from collections import Counter
from contextlib import contextmanager
import time

SCHEMA = 'CORDON_DIAGFAST_TIMING_V1'

def _io_counters():
    try:
        import psutil
        c=psutil.Process().io_counters()
        return {k:int(getattr(c,k)) for k in ('read_bytes','write_bytes','read_count','write_count')}
    except Exception:
        return None


class Telemetry:
    def __init__(self, enabled=True):
        self.enabled = enabled
        self.io_start = _io_counters()
        self.started = time.perf_counter()
        self.cpu_started = time.process_time()
        self.stages = {}
        self.counters = Counter()
        self.stack = []
        self.samples = []
        self.errors = []

    @contextmanager
    def span(self, name):
        if not self.enabled:
            yield
            return
        frame = [time.perf_counter(), time.process_time(), 0., 0.]
        self.stack.append(frame)
        failed = False
        try:
            yield
        except BaseException:
            failed = True
            raise
        finally:
            wall = time.perf_counter() - frame[0]
            cpu = time.process_time() - frame[1]
            self.stack.pop()
            if self.stack:
                self.stack[-1][2] += wall
                self.stack[-1][3] += cpu
            r = self.stages.setdefault(name, {'calls':0, 'errors':0, 'wall_inclusive_s':0.,
                'wall_exclusive_s':0., 'cpu_inclusive_s':0., 'cpu_exclusive_s':0.})
            r['calls'] += 1; r['errors'] += int(failed)
            r['wall_inclusive_s'] += wall; r['wall_exclusive_s'] += max(0., wall-frame[2])
            r['cpu_inclusive_s'] += cpu; r['cpu_exclusive_s'] += max(0., cpu-frame[3])

    def count(self, key, value=1):
        if self.enabled:
            self.counters[key] += value

    def sample(self, value):
        if self.enabled and len(self.samples) < 48:
            self.samples.append(value)

    def report(self):
        rss = None
        try:
            import resource, sys
            rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024**2 if sys.platform=='darwin' else 1024.)
        except Exception:
            pass
        io_end=_io_counters()
        io_delta={k:io_end[k]-self.io_start[k] for k in io_end} if io_end is not None and self.io_start is not None else None
        return {'process_io_delta':io_delta, 'schema':SCHEMA, 'instrumentation_enabled':self.enabled,
            'wall_s':time.perf_counter()-self.started, 'cpu_s':time.process_time()-self.cpu_started,
            'peak_process_rss_mib':rss, 'stages':self.stages,
            'counters':dict(sorted(self.counters.items())), 'bounded_samples':self.samples,
            'native_transport_bytes':'NOT_MEASURED_PROVIDER_DOES_NOT_EXPOSE_WIRE_BYTES',
            'rss_scope':'PROCESS_LIFETIME_PEAK_NOT_PER_STAGE',
            'nested_times_are_not_additive':True, 'apply_permitted':False,
            'assignment_executed':False, 'calibration_ready':False}
