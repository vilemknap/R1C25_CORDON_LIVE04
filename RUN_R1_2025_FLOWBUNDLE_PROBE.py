r"""Run from Visum Scripts -> Execute script file.  ~5-15 min.  Network, demand and parameters stay unchanged.

LIVE05.6 probe for the filtered geometry read (speed-up option 2).  Every capture reads the whole
path-link hierarchy of the representative DSeg (~26 million rows per mode), although only the paths
over a cordon station, an NDS/ASD profile or a K1/K2 arm can contribute to the objective.  Visum can
list only the routes of a flow bundle (route filter "flow bundle routes").  This script measures on
the open version, for DSeg NATIVE_CW:

  1. the flow bundle over all observed links (32 station links + 120 LIVE05 links) - does Visum keep
     every route over ANY of them (OR) or only routes over ALL of them (AND)?
  2. how many routes / path-link rows the filtered list has and how long the read takes,
     compared with the time of the same number of rows of the full list;
  3. the proof the calibrator would require: on every observed link, the volume of NATIVE_CW implied
     by the filtered routes x their path volumes equals Visum's VOLVEH_DSEG(NATIVE_CW,AP).

Only the flow bundle (an analysis object) is set and cleared again at the end; nothing else is
written.  Do not save the version afterwards if you want it bit-identical (the flow bundle is empty
again anyway).  No output in Visum; the result is
%LOCALAPPDATA%\R1C25_BOOT\FLOWBUNDLE_PROBE_<time>\PROBE.json (traceback in LAST_LAUNCHER_OUTPUT.txt).
"""
import csv
import datetime
import json
import os
import time
import traceback
from collections import defaultdict
from pathlib import Path

DSEG = 'NATIVE_CW'
PAGE = 1024
COLS = ('OrigZoneNo', 'DestZoneNo', 'PathIndex', 'Index', 'LinkNo', 'FromNodeNo', 'ToNodeNo')
FILTER_NAMES = ('routeFilter_filterFlowBundleRoutes', 'routeFilter_filterFlowBundle', 'routeFilterFlowBundleRoutes')
HERE = Path(__file__).resolve().parent if '__file__' in globals() else Path.cwd()


def _lists(v):
    try:
        return v.Workbench.Lists
    except Exception:
        return v.Lists


def _member(value):
    return value() if callable(value) and not hasattr(value, 'AddColumn') else value


def _observed_links():
    out = {}
    with open(HERE / 'data/audited/STATION_MAPPING.csv', encoding='utf-8-sig') as f:
        for r in csv.DictReader(f, delimiter=';'):
            out[(int(r['link_no']), int(r['from_node_no']), int(r['to_node_no']))] = 'STATION'
    with open(HERE / 'data/audited/EXTRA_OBSERVATIONS_LIVE05.csv', encoding='utf-8-sig') as f:
        for r in csv.DictReader(f, delimiter=';'):
            for k in ('in_link', 'out_link'):
                if r.get(k):
                    out.setdefault(tuple(int(x) for x in r[k].split(':')), 'EXTRA')
    return out


def _read_all(obj):
    rows, first, calls = [], 1, 0
    while True:
        page = obj.SaveToArray(first, first + PAGE - 1)
        calls += 1
        n = 0 if page is None else len(page)
        rows.extend(page or ())
        if n < PAGE:
            return rows, calls
        first += n


def _routes(rows):
    """{(orig, dest, index): [link keys in order]} from the parent/child hierarchy rows."""
    out, cur = {}, None
    for r in rows:
        if r[0] not in ('', None):
            cur = (int(float(r[0])), int(float(r[1])), int(float(r[2])))
            out.setdefault(cur, [])
        if r[4] not in ('', None) and cur is not None:
            out[cur].append((int(float(r[4])), int(float(r[5])), int(float(r[6]))))
    return out


