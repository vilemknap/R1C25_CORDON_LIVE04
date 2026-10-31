import copy
import dataclasses
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import hashlib
import numpy as np
import pytest
from cordon2025.common import ROOT,canonical_hash,sha256,write_json,read_config,ContractError
from cordon2025.fixtures import create_cache,config,chain_mapping
from cordon2025.incidence import build_from_snapshot,aggregate_observations,check_epoch_support
from cordon2025.perf01_cache import (get_or_build,writer_lock,verify_entry,load_compact_result,
                                    write_run_binding,verify_run_binding)
from cordon2025.perf01_codec import legacy_value,export_legacy,read_arrays
from cordon2025.perf01_identity import source_seal,cache_keys,file_record,strict_json,relative_file

A=(101,1,2);B=(102,2,3);C=(103,3,4)
RA=(101,2,1);RB=(102,3,2);RC=(103,4,3)

@pytest.fixture
def setup(tmp_path):
    paths=[('C',10,20,1,[A,B,C],{'NATIVE_CW':60.,'EXOG_EE_CF':30.}),
           ('C',10,20,2,[A,B],{'NATIVE_CW':40.,'EXOG_EE_CF':10.}),
           ('C_NOT',10,20,1,[B,C],{'NATIVE_CW_NOT':50.}),
           ('C',20,10,1,[RC,RB,RA],{'NATIVE_CW':50.,'EXOG_EE_CF':5.}),
           ('C',30,40,1,[],{'NATIVE_CW':8.,'EXOG_EE_CF':1.}),
           ('C',50,60,1,[A,B,RB,RA,A],{'NATIVE_CW':7.,'EXOG_EE_CF':2.}),
           ('C',70,80,1,[(104,4,5)],{'NATIVE_CW':0.,'EXOG_EE_CF':0.})]
    p=tmp_path/'source'/'p.sqlite';m,e=create_cache(p,paths)
    c=dict(config(['NATIVE_CW','NATIVE_CW_NOT','EXOG_EE_CF']),model_year=2025,
           survey_year=2026,basis='RPDI',mode='OFFLINE_PROPOSAL')
    return {'p':p,'m':m,'e':e,'ep':p.with_suffix('.evidence.json'),'c':c,'root':tmp_path/'derived','tmp':tmp_path}


def call(s,**kw):
    opts=dict(cache_dir=s['root'],policy='build-offline');opts.update(kw)
    return get_or_build(s['p'],s['m'],s['c'],s['ep'],**opts)


def same(a,b):
    assert a.rows==b.rows
    assert a.variables==b.variables
    assert a.projection_base_variables==b.projection_base_variables
    assert legacy_value(a.audit)==legacy_value(b.audit)
    for name in ('q_current','model','mutable','fixed'):
        assert np.array_equal(getattr(a,name),getattr(b,name)),name
    for name in ('operator','share_operator'):
        for field in ('row_idx','col_idx','values'):
            assert np.array_equal(getattr(getattr(a,name),field),getattr(getattr(b,name),field))


def update_evidence(s):write_json(s['ep'],s['e'])


def reseal(folder):
    mp=folder/'MANIFEST.json';m=strict_json(mp)
    for rec in m['files']:rec.update(file_record(folder/rec['path']))
    write_json(mp,m);done=strict_json(folder/'COMPLETE.json');done['manifest_sha256']=sha256(mp);write_json(folder/'COMPLETE.json',done)


