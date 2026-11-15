"""Bounded geometry ingestion; COM and cooperative control stay on the owner thread.

The unmodified geometry parser runs on one worker with its own SQLite connection.
Only detached scalar rows cross the page queue. The original connection is idle
until the worker has closed and joined. No routing, pagination, proof or tolerance
is changed. At most two batches are live: one consumed and one being read/queued.
"""
from __future__ import annotations

from copy import copy
from itertools import islice
from pathlib import Path
from queue import Empty, Queue
import sqlite3
import threading
import time

from .common import require, parent_module

_END = object()
_READ_FAILED = object()
_SCALARS = (int, float, str, bool, type(None))


class _Cancelled(Exception):
    pass


class _SourceReadFailed(Exception):
    pass


class _WorkerControl:
    """Synchronous checkpoint requests; the real control is never called here."""
    def __init__(self, events, cancel):
        self.events, self.cancel = events, cancel
        self.wait_seconds = 0.0

    def checkpoint(self, *args, **kwargs):
        response = Queue(1)
        self.events.put((args, kwargs, response))
        started = time.perf_counter()
        try:
            while not self.cancel.is_set():
                try:
                    response.get(timeout=.05)
                except Empty:
                    continue
                return
            raise _Cancelled()
        finally:
            self.wait_seconds += time.perf_counter() - started


def _detach(batch):
    # SAFEARRAY results are normally tuples of scalar tuples. Validate on the
    # COM owner: a provider object must never be inspected/released on a worker.
    result = []
    for row in batch:
        require(type(row) in (tuple, list), 'GEOMETRY_PIPELINE_NONSCALAR_ROW')
        require(all(type(v) in _SCALARS for v in row), 'GEOMETRY_PIPELINE_NONSCALAR_CELL')
        result.append(tuple(row))
    return tuple(result)


def add_geometry(collector, mode, raw_rows, *, batch_size, fast_parser=True):
    """Return (original parser audit, timing). Raise after draining/closing worker.

    Read errors are delivered in stream order, so a parser error in an earlier
    batch takes precedence. STOP/control errors cancel and join the worker before
    returning to the caller's normal failed-capture cleanup. Never publish here.
    """
    require(type(batch_size) is int and batch_size > 0, 'GEOMETRY_PIPELINE_BATCH_SIZE')
    require(not collector.db.in_transaction, 'GEOMETRY_PIPELINE_OPEN_TRANSACTION')
    two = parent_module('r1_15a2_two_mode_v238')
    if fast_parser:
        from .live04_fastgeom import add_geometry as parse
    else:
        parse = two.TwoModeRouteCollector.add_geometry
    # Resolve imports and connection settings before starting the worker.
    pragmas = {name: collector.db.execute('PRAGMA ' + name).fetchone()[0]
               for name in ('foreign_keys', 'synchronous', 'cache_size')}
    worker_collector = copy(collector)
    worker_collector.db = None
    pages, events, result = Queue(1), Queue(), Queue(1)
    cancel = threading.Event()
    control = _WorkerControl(events, cancel)
    worker_collector.control = control
    owner = threading.get_ident()
    wait_data = 0.0

    def rows():
        nonlocal wait_data
        while not cancel.is_set():
            start = time.perf_counter()
            try:
                batch = pages.get(timeout=.05)
            except Empty:
                wait_data += time.perf_counter() - start
                continue
            wait_data += time.perf_counter() - start
            if batch is _END:
                return
            if batch is _READ_FAILED:
                raise _SourceReadFailed()
            # ACK wakes the producer before parsing. Without this handoff short
            # Python batches can finish within one GIL quantum, serializing the
            # supposedly concurrent reader and parser despite a blocking COM API.
            control.checkpoint()
            yield from batch
            # Drop the consumed batch BEFORE asking for another (two-batch bound).
            del batch
        raise _Cancelled()

    def worker():
        start = time.perf_counter()
        db = None
        try:
            # mode=rw: cannot silently create a missing staging database.
            db = sqlite3.connect(Path(collector.route_db_path).resolve().as_uri() + '?mode=rw', uri=True)
            worker_collector.db = db
            for name, value in pragmas.items():
                db.execute('PRAGMA %s=%d' % (name, int(value)))
            audit = parse(worker_collector, mode, rows())
            outcome = (audit, None)
        except BaseException as exc:
            outcome = (None, exc)
        finally:
            if db is not None:
                try:
                    db.close()
                except BaseException as exc:
                    if outcome[1] is None:
                        outcome = (None, exc)
            worker_collector.db = None
        elapsed = time.perf_counter() - start
        result.put((outcome, max(0.0, elapsed - wait_data - control.wait_seconds)))
        events.put(None)

    thread = threading.Thread(target=worker, name='R1C25-geometry-parser')
    raw_rows = iter(raw_rows)
    start = time.perf_counter()
    read_seconds = 0.0
    batches = count = 0
    exhausted = False
    source_error = None
    try:
        thread.start()
        while result.empty():
            # At most one worker checkpoint can be outstanding (it waits for ACK).
            try:
                event = events.get(timeout=0.0 if not exhausted and pages.empty() else .05)
            except Empty:
                event = None
            if event is not None:
                args, kwargs, response = event
                try:
                    collector.control.checkpoint(*args, **kwargs)
                except BaseException:
                    cancel.set()
                    raise
                response.put(None)
            if result.empty() and not exhausted and pages.empty():
                collector.control.checkpoint()
                t = time.perf_counter()
                try:
                    batch = _detach(tuple(islice(raw_rows, batch_size)))
                except BaseException as exc:
                    # Deliver after the previously submitted rows, including STOP
                    # detected by the original bounded reader.
                    # Keep the exception/traceback on the COM owner too: a
                    # traceback from a provider may itself retain COM objects.
                    source_error = exc
                    batch = _READ_FAILED
                    exhausted = True
                read_seconds += time.perf_counter() - t
                if not batch:
                    batch = _END
                    exhausted = True
                if batch is not _READ_FAILED and batch is not _END:
                    batches += 1
                    count += len(batch)
                pages.put_nowait(batch)
                del batch
            else:
                # Keep STOP responsive even when SQLite is busy; no long waits.
                collector.control.checkpoint()
        (audit, error), process_seconds = result.get_nowait()
        if isinstance(error, _SourceReadFailed):
            raise source_error
        if error is not None:
            raise error
        # Mutable audit/maps are shared while the owner is idle. These scalar
        # counters are the only parser writes needing explicit synchronization.
        collector.geometry_count = worker_collector.geometry_count
        collector._posting_chunk = worker_collector._posting_chunk
        collector._last_resource_check = worker_collector._last_resource_check
        return audit, {'enabled': True, 'batches': batches, 'rows': count,
                       'batch_size': batch_size, 'max_live_batches': 2,
                       'wall_seconds': round(time.perf_counter() - start, 6),
                       'read_and_detach_seconds': round(read_seconds, 6),
                       'worker_active_seconds': round(process_seconds, 6),
                       'worker_data_wait_seconds': round(wait_data, 6),
                       'worker_control_wait_seconds': round(control.wait_seconds, 6),
                       'com_owner_thread': owner, 'worker_joined_before_return': True}
    finally:
        cancel.set()
        # All processing is bounded local work; no native COM call on this worker.
        while thread.is_alive():
            thread.join(timeout=.05)
        close = getattr(raw_rows, 'close', None)
        if close is not None:
            close()
