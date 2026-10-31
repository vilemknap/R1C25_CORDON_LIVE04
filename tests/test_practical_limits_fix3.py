"""FIX3: real capture replay, numerical limits and corruption counterexamples."""
from dataclasses import replace
from pathlib import Path
from contextlib import closing
import copy
import json
import os
import sqlite3
import numpy as np
import pytest
from cordon2025.common import ROOT, ContractError, canonical_hash, read_config, sha256
from cordon2025.parity import ParityPolicy, compare, compare_database
from cordon2025.visum_startup import settings, ReadControl, preflight, capture
from cordon2025.limits import numerical
from cordon2025.aggressive_policy import effective_config, META
from cordon2025.external_parity import check_matrix_authorities
from cordon2025.authority import mapping
from cordon2025.incidence import build_from_snapshot
from fake_visum_startup import FakeVisum, ListObj


def arrays(n=3):
    v=np.zeros((n,n));p=v.copy();counts=np.zeros_like(v,dtype=np.int64)
    return v,p,counts,np.arange(1,n+1,dtype=np.int64)


def result(v,p,n,z,policy=None,lattice=0.):
    return compare(v,p,n,z,'NATIVE_CW',policy or ParityPolicy(),max_lattice_error=lattice)


def test_rounding_envelope_is_per_path_not_blanket_OD_constant():
    v,p,n,z=arrays();v[0,1]=1.00049;p[0,1]=1.;n[0,1]=1
    # Larger reference flow avoids an intentionally strict aggregate small-case cap.
    v[1,2]=p[1,2]=100.;n[1,2]=1
    r=result(v,p,n,z)
    assert r['status']=='PASS' and r['strict_legacy_inconsistent_od_count']==1
    v[0,1]=1.0011
    assert result(v,p,n,z)['status']=='FAIL'
    n[0,1]=3
    assert result(v,p,n,z)['status']=='PASS'


def test_nonlattice_source_does_not_get_unproven_rounding_allowance():
    v,p,n,z=arrays();v[0,1]=1.00049;p[0,1]=1.;n[0,1]=1;v[1,2]=p[1,2]=100.;n[1,2]=1
    r=result(v,p,n,z,lattice=0.0001)
    assert r['status']=='FAIL' and r['effective_path_volume_quantum']==0


def test_zero_volume_path_is_not_same_as_absent_path():
    v,p,n,z=arrays();v[0,1]=0.0003;n[0,1]=1;v[1,2]=p[1,2]=100.;n[1,2]=1
    r=result(v,p,n,z)
    assert r['status']=='PASS' and r['positive_matrix_zero_path_flow_count']==1
    assert r['positive_matrix_no_path_rows_count']==0
    n[0,1]=0;r=result(v,p,n,z)
    assert r['positive_matrix_no_path_rows_count']==1 and r['positive_matrix_zero_path_flow_mass']==.0003
    assert not r['raw_matrix_and_paths_modified']


def test_true_missing_path_not_hidden_by_global_total():
    v,p,n,z=arrays();v[0,1]=.01;v[1,2]=p[1,2]=10000.;n[1,2]=1
    r=result(v,p,n,z)
    assert r['status']=='FAIL' and r['missing_or_inconsistent_od_count']==1


def test_equal_total_does_not_hide_redistribution():
    v,p,n,z=arrays();v[0,1]=v[1,2]=100.;p[0,1]=101.;p[1,2]=99.;n[0,1]=n[1,2]=1
    r=result(v,p,n,z)
    assert r['status']=='FAIL' and abs(r['net_path_minus_matrix'])<1e-12
    assert 'AGGREGATE_GROSS_VOLUME_MISMATCH' in r['failures']


def test_many_missing_parent_rows_cannot_spend_unlimited_precision():
    v,p,n,z=arrays(30);m=~np.eye(30,dtype=bool);v[m]=.00049
    r=result(v,p,n,z)
    assert r['missing_or_inconsistent_od_count']==0 and r['status']=='FAIL'
    assert 'ZERO_FLOW_DEMAND_BUDGET_EXCEEDED' in r['failures']


