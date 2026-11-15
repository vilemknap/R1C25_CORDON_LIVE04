"""Offline full-parser benchmark with simulated blocking page latency, no COM.

Run outside Visum: python tools/benchmark_geometry_pipeline.py --output result.json
Fixture construction/parent ingestion are outside timing. Both modes use exactly
the current fast parser, durable SQLite settings, rows and commit cadence.
"""
from pathlib import Path
import argparse
import hashlib
import json
import platform
import statistics
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cordon2025.common import parent_module
from cordon2025.live04_fastgeom import add_geometry as sequential
from cordon2025.live04_pipeline import add_geometry as pipeline


def benchmark(routes=12000, length=70, read_ms=12.0, repeats=3):
    two = parent_module('r1_15a2_two_mode_v238')
    supply = parent_module('r1_15a2_supply')
    batch_size = 1024
    keys = [(i + 1, i + routes + 1, 1) for i in range(routes)]
    rows = []
    for i, (o, d, ix) in enumerate(keys):
        rows.append((float(o), float(d), float(ix), '', '', '', ''))
        start = i % 8000 + 1
        rows.extend(('', '', '', float(j + 1), float(start + j), float(start + j), float(start + j + 1))
                    for j in range(length))
    links = {(i, i, i + 1): {'eligible': False} for i in range(1, 8001 + length)}
    st = dict(two.DEFAULT_SETTINGS, page_size=batch_size, min_free_disk_gib=0)
    owner = threading.get_ident()
    measurements = []
    with tempfile.TemporaryDirectory(prefix='r1c25_pipeline_') as tmp:
        for rep in range(repeats):
            # Alternate order to reduce warm-cache bias.
            for enabled in ((False, True) if rep % 2 == 0 else (True, False)):
                dbpath = Path(tmp) / ('%d_%d.sqlite' % (rep, enabled))
                c = two.TwoModeRouteCollector([], supply.SupplyPolicy(), 'benchmark', links,
                                              dbpath, st, None, geometry_only=True)
                c.add_parents('NATIVE_CW', 'C', [(o, d, ix, 1.) for o, d, ix in keys],
                              {'matrix_no': 1, 'matrix_interzonal': float(routes)})

                def read():
                    for first in range(0, len(rows), batch_size):
                        assert threading.get_ident() == owner
                        if read_ms:
                            time.sleep(read_ms / 1000.)  # explicit synthetic COM wait
                        yield from rows[first:first + batch_size]

                try:
                    t = time.perf_counter()
                    if enabled:
                        audit, detail = pipeline(c, 'C', read(), batch_size=batch_size)
                    else:
                        audit, detail = sequential(c, 'C', read()), None
                    elapsed = time.perf_counter() - t
                    assert c.db.execute('PRAGMA quick_check').fetchone() == ('ok',)
                    assert c.db.execute('PRAGMA foreign_key_check').fetchall() == []
                finally:
                    c.close()
                measurements.append({'repeat': rep, 'pipeline': enabled, 'seconds': elapsed,
                                     'sqlite_sha256': hashlib.sha256(dbpath.read_bytes()).hexdigest(),
                                     'audit': audit, 'pipeline_timing': detail})
                dbpath.unlink()
    assert len({r['sqlite_sha256'] for r in measurements}) == 1
    times = {flag: statistics.median(r['seconds'] for r in measurements if r['pipeline'] is flag)
             for flag in (False, True)}
    return {'schema': 'R1C25_GEOMETRY_PIPELINE_BENCHMARK_V1',
            'kind': 'SYNTHETIC_BLOCKING_PAGE_PROVIDER_NOT_NATIVE_COM',
            'python': platform.python_version(), 'platform': platform.platform(),
            'routes': routes, 'link_children_per_route': length, 'rows': len(rows),
            'page_size': batch_size, 'page_wait_ms': read_ms, 'repeats': repeats,
            'median_sequential_seconds': times[False], 'median_pipeline_seconds': times[True],
            'speedup': times[False] / times[True],
            'wall_time_reduction_percent': 100 * (1 - times[True] / times[False]),
            'sqlite_bytes_and_hash_identical': True,
            'native_visum_tested': False, 'measurements': measurements}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--routes', type=int, default=12000)
    parser.add_argument('--length', type=int, default=70)
    parser.add_argument('--read-ms', type=float, default=12.)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.routes < 1 or args.length < 1 or args.read_ms < 0 or args.repeats < 1:
        parser.error('positive routes/length/repeats and nonnegative latency required')
    result = benchmark(args.routes, args.length, args.read_ms, args.repeats)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k != 'measurements'}, indent=2))
