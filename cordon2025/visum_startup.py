"""Read-only Visum startup and saved-path bridge, using the original 15A2 engine.

This is NOT the profile controller with swapped labels. It never calls any
procedure, matrix setter, SaveVersion/LoadVersion, FlowBundle, or a routing engine.
A completed capture enables real baseline diagnostics; it does not certify a
2025 calibrated model or authorize APPLY.
"""
from __future__ import annotations
from pathlib import Path
from collections import defaultdict
from itertools import zip_longest
import hashlib
import json
import os
import re
import sqlite3
import struct
import sys
import threading
import time
import uuid
import numpy as np
from .common import ROOT, require, parent_module, parent_core, read_config, canonical_hash
from .io import write_json, write_csv, write_npz, read_json, sha256, mkdir, safe_failure_report, exception_text
from .session import RunSession
from .authority import mapping
from . import com_busy

DEFAULTS = {'max_dense_matrix_cells':25000000, 'full_geometry_check':True, 'page_size':256,
    'min_free_disk_gib':0.5, 'max_store_gib':0.0,
    'max_parent_rows_per_dseg':5000000, 'max_geometry_rows_per_mode':1000000000,
    'od_parity_atol':1e-5, 'od_parity_rtol':1e-5, 'path_volume_quantum':0.001,
    'path_volume_lattice_atol':1e-9, 'missing_path_cell_atol':0.0005,
    'parity_aggregate_abs_floor':0.01, 'parity_max_net_relative_error':1e-4,
    'parity_max_l1_relative_error':1e-3, 'parity_max_zero_flow_relative_mass':1e-4,
    'matrix_sum_atol':0.001, 'matrix_sum_rtol':1e-7,
    **com_busy.DEFAULTS, 'com_retry_attempts':128, 'com_retry_max_elapsed_seconds':180.0}

ACTIONS = ('PREFLIGHT','CAPTURE_DIAGNOSTICS')


def settings(options=None):
    value=dict(DEFAULTS)
    require(not set(options or {})-set(DEFAULTS),'UNKNOWN_VISUM_STARTUP_OPTION')
    value.update(options or {})
    require(type(value['full_geometry_check']) is bool,'INVALID_GEOMETRY_CHECK_OPTION')
    require(type(value['com_retry_enabled']) is bool,'INVALID_STARTUP_SETTING:com_retry_enabled')
    integers={'page_size':4096,'com_retry_attempts':1000,'max_dense_matrix_cells':100000000,
              'max_parent_rows_per_dseg':10000000,'max_geometry_rows_per_mode':1000000000}
    for k, maximum in integers.items():
        v=value[k]
        require(type(v) is int and 1 <= v <= maximum,'INVALID_STARTUP_SETTING:'+k)
    for k in set(DEFAULTS)-set(integers)-{'full_geometry_check','com_retry_enabled'}:
        v=value[k]
        require(type(v) in (int,float) and np.isfinite(v) and v>=0,'INVALID_STARTUP_SETTING:'+k)
    require(value['com_retry_backoff_factor']>=1,'INVALID_STARTUP_SETTING:com_retry_backoff_factor')
    require(value['com_retry_max_delay_seconds']>=value['com_retry_initial_delay_seconds'],'INVALID_STARTUP_RETRY_DELAY_ORDER')
    require(value['max_store_gib']==0 or 0.001<=value['max_store_gib']<=1024,
            'INVALID_STARTUP_SETTING:max_store_gib')
    from .parity import from_options
    from_options(value)  # validate the same policy that the external reader replays
    return value


class ReadControl:
    """Same-thread COM calls, cooperative STOP, no hidden wall-clock shutdown."""
    def __init__(self,folder):
        self.folder=Path(folder);self.thread=threading.get_ident();self.last=0.;self.state={};self.telemetry_failures=[]
    def checkpoint(self,phase=None,force=False,**details):
        require(threading.get_ident()==self.thread,'COM_THREAD_CHANGED')
        if (self.folder/'STOP_REQUESTED').exists() or (self.folder.parent/'STOP_REQUESTED').exists():
            raise RuntimeError('USER_STOP_REQUESTED')
        if isinstance(details.get('com_retry_event'),dict):
            com_busy.record_event(self,details['com_retry_event'])
        self.state.update(details)
        if phase:self.state['phase']=phase
        now=time.monotonic()
        if force or now-self.last>2:
            try:
                write_json(self.folder/'00_PROGRESS.json',dict(self.state,apply_permitted=False,assignment_executed=False))
            except Exception as exc:
                self.telemetry_failures=(self.telemetry_failures+[exception_text(exc)])[-20:]
            self.last=now


