"""Directional station profile evidence from E41 SDP RAW dataset (OA, 6-18 h)."""
import openpyxl, collections, datetime, json, sys, hashlib
src, d3, out = sys.argv[1:4]
GAP = 7200
wb = openpyxl.load_workbook(src, read_only=True, data_only=True)
ws = wb['Opravený dataset']
hdr = None
cnt = collections.Counter(); det = collections.defaultdict(list); n = 0
for i, r in enumerate(ws.iter_rows(min_row=2, values_only=True)):
    if i == 0:
        hdr = r[:5]; assert tuple(hdr) == ('ID', 'ECV', 'Category', 'dir', 'Timestamp'), hdr; continue
    if r[0] is None: continue
    st = str(r[0]).strip(); st = '5' if st == '5 nové' else st
    s = int(st); cat = str(r[2]).strip(); sg = str(r[3]).strip(); t = r[4]
    assert sg in '+-' and isinstance(t, datetime.time) and 1 <= s <= 16, r
    n += 1
    cnt[(s, sg, cat)] += 1
    if cat == 'OA':
        det[r[1]].append((t.hour * 3600 + t.minute * 60 + t.second, s, sg))
ctx = collections.Counter()
for p, d in det.items():
    d.sort()
    for a, b in zip(d, d[1:]):
        if a[1] != b[1] and b[0] - a[0] <= GAP:
            ctx[(a[1], a[2], 'DEP', b[1])] += 1
            ctx[(b[1], b[2], 'ARR', a[1])] += 1
wb3 = openpyxl.load_workbook(d3, read_only=True, data_only=True)
k = list(wb3['Koeficienty_vypocet'].iter_rows(values_only=True))
assert k[0][0] == 'Zóna' and k[0][3] == 'OA_RPDI', k[0]
coef = {int(r[0]): float(r[3]) for r in k[1:17]}
recog = ('OA', 'LNA', 'STNA', 'TNA', 'BUS')
stations = []
for s in range(1, 17):
    sig = {}
    for sg in '+-':
        oa = cnt[(s, sg, 'OA')]; rec = sum(cnt[(s, sg, c)] for c in recog); unk = cnt[(s, sg, 'Nerozpoznané')]
        oa12 = oa + (unk * oa / rec if rec else 0.0)
        sig[sg] = {'oa_detections_12h': oa, 'unrecognized_detections_12h': unk, 'recognized_detections_12h': rec,
                   'oa_12h_with_unrecognized_share': oa12, 'target_rpdi': oa12 * coef[s],
                   'contexts': {f'{role}:{t}': ctx[(s, sg, role, t)] for (ss, g, role, t) in sorted(ctx) if ss == s and g == sg}}
    stations.append({'station': s, 'zone_coefficient_oa_rpdi': coef[s], 'signs': sig,
                     'target_rpdi_both': sig['+']['target_rpdi'] + sig['-']['target_rpdi']})
h = lambda f: hashlib.sha256(open(f, 'rb').read()).hexdigest()
doc = {'schema': 'LIVE04_10_STATION_PROFILE_EVIDENCE_V1', 'source_raw': 'E41 - SDP_RAW_dataset_FINAL.xlsx', 'source_raw_sha256': h(src),
       'source_d3': 'D3.xlsx', 'source_d3_sha256': h(d3), 'sheet': 'Opravený dataset', 'detections': n,
       'rules': {'category': 'OA (+ Nerozpoznané in proportion OA/recognized per station and sign)',
                 'station_5_nove': 'counted as SDP5 (supplementary camera, sign -, 16-18 h)',
                 'expansion': 'D3 Koeficienty_vypocet OA_RPDI of the station zone (same 12h->RPDI factor as the D3 matrix)',
                 'context_gap_seconds': GAP,
                 'contexts': 'consecutive OA detections of one plate at different stations within the gap: DEP:t at the earlier, ARR:t at the later station'},
       'stations': stations}
json.dump(doc, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, sort_keys=True)
for st in stations:
    s = st['station']; p, m = st['signs']['+'], st['signs']['-']
    print(s, round(p['target_rpdi']), round(m['target_rpdi']), round(st['target_rpdi_both']))