def test_build_hit_exact_oracle_and_source_unchanged(setup,monkeypatch):
    s=setup;before=sha256(s['p']);oracle=build_from_snapshot(s['p'],s['m'],s['c'],s['e'])
    cold=call(s)
    assert cold.status['cache_action']=='CACHE_BUILT_OFFLINE'
    assert cold.status['geometry_redecode_count']==7
    for method in oracle:same(oracle[method],cold.variants[method])
    import cordon2025.incidence as mod
    def forbidden(*a,**k):raise AssertionError('WARM_MUST_NOT_OPEN_SQLITE_OR_DECODE')
    monkeypatch.setattr(mod,'build_from_snapshot',forbidden)
    monkeypatch.setattr(mod,'_snapshot_open',forbidden)
    monkeypatch.setattr(sqlite3,'connect',forbidden)
    hit=call(s,policy='require-verified-hit')
    assert hit.status['cache_action']=='CACHE_HIT_VERIFIED'
    assert hit.status['geometry_redecode_count']==hit.status['native_com_read_count']==hit.status['sqlite_geometry_scans']==0
    for method in oracle:same(oracle[method],hit.variants[method])
    assert sha256(s['p'])==before and hit.status['source_bytes_hashed']>=2*s['p'].stat().st_size


def test_shared_tables_and_legacy_roundtrip(setup):
    s=setup;r=call(s);oracle=build_from_snapshot(s['p'],s['m'],s['c'],s['e'])
    assert len(list(r.folder.glob('*OD_TOTALS*')))==1
    targets={(a,b):10. for a in range(1,5) for b in range(1,5) if a!=b}
    roles={(1,2):'VALIDATION',(1,3):'CALIBRATION'}
    for method,raw in r.variants.items():
        inc=aggregate_observations(raw,targets,roles=roles)
        ref=aggregate_observations(oracle[method],targets,roles=roles)
        out=s['tmp']/method;r.save_incidence(inc,out)
        loaded=load_compact_result(out,r);same(ref,loaded)
        export_legacy(loaded,out/'legacy');ref.save(out/'old')
        assert strict_json(out/'legacy/INCIDENCE_METADATA.json')==strict_json(out/'old/INCIDENCE_METADATA.json')
        assert 'all_od_totals' not in (out/'INCIDENCE_METADATA.json').read_text()
        assert (out/'INCIDENCE_METADATA.json').stat().st_size<15000
    assert canonical_hash(r.variants['ALL_ORDERED_UNIQUE_PAIRS'].audit)==canonical_hash(oracle['ALL_ORDERED_UNIQUE_PAIRS'].audit)


@pytest.mark.parametrize('field,value',[('repeat_policy','FIRST_OCCURRENCE_DIAGNOSTIC'),
    ('mutable_dsegs',[]),('actuatable_zones',[10,20]),('mutable_relation_policy','BOTH_ENDPOINTS_ACTUATABLE')])
def test_derived_parameter_miss_no_silent_rebuild(setup,field,value):
    s=setup;cold=call(s);s['c']['actuatable_zones']=[10,20] if field=='mutable_relation_policy' else s['c'].get('actuatable_zones')
    s['c'][field]=value
    with pytest.raises(ContractError,match='CACHE_MISS'):call(s,policy='require-verified-hit')
    new=call(s)
    assert new.manifest['key']!=cold.manifest['key']
    assert new.manifest['geometry_key']==cold.manifest['geometry_key']
    ref=build_from_snapshot(s['p'],s['m'],s['c'],s['e'])
    for m in ref:same(ref[m],new.variants[m])


@pytest.mark.parametrize('change',['station_id','direction'])
def test_mapping_changes_invalidate_geometry(setup,change):
    s=setup;r=call(s)
    if change=='station_id':s['m'][A]=7
    else:s['m'][A],s['m'][B]=s['m'][B],s['m'][A]
    with pytest.raises(ContractError,match='CACHE_MISS'):call(s,policy='require-verified-hit')
    r2=call(s);assert r2.manifest['geometry_key']!=r.manifest['geometry_key']


