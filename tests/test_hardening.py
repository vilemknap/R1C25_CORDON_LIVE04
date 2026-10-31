import copy,json,sqlite3,subprocess,sys
from pathlib import Path
import numpy as np
import pytest
from cordon2025.common import ROOT,ContractError,read_config,new_output,sha256,deployment_gate,write_csv,write_json
from cordon2025.incidence import build_from_snapshot,aggregate_observations
from cordon2025.authority import _matrix,audit_workbooks
from cordon2025.budget import SharedBudget
from cordon2025.optimizer import solve
from cordon2025.feasibility import evaluate_realizability
from test_optimizer import example,cfg
from test_incidence import fixture
from test_feasibility import basis_for

@pytest.mark.parametrize('field,value', [('apply',True),('run_assignment',True),('run_procseq',True),('write_od',True),('supply_enabled',True),('model_year',2022),('survey_year',2025),('category','LNV'),('basis','PDI')])
def test_config_rejects_scope_or_write_switch(tmp_path,field,value):
    conf=json.loads((ROOT/'CORDON_2025_CONFIG.json').read_text());conf[field]=value
    f=tmp_path/'config.json';f.write_text(json.dumps(conf))
    with pytest.raises(ContractError):read_config(f)

@pytest.mark.parametrize('name',['../2022','/tmp/change','parent/something','..',''])
def test_output_cannot_escape_release(name):
    with pytest.raises(ContractError,match='UNSAFE_OUTPUT'):new_output(name)

def test_nonexistent_cache_fails_not_live_pass(tmp_path):
    _,mapping,e,c=fixture(tmp_path)
    with pytest.raises(ContractError,match='NO_2025_PATH_CACHE'):build_from_snapshot(tmp_path/'absent.sqlite',mapping,c,e)

def test_missing_targets_are_not_zero_observations(tmp_path):
    p,m,e,c=fixture(tmp_path);inc=build_from_snapshot(p,m,c,e)['ALL_ORDERED_UNIQUE_PAIRS']
    a=aggregate_observations(inc,{},roles={})
    assert all(r['observed'] is None for r in a.rows)
    with pytest.raises(ContractError,match='MISSING_OBSERVATION'):aggregate_observations(inc,{},roles={(1,2):'CALIBRATION'})

def test_invalid_geometry_hash_and_mode(tmp_path):
    p,m,e,c=fixture(tmp_path)
    con=sqlite3.connect(p);con.execute("UPDATE geometry SET sequence_sha256='corrupt' WHERE gid=1");con.commit();con.close()
    e['cache_sha256']=sha256(p)
    with pytest.raises(ContractError,match='GEOMETRY_HASH'):build_from_snapshot(p,m,c,e)

def test_complete_snapshot_without_expected_od_is_conditional(tmp_path):
    p,m,e,c=fixture(tmp_path);del e['od_totals']
    r=build_from_snapshot(p,m,c,e)['ALL_ORDERED_UNIQUE_PAIRS']
    assert r.audit['per_od_external_parity']=='NOT_SUPPLIED'
    assert 'PER_OD_EXTERNAL_VOLUME_PARITY_NOT_SUPPLIED' in r.audit['blocked']
    assert not r.audit['production_ready']

def test_zero_volume_row_deletion_cannot_hide_under_total(tmp_path):
    p,m,e,c=fixture(tmp_path);db=sqlite3.connect(p)
    db.execute("UPDATE volumes SET volume=0 WHERE gid=1 AND dseg='NATIVE_CW'");db.commit();db.close()
    e['cache_sha256']=sha256(p);e['dseg_totals']['NATIVE_CW']-=60
    e.pop('od_totals')
    assert build_from_snapshot(p,m,c,e)['ALL_ORDERED_UNIQUE_PAIRS'].audit['DSEG_VOLUME_PARITY']=='PASS'
    db=sqlite3.connect(p);db.execute("DELETE FROM volumes WHERE gid=1 AND dseg='NATIVE_CW'");db.commit();db.close()
    e['cache_sha256']=sha256(p)
    with pytest.raises(ContractError,match='INCOMPLETE_SEGMENT_VOLUME_ROWS'):build_from_snapshot(p,m,c,e)