def test_net_cap_independent_of_l1_cap():
    v,p,n,z=arrays();v[0,1]=1000.;p[0,1]=1000.2;n[0,1]=1000
    r=result(v,p,n,z,policy=replace(ParityPolicy(),path_volume_quantum=0.,atol=.3))
    assert r['missing_or_inconsistent_od_count']==0
    assert r['sum_absolute_od_error']<r['aggregate_limits']['l1_absolute']
    assert r['failures']==['AGGREGATE_NET_VOLUME_MISMATCH']


@pytest.mark.parametrize('field',list(ParityPolicy.__dataclass_fields__))
@pytest.mark.parametrize('bad',[-1.,float('nan'),float('inf'),True])
def test_invalid_precision_limits_fail(field,bad):
    with pytest.raises(ContractError):replace(ParityPolicy(),**{field:bad})


def test_policy_round_trip_and_unknown_fields_fail():
    p=ParityPolicy();assert ParityPolicy.from_record(p.record())==p
    with pytest.raises(ContractError):ParityPolicy.from_record(dict(p.record(),extra=1))


@pytest.mark.parametrize('bad',[-1.,float('nan'),float('inf')])
def test_invalid_raw_values_still_fail(bad):
    v,p,n,z=arrays();v[0,1]=bad
    with pytest.raises(ContractError):result(v,p,n,z)
    v[0,1]=0;p[0,1]=bad
    with pytest.raises(ContractError):result(v,p,n,z)


def test_precision_options_can_now_be_relaxed_explicitly():
    p=settings({'od_parity_atol':.002,'od_parity_rtol':.0001})
    assert p['od_parity_atol']==.002 and p['max_store_gib']==0
    assert p['max_parent_rows_per_dseg']==5000000
    assert p['com_retry_attempts']==128 and p['com_retry_max_elapsed_seconds']==180


def test_practical_config_thresholds_and_legacy_regression():
    raw=json.loads((ROOT/'CORDON_2025_AGGRESSIVE_CONFIG.json').read_text())
    a=effective_config(raw);b=copy.deepcopy(raw);b['limit_profile']='LEGACY_STRICT';b=effective_config(b)
    assert a['generation_min_cal_relative_improvement']==1e-6
    assert b['generation_min_cal_relative_improvement']==1e-5
    assert a['td']['min_selected_component_relative_improvement']==5e-5
    assert b['td']['min_selected_component_relative_improvement']==5e-4
    for k in ('relative_od_lower','relative_od_upper','c17_ridge','ridge','l1','epsilon_abs','mutable_dsegs','validation_unordered_pairs'):
        assert a[k]==b[k]


@pytest.mark.parametrize('cycle',[101,1000,100000])
def test_last_stage_continues_without_artificial_stop(cycle):
    cfg=read_config(ROOT/'CORDON_2025_AGGRESSIVE_CONFIG.json',outer_cycle=cycle)
    assert cfg[META]['stage']['name']=='DISTRIBUTION_FOCUS'
    assert cfg[META]['last_stage_continuation'] and cfg['relative_od_upper']==.08
    assert effective_config(cfg)==cfg


@pytest.mark.parametrize('bad',[-1.,float('nan'),True])
def test_runtime_numeric_overrides_validated(bad):
    with pytest.raises(ContractError):numerical({'numerical_limits':{'feasibility_atol':bad}})


def test_budget_projection_does_not_inflate_accounts_when_less_precise():
    from cordon2025.budget import SharedBudget
    b=SharedBudget([(1,2),(1,3)],[1,2,3],np.array([1.,1000.,1000.]),2001.,'BOUNDED_SCENARIO',{},True)
    u=b.project([100.,100.],tolerance=1e-8)
    ledger=b.ledger(u)
    assert all(r['consumed']<=r['available']+1e-12 for r in ledger['station_accounts'])
    assert ledger['global_credits_consumed']<=ledger['global_credits_available']


def test_practical_feasibility_is_approximate_and_reported():
    from test_optimizer import example,cfg
    from cordon2025.optimizer import solve
    from test_feasibility import basis_for
    from cordon2025.feasibility import evaluate_realizability
    inc=example(matrix=np.eye(4)*100,targets=100+np.array([.0004,-.0004,-.0004,.0004]))
    sol=solve(inc,cfg(ridge=0,l1=0,limit_profile='PRACTICAL_V1'))
    r=evaluate_realizability(inc,sol,basis_for(inc))
    assert r['status']=='SYNTHETIC_FEASIBLE_TG_TD' and r['full_od_max_abs_residual']>1e-5
    assert r['tolerance_abs']==.001 and not r['live_verified']
    assert evaluate_realizability(inc,sol,basis_for(inc),tolerance=1e-6)['status']=='INFEASIBLE_TG_TD'