def retry_policy(opt):
    return com_busy.policy(opt)


def _call(func,control,opt,label):
    return com_busy.read_call(func,control,opt,label)


def _bounded_rows(obj,columns,st,control,opt,phase,**details):
    two=parent_module('r1_15a2_two_mode_v238')
    return two.bounded_rows(com_busy.BoundedReadTarget(obj,control,opt,phase),
                            columns,st,control,phase,**details)


def _columns(collection,names,control,opt):
    """Join bulk attributes by COM index, never zip positional arrays silently."""
    com=parent_module('r1_15a2_com_compat');cols={}
    for name in names:
        control.checkpoint('READ_'+name)
        rows=_call(lambda:com.get_multi_att_values(collection,name,retry_policy=com_busy.NO_RETRY),
                   control,opt,'BULK_'+name)
        pairs=[(com.exact_int(i,'COM row index'),v) for i,v in rows]
        require(len({i for i,v in pairs})==len(pairs),'DUPLICATE_COM_ROW_INDEX:'+name)
        cols[name]=dict(pairs)
    keys=set(cols[names[0]])
    require(all(set(col)==keys for col in cols.values()),'COM_ATTRIBUTE_ROW_COVERAGE_MISMATCH')
    return [{name:cols[name][i] for name in names} for i in sorted(keys)]


def _network(visum,control,opt):
    com=parent_module('r1_15a2_com_compat')
    zones,_=_call(lambda:com.zone_identity(visum,retry_policy=com_busy.NO_RETRY),
                  control,opt,'ZONE_IDENTITY')
    require(zones and all(z>0 for z in zones),'INVALID_ZONE_IDENTITY')
    collection=_call(lambda:visum.Net.Links,control,opt,'NET_LINKS_PROPERTY')
    rows=_columns(collection,('NO','FROMNODENO','TONODENO','TSYSSET'),control,opt)
    links={}
    for row in rows:
        key=tuple(com.exact_int(row[k],k) for k in ('NO','FROMNODENO','TONODENO'))
        require(min(key)>0 and key not in links,'DUPLICATE_OR_INVALID_DIRECTIONAL_LINK')
        tsys=tuple(sorted(t.strip().upper() for t in str(row['TSYSSET']).split(',') if t.strip()))
        links[key]={'eligible':False,'tsys':tsys}
    require(links,'EMPTY_NETWORK')
    fp=canonical_hash({'zones':zones,'links':[(key,val['tsys']) for key,val in sorted(links.items())]})
    return zones,links,fp


def _segments(visum,cfg,control,opt):
    com=parent_module('r1_15a2_com_compat');core=parent_core()
    from r1_15a2_two_mode_v238 import EXPECTED_MODE_DSEGS
    collection=_call(lambda:visum.Net.DemandSegments,control,opt,'NET_DSEGS_PROPERTY')
    rows=_columns(collection,('CODE',),control,opt)
    roster={}
    for r in rows:
        code=str(r['CODE']).strip();norm=core.norm_code(code)
        require(norm not in roster,'DUPLICATE_CANONICAL_LIVE_DSEG')
        roster[norm]=code
    wanted={core.norm_code(c) for c in cfg['selected_dsegs']}
    require(wanted == set().union(*EXPECTED_MODE_DSEGS.values()),'CORDON_REQUIRES_APPROVED_12_OA_SCOPE')
    require(wanted.issubset(roster),'LIVE_OA_SEGMENTS_MISSING:'+','.join(sorted(wanted-set(roster))))
    extra={c for c in roster if c.startswith(('NATIVE_','EXOG_EE_')) and core.family_from_dseg(c) in ('WORK','SERVICE','LONG','FOREIGN')}-wanted
    require(not extra,'UNDECLARED_LIVE_OA_SEGMENT:'+','.join(sorted(extra)))
    result=[]
    for norm in sorted(wanted):
        code=roster[norm]
        obj=_call(lambda:visum.Net.DemandSegments.ItemByKey(code),control,opt,'DSEG_'+code)
        mode=core.norm_code(_call(lambda:obj.AttValue('MODE'),control,opt,'MODE_'+code))
        require(norm in EXPECTED_MODE_DSEGS.get(mode,()),'LIVE_DSEG_MODE_MISMATCH:'+norm)
        result.append({'code':code,'norm_code':norm,'mode':mode,'object':obj})
    return result


