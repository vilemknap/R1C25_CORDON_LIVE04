"""Explicit immutable PERF01 cache for the SAME SEALED OFFLINE snapshot only.

This module never attaches to Visum. The FIX3 cold oracle is not replaced.
Warm verification uses content hashes, not mtime, OD totals or a network hash.
"""
from __future__ import annotations
from contextlib import contextmanager,closing
from dataclasses import dataclass
from pathlib import Path
import json
import os
import shutil
import sqlite3
import sys
import time
import uuid
from .common import require, ContractError, canonical_hash, parent_core, write_json
from .io import native_path, mkdir, retry, copy_verified
from .perf01_identity import (SCHEMA,IMPLEMENTATION,clean_path,relative_file,strict_json,
                               file_record,source_seal,cache_keys,SIDECARS)
from .perf01_codec import save_bundle,load_bundle,export_legacy,read_arrays,validate_result

MARKER='CORDON_PERF01_ROOT.json'
LOCK='.perf01.writer.lock'
MANIFEST='MANIFEST.json'
COMPLETE='COMPLETE.json'
POLICIES=('disabled','build-offline','require-verified-hit')


def peak_rss():
    try:
        import resource
        value=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return value/(1024**2 if sys.platform=='darwin' else 1024)
    except (ImportError,AttributeError):return None


def _sync_directory(path):
    if os.name=='nt':return False  # files themselves fsynced by atomic_output
    fd=os.open(native_path(path),os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)
    return True


def _root_expect(source):
    return {'schema':'CORDON_PERF01_ROOT_V1','source_id':source.source_id,
            'model_year':2025,'survey_year':2026,'authority_family':'CORDON_SDP',
            'origin':source.evidence['origin'],'apply_permitted':False}


def _validate_root(root,source):
    root=clean_path(root)
    require(root.is_dir() and (root/MARKER).is_file(),'PERF01_OWNED_CACHE_ROOT_REQUIRED')
    require(strict_json(root/MARKER)==_root_expect(source),'PERF01_ROOT_SNAPSHOT_MISMATCH')
    return root


