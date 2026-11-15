r"""Run from Visum Scripts -> Execute script file.  READ-ONLY, ~1-3 min.

LIVE04.11 audit of the "no vignette" car demand (_noT demand segments) for the SDP1 deficit:
  1. procedure sequence: number, type, comment of every operation and, where COM exposes it,
     the script file / formula (where is the C vs C_noT split made?); Procedures saved as XML if possible;
  2. matrix totals of the component (91xx), car (93xx) and EE car (94xx) matrices and every matrix
     whose code mentions noT -> the actual _noT share per purpose;
  3. network: links open to C but closed to C_noT (vignette-only network) - count and length by link type;
  4. screenline across D1 at SDP1 (and optionally other stations): every link whose chord crosses
     the line, with its type, TSysSet, ADDVAL1 and VOLVEH_DSEG of all 12 car DSegs -> where the
     model sends the traffic that the D1 count says should be on D1;
  5. vignette pricing readiness: catalogue of ALL matrices (type, data source, formula, sum),
     skim-like matrices, and whether FORMULA of the split-ratio matrices 9231..9234 is editable.
Nothing is written to the model.  No output in Visum; the result is in
%LOCALAPPDATA%\R1C25_BOOT\NOT_SHARE_AUDIT_<time>\ (NOT_SHARE_AUDIT.json, SCREENLINE_<station>.csv,
VIGNETTE_ONLY_LINKS.csv, PROCEDURES.xml if available) and LAST_LAUNCHER_OUTPUT.txt on error.
"""
import csv
import datetime
import json
import math
import os
import traceback
from pathlib import Path

DSEG_CODES = ('NATIVE_CW', 'NATIVE_CW_noT', 'NATIVE_CS', 'NATIVE_CS_noT', 'NATIVE_CL', 'NATIVE_CF',
              'EXOG_EE_CW', 'EXOG_EE_CW_noT', 'EXOG_EE_CS', 'EXOG_EE_CS_noT', 'EXOG_EE_CL', 'EXOG_EE_CF')
MATRIX_NOS = tuple(range(9101, 9118)) + tuple(range(9301, 9307)) + tuple(range(9401, 9407))
# station point (model CRS, from data/audited/STATION_MAPPING.csv), road direction (deg, from the
# station link geometry) and half length of the screenline in km
SCREENLINES = {
    'SDP1': {'x': 221722.2747382021, 'y': 5346485.280668469, 'road_angle_deg': 24.0, 'half_km': 10.0},
    'SDP3': None,       # filled from STATION_MAPPING.csv when present next to this script
    'SDP16': None,
}
LINK_ATTRS = ('NO', 'FROMNODENO', 'TONODENO', 'TYPENO', 'TSYSSET', 'LENGTH', 'ADDVAL1', 'V0PRT',
              r'FROMNODE\XCOORD', r'FROMNODE\YCOORD', r'TONODE\XCOORD', r'TONODE\YCOORD')


def segment_crosses(p1, p2, q1, q2):
    """True when segment p1-p2 crosses segment q1-q2 (proper or touching)."""
    def orient(a, b, c):
        v = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        return 0 if abs(v) < 1e-9 else (1 if v > 0 else -1)
    o1, o2, o3, o4 = orient(p1, p2, q1), orient(p1, p2, q2), orient(q1, q2, p1), orient(q1, q2, p2)
    return o1 * o2 <= 0 and o3 * o4 <= 0 and not (o1 == o2 == 0)


def screenline(spec):
    a = math.radians(float(spec['road_angle_deg']) + 90.0)
    h = 1000.0 * float(spec['half_km'])
    x, y = float(spec['x']), float(spec['y'])
    return (x - h * math.cos(a), y - h * math.sin(a)), (x + h * math.cos(a), y + h * math.sin(a))


def _stations_from_mapping(folder):
    p = Path(folder) / 'data' / 'audited' / 'STATION_MAPPING.csv'
    out = {}
    if not p.is_file():
        return out
    for r in csv.DictReader(open(p, encoding='utf-8-sig'), delimiter=';'):
        lab = r['station_label']
        if lab in out:
            continue
        try:
            ang = float(r['local_angle_deg']) % 180.0
            out[lab] = {'x': float(r['gpkg_x']), 'y': float(r['gpkg_y']), 'road_angle_deg': ang, 'half_km': 10.0}
        except (TypeError, ValueError):
            continue
    return out


