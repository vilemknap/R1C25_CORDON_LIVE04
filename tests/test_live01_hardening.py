"""Negative current-state, import isolation and no-write LIVE01 evidence."""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import types
import pytest
from fake_live01 import Live01Visum
from cordon2025.common import ROOT,read_json
from cordon2025.live01_config import load_config,validate_config
from cordon2025.live01_provenance import guarded_output_root,verify_protected_sources,verify_handoff,bind_snapshot
from cordon2025.live01_visum import model_preflight,verify_end_state,ReadOnlyObject
from cordon2025.visum_startup import settings,ReadControl

@pytest.fixture
def case(tmp_path):
    v=Live01Visum(tmp_path/'model');folder=tmp_path/'out';folder.mkdir()
    return v,load_config(),folder,ReadControl(folder),settings({'min_free_disk_gib':0,'com_retry_initial_delay_seconds':0.,'com_retry_max_delay_seconds':0.,'com_retry_attempts':3})

@pytest.mark.parametrize('value',[None,[True],[0],[-1],['5'],[5,5]])
def test_exclusions_strict(value):
    cfg=load_config();cfg['explicit_excluded_zone_nos']=value
    with pytest.raises(ValueError,match='INVALID_ZONE_EXCLUSIONS'):validate_config(cfg)

@pytest.mark.parametrize('mutation',['zone','td','foreign','protected','freight','script','source'])
def test_independent_end_readback_detects_state_drift(case,mutation):
    v,cfg,folder,ctl,opt=case;pre,state=model_preflight(*case)
    if mutation=='zone':v.Net.Zones.rows[0]['ADD_PROD_W']+=.1
    elif mutation=='td':next(iter(v.Procedures.Operations.items[5].TripDistributionParameters.strata.values())).GravitationParameters.values['PARA_B']+=.01
    elif mutation=='foreign':v.Net.Matrices.ItemByKey(9116).values[0,1]=1.
    elif mutation=='protected':v.Net.Matrices.ItemByKey(9001).values[0,1]=2.
    elif mutation=='freight':v.dsegs['LNV'].ODMatrix.values[0,1]=1.
    elif mutation=='script':(v.source.parent/'20B_synthetic.py').write_text('# changed\n')
    elif mutation=='source':v.source.write_text('changed source, no .ver execution')
    with pytest.raises(ValueError,match='CHANGED'):verify_end_state(v,cfg,folder,ctl,opt,pre,state)
    assert not v.writes

@pytest.mark.parametrize('failure',['missing_protected','negative_distance','td_nan','td_duplicate','wrong_dseg_mode','wrong_year'])
def test_extra_model_failures(case,failure):
    v=case[0]
    if failure=='missing_protected':v.Net.Matrices.items=[x for x in v.Net.Matrices.items if x.no!=9697]
    elif failure=='negative_distance':v.Net.Matrices.ItemByKey(9697).values[0,0]=-1.
    elif failure=='td_nan':next(iter(v.Procedures.Operations.items[5].TripDistributionParameters.strata.values())).GravitationParameters.values['PARA_C']=float('nan')
    elif failure=='td_duplicate':v.Procedures.Operations.items[5].TripDistributionParameters.values['DSTRATSET']+=','+v.Procedures.Operations.items[5].TripDistributionParameters.values['DSTRATSET'].split(',')[0]
    elif failure=='wrong_dseg_mode':v.dsegs['NATIVE_CW'].mode='C_noT'
    elif failure=='wrong_year':v.source=v.source.with_name('R1_2022_generated.ver');v.source.write_text('synthetic');v.IO.CurrentVersionFile=str(v.source)
    with pytest.raises(Exception):model_preflight(*case)
    assert not v.writes


def test_same_data_different_zone_attribute_row_enumeration_is_bound_by_id(case):
    v=case[0];original=v.Net.Zones.GetMultiAttValues
    v.Net.Zones.GetMultiAttValues=lambda name,*args: original(name,*args)[::-1] if name!='NO' else original(name,*args)
    pre,state=model_preflight(*case)
    assert state['zone_rows'][0]['zone_no']==5 and state['zone_rows'][0]['NOT_ZAHR']==1.
    assert state['zone_rows'][-1]['NOT_ZAHR']==0.
    assert not v.writes


def test_16_or_17_dstrata_supported_without_mutating(case):
    v=case[0];v.Procedures.Operations.items[5].TripDistributionParameters.values['DSTRATSET']+=',4_FOREIGN'
    pre,state=model_preflight(*case)
    assert len(state['td_source_set'])==17 and len(state['td_rows'])==16 and not v.writes


def test_output_guards(tmp_path):
    with pytest.raises(ValueError,match='TRAVERSAL'):guarded_output_root(tmp_path/'..'/'outside')
    with pytest.raises(ValueError,match='INSIDE_RELEASE'):guarded_output_root(ROOT/'provenance'/'bad_run')
    target=tmp_path/'target';target.mkdir();link=tmp_path/'link';link.symlink_to(target,target_is_directory=True)
    with pytest.raises(ValueError,match='LINK_FORBIDDEN'):guarded_output_root(link/'child')


def test_windows_reparse_output_rejected_mock(tmp_path,monkeypatch):
    original=Path.lstat
    def stats(p,*args,**kwargs):
        if p==tmp_path:return types.SimpleNamespace(st_mode=0o40755,st_file_attributes=0x400)
        return original(p,*args,**kwargs)
    monkeypatch.setattr(Path,'lstat',stats)
    with pytest.raises(ValueError,match='REPARSE'):guarded_output_root(tmp_path/'child')