def test_solver_weights_targets_roles_not_geometry_inputs(setup):
    s=setup;r=call(s);s['c']['lambda_l2']=999;s['c']['c17_policy']='UNAPPROVED'
    h=call(s,policy='require-verified-hit');assert h.status['hit']
    raw=h.variants['ALL_ORDERED_UNIQUE_PAIRS']
    a=aggregate_observations(raw,{(1,2):10,(2,1):20},roles={(1,2):'CALIBRATION'})
    b=aggregate_observations(raw,{(1,2):15,(2,1):25},roles={(1,2):'VALIDATION'})
    assert a.rows[0]['observed']==30 and b.rows[0]['observed']==40
    assert a.rows[0]['role']!=b.rows[0]['role']
    assert np.array_equal(a.model,b.model)
    with pytest.raises(ContractError,match='LEAKAGE'):
        aggregate_observations(raw,{},roles={(1,2):'CALIBRATION',(2,1):'VALIDATION'})


@pytest.mark.parametrize('field,value,match',[
    ('model_year',2022,'YEAR'),('survey_year',2025,'YEAR'),('basis','PDI','SCOPE'),
    ('apply',True,'OFFLINE'),('run_assignment',True,'LIVE_SWITCH'),
    ('persistent_path_cache_enabled',True,'REUSE_FORBIDDEN'),
    ('automatic_cache_discovery',True,'DISCOVERY'),
    ('actual_network_sha256','a'*64,'IDENTITY'),('actual_demand_sha256','b'*64,'IDENTITY')])
def test_scope_hard_gates(setup,field,value,match):
    s=setup;call(s);s['c'][field]=value
    with pytest.raises(Exception,match=match):call(s)


def test_new_assignment_not_inferred_from_matrix_network(setup):
    call(setup)
    with pytest.raises(ContractError,match='CACHE_EPOCH_NOT_PROVEN'):call(setup,context='after-new-assignment')


@pytest.mark.parametrize('suffix',['-wal','-shm','-journal'])
def test_sidecars_block_even_empty(setup,suffix):
    call(setup);Path(str(setup['p'])+suffix).touch()
    with pytest.raises(ContractError,match='SIDECAR'):call(setup)


@pytest.mark.parametrize('key,value,match',[
    ('completed',False,'NOT_COMPLETE'),('geometry_full_identity_proven',False,'PROOF'),
    ('model_year',2022,'MODEL_YEAR'),('cache_sha256','0'*64,'SHA256'),
    ('demand_sha256','bad','IDENTITY'),('od_totals',None,'AUTHORITY')])
def test_source_evidence_invalid(setup,key,value,match):
    s=setup;call(s);s['e'][key]=value;update_evidence(s)
    with pytest.raises(Exception,match=match):call(s)


def test_source_bytes_changed_same_size_and_mtime_rejected(setup):
    s=setup;call(s);st=s['p'].stat();data=bytearray(s['p'].read_bytes());data[-1]^=1;s['p'].write_bytes(data)
    os.utime(s['p'],ns=(st.st_atime_ns,st.st_mtime_ns))
    with pytest.raises(ContractError,match='SHA256'):call(s)


def test_source_resealed_new_geometry_cannot_use_old_root(setup):
    s=setup;call(s)
    with sqlite3.connect(s['p']) as db:db.execute("UPDATE geometry SET edge_ids=x'01000000' WHERE gid=1")
    s['e']['cache_sha256']=sha256(s['p']);update_evidence(s)
    with pytest.raises(ContractError,match='ROOT_SNAPSHOT_MISMATCH'):call(s)


def test_malformed_source_geometry_not_accepted_for_build(setup):
    s=setup
    with sqlite3.connect(s['p']) as db:db.execute('UPDATE geometry SET edge_ids=NULL WHERE gid=1')
    s['e']['cache_sha256']=sha256(s['p']);update_evidence(s)
    with pytest.raises(ContractError,match='NULL_GEOMETRY'):call(s)
    assert not list(s['root'].glob('*/COMPLETE.json'))


@pytest.mark.parametrize('artifact',['COMPLETE.json','MANIFEST.json','ALL_OD_TOTALS.npz','ALL_ORDERED_UNIQUE_PAIRS.npz','SHARED_AUDIT.json'])
def test_damaged_derived_never_rebuild_silently(setup,artifact):
    s=setup;r=call(s);(r.folder/artifact).write_bytes(b'broken')
    with pytest.raises(Exception):call(s,policy='build-offline')
    assert (r.folder/artifact).read_bytes()==b'broken'