def _matrix(ds,zone_count,control,opt):
    """Read each array once, verify SUM, retain exact independent matrix bytes."""
    require(zone_count*zone_count<=opt['max_dense_matrix_cells'],'DENSE_MATRIX_MEMORY_BUDGET_EXCEEDED_BEFORE_COM_READ')
    com=parent_module('r1_15a2_com_compat')
    matrix=_call(lambda:ds['object'].ODMatrix,control,opt,'OD_MATRIX_'+ds['code'])
    arr=np.asarray(_call(lambda:matrix.GetValues(),control,opt,'OD_VALUES_'+ds['code']),dtype='<f8')
    require(arr.shape==(zone_count,zone_count) and np.isfinite(arr).all() and (arr>=0).all(),'INVALID_DSEG_MATRIX_AUTHORITY:'+ds['code'])
    no=com.exact_int(_call(lambda:matrix.AttValue('NO'),control,opt,'MATRIX_NO'),'Matrix.NO')
    declared=com.finite_float(_call(lambda:matrix.AttValue('SUM'),control,opt,'MATRIX_SUM'),'Matrix.SUM')
    total=float(arr.sum(dtype=np.float64));diag=float(np.trace(arr))
    require(abs(total-declared)<=max(opt['matrix_sum_atol'],abs(total)*opt['matrix_sum_rtol']),'MATRIX_SUM_MISMATCH:'+ds['code'])
    return arr,{'matrix_no':no,'matrix_total':total,'matrix_diagonal':diag,'matrix_interzonal':max(0.,total-diag),
        'matrix_sha256':hashlib.sha256(np.ascontiguousarray(arr).tobytes()).hexdigest(),'matrix_shape':list(arr.shape)}


def _new_list(visum,kind,code,control,opt):
    # Retry a NEW list as a unit, not AddColumn on an unknown partially-mutated list.
    two=parent_module('r1_15a2_two_mode_v238')
    rt=parent_module('r1_15a2_runtime_v1')
    def create():
        # Do not switch to legacy Visum.Lists after a transient Workbench error.
        # The official object and column helpers are the original 15A2 helpers.
        lists=visum.Workbench.Lists
        obj=rt.create_list(lists,kind)
        all_routes,_=rt.get_all_routes_filter()
        obj.SetObjects(0,code,all_routes)
        columns=two.PARENT_COLUMNS if kind=='CreatePrTPathList' else two.GEOMETRY_COLUMNS
        for column in columns:obj.AddColumn(column)
        return obj
    return _call(create,control,opt,'CREATE_LIST_'+code)