class RoundedList(ListObj):
    def SetObjects(self,*args):
        super().SetObjects(*args)
        if self.kind=='parent':
            for row in self.rows:row[3]=round(row[3],3)


def rounded_capture(tmp_path):
    v=FakeVisum(tmp_path/'model')
    for ds in v.dsegs.values():
        ds.ODMatrix.values[0,1]+=.00049
        ds.ODMatrix.values[1,2]-=.00049
        ds.ODMatrix.values[0,2]=.0002  # tiny missing row, explicitly budgeted/audited
    v.Workbench.Lists.CreatePrTPathList=lambda:RoundedList(v,'parent')
    cfg=read_config(ROOT/'CORDON_2025_AGGRESSIVE_CONFIG.json');out=tmp_path/'out';out.mkdir()
    opt=settings({'page_size':2,'min_free_disk_gib':0.})
    ctl=ReadControl(out);pre=preflight(v,cfg,out,ctl,opt);path,ep=capture(v,cfg,out,ctl,opt,pre)
    return v,cfg,out,path,json.loads(ep.read_text())


def test_full_mock_capture_rounding_and_external_replay_agree(tmp_path):
    v,cfg,out,path,e=rounded_capture(tmp_path);cfg['mutable_dsegs']=[]
    sm,_=mapping(ROOT/'data/audited/STATION_MAPPING.csv')
    inc=build_from_snapshot(path,sm,cfg,e)
    assert all(i.audit['per_od_external_parity']=='PASS' for i in inc.values())
    reports=json.loads((out/'OD_PARITY.json').read_text())
    assert len(reports)==12 and all(r['status']=='PASS' and r['quantization_compatible'] for r in reports)
    assert all(r['positive_matrix_no_path_rows_count']==1 for r in reports)
    assert not v.writes and not v.unbounded
    with closing(sqlite3.connect(path)) as db:
        assert db.execute('SELECT COUNT(*) FROM volumes').fetchone()[0]==24


@pytest.mark.parametrize('damage',['policy_hash','policy_cache','volume','matrix','zero_row'])
def test_corruption_is_not_reclassified_as_rounding(tmp_path,damage):
    from cordon2025.io import write_npz
    v,cfg,out,path,e=rounded_capture(tmp_path);cfg['mutable_dsegs']=[]
    sm,_=mapping(ROOT/'data/audited/STATION_MAPPING.csv')
    if damage in ('policy_hash','policy_cache'):
        e['path_matrix_parity_policy']['atol']=100.
        if damage=='policy_cache':e['path_matrix_parity_policy_sha256']=canonical_hash(e['path_matrix_parity_policy'])
    elif damage=='matrix':
        rec=e['od_matrix_authorities'][0];f=out/rec['path']
        with np.load(f) as a:values=a['values'].copy();zones=a['zone_nos'].copy()
        values[0,1]+=1.;values[1,2]-=1.;write_npz(f,values=values,zone_nos=zones)
        rec['sha256']=sha256(f)
    else:
        with closing(sqlite3.connect(path)) as db:
            if damage=='zero_row':db.execute('DELETE FROM volumes WHERE gid=1 AND dseg=(SELECT MIN(dseg) FROM volumes)')
            else:db.execute('UPDATE volumes SET volume=volume+1 WHERE gid=1')
            db.commit()
        e['cache_sha256']=sha256(path)
    with pytest.raises(ContractError):build_from_snapshot(path,sm,cfg,e)


def test_input_npz_and_cache_never_changed_by_parity(tmp_path):
    _,_,_,path,e=rounded_capture(tmp_path)
    before=sha256(path)
    rec=e['od_matrix_authorities'][0]
    with np.load(path.parent/rec['path']) as data:
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
            compare_database(db,rec['dseg'],data['values'],data['zone_nos'],ParityPolicy())
    assert sha256(path)==before and sha256(path.parent/rec['path'])==rec['sha256']