@pytest.mark.parametrize('bad',['nan','object','wrong_shape','negative','index'])
def test_npz_invalid_even_with_recomputed_checksums(setup,bad):
    s=setup;r=call(s);p=r.folder/'ALL_ORDERED_UNIQUE_PAIRS.npz'
    with np.load(p,allow_pickle=False) as z:a={k:z[k] for k in z.files}
    if bad=='nan':a['model'][0]=np.nan
    elif bad=='object':a['model']=np.array([{} for _ in a['model']],dtype=object)
    elif bad=='wrong_shape':a['q']=a['q'].reshape(-1,1)
    elif bad=='negative':a['through'][0]=-1
    else:a['row'][0]=999
    with open(p,'wb') as f:np.savez_compressed(f,**a)
    reseal(r.folder)
    with pytest.raises(Exception):call(s,policy='require-verified-hit')


def test_partial_stage_not_a_hit_and_repair_safe(setup):
    s=setup
    def die(phase,stage):
        if phase=='BEFORE_PUBLISH':raise OSError('SIMULATED_CRASH')
    with pytest.raises(OSError,match='SIMULATED_CRASH'):call(s,_fault=die)
    assert not list(s['root'].glob('*/COMPLETE.json'))
    with pytest.raises(ContractError,match='CACHE_MISS'):call(s,policy='require-verified-hit')
    assert call(s).status['cache_action']=='CACHE_BUILT_OFFLINE'


def test_stale_lock_never_stolen_reader_can_read_completed(setup):
    s=setup;r=call(s);lock=s['root']/'.perf01.writer.lock';lock.write_text('old-owner')
    assert call(s,policy='require-verified-hit').status['hit']
    s['c']['mutable_dsegs']=[]
    with pytest.raises(ContractError,match='LOCKED'):call(s)
    assert lock.read_text()=='old-owner'


def test_two_writers_conflict(setup):
    s=setup;call(s);source=source_seal(s['p'],s['ep'],s['c'])
    with writer_lock(s['root'],source):
        with pytest.raises(ContractError,match='LOCKED'):
            with writer_lock(s['root'],source):pass


def test_unowned_root_not_adopted(setup):
    s=setup;s['root'].mkdir();(s['root']/'unrelated.txt').write_text('protected')
    with pytest.raises(ContractError,match='UNKNOWN_NONEMPTY'):call(s)
    assert (s['root']/'unrelated.txt').read_text()=='protected'


@pytest.mark.parametrize('where',['source','root','derived'])
def test_symlink_rejected(setup,where):
    s=setup
    if where=='source':
        p=s['p'];link=s['tmp']/'alias.sqlite';link.symlink_to(p);s['p']=link
    elif where=='root':
        real=s['tmp']/'real';real.mkdir();s['root'].symlink_to(real,target_is_directory=True)
    else:
        r=call(s);p=r.folder/'ALL_OD_TOTALS.npz';saved=s['tmp']/'od.npz';p.rename(saved);p.symlink_to(saved)
    with pytest.raises(ContractError,match='SYMLINK'):call(s)


@pytest.mark.parametrize('name',['../x','/tmp/x','C:/x','a\\x','./x','a//x'])
def test_path_traversal(setup,name):
    with pytest.raises(ContractError,match='PATH'):relative_file(setup['tmp'],name)


def test_source_mutation_during_build_not_published(setup):
    s=setup
    def mutate(phase,stage):
        if phase=='AFTER_DATA':s['ep'].write_text(s['ep'].read_text()+'\n')
    with pytest.raises(ContractError,match='SOURCE_CHANGED'):call(s,_fault=mutate)
    assert not list(s['root'].glob('*/COMPLETE.json'))