def _cols(coll, names):
    cols = {}
    for n in names:
        try:
            cols[n] = [row[1] for row in coll.GetMultiAttValues(n, False)]
        except Exception as exc:
            cols[n] = None
            cols['_error_' + n] = repr(exc)[:200]
    return cols


RATIO_MATRIX_NOS = (9231, 9232, 9233, 9234)
CATALOGUE_ATTRS = ('NAME', 'MATRIXTYPE', 'OBJECTTYPEREF', 'DATASOURCETYPE', 'FORMULA', 'DSEGCODE', 'SUM')


def matrix_catalogue(v):
    """Every matrix: number, code and the attributes COM exposes (type, data source, formula, sum);
    for the split-ratio matrices also whether FORMULA is editable. Read-only."""
    out = {'matrices': [], 'skim_like': [], 'ratio_matrices': {}}
    try:
        allm = list(v.Net.Matrices.GetAll)
    except Exception as exc:
        out['error'] = repr(exc)[:300]
        return out
    for m in allm:
        try:
            rec = {'no': int(m.AttValue('NO')), 'code': str(m.AttValue('CODE'))}
        except Exception:
            continue
        for a in CATALOGUE_ATTRS:
            try:
                rec[a.lower()] = m.AttValue(a)
            except Exception:
                pass
        out['matrices'].append(rec)
        text = ' '.join(str(rec.get(k, '')) for k in ('code', 'name', 'matrixtype')).upper()
        if 'SKIM' in text or 'TCUR' in text or 'T0' in text.split() or 'IMP' in text:
            out['skim_like'].append(rec)
        if rec['no'] in RATIO_MATRIX_NOS:
            ed = None
            try:
                ed = bool(m.Attributes.ItemByKey('FORMULA').Editable)
            except Exception as exc:
                ed = 'UNKNOWN:' + repr(exc)[:120]
            out['ratio_matrices'][str(rec['no'])] = dict(rec, formula_editable=ed)
    out['matrices'].sort(key=lambda r: r['no'])
    return out


