"""Read-only D1/D2/D3 lineage audit. No formula recalculation or source rewriting."""
from __future__ import annotations
import re
import json
from pathlib import Path
import numpy as np
from .common import write_npz
from .io import mkdir
from .common import require, finite, sha256, read_csv, write_json, write_csv

CATEGORIES = ('OA','LNA','STNA','TNA','BUS')
BLOCKS = {'Transit': 6, 'NonTransit': 29, 'ALL': 52}

def mapping(path, station_count=16):
    idx = {}; provenance = []
    for r in read_csv(path):
        sid = int(r['station_id'])
        key = tuple(int(r[x]) for x in ('link_no','from_node_no','to_node_no'))
        require(1 <= sid <= station_count, 'INVALID_STATION')
        require(key not in idx, 'DUPLICATE_DIRECTED_MAPPING')
        require(key[1] != key[2], 'SELF_LOOP_STATION_LINK')
        idx[key] = sid
        provenance.append(dict(r, source_sha256=sha256(path)))
    require(set(idx.values()) == set(range(1,station_count+1)), 'INCOMPLETE_STATION_MAPPING')
    require(len(idx) == station_count*2 and all(list(idx.values()).count(s)==2 for s in range(1,station_count+1)), 'EXPECTED_TWO_DIRECTIONS_PER_STATION')
    return idx, provenance

def _rows(ws, end=70):
    return list(ws.iter_rows(max_row=end, values_only=True))

def _matrix(rows, start, label):
    vals = []
    header=rows[start-2]
    require(list(header[1:17])==['SDP%d'%i for i in range(1,17)],'COLUMN_LABEL_MISMATCH:'+label)
    normalize=lambda x: str(x).replace(' ','').replace('\n','')
    require(normalize(header[17])=='VJAZD(bezpáru)','C17_COLUMN_LABEL_MISMATCH:'+label)
    require(normalize(rows[start+15][0]) in ('VJAZD(bezpáru)','VÝJAZD(bezpáru)'), 'C17_ROW_LABEL_MISMATCH:'+label)
    require(normalize(rows[start+16][0])=='vjazd-výjazd','RETURN_ROW_LABEL_MISMATCH:'+label)
    require(normalize(header[18]) in ('vjazd-výjazd','výjazd-vjazd'),'RETURN_COLUMN_LABEL_MISMATCH:'+label)
    for i in range(18):
        row = rows[start-1+i]
        if i < 16:
            require(row[0] == 'SDP%d' % (i+1), 'ROW_LABEL_MISMATCH:' + label)
        vals.append([finite(row[j+1],label+':'+str((i,j))) for j in range(18)])
    return np.array(vals)