def test_donor_function_source_exact_hash():
    evidence=read_json(ROOT/'provenance/live01/EXACT_FUNCTIONS.json')
    text=(ROOT/'cordon2025/live01_donor_scope.py').read_text();tree=ast.parse(text)
    for name,want in evidence['functions'].items():
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
        raw=ast.get_source_segment(text,node)
        assert hashlib.sha256(raw.encode()).hexdigest()==want
    assert verify_protected_sources()['checked']>1500


def test_original_import_scope_restores_on_failure_and_success():
    import cordon_visum_bootstrap as boot
    before_path=list(sys.path);before={k:v for k,v in sys.modules.items() if boot._owned(k)}
    for fail in (False,True):
        try:
            with boot.isolated_imports(ROOT):
                __import__('cordon2025.live01_config')
                if fail:raise RuntimeError('injected')
        except RuntimeError as e:assert str(e)=='injected'
        assert list(sys.path)==before_path
        assert {k:v for k,v in sys.modules.items() if boot._owned(k)}==before
        assert not hasattr(sys,'_r1_cordon2025_busy')


def test_launcher_refuses_foreign_profile_without_touching_it(monkeypatch):
    import cordon_live01_bootstrap as boot
    foreign=types.ModuleType('r1_15a2_foreign_fixture');foreign.__file__='/other/2022/r1_15a2_foreign_fixture.py'
    monkeypatch.setitem(sys.modules,foreign.__name__,foreign)
    result=boot.launch({'Visum':object()})
    assert 'FOREIGN_PROFILE_MODULE_COLLISION' in result['reason']
    assert sys.modules[foreign.__name__] is foreign


def test_launcher_scope_restored_after_integrity_failure(monkeypatch,tmp_path):
    import cordon_live01_bootstrap as boot
    original=list(sys.path)
    wrong=tmp_path/'wrong';wrong.mkdir()
    import shutil
    shutil.copy2(ROOT/'cordon_visum_bootstrap.py',wrong/'cordon_visum_bootstrap.py')
    shutil.copy2(ROOT/'verify_release.py',wrong/'verify_release.py')
    result=boot.launch({'Visum':object()},root=wrong)
    assert result['status']=='LIVE01_STARTUP_BLOCKED'
    assert list(sys.path)==original and not hasattr(sys,'_r1_cordon2025_busy')


def test_run_locked_and_unowned_root_blocks_without_writes(tmp_path):
    from cordon2025.live01_baseline import run
    from cordon2025.session import RunSession
    v=Live01Visum(tmp_path/'model');root=tmp_path/'runs'
    with RunSession('OTHER',root):
        with pytest.raises(ValueError,match='LOCKED'):run(v,output_root=root)
    bad=tmp_path/'unowned';bad.mkdir();(bad/'file').write_text('do not adopt')
    with pytest.raises(ValueError,match='UNOWNED'):run(v,output_root=bad)
    assert not v.writes


def test_source_binding_never_accepts_stale_or_partial(tmp_path):
    from cordon2025.common import canonical_hash
    from cordon2025.io import sha256
    from cordon2025.live01_visum import expected_bindings
    file=tmp_path/'fake_snapshot';file.write_bytes(b'not a real sqlite; binding unit test')
    codes=list(expected_bindings());report={'network_sha256':'network','matrix_audit':{c:{} for c in codes}}
    state={'source_version':'model_2025.ver','current_model_fingerprint':'state','od_segment_bindings':{c:{} for c in codes}}
    evidence={'completed':True,'geometry_full_identity_proven':True,'model_year':2025,'origin':'VISUM_SAVED_PATHS','network_sha256':'network',
       'demand_sha256':canonical_hash(report['matrix_audit']),'cache_sha256':sha256(file),'source_version':state['source_version'],
       'full_geometry_checks':[{'dseg':c,'check':'FULL_SAME_MODE_MATCH'} for c in codes],
       'od_matrix_authorities':[{'dseg':c} for c in codes],'dseg_totals':{c:1 for c in codes}}
    assert bind_snapshot((report,),state,evidence,file)['new_assignment_verified'] is False
    for field,bad in [('completed',False),('geometry_full_identity_proven',False),('model_year',2022),('network_sha256','old'),('demand_sha256','old'),('cache_sha256','changed'),('source_version','other'),('full_geometry_checks',evidence['full_geometry_checks'][:-1]),('od_matrix_authorities',[]),('dseg_totals',{})]:
        with pytest.raises(ValueError):bind_snapshot((report,),state,dict(evidence,**{field:bad}),file)


def test_com_thread_and_stop_are_not_bypassed(case):
    import concurrent.futures
    v,cfg,folder,ctl,opt=case;proxy=ReadOnlyObject(v,ctl,opt)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        with pytest.raises(Exception,match='COM_THREAD_CHANGED'):pool.submit(lambda:proxy.Net).result()
    (folder/'STOP_REQUESTED').write_text('stop')
    with pytest.raises(Exception,match='STOP_REQUESTED'):proxy.Net
    assert not v.writes


def test_ambiguous_injection_refused():
    import cordon_live01_bootstrap as boot
    result=boot.launch({'Visum':object(),'COM':object()})
    assert result['reason']=='AMBIGUOUS_INJECTED_VISUM_AND_COM'