def main(namespace):
    v = namespace.get('Visum')
    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    folder = Path(os.environ.get('LOCALAPPDATA') or Path.home()) / 'R1C25_BOOT' / ('FLOWBUNDLE_PROBE_' + stamp)
    folder.mkdir(parents=True, exist_ok=True)
    res = {'schema': 'R1C25_FLOWBUNDLE_PROBE_V1', 'dseg': DSEG, 'started': stamp, 'steps': {}}

    def save():
        (folder / 'PROBE.json').write_text(json.dumps(res, indent=1, default=str), encoding='utf-8')

    try:
        res['version'] = str(v.IO.CurrentVersionFile)
    except Exception:
        res['version'] = None
    observed = _observed_links()
    res['observed_links'] = {'total': len(observed),
                             'by_kind': {k: sum(1 for x in observed.values() if x == k) for k in ('STATION', 'EXTRA')}}
    # route filter constant
    filt = None
    try:
        import win32com.client
        consts = win32com.client.constants
        for name in FILTER_NAMES:
            try:
                filt = getattr(consts, name); res['route_filter'] = {'name': name, 'value': filt}; break
            except AttributeError:
                continue
    except Exception as exc:
        res['route_filter_error'] = repr(exc)[:300]
    if filt is None:
        res['route_filter'] = {'name': None, 'note': 'constant not found; trying the numeric values 1..4'}
    save()

    # parent path volumes (cheap, full)
    t0 = time.perf_counter()
    plist = _member(_lists(v).CreatePrTPathList)
    for c in ('OrigZoneNo', 'DestZoneNo', 'Index', 'Vol(AP)'):
        plist.AddColumn(c)
    plist.SetObjects(0, DSEG, 0)
    prow, _ = _read_all(plist)
    vol = {(int(float(r[0])), int(float(r[1])), int(float(r[2]))): float(r[3]) for r in prow}
    res['steps']['parents'] = {'routes': len(vol), 'seconds': round(time.perf_counter() - t0, 2)}
    save()

    # Visum link volumes on the observed links
    coll = v.Net.Links
    cols = {a: dict(coll.GetMultiAttValues(a, False))
            for a in ('NO', 'FROMNODENO', 'TONODENO', 'VOLVEH_DSEG(%s,AP)' % DSEG)}
    visum_vol = {}
    for i, no in cols['NO'].items():
        key = (int(no), int(cols['FROMNODENO'][i]), int(cols['TONODENO'][i]))
        if key in observed:
            visum_vol[key] = float(cols['VOLVEH_DSEG(%s,AP)' % DSEG][i] or 0.0)
    res['observed_links']['found_in_network'] = len(visum_vol)
    save()

    fb = v.Net.FlowBundle
    try:
        # 1) flow bundle over all observed links in ONE net element container
        fb.Clear()
        try:
            fb.DemandSegments = DSEG
        except Exception as exc:
            res['steps']['demand_segments_error'] = repr(exc)[:300]
        elems = v.CreateNetElements()
        added = 0
        for (no, f, t) in visum_vol:
            try:
                elems.Add(coll.ItemByKey(f, t)); added += 1
            except Exception as exc:
                res.setdefault('add_errors', []).append([no, f, t, repr(exc)[:120]])
        res['steps']['net_elements'] = added
        t0 = time.perf_counter()
        fb.Execute(elems)
        res['steps']['flow_bundle_execute_seconds'] = round(time.perf_counter() - t0, 2)
        save()

        for value in ([filt] if filt is not None else [1, 2, 3, 4]):
            rec = {'filter_value': value}
            try:
                t0 = time.perf_counter()
                obj = _member(_lists(v).CreatePrTPathLinkList)
                for c in COLS:
                    obj.AddColumn(c)
                obj.SetObjects(0, DSEG, value)
                rows, calls = _read_all(obj)
                rec.update(rows=len(rows), com_calls=calls, read_seconds=round(time.perf_counter() - t0, 2))
                routes = _routes(rows)
                rec['routes'] = len(routes)
                rec['routes_share_of_all'] = round(len(routes) / max(1, len(vol)), 4)
                implied = defaultdict(float)
                for k, links in routes.items():
                    for key in set(links):
                        implied[key] += vol.get(k, 0.0) * links.count(key)
                bad = []
                for key, vv in visum_vol.items():
                    d = abs(implied.get(key, 0.0) - vv)
                    if d > 1.0 + 0.001 * vv:
                        bad.append({'link': list(key), 'visum': round(vv, 3), 'implied': round(implied.get(key, 0.0), 3)})
                rec['links_compared'] = len(visum_vol)
                rec['links_mismatch'] = len(bad)
                rec['mismatch_examples'] = bad[:10]
                rec['semantics'] = ('OR_ALL_ROUTES_OVER_ANY_OBSERVED_LINK' if not bad and routes else
                                    'NOT_COMPLETE_(AND_OR_OTHER)' if routes else 'EMPTY')
            except Exception as exc:
                rec['error'] = repr(exc)[:400]
            res['steps'].setdefault('filtered_lists', []).append(rec)
            save()
            if filt is not None or rec.get('semantics') == 'OR_ALL_ROUTES_OVER_ANY_OBSERVED_LINK':
                break
        # timing reference: the same number of rows from the FULL list
        n_ref = max((r.get('rows', 0) for r in res['steps'].get('filtered_lists', [])), default=0) or 200000
        t0 = time.perf_counter()
        full = _member(_lists(v).CreatePrTPathLinkList)
        for c in COLS:
            full.AddColumn(c)
        full.SetObjects(0, DSEG, 0)
        first, got = 1, 0
        while got < n_ref:
            page = full.SaveToArray(first, first + PAGE - 1)
            n = 0 if page is None else len(page)
            got += n; first += n
            if n < PAGE:
                break
        res['steps']['full_list_same_rows'] = {'rows': got, 'seconds': round(time.perf_counter() - t0, 2)}
    finally:
        try:
            fb.Clear()
            res['flow_bundle_cleared'] = True
        except Exception as exc:
            res['flow_bundle_clear_error'] = repr(exc)[:300]
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