def preflight(visum,cfg,folder,control,opt):
    com=parent_module('r1_15a2_com_compat');rt=parent_module('r1_15a2_runtime_v1')
    _call(lambda:com.bind_injected({'Visum':visum}),control,opt,'BIND_INJECTED_PROPERTIES')
    api=parent_module('r1_15a2_live_api_audit')
    source=_call(lambda:api.current_version_file(visum),control,opt,'CURRENT_VERSION')
    require(not re.search(r'(?<![0-9])2022(?![0-9])',str(source)),'MODEL_2022_SOURCE_REFUSED')
    zone_nos,links,network_hash=_network(visum,control,opt)
    station_map,_=mapping(ROOT/'data/audited/STATION_MAPPING.csv')
    missing=[key for key in station_map if key not in links]
    write_json(folder/'STATION_MAPPING_CHECK.json',{'stations':len(set(station_map.values())),
        'directed_keys':len(station_map),'missing_directed_keys':missing,'network_sha256':network_hash})
    require(not missing,'STATION_LINK_MAPPING_DOES_NOT_MATCH_CURRENT_NETWORK')
    dsegs=_segments(visum,cfg,control,opt)
    matrix_audit={};sample_audit=[]
    two=parent_module('r1_15a2_two_mode_v238')
    for ds in dsegs:
        arr,info=_matrix(ds,len(zone_nos),control,opt);matrix_audit[ds['norm_code']]=info
        for kind,cols in (('CreatePrTPathList',two.PARENT_COLUMNS),('CreatePrTPathLinkList',two.GEOMETRY_COLUMNS)):
            obj=_new_list(visum,kind,ds['code'],control,opt)
            ole,memid,invkind=rt.verified_bounded_signature(com_busy.BoundedReadTarget(obj,control,opt,'PREFLIGHT_SIGNATURE'))
            raw=_call(lambda:com.bounded_ole_invoke_with_retry(ole,memid,invkind,1,8,
                retry_policy=com_busy.NO_RETRY,label='PREFLIGHT_'+kind),control,opt,'PREFLIGHT_'+kind)
            raw=[] if raw is None else raw
            require(len(raw)<=8 and all(len(row)==len(cols) for row in raw),'PREFLIGHT_LIST_SCHEMA_MISMATCH')
            require(raw or info['matrix_interzonal']<=1e-9,'NO_SAVED_PRT_PATHS_FOR_POSITIVE_DEMAND:'+ds['code'])
            sample_audit.append({'dseg':ds['code'],'list':kind,'sample_rows':len(raw),'bounded_signature_verified':True})
        del arr
    report={'status':'VISUM_READONLY_PREFLIGHT_PASS','source_version':str(source),
        'source_year_hint_2025':bool(re.search(r'(?<![0-9])2025(?![0-9])',str(source))),
        'model_year':2025,'model_year_authority':'USER_REQUESTED_NOT_INFERRED_FROM_VISUM_APPLICATION_VERSION',
        'network_sha256':network_hash,'network_fingerprint_scope':'ZONE_ORDER_DIRECTED_LINK_KEYS_TSYS_NOT_COMPLETE_SUPPLY_STATE',
        'zone_count':len(zone_nos),'link_count':len(links),'matrix_audit':matrix_audit,
        'path_list_probes':sample_audit,'dsegs':[{'code':d['code'],'norm_code':d['norm_code'],'mode':d['mode']} for d in dsegs],
        'calibration_ready':False,'apply_permitted':False,'assignment_executed':False,
        'remaining_gates':['OBSERVATION_SEMANTICS_UNAPPROVED','YEAR_BRIDGE_UNAPPROVED','C17_POLICY_UNAPPROVED',
            'LIVE_TG_TD_CANDIDATE_ADAPTER_NOT_IMPLEMENTED','NATIVE_WINDOWS_VISUM_ACCEPTANCE_NOT_YET_RECORDED']}
    write_json(folder/'PREFLIGHT.json',report)
    return report,source,zone_nos,links,dsegs


def _od_parity(db,ds,values,zone_nos,opt):
    from .parity import compare_database, from_options
    return compare_database(db, ds['norm_code'], values, zone_nos, from_options(opt))



def _add_parents_with_precision(collector,ds,mode,rows,authority,values,zones,opt):
    """Replace only the legacy aggregate guard with independent cell evidence.

    The unmodified 15A2 parser raises its aggregate failure AFTER committing all
    rows and its audit. Every structural/parser/resource exception still escapes.
    This helper never marks the inherited audit as passed or modifies its data.
    """
    two=parent_module('r1_15a2_two_mode_v238')
    inherited_failure=None
    try:
        collector.add_parents(ds['norm_code'],mode,rows,authority)
    except two.SupplyContractError as exc:
        expected='SAME_RUN_OFFDIAGONAL_PARITY_FAILED:'+ds['norm_code']
        if exception_text(exc) != expected:
            raise
        require(ds['norm_code'] in collector.parents,'INCOMPLETE_INHERITED_PARENT_AUDIT')
        inherited_failure=expected
    parity,_=_od_parity(collector.db,ds,values,zones,opt)
    parity['inherited_aggregate_parity_passed']=bool(collector.parents[ds['norm_code']]['passes'])
    parity['inherited_aggregate_failure']=inherited_failure
    parity['independent_per_OD_precision_check_required']=True
    return parity


def _geometry_equal(main,other,mode):
    fields='orig,dest,path_index,edge_count,sequence_sha256'
    query='SELECT '+fields+' FROM geometry WHERE mode=? ORDER BY orig,dest,path_index'
    for left,right in zip_longest(main.execute(query,(mode,)),other.execute(query,(mode,))):
        require(left==right,'FULL_SAME_MODE_GEOMETRY_DIFFERS_USE_PER_DSEG_GEOMETRY_DESIGN')