def main(namespace):
    v = namespace.get('Visum')
    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    out = Path(os.environ.get('LOCALAPPDATA') or Path.home()) / 'R1C25_BOOT' / ('NOT_SHARE_AUDIT_' + stamp)
    out.mkdir(parents=True, exist_ok=True)
    res = {'schema': 'R1C25_NOT_SHARE_AUDIT_V1', 'read_only': True, 'started': stamp}

    def save():
        (out / 'NOT_SHARE_AUDIT.json').write_text(json.dumps(res, indent=1, default=str), encoding='utf-8')

    try:
        res['version'] = str(v.IO.CurrentVersionFile)
    except Exception:
        res['version'] = None
    # 1) procedure sequence
    ops = []
    try:
        for op in v.Procedures.Operations.GetAll:
            row = {}
            for a in ('NO', 'OPERATIONTYPE', 'COMMENT', 'ACTIVE'):
                try:
                    row[a] = op.AttValue(a)
                except Exception:
                    pass
            for acc, attrs in (('RunScriptParameters', ('SCRIPTFILE', 'SCRIPTFILENAME')),
                               ('CombinationOfMatricesAndVectorsParameters', ('FORMULA', 'RESULTMATRIX')),
                               ('MatrixCalculationParameters', ('FORMULA', 'RESULTMATRIX'))):
                try:
                    p = getattr(op, acc)
                    for a in attrs:
                        try:
                            row[acc + '.' + a] = p.AttValue(a)
                        except Exception:
                            pass
                except Exception:
                    pass
            ops.append(row)
    except Exception as exc:
        res['operations_error'] = repr(exc)[:300]
    res['operations'] = ops
    for name in ('SaveXml', 'SaveXML'):
        try:
            getattr(v.Procedures, name)(str(out / 'PROCEDURES.xml'))
            res['procedures_xml'] = 'PROCEDURES.xml'
            break
        except Exception as exc:
            res['procedures_xml_error_' + name] = repr(exc)[:200]
    save()
    # 2) matrix totals
    mats = []
    try:
        for m in v.Net.Matrices.GetAll:
            try:
                no = int(m.AttValue('NO')); code = str(m.AttValue('CODE'))
            except Exception:
                continue
            if no in MATRIX_NOS or 'NOT' in code.upper():
                rec = {'no': no, 'code': code}
                for a in ('NAME', 'SUM', 'DIAGSUM'):
                    try:
                        rec[a.lower()] = m.AttValue(a)
                    except Exception:
                        pass
                mats.append(rec)
    except Exception as exc:
        res['matrices_error'] = repr(exc)[:300]
    res['matrices'] = sorted(mats, key=lambda r: r['no'])
    by_code = {r['code'].upper(): r.get('sum') for r in mats}
    shares = {}
    for base in ('NATIVE_CW', 'NATIVE_CS', 'EXOG_EE_CW', 'EXOG_EE_CS'):
        a = by_code.get(base); b = by_code.get(base + '_NOT')
        if isinstance(a, (int, float)) and isinstance(b, (int, float)) and a + b > 0:
            shares[base] = {'with_vignette': a, 'no_vignette': b, 'no_vignette_share': b / (a + b)}
    res['no_vignette_share_by_matrix_code'] = shares
    save()
    # 5) vignette pricing readiness (variant b: the split is a visible Visum formula):
    #    catalogue of all matrices (type, data source, formula) -> which skim matrices exist for
    #    C and C_noT, and whether the FORMULA of the split-ratio matrices 9231..9234 is editable.
    res['matrix_catalogue'] = matrix_catalogue(v)
    save()
    # 3) + 4) network
    links = _cols(v.Net.Links, LINK_ATTRS + tuple('VOLVEH_DSEG(%s,AP)' % c for c in DSEG_CODES))
    n = len(links['NO'] or [])
    res['links'] = n
    vig = {}
    rows = []
    for i in range(n):
        ts = set(str(links['TSYSSET'][i] or '').split(','))
        if 'C' in ts and 'C_noT' not in ts:
            t = int(links['TYPENO'][i]); km = float(links['LENGTH'][i] or 0.0)
            s = vig.setdefault(t, {'links': 0, 'km': 0.0}); s['links'] += 1; s['km'] += km
            rows.append({k: links[k][i] for k in ('NO', 'FROMNODENO', 'TONODENO', 'TYPENO', 'LENGTH', 'ADDVAL1')})
    res['vignette_only_links_by_type'] = {str(k): v_ for k, v_ in sorted(vig.items())}
    with open(out / 'VIGNETTE_ONLY_LINKS.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['NO', 'FROMNODENO', 'TONODENO', 'TYPENO', 'LENGTH', 'ADDVAL1'], delimiter=';')
        w.writeheader(); w.writerows(rows)
    lines = dict(SCREENLINES)
    found = _stations_from_mapping(Path(__file__).resolve().parent) if '__file__' in globals() else {}
    for lab in list(lines):
        if lines[lab] is None:
            lines[lab] = found.get(lab)
    res['screenlines'] = {}
    xy = [links[k] for k in (r'FROMNODE\XCOORD', r'FROMNODE\YCOORD', r'TONODE\XCOORD', r'TONODE\YCOORD')]
    for lab, spec in lines.items():
        if not spec or any(c is None for c in xy):
            res['screenlines'][lab] = {'error': 'NO_SPEC_OR_NO_COORDINATES'}
            continue
        q1, q2 = screenline(spec)
        hits = []
        for i in range(n):
            p1 = (float(xy[0][i]), float(xy[1][i])); p2 = (float(xy[2][i]), float(xy[3][i]))
            if segment_crosses(p1, p2, q1, q2):
                rec = {k: links[k][i] for k in ('NO', 'FROMNODENO', 'TONODENO', 'TYPENO', 'TSYSSET', 'LENGTH',
                                                'ADDVAL1', 'V0PRT')}
                for c in DSEG_CODES:
                    col = links.get('VOLVEH_DSEG(%s,AP)' % c)
                    rec[c] = float(col[i]) if col is not None else None
                rec['CAR_TOTAL'] = sum(rec[c] or 0.0 for c in DSEG_CODES)
                rec['NO_VIGNETTE'] = sum(rec[c] or 0.0 for c in DSEG_CODES if c.endswith('_noT'))
                hits.append(rec)
        hits.sort(key=lambda r: -r['CAR_TOTAL'])
        with open(out / ('SCREENLINE_%s.csv' % lab), 'w', newline='', encoding='utf-8') as f:
            if hits:
                w = csv.DictWriter(f, fieldnames=list(hits[0]), delimiter=';'); w.writeheader(); w.writerows(hits)
        res['screenlines'][lab] = {'spec': spec, 'line': [q1, q2], 'links_crossing': len(hits),
                                   'car_total': sum(r['CAR_TOTAL'] for r in hits),
                                   'no_vignette_total': sum(r['NO_VIGNETTE'] for r in hits),
                                   'top10': hits[:10]}
        save()
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