def test_mutable_solver_and_epoch_support_parity(setup):
    s=setup;r=call(s);oracle=build_from_snapshot(s['p'],s['m'],s['c'],s['e'])
    from cordon2025.optimizer import solve
    for method in r.variants:
        rows={(i,j):90 for i in range(1,5) for j in range(1,5) if i!=j}
        roles={(i,j):'CALIBRATION' for i in range(1,5) for j in range(i+1,5)}
        a=aggregate_observations(r.variants[method],rows,roles=roles)
        b=aggregate_observations(oracle[method],rows,roles=roles)
        cfg=read_config();cfg['mutable_dsegs']=s['c']['mutable_dsegs']
        x=solve(a,cfg,allow_unapproved_scenario=True);y=solve(b,cfg,allow_unapproved_scenario=True)
        assert np.array_equal(x.delta_q,y.delta_q)
        assert not any(v['dseg_code'].startswith('EXOG') for v in a.variables)
        with pytest.raises(ContractError,match='NEW_POSITIVE'):
            check_epoch_support(a,[{'dseg':'NATIVE_CW','orig':999,'dest':1000,'volume':1}])


def test_zero_mutable_baseline(setup):
    s=setup;s['c']['mutable_dsegs']=[];r=call(s)
    for inc in r.variants.values():
        assert not inc.variables and inc.operator.n_cols==0 and not len(inc.operator.values)
        assert np.array_equal(inc.model,inc.fixed)


def test_new_process_verified_hit(setup):
    s=setup;r=call(s);cfg=s['tmp']/'config.json';write_json(cfg,s['c']);mp=s['tmp']/'map.json';write_json(mp,[[*k,v] for k,v in s['m'].items()])
    code='''import json,sys
from cordon2025.perf01_cache import get_or_build
p,e,c,m,d=sys.argv[1:]
mp={tuple(x[:3]):x[3] for x in json.load(open(m))}
r=get_or_build(p,mp,json.load(open(c)),e,cache_dir=d,policy='require-verified-hit')
print(json.dumps({'action':r.status['cache_action'],'decode':r.status['geometry_redecode_count'],'sum':float(r.variants['ALL_ORDERED_UNIQUE_PAIRS'].model.sum())}))
'''
    proc=subprocess.run([sys.executable,'-c',code,*map(str,(s['p'],s['ep'],cfg,mp,s['root']))],cwd=ROOT,text=True,capture_output=True,timeout=30)
    assert proc.returncode==0,proc.stderr
    report=json.loads(proc.stdout.strip());assert report=={'action':'CACHE_HIT_VERIFIED','decode':0,'sum':float(r.variants['ALL_ORDERED_UNIQUE_PAIRS'].model.sum())}


def test_run_binding_checks_source_and_derived(setup):
    s=setup;r=call(s);out=s['tmp']/'run';out.mkdir();write_run_binding(out,r)
    assert verify_run_binding(out)['status']=='PERF01_RUN_REFERENCE_VERIFIED'
    (r.folder/'STATION_HITS.csv').write_text('tampered')
    with pytest.raises(ContractError,match='HASH'):verify_run_binding(out)


@pytest.fixture
def native(tmp_path):
    from fake_visum_startup import FakeVisum
    from cordon2025.visum_startup import preflight,capture,settings,ReadControl
    from cordon2025.authority import mapping
    v=FakeVisum(tmp_path/'model');out=tmp_path/'capture';out.mkdir()
    cfg=read_config(ROOT/'CORDON_2025_AGGRESSIVE_CONFIG.json')
    opt=settings({'page_size':2,'min_free_disk_gib':0})
    ctl=ReadControl(out);pre=preflight(v,cfg,out,ctl,opt);p,ep=capture(v,cfg,out,ctl,opt,pre)
    m,_=mapping(ROOT/'data/audited/STATION_MAPPING.csv');cfg['mutable_dsegs']=[]
    return {'p':p,'ep':ep,'e':strict_json(ep),'c':cfg,'m':m,'root':tmp_path/'derived','tmp':tmp_path,'fake':v}