def _cleanup_store(store,path,control):
    primary=sys.exc_info()[0] is not None
    errors=[]
    if store is not None:
        try:store.close()
        except Exception as exc:errors.append(exc)
    if path is not None:
        try:
            if path.exists():path.unlink()
        except Exception as exc:errors.append(exc)
    if errors:
        control.state.setdefault('cleanup_errors',[]).extend(exception_text(e) for e in errors)
        if not primary:raise errors[0]


def capture(visum,cfg,folder,control,opt,pre):
    report,source,zones,links,dsegs=pre
    two=parent_module('r1_15a2_two_mode_v238');supply=parent_module('r1_15a2_supply')
    # Original parser/collector preserved. Only resource accounting is specialized:
    # 0 means no artificial SQLite size cap, but actual free space is always checked.
    st=dict(two.DEFAULT_SETTINGS,page_size=opt['page_size'],min_free_disk_gib=opt['min_free_disk_gib'],
            max_store_gib=opt['max_store_gib'] or 1024.,
            max_parent_rows_per_dseg=opt['max_parent_rows_per_dseg'],
            max_geometry_rows_per_mode=opt['max_geometry_rows_per_mode'],
            com_retry_policy=retry_policy(opt))
    class CordonCollector(two.TwoModeRouteCollector):
        def check_resources(self,force=False):
            now=time.monotonic()
            if not force and now-self._last_resource_check<5:return
            self._last_resource_check=now
            dbpath=Path(self.route_db_path)
            # Count journals too; do not defer a real disk failure to SQLite.
            size=sum(p.stat().st_size for p in [dbpath,Path(str(dbpath)+'-wal'),
                     Path(str(dbpath)+'-journal')] if p.exists())
            if opt['max_store_gib'] and size>opt['max_store_gib']*1024**3:
                raise two.DesignStopRequested('SQLITE_STORAGE_BUDGET_EXCEEDED')
            if two.shutil.disk_usage(dbpath.parent).free<opt['min_free_disk_gib']*1024**3:
                raise two.DesignStopRequested('LOW_FREE_DISK_SPACE')
    path=folder/'p.sqlite';collector=None;checks=[];geometry_checks=[]
    parent_hash=canonical_hash({'network':report['network_sha256'],'matrices':report['matrix_audit']})
    matrix_dir=folder/'matrix_authority';mkdir(matrix_dir)
    try:
        collector=CordonCollector([],supply.SupplyPolicy(),parent_hash,links,path,st,control,geometry_only=True)
        groups=defaultdict(list)
        for ds in dsegs:groups[ds['mode']].append(ds)
        for group in groups.values():
            group.sort(key=lambda d:(d['norm_code'] not in ('NATIVE_CW','NATIVE_CW_NOT'),d['norm_code']))
        for mode in sorted(groups):
            for ds in groups[mode]:
                arr,authority=_matrix(ds,len(zones),control,opt)
                require(authority==report['matrix_audit'][ds['norm_code']],'MATRIX_CHANGED_SINCE_PREFLIGHT:'+ds['code'])
                write_npz(matrix_dir/(ds['norm_code']+'.npz'),values=arr,zone_nos=np.asarray(zones,dtype=np.int64))
                obj=_new_list(visum,'CreatePrTPathList',ds['code'],control,opt)
                rows=_bounded_rows(obj,two.PARENT_COLUMNS,st,control,opt,'PARENTS',dseg=ds['code'])
                parity=_add_parents_with_precision(collector,ds,mode,rows,authority,arr,zones,opt);checks.append(parity)
                write_json(folder/'OD_PARITY.json',checks)
                require(parity['status']=='PASS','PER_OD_PATH_MATRIX_PARITY_FAIL:'+ds['code'])
                del arr,rows,obj
            ds=groups[mode][0]
            obj=_new_list(visum,'CreatePrTPathLinkList',ds['code'],control,opt)
            collector.add_geometry(mode,_bounded_rows(obj,two.GEOMETRY_COLUMNS,st,control,opt,'GEOMETRY',dseg=ds['code']))
            del obj
            geometry_checks.append({'dseg':ds['norm_code'],'check':'FULL_REPRESENTATIVE'})
            if opt['full_geometry_check']:
                # Reuse the ORIGINAL hierarchy parser in a bounded temporary store.
                # This first-run proof is intentionally more expensive than samples.
                for ds in groups[mode][1:]:
                    scratch=folder/('proof_'+ds['norm_code']+'.sqlite');probe=None
                    try:
                        probe=CordonCollector([],supply.SupplyPolicy(),parent_hash,links,scratch,st,control,geometry_only=True)
                        parent_rows=collector.db.execute('SELECT g.orig,g.dest,g.path_index,v.volume FROM geometry g JOIN volumes v ON v.gid=g.gid WHERE v.dseg=? ORDER BY g.orig,g.dest,g.path_index',(ds['norm_code'],))
                        with np.load(matrix_dir/(ds['norm_code']+'.npz'),allow_pickle=False) as saved:
                            proof_parity=_add_parents_with_precision(probe,ds,mode,parent_rows,
                                report['matrix_audit'][ds['norm_code']],saved['values'],saved['zone_nos'],opt)
                        require(proof_parity['status']=='PASS','PROOF_STORE_PER_OD_PARITY_FAIL:'+ds['code'])
                        obj=_new_list(visum,'CreatePrTPathLinkList',ds['code'],control,opt)
                        probe.add_geometry(mode,_bounded_rows(obj,two.GEOMETRY_COLUMNS,st,control,opt,'FULL_GEOMETRY_CHECK',dseg=ds['code']))
                        _geometry_equal(collector.db,probe.db,mode)
                        geometry_checks.append({'dseg':ds['norm_code'],'check':'FULL_SAME_MODE_MATCH'})
                    finally:
                        _cleanup_store(probe,scratch,control)
        # Check for source changes, including assignment path volumes with stable OD.
        for ds in dsegs:
            _,authority=_matrix(ds,len(zones),control,opt)
            require(authority==report['matrix_audit'][ds['norm_code']],'MATRIX_CHANGED_DURING_CAPTURE:'+ds['code'])
            obj=_new_list(visum,'CreatePrTPathList',ds['code'],control,opt)
            returned={}
            com=parent_module('r1_15a2_com_compat')
            for row in _bounded_rows(obj,two.PARENT_COLUMNS,st,control,opt,'FINAL_PATH_READBACK',dseg=ds['code']):
                key=tuple(com.exact_int(v,'path key') for v in row[:3]);vol=com.finite_float(row[3],'Vol(AP)')
                require(key not in returned and vol>=0,'FINAL_PATH_KEYS_OR_VOLUMES_INVALID')
                returned[key]=vol
            hh=hashlib.sha256()
            for key,vol in sorted(returned.items()):hh.update(struct.pack('<IIId',*key,vol))
            require(hh.hexdigest()==collector.parents[ds['norm_code']]['keys_and_volumes_sha256'],'PATH_VOLUMES_CHANGED_DURING_CAPTURE:'+ds['code'])
        zones2,links2,nh2=_network(visum,control,opt)
        require(nh2==report['network_sha256'] and zones2==zones,'NETWORK_CHANGED_DURING_CAPTURE')
        dsegs2=_segments(visum,cfg,control,opt)
        require([(d['code'],d['mode']) for d in dsegs2]==[(d['code'],d['mode']) for d in dsegs],'DSEG_SCOPE_CHANGED_DURING_CAPTURE')
        api=parent_module('r1_15a2_live_api_audit')
        require(_call(lambda:api.current_version_file(visum),control,opt,'FINAL_CURRENT_VERSION')==source,
                'OPEN_MODEL_CHANGED_DURING_CAPTURE')
        sums={d:float(a['saved_path_volume_sum']) for d,a in collector.parents.items()}
        identity='FULL_SAME_MODE_GEOMETRY_COMPARED_THIS_CAPTURE' if opt['full_geometry_check'] else 'PROVISIONAL_REPRESENTATIVE_ONLY'
        collector.db.execute('UPDATE metadata SET value=? WHERE key=?',(identity,'geometry_identity'))
        from .parity import from_options
        parity_policy=from_options(opt).record()
        collector.db.execute('INSERT INTO metadata VALUES(?,?)',('path_matrix_parity_policy',json.dumps(parity_policy,sort_keys=True)))
        collector.db.execute('INSERT INTO metadata VALUES(?,?)',('capture_complete','true'))
        collector.db.commit()
        collector.close();collector=None
        evidence={'path_matrix_parity_policy':parity_policy,
            'path_matrix_parity_policy_sha256':canonical_hash(parity_policy),
            'schema':'CORDON_FROZEN_CACHE_EVIDENCE_V1','completed':True,'model_year':2025,
            'basis':'RPDI','category':'OA','origin':'VISUM_SAVED_PATHS','cache_sha256':sha256(path),
            'network_sha256':report['network_sha256'],'demand_sha256':canonical_hash(report['matrix_audit']),
            'dseg_totals':sums,'geometry_full_identity_proven':bool(opt['full_geometry_check']),
            'source_version':str(source),'model_year_authority':report['model_year_authority'],
            'period_authority':'USER_CONTRACT_RPDI_NOT_DERIVED_FROM_COM_PERIOD_METADATA',
            'external_od_parity_sha256':sha256(folder/'OD_PARITY.json'),
            'od_matrix_authorities':[{'dseg':ds['norm_code'],'path':'matrix_authority/'+ds['norm_code']+'.npz',
              'sha256':sha256(matrix_dir/(ds['norm_code']+'.npz'))} for ds in dsegs],
            'full_geometry_checks':geometry_checks,'assignment_freshness':'NOT_CERTIFIED_NO_NEW_ASSIGNMENT_RUN',
            'apply_permitted':False,'live_calibration_verified':False}
        write_json(folder/'SNAPSHOT_EVIDENCE.json',evidence)
        write_json(folder/'GEOMETRY_PROOF.json',{'full':opt['full_geometry_check'],'checks':geometry_checks})
        return path,folder/'SNAPSHOT_EVIDENCE.json'
    finally:
        if collector is not None:_cleanup_store(collector,None,control)