@contextmanager
def writer_lock(root,source):
    root=clean_path(root);expected=_root_expect(source)
    if root.exists():
        require(root.is_dir(),'PERF01_ROOT_NOT_DIRECTORY')
        if (root/MARKER).exists():_validate_root(root,source)
        else:require(not list(root.iterdir()),'PERF01_UNKNOWN_NONEMPTY_ROOT')
    else:mkdir(root)
    token=uuid.uuid4().hex
    try:
        fd=os.open(native_path(root/LOCK),os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError as exc:
        raise ContractError('PERF01_WRITER_LOCKED_NO_AUTO_STEAL') from exc
    try:
        with os.fdopen(fd,'w',encoding='ascii') as f:f.write(token);f.flush();os.fsync(f.fileno())
        # Recheck under lock; do not adopt content introduced by a race.
        if (root/MARKER).exists():_validate_root(root,source)
        else:
            require({p.name for p in root.iterdir()}=={LOCK},'PERF01_UNKNOWN_NONEMPTY_ROOT')
            write_json(root/MARKER,expected)
        yield root
    finally:
        primary=sys.exc_info()[0] is not None
        try:
            require((root/LOCK).read_text(encoding='ascii')==token,'PERF01_LOCK_OWNER_CHANGED')
            retry(lambda:os.unlink(native_path(root/LOCK)))
        except Exception:
            if not primary:raise


def _records(folder):
    result=[]
    for p in sorted(folder.iterdir()):
        clean_path(p)
        require(p.is_file(),'PERF01_UNEXPECTED_BUNDLE_DIRECTORY')
        if p.name in (MANIFEST,COMPLETE):continue
        result.append(dict(path=p.name,**file_record(p,None)))
    return result


def verify_entry(folder,expected_key,expected_source=None,counter=None):
    folder=clean_path(folder)
    require(folder.is_dir() and (folder/COMPLETE).is_file(),'PERF01_INCOMPLETE_DERIVED_BUNDLE')
    done=strict_json(folder/COMPLETE)
    mr=file_record(folder/MANIFEST,counter,'derived_bytes_read')
    require(done.get('schema')==SCHEMA and done.get('completed') is True and done.get('key')==expected_key
            and mr['sha256']==done.get('manifest_sha256'),'PERF01_MANIFEST_SEAL_MISMATCH')
    m=strict_json(folder/MANIFEST)
    require(m.get('schema')==SCHEMA and m.get('implementation')==IMPLEMENTATION and m.get('key')==expected_key,
            'PERF01_MANIFEST_SCHEMA_OR_KEY')
    require(canonical_hash(m['identities']['incidence'])==expected_key and
            canonical_hash(m['identities']['geometry'])==m.get('geometry_key'), 'PERF01_MANIFEST_IDENTITY_MISMATCH')
    require(m.get('apply_permitted') is False and m.get('assignment_executed') is False and
            m.get('live_calibration_verified') is False and m.get('source_validation',{}).get('sqlite_integrity')=='ok',
            'PERF01_INVALID_TRUTH_BOUNDARY')
    if expected_source is not None:
        require(m.get('source_id')==expected_source.source_id,'PERF01_SOURCE_ID_MISMATCH')
    seen=set()
    for rec in m['files']:
        p=relative_file(folder,rec['path'])
        require(p.parent==folder and rec['path'] not in seen and rec['path'] not in (MANIFEST,COMPLETE), 'PERF01_DUPLICATE_OR_NESTED_ARTIFACT')
        seen.add(rec['path'])
        require(file_record(p,counter,'derived_bytes_read')=={k:rec[k] for k in ('bytes','sha256')},'PERF01_DERIVED_HASH_MISMATCH:'+rec['path'])
    require({p.name for p in folder.iterdir()}==seen|{MANIFEST,COMPLETE},'PERF01_UNSEALED_BUNDLE_ARTIFACT')
    for p in folder.iterdir():clean_path(p)
    expected={'SHARED_AUDIT.json','ALL_OD_TOTALS.npz','VARIABLE_TABLES.npz','STATION_HITS.csv',
              'ALL_ORDERED_UNIQUE_PAIRS.npz','ALL_ORDERED_UNIQUE_PAIRS.json','EXACT_TWO_HITS.npz','EXACT_TWO_HITS.json'}
    require(seen==expected,'PERF01_BUNDLE_FILES_INCOMPLETE')
    return m,mr['sha256']


@dataclass
class CacheResult:
    variants: dict
    status: dict
    folder: Path
    manifest: dict
    manifest_sha256: str
    source: object

    def save_incidence(self,inc,folder,*,legacy=False):
        if legacy:
            export_legacy(inc,folder);return
        from .common import write_npz
        out=clean_path(folder)
        require(self.folder not in out.parents and out!=self.folder,'PERF01_IMMUTABLE_BUNDLE_OUTPUT_COLLISION')
        mkdir(out)
        write_npz(out/'INCIDENCE.npz',row=inc.operator.row_idx,col=inc.operator.col_idx,
                  through=inc.operator.values,share=inc.share_operator.values,q=inc.q_current,
                  model=inc.model,mutable=inc.mutable,fixed=inc.fixed)
        # common audit and variable rows reside once in the immutable bundle.
        base=self.variants[inc.audit['method']]
        delta={k:v for k,v in inc.audit.items() if k not in base.audit or v is not base.audit[k] and v!=base.audit[k]}
        write_json(out/'INCIDENCE_METADATA.json',{'schema':'CORDON_INCIDENCE_REFERENCE_V4',
                   'method':inc.audit['method'],'rows':inc.rows,'audit_overrides':delta,
                   'incidence_sha256':file_record(out/'INCIDENCE.npz')['sha256'],
                   'shared_authority':{'key':self.manifest['key'],'manifest_sha256':self.manifest_sha256,
                                       'cache_root_hint':str(self.folder.parent),'source_id':self.manifest['source_id']},
                   'apply_permitted':False,'production_ready':False})

    def save_hits_reference(self,path):
        rec=next(r for r in self.manifest['files'] if r['path']=='STATION_HITS.csv')
        write_json(path,{'schema':'CORDON_STATION_HITS_REFERENCE_V1','bundle_key':self.manifest['key'],
                         'manifest_sha256':self.manifest_sha256,'artifact':rec,
                         'cache_root_hint':str(self.folder.parent),'apply_permitted':False})


def load_compact_result(folder,verified_cache):
    """Resolve a small run report only through an already verified CacheResult."""
    from .incidence import Incidence
    folder=clean_path(folder);meta=strict_json(folder/'INCIDENCE_METADATA.json')
    require(meta.get('schema')=='CORDON_INCIDENCE_REFERENCE_V4','PERF01_RESULT_SCHEMA')
    ref=meta['shared_authority']
    require(ref['key']==verified_cache.manifest['key'] and ref['manifest_sha256']==verified_cache.manifest_sha256
            and ref['source_id']==verified_cache.manifest['source_id'],'PERF01_RESULT_REFERENCE_MISMATCH')
    require(meta.get('apply_permitted') is False and meta.get('production_ready') is False,'PERF01_RESULT_FLAGS')
    method=meta['method'];require(method in verified_cache.variants,'PERF01_RESULT_METHOD')
    require(file_record(folder/'INCIDENCE.npz')['sha256']==meta['incidence_sha256'],'PERF01_RESULT_ARRAY_HASH')
    from .perf01_codec import ARRAY_NAMES
    a=read_arrays(folder/'INCIDENCE.npz',ARRAY_NAMES);base=verified_cache.variants[method]
    # The only downstream audit extension in FIX3 is aggregation.
    require(not set(meta['audit_overrides'])-{'aggregation'},'PERF01_RESULT_AUDIT_OVERRIDE_FORBIDDEN')
    core=parent_core();nr=len(meta['rows']);nc=len(base.variables)
    result=Incidence(meta['rows'],base.variables,base.projection_base_variables,a['q'],
               core.SparseOperator(a['row'],a['col'],a['through'],nr,nc),
               core.SparseOperator(a['row'],a['col'],a['share'],nr,nc),a['model'],a['mutable'],a['fixed'],
               dict(base.audit,**meta['audit_overrides']))
    return validate_result(result)


def get_or_build(path,station_map,cfg,evidence_path,*,cache_dir,policy='require-verified-hit',
                 source_checkpoint=None,context='same-sealed-snapshot',status_path=None,_fault=None):
    """Return both directed methods. HIT never invokes the old cold builder.

    _fault is a test-only callback at publication boundaries, not a cache bypass.
    """
    from .state import validate_perf01_options
    validate_perf01_options(policy,cache_dir,context)
    begin=time.perf_counter();cpu=time.process_time()
    status={'schema':'CORDON_PERF01_CACHE_STATUS_V1','manifest_schema':SCHEMA,'implementation':IMPLEMENTATION,
            'cache_action':'BLOCKED','hit':False,'miss_reason':None,'geometry_redecode_count':0,
            'station_hit_visits':0,'sqlite_geometry_scans':0,'native_com_read_count':0,
            'source_bytes_hashed':0,'derived_bytes_read':0,'derived_bytes_written':0,
            'hash_byte_counter_scope':'PERF01_VALIDATOR_SUCCESSFUL_BYTES_EXCLUDES_COLD_ORACLE_INTERNAL_HASHING',
            'apply_permitted':False,'assignment_executed':False,'live_calibration_verified':False}
    root=clean_path(cache_dir);sp=clean_path(status_path) if status_path else None
    from .common import ROOT
    require('2022' not in root.parts,'MODEL_2022_OUTPUT_ROOT_FORBIDDEN')
    protected=[ROOT/part for part in ('parent','cordon2025','data','tests','docs')]
    require(root!=ROOT and not any(root==p or p in root.parents for p in protected),'PERF01_PROTECTED_SOURCE_ROOT')
    require(policy in ('build-offline','require-verified-hit'),'PERF01_POLICY_REQUIRES_EXPLICIT_BUILD_OR_HIT')
    require(sp is None or (sp!=root and root not in sp.parents),'PERF01_STATUS_INSIDE_CACHE_FORBIDDEN')
    require(root!=clean_path(path).parent and root not in clean_path(path).parents,'PERF01_CACHE_INPUT_ROOT_COLLISION')
    require(sp is None or (not sp.exists() and sp not in
            (clean_path(path),clean_path(evidence_path))), 'PERF01_STATUS_OUTPUT_COLLISION')
    source=None;result=None
    try:
        t=time.perf_counter()
        source=source_seal(path,evidence_path,cfg,checkpoint=source_checkpoint,context=context,counter=status)
        require(sp is None or sp not in source.tracked,'PERF01_STATUS_INPUT_COLLISION')
        gkey,key,ids=cache_keys(source,station_map,cfg)
        status.update(source_id=source.source_id,source_identities=source.identity,geometry_key=gkey,incidence_key=key,
                      origin=source.evidence['origin'],source_verification_wall_s=time.perf_counter()-t)
        folder=relative_file(root,key)
        if root.exists():
            if (root/MARKER).exists():_validate_root(root,source)
            else:require(not list(root.iterdir()),'PERF01_UNKNOWN_NONEMPTY_ROOT')
        if not folder.exists():
            require(policy!='require-verified-hit','PERF01_CACHE_MISS_NO_REBUILD')
            status['miss_reason']='NO_DERIVED_BUNDLE_FOR_KEY'
            with writer_lock(root,source):
                # Another writer could have finished after the initial lookup.
                if not folder.exists():
                    stage=root/('.stg-'+uuid.uuid4().hex[:12]);mkdir(stage,exist_ok=False)
                    try:
                        from .incidence import build_from_snapshot,SCHEMA as SQL_SCHEMA
                        t=time.perf_counter()
                        with closing(sqlite3.connect(source.path.as_uri()+'?mode=ro',uri=True)) as db:
                            db.execute('PRAGMA query_only=ON')
                            require(db.execute('PRAGMA integrity_check').fetchone()[0]=='ok','SQLITE_INTEGRITY_FAIL')
                            md=dict(db.execute('SELECT key,value FROM metadata'))
                            if source.evidence['origin']=='VISUM_SAVED_PATHS':
                                require(md.get('capture_complete')=='true','PERF01_SQLITE_CAPTURE_NOT_COMPLETE')
                                require(md.get('geometry_identity')=='FULL_SAME_MODE_GEOMETRY_COMPARED_THIS_CAPTURE',
                                        'PERF01_SQLITE_GEOMETRY_PROVISIONAL')
                            inventory=[{'dseg':c,'mode':m,'audit':json.loads(a)} for c,m,a in db.execute('SELECT dseg,mode,audit_json FROM segments ORDER BY dseg')]
                        variants=build_from_snapshot(source.path,station_map,cfg,source.evidence,hits_output=stage/'STATION_HITS.csv')
                        metrics=next(iter(variants.values())).audit['metrics']
                        status.update(geometry_redecode_count=metrics['decoded_geometry'],
                                      station_hit_visits=metrics['geometry_edge_count'],sqlite_geometry_scans=1,
                                      cold_build_wall_s=time.perf_counter()-t)
                        t=time.perf_counter();save_bundle(stage,variants)
                        # Release cold Python all-OD dictionaries before verifying typed data.
                        del variants
                        import gc
                        gc.collect()
                        if _fault:_fault('AFTER_DATA',stage)
                        source.recheck(status)
                        m={'schema':SCHEMA,'implementation':IMPLEMENTATION,'key':key,'geometry_key':gkey,
                           'source_id':source.source_id,'source':source.identity,'identities':ids,
                           'source_validation':{'sqlite_schema':SQL_SCHEMA,'sqlite_integrity':'ok','metadata':md,
                                                'mode_dseg_inventory':inventory,'oracle':'FIX3_BUILD_FROM_SNAPSHOT',
                                                'full_geometry_proof':True,'per_od_parity':'PASS'},
                           'files':_records(stage),'apply_permitted':False,'assignment_executed':False,
                           'live_calibration_verified':False}
                        write_json(stage/MANIFEST,m)
                        mh=file_record(stage/MANIFEST)['sha256']
                        write_json(stage/COMPLETE,{'schema':SCHEMA,'key':key,'completed':True,'manifest_sha256':mh})
                        verify_entry(stage,key,source,status)
                        check=load_bundle(stage);del check
                        if _fault:_fault('BEFORE_PUBLISH',stage)
                        _sync_directory(stage)
                        retry(lambda:os.rename(native_path(stage),native_path(folder)))
                        _sync_directory(root)
                        status['derived_bytes_written']=sum(p.stat().st_size for p in folder.iterdir())
                        status['cache_action']='CACHE_BUILT_OFFLINE'
                        status['publication_wall_s']=time.perf_counter()-t
                    finally:
                        if stage.exists():shutil.rmtree(native_path(stage))
        t=time.perf_counter();m,mh=verify_entry(folder,key,source,status)
        require(m['identities']==ids,'PERF01_IDENTITIES_DIFFER')
        require(m['source_validation']['sqlite_schema']=='R1_15A2_TWO_MODE_PATH_STORE_V238','PERF01_VALIDATION_SCHEMA')
        require(m['identities']['geometry']['source_id']==source.source_id,'PERF01_GEOMETRY_SOURCE_BINDING')
        from .state import snapshot_semantics
        snapshot_semantics(source.evidence,cfg,m['source_validation']['metadata'])
        variants=load_bundle(folder)
        # File hashes are rechecked after deserialization to catch concurrent edits.
        verify_entry(folder,key,source,status)
        status['derived_bytes_read']+=sum(r['bytes'] for r in m['files'] if r['path']!='STATION_HITS.csv')
        status['load_wall_s']=time.perf_counter()-t
        source.recheck(status)
        if status['cache_action']!='CACHE_BUILT_OFFLINE':status.update(cache_action='CACHE_HIT_VERIFIED',hit=True)
        status['validation_status']='SOURCE_AND_DERIVED_CONTENT_VERIFIED'
        status['source_validation_reuse']='SAME_BYTES_SAME_ALGORITHM_NOT_NEW_ASSIGNMENT'
        result=CacheResult(variants,status,folder,m,mh,source)
        return result
    except Exception as exc:
        status.update(cache_action='BLOCKED',error_code=str(exc),miss_reason=str(exc))
        raise
    finally:
        status.update(elapsed_wall_s=time.perf_counter()-begin,cpu_s=time.process_time()-cpu,peak_rss_mib=peak_rss())
        if sp is not None and (source is None or sp not in source.tracked):
            from .io import telemetry_json
            status['status_write_result']=telemetry_json(sp,{k:v for k,v in status.items() if k!='status_write_result'})


def write_run_binding(folder,result):
    require(clean_path(result.folder.parent) not in clean_path(folder).parents,'PERF01_RUN_INSIDE_DERIVED_ROOT')
    write_json(Path(folder)/'PERF01_RUN_BINDING.json',{'schema':'CORDON_PERF01_RUN_BINDING_V1',
               'cache_root':str(result.folder.parent),'key':result.manifest['key'],
               'manifest_sha256':result.manifest_sha256,'source_id':result.source.source_id,
               'source_sqlite':str(result.source.path),
               'source_files':[dict(path=str(p),**rec) for p,rec in result.source.tracked.items()],
               'apply_permitted':False})


def verify_run_binding(folder):
    b=strict_json(Path(folder)/'PERF01_RUN_BINDING.json')
    require(b.get('schema')=='CORDON_PERF01_RUN_BINDING_V1' and b.get('apply_permitted') is False,'PERF01_RUN_BINDING_SCHEMA')
    require(not any(Path(b['source_sqlite']+s).exists() for s in SIDECARS),'LIVE_SQLITE_SIDECAR_PRESENT_COPY_COMPLETED_SNAPSHOT')
    for rec in b['source_files']:
        require(file_record(rec['path'])=={k:rec[k] for k in ('bytes','sha256')},'PERF01_BOUND_SOURCE_CHANGED')
    m,mh=verify_entry(relative_file(b['cache_root'],b['key']),b['key'])
    require(mh==b['manifest_sha256'] and m['source_id']==b['source_id'],'PERF01_BOUND_DERIVED_CHANGED')
    return {'status':'PERF01_RUN_REFERENCE_VERIFIED','apply_permitted':False}