def test_native_12_dseg_seal_and_120_observations(native):
    s=native;writes=list(s['fake'].writes);r=call(s);h=call(s,policy='require-verified-hit')
    assert len(r.manifest['source_validation']['mode_dseg_inventory'])==12
    from cordon2025.__main__ import targets_from_audit
    targets=targets_from_audit();holdout={tuple(p) for p in s['c']['validation_unordered_pairs']}
    roles={(a,b):'VALIDATION' if (a,b) in holdout else 'CALIBRATION' for a in range(1,17) for b in range(a+1,17)}
    from cordon2025.state import observation_roster
    for method in r.variants:
        same(r.variants[method],h.variants[method]);inc=aggregate_observations(h.variants[method],targets,roles=roles)
        roster=observation_roster(inc.rows)
        assert (roster['rows'],roster['calibration'],roster['validation'])==(120,108,12)
    assert s['fake'].writes==writes


@pytest.mark.parametrize('damage',['missing_matrix','parity_fail','proof_false','wrong_mode'])
def test_native_source_faults(native,damage):
    s=native
    if damage=='missing_matrix':(s['p'].parent/s['e']['od_matrix_authorities'][0]['path']).unlink()
    elif damage=='parity_fail':
        p=s['p'].parent/'OD_PARITY.json';d=strict_json(p);d[0]['status']='FAIL';write_json(p,d);s['e']['external_od_parity_sha256']=sha256(p);update_evidence(s)
    elif damage=='proof_false':
        p=s['p'].parent/'GEOMETRY_PROOF.json';d=strict_json(p);d['full']=False;write_json(p,d)
    else:
        with sqlite3.connect(s['p']) as db:db.execute("UPDATE segments SET mode='C_NOT' WHERE dseg='NATIVE_CW'")
        s['e']['cache_sha256']=sha256(s['p']);update_evidence(s)
    with pytest.raises(Exception):call(s)


def test_cli_build_hit_and_verify_run(native):
    s=native
    from cordon2025.__main__ import main
    from cordon2025.session import verify_run
    out=s['tmp']/'runs'
    common=['inspect-cache','--config',str(ROOT/'CORDON_2025_AGGRESSIVE_CONFIG.json'),
            '--cache',str(s['p']),'--evidence',str(s['ep']),'--reuse-cache-dir',str(s['root']),'--output-root',str(out)]
    assert main(common+['--reuse-policy','build-offline','--run-name','cold'])==0
    assert main(common+['--reuse-policy','require-verified-hit','--run-name','warm'])==0
    report=strict_json(out/'warm/PERF01_CACHE_STATUS.json')
    assert report['cache_action']=='CACHE_HIT_VERIFIED' and report['geometry_redecode_count']==0
    assert verify_run(out/'warm')['completed']
    assert not (out/'warm/STATION_HITS.csv').exists()
    assert strict_json(out/'warm/RUN_REPORT.json')['apply_permitted'] is False


def test_old_incomplete_uploaded_cache_not_adopted():
    p=Path('/mnt/data/p.sqlite');ep=Path('/mnt/data/SNAPSHOT_EVIDENCE.json')
    if not p.exists() or not ep.exists():pytest.skip('historical upload not installed')
    if sha256(p)=='7e35a96ac1bc4fb306049d410379e349fde5aa8a07b15bf11301ed858253fa9a':pytest.skip('this is the complete cache, not the negative fixture')
    cfg=read_config();
    with pytest.raises(Exception,match='SHA256'):source_seal(p,ep,cfg)


def test_status_output_cannot_overwrite_source_on_failed_read(setup):
    s=setup;before=s['ep'].read_bytes();s['e']['completed']=False;update_evidence(s);before=s['ep'].read_bytes()
    with pytest.raises(Exception,match='OUTPUT_COLLISION'):call(s,status_path=s['ep'])
    assert s['ep'].read_bytes()==before


def test_algorithm_fingerprint_change_invalidates(setup,monkeypatch):
    s=setup;call(s)
    import cordon2025.perf01_identity as mod
    old=mod.algorithm_identity
    def changed():
        data=old();data['sha256']='a'*64;return data
    monkeypatch.setattr(mod,'algorithm_identity',changed)
    with pytest.raises(Exception,match='CACHE_MISS'):call(s,policy='require-verified-hit')


