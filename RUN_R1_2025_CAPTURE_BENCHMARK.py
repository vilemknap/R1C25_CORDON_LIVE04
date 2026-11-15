r"""Run from Visum Scripts -> Execute script file.  READ-ONLY, ~10-20 min.

LIVE04.10.4 capture benchmark: measures on the open 2025 version how the path-link geometry read
(the largest part of every capture) depends on
  * the position of the page in the list (does SaveToArray(first, last) restart from the top?),
  * the page size (256 = current, 1024, 4096),
  * the number of list columns (7 = current schema, 5 = without Index/LinkNo),
and times the parent path list and the all-link VOLVEH_DSEG read.
Nothing is written to the model; only list objects are created.  No output in Visum; the result is in
%LOCALAPPDATA%\R1C25_BOOT\CAPTURE_BENCH_<time>\BENCH.json (and LAST_LAUNCHER_OUTPUT.txt on error).
Can run in a second Visum instance with a copy of the same version while nothing else runs in it.
"""
import datetime
import json
import os
import time
import traceback
from pathlib import Path

DSEG = 'NATIVE_CW'                                    # representative of mode C
DSEG_CODES = ('EXOG_EE_CF', 'EXOG_EE_CL', 'EXOG_EE_CS', 'EXOG_EE_CS_noT', 'EXOG_EE_CW', 'EXOG_EE_CW_noT',
              'NATIVE_CF', 'NATIVE_CL', 'NATIVE_CS', 'NATIVE_CS_noT', 'NATIVE_CW', 'NATIVE_CW_noT')
COLS7 = ('OrigZoneNo', 'DestZoneNo', 'PathIndex', 'Index', 'LinkNo', 'FromNodeNo', 'ToNodeNo')
COLS5 = ('OrigZoneNo', 'DestZoneNo', 'PathIndex', 'FromNodeNo', 'ToNodeNo')
POSITIONS = (1, 100001, 200001, 300001, 400001)      # route positions (mode C has ~437 000 routes)
PAGES_PER_PROBE = 4
MAX_SECONDS_PER_PROBE = 240.0


def _lists(v):
    try:
        return v.Workbench.Lists
    except Exception:
        return v.Lists


def _signature(obj):
    ole = obj._oleobj_
    ti = ole.GetTypeInfo(); ta = ti.GetTypeAttr()
    for i in range(int(ta.cFuncs if hasattr(ta, 'cFuncs') else ta[8])):
        d = ti.GetFuncDesc(i)
        memid = int(d.memid if hasattr(d, 'memid') else d[0])
        names = [str(x) for x in ti.GetNames(memid)]
        if names and names[0].lower() == 'savetoarray':
            return ole, memid, int(d.invkind if hasattr(d, 'invkind') else d[4])
    raise RuntimeError('SAVETOARRAY_NOT_FOUND')


def _member(value):
    # COM properties may surface as bound methods (PTV Visum / win32com dynamic dispatch)
    return value() if callable(value) and not hasattr(value, 'AddColumn') else value


def _new(v, kind, code, cols):
    obj = _member(getattr(_lists(v), kind))
    for c in cols:
        obj.AddColumn(c)
    obj.SetObjects(0, code, 0)
    return obj


def _probe(obj, first, size, pages):
    ole, memid, kind = _signature(obj)
    out = []; t_all = time.perf_counter()
    for p in range(pages):
        a = first + p * size
        t0 = time.perf_counter()
        raw = ole.Invoke(memid, 0, kind, True, a, a + size - 1)
        dt = time.perf_counter() - t0
        rows = 0 if raw is None else len(raw)
        out.append({'first': a, 'size': size, 'seconds': round(dt, 4), 'rows': rows})
        if rows == 0 or time.perf_counter() - t_all > MAX_SECONDS_PER_PROBE:
            break
    s = sum(x['seconds'] for x in out); r = sum(x['rows'] for x in out)
    return {'first': first, 'page_size': size, 'pages': out, 'seconds': round(s, 3), 'rows': r,
            'seconds_per_1000_rows': round(1000 * s / r, 4) if r else None,
            'routes': sum(min(size, x['rows']) for x in out)}