def test_model_year_and_network_are_independent(tmp_path):
    p,m,e,c=fixture(tmp_path);c['actual_network_sha256']='other'
    with pytest.raises(ContractError,match='NETWORK_IDENTITY'):build_from_snapshot(p,m,c,e)
    c['actual_network_sha256']=e['network_sha256'];e['model_year']=2022
    with pytest.raises(ContractError,match='MODEL_YEAR_NOT_2025'):build_from_snapshot(p,m,c,e)

@pytest.mark.parametrize('field,value',[('ridge',-1),('l1',float('nan')),('epsilon_abs',-1),('relative_od_lower',-1),('kkt_tolerance',float('inf'))])
def test_solver_rejects_invalid_parameters(field,value):
    with pytest.raises(ContractError):solve(example(),cfg(**{field:value}))

def test_budget_cannot_be_enabled_by_truthy_string():
    with pytest.raises(ContractError,match='OPT_IN'):SharedBudget([(1,2)],[1,2],np.ones(2),2,'BOUNDED_SCENARIO',{},'no')

def test_zero_budget_reduces_exactly_to_parent_loss():
    inc=example();b=SharedBudget([(1,2),(1,3)],[1,2,3],np.zeros(3),0,'BOUNDED_SCENARIO',{},True)
    a=solve(inc,cfg());s=solve(inc,cfg(),b)
    assert np.allclose(a.x,s.x,atol=1e-10) and np.all(s.uncertainty==0)

def test_feasibility_blocks_frozen_scope_not_only_dseg():
    inc=example(matrix=np.eye(4)*100,targets=[120,80,80,120]);s=solve(inc,cfg())
    basis=basis_for(inc)
    # Same DSeg but an OD outside the allowed actuator keys may not be changed.
    basis.row_keys[3]=('NATIVE_CW',900,901)
    with pytest.raises(ContractError,match='GUIDED_OD_MISSING'):evaluate_realizability(inc,s,basis)

def test_all_approval_flags_still_do_not_allow_v1_apply():
    from cordon2025.common import APPROVAL_FIELDS
    c={'approvals':{k:{'approved':True,'evidence_sha256':'x','authority_id':'x'} for k in APPROVAL_FIELDS}}
    g=deployment_gate(c,True)
    assert not g['apply_permitted'] and g['blockers']==['NOT_LIVE_TESTED','V1_OFFLINE_ONLY']

def test_parent_config_and_controller_bytes_unchanged():
    baseline=json.loads((ROOT/'docs/evidence/parent_manifest.json').read_text())
    if 'files' in baseline:baseline=baseline['files']
    for name in ('R1_15A2_CONFIG_V2_4_9_15.json','r1_15a2_overnight_controller_v242.py','r1_15a2_two_mode_adapter_v238.py'):
        expected=baseline[name]
        if isinstance(expected,dict):expected=expected['sha256']
        assert sha256(ROOT/'parent'/name)==expected