def test_method_change_not_ignored(setup):
    s=setup;call(s);s['c']['observation_methods']=['ENDPOINT_ONLY']
    with pytest.raises(Exception,match='ENUMERATION'):call(s)


def test_zero_native_calls_by_import_trap(setup,monkeypatch):
    import builtins
    old=builtins.__import__
    def trap(name,*args,**kwargs):
        if name.startswith(('win32com','pythoncom')):raise AssertionError('NO_COM_IMPORT_ALLOWED')
        return old(name,*args,**kwargs)
    monkeypatch.setattr(builtins,'__import__',trap)
    assert call(setup).status['native_com_read_count']==0
    assert call(setup,policy='require-verified-hit').status['native_com_read_count']==0


@pytest.mark.parametrize('field,value',[('capture_complete','false'),('geometry_identity','PROVISIONAL_REPRESENTATIVE_ONLY')])
def test_native_sqlite_completion_is_not_just_json(native,field,value):
    s=native
    with sqlite3.connect(s['p']) as db:db.execute('UPDATE metadata SET value=? WHERE key=?',(value,field))
    s['e']['cache_sha256']=sha256(s['p']);update_evidence(s)
    with pytest.raises(Exception,match='SQLITE_'):call(s)


def test_checkpoint_binding_and_mismatch(native):
    s=native
    files=[]
    for path in [s['p'],s['ep'],s['p'].parent/'GEOMETRY_PROOF.json',s['p'].parent/'OD_PARITY.json',
                 *[s['p'].parent/r['path'] for r in s['e']['od_matrix_authorities']]]:
        files.append(dict(path=path.relative_to(s['p'].parent).as_posix(),**file_record(path)))
    cp=s['p'].parent/'RUN_CHECKPOINT.json';write_json(cp,{'completed':True,'stage':'READONLY_VISUM_RUN_COMPLETE',
        'context':{'model_year':2025,'survey_year':2026},'artifacts':files})
    assert call(s,source_checkpoint=cp).status['cache_action']=='CACHE_BUILT_OFFLINE'
    files[0]['sha256']='0'*64;d=strict_json(cp);d['artifacts']=files;write_json(cp,d)
    with pytest.raises(Exception,match='CHECKPOINT_SOURCE'):call(s,source_checkpoint=cp)


def test_crashed_process_leaves_lock_no_partial_hit(setup):
    s=setup;cf=s['tmp']/'cfg.json';mf=s['tmp']/'mapping.json';write_json(cf,s['c']);write_json(mf,[[*k,v] for k,v in s['m'].items()])
    code='''import json,os,sys
from cordon2025.perf01_cache import get_or_build
p,e,c,m,d=sys.argv[1:]
def fault(phase,stage):
 if phase=='BEFORE_PUBLISH':os._exit(73)
get_or_build(p,{tuple(x[:3]):x[3] for x in json.load(open(m))},json.load(open(c)),e,cache_dir=d,policy='build-offline',_fault=fault)
'''
    proc=subprocess.run([sys.executable,'-c',code,*map(str,(s['p'],s['ep'],cf,mf,s['root']))],cwd=ROOT,timeout=30)
    assert proc.returncode==73
    assert (s['root']/'.perf01.writer.lock').exists()
    with pytest.raises(Exception,match='CACHE_MISS'):call(s,policy='require-verified-hit')
    with pytest.raises(Exception,match='LOCKED'):call(s)
    # Manual recovery ONLY after confirmed process exit. Never implicit lock theft.
    import shutil
    for stage in s['root'].glob('.stg-*'):shutil.rmtree(stage)
    (s['root']/'.perf01.writer.lock').unlink()
    assert call(s).status['cache_action']=='CACHE_BUILT_OFFLINE'