def main(namespace):
    v = namespace.get('Visum')
    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    folder = Path(os.environ.get('LOCALAPPDATA') or Path.home()) / 'R1C25_BOOT' / ('CAPTURE_BENCH_' + stamp)
    folder.mkdir(parents=True, exist_ok=True)
    res = {'schema': 'R1C25_CAPTURE_BENCHMARK_V1', 'read_only': True, 'dseg': DSEG, 'started': stamp, 'tests': {}}

    def save():
        (folder / 'BENCH.json').write_text(json.dumps(res, indent=1), encoding='utf-8')

    def step(name, fn):
        t0 = time.perf_counter()
        try:
            res['tests'][name] = fn()
        except Exception as exc:
            res['tests'][name] = {'error': repr(exc)[:500], 'traceback': traceback.format_exc()[-1500:]}
        res['tests'][name] = dict(res['tests'][name], wall_seconds=round(time.perf_counter() - t0, 2)) \
            if isinstance(res['tests'][name], dict) else res['tests'][name]
        save()

    try:
        res['version'] = str(v.IO.CurrentVersionFile)
    except Exception:
        res['version'] = None
    # 1) position effect, current schema and page size
    step('position_256_cols7', lambda: {'probes': [_probe(_new(v, 'CreatePrTPathLinkList', DSEG, COLS7), p, 256,
                                                          PAGES_PER_PROBE) for p in POSITIONS]})
    # 2) page size at a deep position
    step('page_size_deep_cols7', lambda: {'probes': [_probe(_new(v, 'CreatePrTPathLinkList', DSEG, COLS7), 300001, s,
                                                            max(1, PAGES_PER_PROBE * 256 // s)) for s in (256, 1024, 4096)]})
    step('page_size_start_cols7', lambda: {'probes': [_probe(_new(v, 'CreatePrTPathLinkList', DSEG, COLS7), 1, s,
                                                             max(1, PAGES_PER_PROBE * 256 // s)) for s in (256, 1024, 4096)]})
    # 3) fewer columns, same position / size
    step('columns5_deep_256', lambda: {'probes': [_probe(_new(v, 'CreatePrTPathLinkList', DSEG, COLS5), 300001, 256,
                                                         PAGES_PER_PROBE)]})
    # 4) whole parent path list of one DSeg, two page sizes
    def parents(size):
        obj = _new(v, 'CreatePrTPathList', DSEG, ('OrigZoneNo', 'DestZoneNo', 'Index', 'Vol(AP)'))
        ole, memid, kind = _signature(obj); first = 1; t0 = time.perf_counter(); n = 0; calls = 0
        while True:
            raw = ole.Invoke(memid, 0, kind, True, first, first + size - 1); calls += 1
            k = 0 if raw is None else len(raw); n += k
            if k < size:
                break
            first += k
        return {'page_size': size, 'rows': n, 'calls': calls, 'seconds': round(time.perf_counter() - t0, 3)}
    step('parent_list_full', lambda: {'runs': [parents(256), parents(4096)]})
    # 5) all-link VOLVEH_DSEG for the 12 DSegs
    def links():
        # the same per-attribute bulk read as the capture (GetMultiAttValues)
        names = ['NO', 'FROMNODENO', 'TONODENO'] + ['VOLVEH_DSEG(%s,AP)' % c for c in DSEG_CODES]
        coll = v.Net.Links; per = {}; n = 0; t0 = time.perf_counter()
        for name in names:
            t1 = time.perf_counter(); rows = coll.GetMultiAttValues(name, False); n = len(rows)
            per[name] = round(time.perf_counter() - t1, 3)
        return {'links': n, 'columns': len(names), 'seconds': round(time.perf_counter() - t0, 3), 'per_attribute': per}
    step('all_link_volumes', links)
    res['finished'] = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    save()
    return res


if __name__ == '__main__':
    import io as _io, sys as _sys
    _saved = (_sys.stdout, _sys.stderr); _buf = _io.StringIO(); _sys.stdout = _sys.stderr = _buf
    try:
        main(globals())
    except BaseException:
        _buf.write(traceback.format_exc())
    finally:
        _sys.stdout, _sys.stderr = _saved
        try:
            _d = Path(os.environ.get('LOCALAPPDATA') or Path.home()) / 'R1C25_BOOT'; _d.mkdir(parents=True, exist_ok=True)
            (_d / 'LAST_LAUNCHER_OUTPUT.txt').write_text(_buf.getvalue() or '(no output)\n', encoding='utf-8')
        except Exception:
            pass