def audit_workbooks(source_dir, output_dir):
    # Spreadsheet audit is an explicit offline operation, never a Visum startup dependency.
    import openpyxl
    from openpyxl.utils import get_column_letter
    src, out = Path(source_dir), Path(output_dir)
    manifest = {name: sha256(src/name) for name in ('D1.xlsx','D2.xlsx','D3.xlsx','MAPPING_INPUT.csv','MAPPING_INPUT.json','PHYSICAL_TARGETS_INPUT.csv')}
    wb = [openpyxl.load_workbook(src/n, read_only=True, data_only=True, keep_links=False) for n in ('D1.xlsx','D2.xlsx','D3.xlsx')]
    arrays = {}; lineage = []; c17 = []; target_rows=[]; formula_evidence=[]
    try:
        for cat in CATEGORIES:
            sheets = [f'OD {cat} CELKOM S SDP4',f'OD {cat} FINAL EMPIRICK\u00c9']
            rows_pre, rows_final = [_rows(wb[0][s]) for s in sheets]
            rows_d2f, rows_sym = [_rows(wb[1][f'OD {cat} {s}']) for s in ('FINAL','SYM')]
            # The actual workbook label is retained, not guessed into driving direction.
            header = str(rows_final[1][0]); require('Riadok' in header, 'MISSING_DIRECTION_LABEL')
            for typ, start in BLOCKS.items():
                pre = _matrix(rows_pre,start,sheets[0]); final=_matrix(rows_final,start,sheets[1])
                d2f=_matrix(rows_d2f,start,'D2 FINAL');sym=_matrix(rows_sym,start,'D2 SYM')
                d3sheet=f'{cat}_{typ}_RPDI';d3rows=_rows(wb[2][d3sheet],45)
                require(str(d3rows[2][0]).startswith('O\\D (M0'), 'D3_LAYOUT_UNRECOGNIZED')
                require(str(d3rows[24][0]).startswith('VYSLEDOK'), 'D3_RESULT_LAYOUT_UNRECOGNIZED')
                m0=_matrix(d3rows,4,'D3 M0');rpdi=_matrix(d3rows,27,'D3 RPDI')
                checks={'D1_FINAL_EQUALS_D2_FINAL':bool(np.array_equal(final,d2f)),
                        'D2_SYM_EQUALS_D3_M0':bool(np.array_equal(sym,m0)),
                        'D2_SYMMETRY':bool(np.array_equal(sym,sym.T)),
                        'D3_RPDI_SYMMETRY':bool(np.array_equal(rpdi,rpdi.T)),
                        'NONNEGATIVE_CLASSIFICATION_ADDITION':bool(np.all(final-pre>=0)),
                        'D3_CONVERGENCE':finite(d3rows[4][22],'rowfactor')<=finite(d3rows[6][22],'conv_tol') and finite(d3rows[5][22],'colfactor')<=finite(d3rows[6][22],'conv_tol')}
                require(all(checks.values()), 'AUTHORITY_LINEAGE_FAIL:' + str((cat,typ,checks)))
                # D2 uses parity-dependent integer rounding, separately for Transit/NonTransit.
                sym_error=float(np.max(np.abs(sym-(final+final.T)/2)))
                lineage.append(dict(category=cat,trip_type=typ,checks=checks,
                    empiric_sum=float(final.sum()),sym_sum=float(sym.sum()),sym_max_deviation_from_exact_mean=sym_error,
                    rpdi_physical_sum=float(rpdi[:16,:16].sum()),c17_one_margin=float(rpdi[:16,16].sum()),
                    empirical_unknown_addition=float((final-pre).sum()),
                    source_hashes=manifest,original_orientation_label=header,
                    model_direction_approved=False,formula_rounding_verified_separately=True))
                for label, a in [('D1_PRE',pre),('D1_FINAL',final),('D2_FINAL',d2f),('D2_SYM',sym),('D3_M0',m0),('D3_RPDI',rpdi)]:
                    arrays[f'{cat}_{typ}_{label}']=a
                if typ != 'ALL': continue
                for i in range(16):
                    csym=float(sym[i,16]); cfinal=float(rpdi[i,16])
                    c17.append({'category':cat,'station_id':i+1,'survey_year':2026,'basis':'RPDI',
                        'D2_pre_row_to_C17':float(final[i,16]),'D2_pre_C17_to_column':float(final[16,i]),
                        'D2_sym_one_margin':csym,'D3_station_to_C17':cfinal,'D3_C17_to_station':float(rpdi[16,i]),
                        'canonical_one_margin_credits':cfinal,'expansion_ratio_sym_to_RPDI':(cfinal/csym if csym else None),
                        'D3_special_row_to_return':float(rpdi[i,17]),'D3_special_return_to_column':float(rpdi[17,i]),
                        'D2_row_cell':f"'OD {cat} FINAL'!R{52+i}", 'D2_col_cell':f"'OD {cat} FINAL'!{get_column_letter(i+2)}68",
                        'D3_row_cell':f"'{d3sheet}'!R{27+i}",'D3_col_cell':f"'{d3sheet}'!{get_column_letter(i+2)}43",
                        'D2_sha256':manifest['D2.xlsx'],'D3_sha256':manifest['D3.xlsx'],
                        'allocation_policy':'UNAPPROVED','production_pair_allocation':False})
                    for j in range(16):
                        target_rows.append({'category':cat,'matrix_row_station':i+1,'matrix_column_station':j+1,
                            'observed_rpdi':float(rpdi[i,j]),'empiric_before_sym':float(final[i,j]),
                            'classification_addition_empiric':float(final[i,j]-pre[i,j]),
                            'D2_sym':float(sym[i,j]),'D3_M0':float(m0[i,j]),'survey_year':2026,'basis':'RPDI',
                            'D3_cell':f"'{d3sheet}'!{get_column_letter(j+2)}{27+i}",
                            'D3_sha256':manifest['D3.xlsx'],'D1_sha256':manifest['D1.xlsx'],
                            'role':'DIAGNOSTIC','direction_status':'MATRIX_AXES_NOT_MODEL_DIRECTIONS'})
        # Verify ALL composition in source; D3 types independently expanded: do not sum into a new ALL target.
        for cat in CATEGORIES:
            for label in ('D1_PRE','D1_FINAL','D2_FINAL','D2_SYM'):
                require(np.array_equal(arrays[f'{cat}_ALL_{label}'],arrays[f'{cat}_Transit_{label}']+arrays[f'{cat}_NonTransit_{label}']), 'ALL_COMPOSITION_MISMATCH')
        input_rows=read_csv(src/'PHYSICAL_TARGETS_INPUT.csv')
        by_input={(r['category'],int(r['origin_station_id']),int(r['destination_station_id'])):finite(r['rpdi_value'],'target') for r in input_rows}
        require(len(input_rows)==len(by_input)==1280,'PHYSICAL_TARGET_COUNT')
        for r in target_rows:
            require(by_input[(r['category'],r['matrix_row_station'],r['matrix_column_station'])]==r['observed_rpdi'],'PHYSICAL_CSV_VS_D3_MISMATCH')
        idx,maprows=mapping(src/'MAPPING_INPUT.csv')
        jm=json.loads((src/'MAPPING_INPUT.json').read_text(encoding='utf-8-sig'))
        records=[(tuple(int(l[k]) for k in ('link_no','from_node_no','to_node_no')),int(st['station_id']))
            for st in jm['stations'] for l in st['selected_links']]
        require(len(records)==len(idx) and dict(records)==idx,'MAPPING_CSV_JSON_MISMATCH')
        require(all(k[0]==2004231 for k,v in idx.items() if v==16),'SDP16_MANUAL_OVERRIDE_MISMATCH')
        # Capture exact formulas as evidence without recalculating or silently changing the sources.
        f2=openpyxl.load_workbook(src/'D2.xlsx',read_only=True,data_only=False,keep_links=False)
        f3=openpyxl.load_workbook(src/'D3.xlsx',read_only=True,data_only=False,keep_links=False)
        try:
            for f,s,cells in [(f2,'OD OA SYM',('C6','C52','D52','R52')),(f3,'OA_ALL_RPDI',('B4','D27','R27'))]:
                rs=_rows(f[s],55)
                for cell in cells:
                    from openpyxl.utils.cell import coordinate_to_tuple
                    ri,ci=coordinate_to_tuple(cell)
                    formula_evidence.append({'sheet':s,'cell':cell,'formula':str(rs[ri-1][ci-1])})
        finally:f2.close();f3.close()
        mkdir(out)
        write_npz(out/'AUDITED_MATRICES.npz',**arrays)
        write_csv(out/'PHYSICAL_TARGETS.csv',target_rows);write_csv(out/'C17_STATION_BUDGETS.csv',c17);write_csv(out/'STATION_MAPPING.csv',maprows)
        addition={cat:float((arrays[f'{cat}_ALL_D1_FINAL']-arrays[f'{cat}_ALL_D1_PRE']).sum()) for cat in CATEGORIES}
        physical_add={cat:float((arrays[f'{cat}_ALL_D1_FINAL']-arrays[f'{cat}_ALL_D1_PRE'])[:16,:16].sum()) for cat in CATEGORIES}
        report={'status':'STATIC_PASS','source_hashes':manifest,'checks':lineage,'unknown_classification_totals':addition,
            'unknown_classification_physical':physical_add,'unknown_classification_grand_total':sum(addition.values()),
            'physical_RPDI_by_category':{cat:float(arrays[f'{cat}_ALL_D3_RPDI'][:16,:16].sum()) for cat in CATEGORIES},
            'C17_one_margin_by_category':{cat:float(arrays[f'{cat}_ALL_D3_RPDI'][:16,16].sum()) for cat in CATEGORIES},
            'formula_evidence':formula_evidence,'formula_recalculation_performed':False,
            'source_files_unchanged':all(sha256(src/n)==h for n,h in manifest.items()),
            'direction_approved':False,'observation_semantics_approved':False,'year_bridge_approved':False,
            'production_ready':False,'apply_permitted':False,'target_count':len(target_rows),'mapping_count':len(idx)}
        require(report['source_files_unchanged'],'AUTHORITY_SOURCE_CHANGED_DURING_AUDIT')
        write_json(out/'AUTHORITY_AUDIT.json',report)
        return report
    finally:
        for w in wb:w.close()