def test_real_native_CW_capture_replay():
    database=os.environ.get('R1_REAL_PARITY_SQLITE');matrix=os.environ.get('R1_REAL_PARITY_NPZ')
    if not database or not matrix:pytest.skip('Real user failure fixture supplied externally, not embedded')
    before=(sha256(database),sha256(matrix))
    with np.load(matrix,allow_pickle=False) as a:
        with closing(sqlite3.connect(Path(database).as_uri()+'?mode=ro',uri=True)) as db:
            r,_=compare_database(db,'NATIVE_CW',a['values'],a['zone_nos'],ParityPolicy())
            old,_=compare_database(db,'NATIVE_CW',a['values'],a['zone_nos'],ParityPolicy.legacy())
            assert db.execute("SELECT value FROM metadata WHERE key='capture_complete'").fetchone() is None
    assert r['status']=='PASS' and old['status']=='FAIL'
    assert r['strict_legacy_inconsistent_od_count']==405657 and r['missing_or_inconsistent_od_count']==0
    assert r['positive_matrix_no_path_rows_count']==0
    assert r['positive_matrix_zero_path_flow_count']==90852
    assert abs(r['net_path_minus_matrix']+4.1968958366)<1e-6
    assert r['quantization_compatible']
    assert (sha256(database),sha256(matrix))==before


def test_small_segment_verified_rounding_not_rejected_twice_by_percentage():
    v,p,n,z=arrays(30);m=~np.eye(30,dtype=bool);v[m]=.00049;n[m]=1
    r=result(v,p,n,z)
    assert r['status']=='PASS' and r['raw_errors_above_residual_limits']
    assert r['unexplained_l1_error']==0 and r['unexplained_zero_flow_demand_mass']==0
    assert r['positive_matrix_zero_path_flow_mass']>0.4
    assert not r['raw_matrix_and_paths_modified']


def test_internal_mutable_sum_uses_practical_accuracy(tmp_path,monkeypatch):
    from test_incidence import fixture
    from cordon2025.common import parent_core
    p,m,e,c=fixture(tmp_path);c['limit_profile']='PRACTICAL_V1'
    core=parent_core();original=core.SparseOperator.forward
    def perturbed(self,x):return original(self,x)+5e-7
    monkeypatch.setattr(core.SparseOperator,'forward',perturbed)
    assert build_from_snapshot(p,m,c,e)
    c['limit_profile']='LEGACY_STRICT'
    with pytest.raises(ContractError,match='MUTABLE_PREDICTION_PARITY_FAIL'):
        build_from_snapshot(p,m,c,e)


@pytest.mark.parametrize('demand,expected',[(.294,'PASS'),(.4,'FAIL')])
def test_legacy_aggregate_guard_replaced_only_by_cellwise_proof(tmp_path,demand,expected):
    from cordon2025.visum_startup import _add_parents_with_precision
    from cordon2025.common import parent_module
    two=parent_module('r1_15a2_two_mode_v238');supply=parent_module('r1_15a2_supply')
    v,p,n,z=arrays();v[0,1]=demand
    ds={'norm_code':'NATIVE_CW','code':'NATIVE_CW'}
    ctl=ReadControl(tmp_path);opt=settings({'min_free_disk_gib':0.})
    authority={'matrix_interzonal':demand,'matrix_total':demand,'matrix_diagonal':0.,'matrix_no':9301}
    store=two.TwoModeRouteCollector([],supply.SupplyPolicy(),'example',{},tmp_path/'tiny.sqlite',
              dict(two.DEFAULT_SETTINGS,min_free_disk_gib=0.),ctl,geometry_only=True)
    try:
        report=_add_parents_with_precision(store,ds,'C',[(1,2,i,0.) for i in range(1,601)],authority,v,z,opt)
        assert report['status']==expected
        assert not report['inherited_aggregate_parity_passed']
        assert report['inherited_aggregate_failure']=='SAME_RUN_OFFDIAGONAL_PARITY_FAILED:NATIVE_CW'
        assert store.db.execute('SELECT COUNT(*) FROM volumes').fetchone()[0]==600
        assert store.db.execute('SELECT SUM(volume) FROM volumes').fetchone()[0]==0.
    finally:store.close()
