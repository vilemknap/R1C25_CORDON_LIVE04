import copy
import numpy as np
import pytest
from cordon2025.common import ROOT,read_csv,parent_core,read_json
from cordon2025.live01_config import load_config,calculation_config,validate_config
from cordon2025.live01_observations import load_authority,audit_cells,aggregate_whole
from cordon2025.incidence import Incidence
from cordon2025.optimizer import build_problem,solve
from cordon2025.targeting import path_targeting_report


def directed_fixture(cells):
    keys=sorted(k for k in cells if k[0]!=k[1]);q=np.array([cells[k] for k in keys]);n=len(keys);core=parent_core()
    meta=[{'origin':a,'destination':b,'dseg_code':'NATIVE_CW','family':'WORK','q_current':float(q[i]),'variable_index':i,'path_count':1} for i,(a,b) in enumerate(keys)]
    rows=[{'origin_station':a,'destination_station':b,'role':'DIAGNOSTIC','method':'ALL_ORDERED_UNIQUE_PAIRS'} for a,b in keys]
    rr=np.arange(n,dtype=np.int64)
    return Incidence(rows,meta,meta,q,core.SparseOperator(rr,rr,q,n,n),core.SparseOperator(rr,rr,np.ones(n),n,n),q.copy(),q.copy(),np.zeros(n),{'method':'ALL_ORDERED_UNIQUE_PAIRS','origin':'SYNTHETIC_TEST_FIXTURE','all_od_totals':[]})


def test_all_256_cells_120_cal_and_exact_legacy_transform():
    cfg=load_config();cells,a=load_authority(cfg)
    assert (a['source_cells'],a['diagonal_cells'],a['offdiagonal_cells'])==(256,16,240)
    directed=directed_fixture(cells);inc,trace,roster=aggregate_whole(directed,cells)
    assert (roster['rows'],roster['calibration'],roster['validation'])==(120,120,0)
    mathcfg=calculation_config(cfg,list(range(1,682)))
    problem,selected,y,base,eps=build_problem(inc,mathcfg)
    assert len(selected)==problem.operator.n_rows==120
    assert np.array_equal(y,base) and all(t['residual']==0 for t in trace)
    s=solve(inc,mathcfg);assert s.report['objective_final']==0
    assert not np.any(s.x)
    assert len({(r['origin_station'],r['destination_station']) for r in inc.rows})==120


@pytest.mark.parametrize('pair',read_json(ROOT/'CORDON_2025_CONFIG.json')['validation_unordered_pairs'])
def test_each_previous_holdout_changes_loss(pair):
    live=load_config();cells,_=load_authority(live);source=directed_fixture(cells)
    changed=dict(cells);a,b=pair;changed[a,b]+=3;changed[b,a]+=3
    inc,trace,roster=aggregate_whole(source,changed)
    problem,selected,y,base,_=build_problem(inc,calculation_config(live))
    assert len(selected)==120 and np.count_nonzero(y-base)==1
    assert float(np.sum((problem.row_weight*(y-base))**2))>0
    assert path_targeting_report(inc)['family_pressures']


@pytest.mark.parametrize('damage',['duplicate','missing','nan','inf','negative','asymmetry','diagonal','year','unit'])
def test_invalid_cells_fail(damage):
    rows=[r for r in read_csv(ROOT/'data/audited/PHYSICAL_TARGETS.csv') if r['category']=='OA']
    if damage=='duplicate':rows.append(dict(rows[0]))
    elif damage=='missing':rows.pop()
    elif damage in ('nan','inf','negative'):rows[1]['observed_rpdi']={'nan':'nan','inf':'inf','negative':'-1'}[damage]
    elif damage=='asymmetry':rows[1]['observed_rpdi']='9999'
    elif damage=='diagonal':rows[0]['observed_rpdi']='1'
    elif damage=='year':rows[0]['survey_year']='2022'
    else:rows[0]['basis']='HOUR'
    with pytest.raises(ValueError):audit_cells(rows)


def test_zero_pair_not_silently_filtered():
    rows=read_csv(ROOT/'data/audited/PHYSICAL_TARGETS.csv')
    for r in rows:
        if r['category']=='OA' and {r['matrix_row_station'],r['matrix_column_station']}=={'1','2'}:r['observed_rpdi']='0'
    cells,a=audit_cells(rows);assert a['unordered_pairs']==120 and a['nonzero_offdiagonal']==238


@pytest.mark.parametrize('key,value',[('writes_enabled',True),('assignment_enabled',True),('apply_permitted',True),('capture_backend','FAST_EXACT'),('validation_rows',12),('c17_allocation_policy','BOUNDED_SCENARIO'),('execution_mode','PRODUCTION'),('model_year',2022),('outer_cycle',True),('primary_aggregation','MEAN')])
def test_bad_live_config_refused(key,value):
    c=load_config();c[key]=value
    with pytest.raises(ValueError):validate_config(c)


def test_old_aggressive_guards_unchanged():
    from cordon2025.aggressive_policy import assert_offline_contract
    cfg=calculation_config(load_config())
    with pytest.raises(ValueError,match='AGGRESSIVE_OFFLINE_ONLY'):assert_offline_contract(cfg)