def test_no_live_import_needed_in_clean_process():
    code="""
import sys
class DenyCOM:
 def find_spec(self,fullname,path=None,target=None):
  if fullname.startswith(('win32com','pythoncom','pywintypes')):raise RuntimeError('COM forbidden in offline test')
sys.meta_path.insert(0,DenyCOM())
from cordon2025.demos import algebra_example
from cordon2025.optimizer import solve
from cordon2025.common import read_config
r=solve(algebra_example([[100]], [120]), read_config())
assert not r.report['live_visum_tested']
"""
    result=subprocess.run([sys.executable,'-c',code],cwd=ROOT,capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stderr

def test_source_matrix_header_is_not_assumed():
    rows=[['Header','SDP2','SDP1']+[f'SDP{i}' for i in range(3,17)]+['VJAZD (bez p\u00e1ru)','vjazd-v\u00fdjazd']]
    rows += [[f'SDP{i}']+[0]*18 for i in range(1,17)]
    rows += [['VJAZD (bez p\u00e1ru)']+[0]*18,['vjazd-v\u00fdjazd']+[0]*18]
    with pytest.raises(ContractError,match='COLUMN_LABEL_MISMATCH'):_matrix(rows,2,'TEST')


def test_old_2022_entrypoint_refuses_modified_fork_identity():
    # Do not update the 2022 manifest to bless new 2025 code. It must reject it.
    from cordon2025.common import parent_core
    parent_core()
    from r1_15a2_safety_v24915 import preflight_v24915_deployment_files
    from r1_15a2_supply import SupplyContractError
    with pytest.raises(SupplyContractError,match='V24915_RUNTIME_BUNDLE_INVALID') as failure:
        preflight_v24915_deployment_files(ROOT/'parent')
    items=json.loads(str(failure.value).split('V24915_RUNTIME_BUNDLE_INVALID:',1)[1])
    assert {r['path'] for r in items}=={'r1_15a2_core.py','r1_15a2_two_mode_v238.py','r1_15a2_com_compat.py','r1_15a2_supply.py'}
    assert {r['reason'] for r in items}=={'SIZE_MISMATCH'}


def test_dseg_mode_authority_independent_of_matching_two_tables(tmp_path):
    p,m,e,c=fixture(tmp_path)
    db=sqlite3.connect(p);db.execute("UPDATE segments SET mode='C_NOT' WHERE dseg='NATIVE_CW'");db.commit();db.close()
    e['cache_sha256']=sha256(p)
    with pytest.raises(ContractError,match='DSEG_MODE_AUTHORITY'):build_from_snapshot(p,m,c,e)

def test_fixed_only_inspection_requires_no_zonal_actuator_authority(tmp_path):
    p,m,e,c=fixture(tmp_path);c['mutable_dsegs']=[];c['mutable_relation_policy']='BOTH_ENDPOINTS_ACTUATABLE';c['actuatable_zones']=None
    r=build_from_snapshot(p,m,c,e)['ALL_ORDERED_UNIQUE_PAIRS']
    assert len(r.variables)==0 and np.array_equal(r.model,r.fixed)

def test_sparse_adjoint_and_abs_relative_change_equivalence(tmp_path):
    p,m,e,c=fixture(tmp_path);r=build_from_snapshot(p,m,c,e)['ALL_ORDERED_UNIQUE_PAIRS']
    rng=np.random.default_rng(508)
    x=rng.normal(size=r.operator.n_cols);z=rng.normal(size=r.operator.n_rows)
    assert z@r.operator.forward(x)==pytest.approx(x@r.operator.transpose(z),abs=1e-9)
    assert np.allclose(r.operator.forward(x),r.share_operator.forward(x*r.q_current))


def test_mapping_and_policy_part_of_incidence_identity(tmp_path):
    p,m,e,c=fixture(tmp_path)
    a=build_from_snapshot(p,m,c,e)['ALL_ORDERED_UNIQUE_PAIRS']
    m2={k:(2 if v==1 else 1 if v==2 else v) for k,v in m.items()}
    b=build_from_snapshot(p,m2,c,e)['ALL_ORDERED_UNIQUE_PAIRS']
    assert a.audit['cache_sha256']==b.audit['cache_sha256']
    assert a.audit['mapping_sha256']!=b.audit['mapping_sha256']
    c['repeat_policy']='FIRST_OCCURRENCE_DIAGNOSTIC'
    d=build_from_snapshot(p,m,c,e)['ALL_ORDERED_UNIQUE_PAIRS']
    assert d.audit['incidence_contract_sha256']!=a.audit['incidence_contract_sha256']
