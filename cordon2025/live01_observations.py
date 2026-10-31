"""Whole final RPDI matrix authority. Legacy aggregation is not redefined."""
from pathlib import Path
from .common import ROOT, require, finite, read_csv, sha256, canonical_hash
from .incidence import aggregate_observations
from .state import observation_roster

POLICY = 'WHOLE_FINAL_SYMMETRIC_RPDI_MATRIX'

def audit_cells(rows):
    cells = {}
    for r in rows:
        if r['category'] != 'OA':
            continue
        a, b = int(r['matrix_row_station']), int(r['matrix_column_station'])
        require(1 <= a <= 16 and 1 <= b <= 16, 'WHOLE_MATRIX_INVALID_STATION')
        require((a, b) not in cells, 'WHOLE_MATRIX_DUPLICATE_CELL')
        require(str(r['survey_year']) == '2026' and r['basis'] == 'RPDI', 'WHOLE_MATRIX_UNIT_OR_YEAR')
        cells[a, b] = finite(r['observed_rpdi'], 'observed_rpdi')
    require(set(cells) == {(a,b) for a in range(1,17) for b in range(1,17)}, 'WHOLE_MATRIX_MISSING_CELL')
    require(all(cells[a,a] == 0 for a in range(1,17)), 'WHOLE_MATRIX_NONZERO_DIAGONAL')
    require(all(cells[a,b] == cells[b,a] for a,b in cells), 'WHOLE_MATRIX_ASYMMETRY')
    trace = [{'origin_station':a,'destination_station':b,'source_value':v,
              'source_status':'AUDITED_STRUCTURAL_ZERO' if a==b else 'USED_IN_WHOLE_MATRIX'}
             for (a,b),v in sorted(cells.items())]
    audit = {'schema':'LIVE01_WHOLE_MATRIX_AUTHORITY_V1','policy':POLICY,
             'source_cells':256,'diagonal_cells':16,'offdiagonal_cells':240,
             'unordered_pairs':120,'calibration':120,'validation':0,
             'nonzero_offdiagonal':sum(v>0 for (a,b),v in cells.items() if a!=b),
             'source_values_modified':False,'source_trace':trace,'cells_sha256':canonical_hash(trace),
             'effective_transform':'EXISTING_BIDIRECTIONAL_SUM_BOTH_MODEL_AND_TARGET',
             'production_approved':False}
    return cells, audit


def load_authority(cfg):
    p = ROOT/'data/audited/PHYSICAL_TARGETS.csv'
    require(sha256(p) == cfg['authority_pins']['physical_targets'], 'WHOLE_MATRIX_SOURCE_HASH_CHANGED')
    cells, audit = audit_cells(read_csv(p))
    audit.update(source_path=p.relative_to(ROOT).as_posix(), source_sha256=sha256(p))
    return cells, audit


def aggregate_whole(inc, cells):
    """One row per unordered pair; use original target/model sum exactly once."""
    off = {(a,b):v for (a,b),v in cells.items() if a!=b}
    roles = {k:'CALIBRATION' for k in off}
    result = aggregate_observations(inc, off, bidirectional=True, roles=roles)
    roster = observation_roster(result.rows)
    require((roster['rows'],roster['calibration'],roster['validation']) == (120,120,0), 'WHOLE_MATRIX_ROSTER_OMISSION')
    require({(r['origin_station'],r['destination_station']) for r in result.rows}
            == {(a,b) for a in range(1,17) for b in range(a+1,17)}, 'WHOLE_MATRIX_PAIR_IDENTITY')
    trace=[]
    directed={(r['origin_station'],r['destination_station']):float(inc.model[i]) for i,r in enumerate(inc.rows)}
    for i,r in enumerate(result.rows):
        a,b=r['origin_station'],r['destination_station']
        y=cells[a,b]+cells[b,a]
        require(r['observed']==y, 'WHOLE_MATRIX_TARGET_TRANSFORM_CHANGED')
        require(float(result.model[i])==directed[a,b]+directed[b,a], 'WHOLE_MATRIX_MODEL_TRANSFORM_CHANGED')
        trace.append({'origin_station':a,'destination_station':b,'source_ij':cells[a,b],
                      'source_ji':cells[b,a],'effective_target':y,'model_ij':directed[a,b],
                      'model_ji':directed[b,a],'effective_model':float(result.model[i]),
                      'role':'CALIBRATION','objective_multiplicity':1,
                      'residual':float(result.model[i])-y})
    result.audit.update(observation_policy=POLICY,whole_matrix_roster=roster)
    return result,trace,roster
