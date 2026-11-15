"""LIVE05.6: geometry ingestion overlapped with the COM read (user request 2026-11-15).

The path-link hierarchy of the representative DSeg (~26 million rows per mode) is read page by
page through COM and then parsed into the SQLite store.  Serially both phases add up
(~6-7 min COM + ~4 min Python per capture on the live model).  Here the COM read stays on the
COM thread (Visum objects are apartment bound) and hands complete pages to ONE worker thread
that runs the unchanged parser (live04_fastgeom / donor add_geometry) in the same row order, so
the store is identical to the serial one.  pywin32 releases the GIL inside each COM call, so the
parser runs while Visum prepares the next page.

* The worker gets a control proxy: progress details it reports are forwarded by the COM thread
  (LiveControl.checkpoint must run there), a stop request is still honoured between pages.
* Any error of either side stops both; the worker's own exception is re-raised unchanged.
* The SQLite connection is reopened with check_same_thread=False and the donor's PRAGMAs; only one
  thread uses it at any time (worker while parsing, COM thread afterwards).
"""
import queue
import sqlite3
import threading

PRAGMAS = ('PRAGMA journal_mode=DELETE;PRAGMA synchronous=FULL;PRAGMA foreign_keys=ON;'
           'PRAGMA cache_size=-32768;')
BATCH_ROWS = 4096
QUEUE_BATCHES = 64


def shareable_connection(collector):
    """Swap the collector's connection for one usable from the parser thread (same file, same PRAGMAs)."""
    collector.db.commit()
    collector.db.close()
    collector.db = sqlite3.connect(collector.route_db_path, check_same_thread=False)
    collector.db.executescript(PRAGMAS)


class _ControlProxy:
    """Collects checkpoint details of the parser thread; the COM thread forwards them."""

    def __init__(self, real):
        self.real = real
        self.lock = threading.Lock()
        self.pending = None

    def checkpoint(self, phase=None, force=False, **details):
        with self.lock:
            self.pending = (phase, details)

    def __getattr__(self, name):
        return getattr(self.real, name)

    def forward(self):
        with self.lock:
            item, self.pending = self.pending, None
        if item is not None:
            self.real.checkpoint(item[0], **item[1])


class _Abort(Exception):
    pass


def add_geometry(collector, mode, rows, impl):
    """impl(mode, rows) parsed in a worker thread while ``rows`` (COM pages) are read here."""
    q = queue.Queue(maxsize=QUEUE_BATCHES)
    done = object()
    failed = threading.Event()
    box = {}
    proxy = _ControlProxy(collector.control)

    def source():
        while True:
            item = q.get()
            if item is done:
                return
            if isinstance(item, _Abort):
                raise item
            yield from item

    def work():
        try:
            box['result'] = impl(mode, source())
        except BaseException as exc:          # noqa: B902 - re-raised on the COM thread
            box['error'] = exc
            failed.set()

    def put(item):
        while True:
            if failed.is_set():
                return False
            try:
                q.put(item, timeout=0.2)
                return True
            except queue.Full:
                proxy.forward()

    real = collector.control
    collector.control = proxy
    worker = threading.Thread(target=work, name='LIVE05_GEOMETRY_PARSER', daemon=True)
    worker.start()
    try:
        batch = []
        for row in rows:
            batch.append(row)
            if len(batch) >= BATCH_ROWS:
                proxy.forward()
                if not put(batch):
                    break
                batch = []
        if not failed.is_set() and batch:
            put(batch)
        if not failed.is_set():
            put(done)
    except BaseException as exc:
        # COM side failed (or a stop request): end the parser, then report the COM error
        try:
            q.put_nowait(_Abort('COM_READ_FAILED'))
        except queue.Full:
            try:
                while True:
                    q.get_nowait()
            except queue.Empty:
                pass
            q.put_nowait(_Abort('COM_READ_FAILED'))
        worker.join()
        collector.control = real
        raise
    worker.join()
    collector.control = real
    proxy.forward()
    if 'error' in box:
        raise box['error']
    return box.get('result')