def test_c17_unchanged_with_warm_arrays(setup):
    from cordon2025.budget import SharedBudget
    # Reuse the production budget example fixture; check solver's shared budget.
    from cordon2025.optimizer import solve
    s=setup;h=call(s);a=h.variants['ALL_ORDERED_UNIQUE_PAIRS']
    targets={(i,j):10 for i in range(1,5) for j in range(1,5) if i!=j}
    roles={(i,j):'CALIBRATION' for i in range(1,5) for j in range(i+1,5)}
    aa=aggregate_observations(a,targets,roles=roles)
    oracle=aggregate_observations(build_from_snapshot(s['p'],s['m'],s['c'],s['e'])['ALL_ORDERED_UNIQUE_PAIRS'],targets,roles=roles)
    cfg=read_config();cfg['solver_max_iter']=500;cfg['block_max_iter']=20
    budget=SharedBudget([(r['origin_station'],r['destination_station']) for r in aa.rows],
                       [1,2,3,4],np.full(4,10.),40.,'BOUNDED_SCENARIO',{'origin':'SYNTHETIC_TEST'},True)
    x=solve(aa,cfg,budget,allow_unapproved_scenario=True);y=solve(oracle,cfg,budget,allow_unapproved_scenario=True)
    assert budget.ledger(x.uncertainty)['global_credits_consumed']<=40.0000001
    assert np.array_equal(x.uncertainty,y.uncertainty)
    assert np.array_equal(x.delta_q,y.delta_q)


def test_transient_file_read_retries_preserve_content(setup,monkeypatch):
    import builtins
    s=setup;old=builtins.open;count=[0]
    def fail_twice(file,*args,**kwargs):
        if str(file)==str(s['p']) and count[0]<2:
            count[0]+=1;exc=PermissionError(13,'sharing violation');exc.winerror=32;raise exc
        return old(file,*args,**kwargs)
    monkeypatch.setattr(builtins,'open',fail_twice)
    r=call(s);assert count[0]==2 and r.status['cache_action']=='CACHE_BUILT_OFFLINE'


def test_dictionary_index_tamper_rejected_even_if_resealed(setup):
    s=setup;r=call(s);p=r.folder/'ALL_OD_TOTALS.npz'
    with np.load(p,allow_pickle=False) as z:a={k:z[k] for k in z.files}
    a['dseg'][0]=30000
    with open(p,'wb') as f:np.savez_compressed(f,**a)
    reseal(r.folder)
    with pytest.raises(Exception,match='DICTIONARY_INDEX'):call(s,policy='require-verified-hit')


def test_windows_reparse_point_rejected(setup,monkeypatch):
    from types import SimpleNamespace
    from cordon2025.perf01_identity import clean_path
    s=setup;old=os.lstat
    def marked(path,*args,**kwargs):
        st=old(path,*args,**kwargs)
        if str(path)==str(s['p']):return SimpleNamespace(st_mode=st.st_mode,st_file_attributes=0x400)
        return st
    monkeypatch.setattr(os,'lstat',marked)
    with pytest.raises(Exception,match='REPARSE'):clean_path(s['p'])


def test_unicode_space_uri_source_path(tmp_path):
    root=tmp_path/('model space # '+chr(382));root.mkdir()
    p=root/'source file.sqlite';m,e=create_cache(p,[('C',10,20,1,[A,B],{'NATIVE_CW':1.5})])
    cfg=dict(config(['NATIVE_CW']),model_year=2025,survey_year=2026,basis='RPDI',mode='OFFLINE_PROPOSAL')
    r=get_or_build(p,m,cfg,p.with_suffix('.evidence.json'),cache_dir=tmp_path/'derived',policy='build-offline')
    assert r.variants['ALL_ORDERED_UNIQUE_PAIRS'].model.sum()==1.5


def test_duplicate_json_keys_not_silently_accepted(setup):
    s=setup;s['ep'].write_text('{"completed":true,"completed":false}')
    with pytest.raises(Exception,match='DUPLICATE_JSON'):call(s)