def _run_scoped(visum,*,action='PREFLIGHT',output_root=None,options=None,hotfix_evidence=None):
    require(action in ACTIONS,'UNSUPPORTED_VISUM_ACTION_APPLY_NOT_IMPLEMENTED')
    configured=read_json(ROOT/'CORDON_2025_STARTUP_OPTIONS.json') if (ROOT/'CORDON_2025_STARTUP_OPTIONS.json').is_file() else {}
    configured.update(options or {})
    opt=settings(configured);cfg=read_config(ROOT/'CORDON_2025_AGGRESSIVE_CONFIG.json')
    name='VISUM_'+action+'_'+uuid.uuid4().hex[:12]
    folder=None;control=None;opt_for_report=opt
    try:
        with RunSession(name,output_root) as session:
            folder=session.folder;session.start(cfg,{'config':ROOT/'CORDON_2025_AGGRESSIVE_CONFIG.json'})
            control=ReadControl(folder)
            write_json(folder/'STARTUP_OPTIONS.json',opt)
            write_json(folder/'COMBUSY_HOTFIX_ACTIVATION.json',hotfix_evidence or {})
            pre=preflight(visum,cfg,folder,control,opt)
            session.checkpoint('READONLY_PREFLIGHT_COMPLETE')
            result=pre[0]
            if action=='CAPTURE_DIAGNOSTICS':
                cache,evidence=capture(visum,cfg,folder,control,opt,pre)
                session.checkpoint('CAPTURE_CLOSED_AND_SEALED')
                from .__main__ import empirical_run
                result=empirical_run(folder,cfg,cache,evidence,propose=False)
                result.update(status='VISUM_SAVED_PATH_DIAGNOSTICS_COMPLETE',apply_permitted=False,
                    assignment_executed=False,calibration_ready=False,live_calibration_verified=False,
                    geometry_full_identity_proven=opt['full_geometry_check'])
            result=dict(result,output_directory=str(folder),action=action,telemetry_write_errors=control.telemetry_failures)
            result['com_busy_retry']=com_busy.telemetry(control,opt)
            write_json(folder/'COM_READ_RETRY.json',result['com_busy_retry'])
            write_json(folder/'00_RESULT.json',result)
            session.checkpoint('READONLY_VISUM_RUN_COMPLETE',completed=True)
            return result
    except BaseException as exc:
        import traceback
        if folder is not None and control is not None:
            try:write_json(folder/'COM_READ_RETRY.json',com_busy.telemetry(control,opt_for_report))
            except Exception:pass
        safe_failure_report(folder,exc,traceback_text=traceback.format_exc())
        raise


def run(visum,*,action='PREFLIGHT',output_root=None,options=None):
    require(action in ACTIONS,'UNSUPPORTED_VISUM_ACTION_APPLY_NOT_IMPLEMENTED')
    settings(options)  # Fail before even installing read-only runtime wrappers.
    with com_busy.parent_hotfix_scope() as proof:
        return _run_scoped(visum,action=action,output_root=output_root,
                           options=options,hotfix_evidence=proof)
