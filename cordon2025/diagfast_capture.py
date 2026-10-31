"""Narrow FAST capture fork. Only same-mode proof sink differs from pinned legacy.
Generated from visum_startup.capture at development time, NOT evaluated at runtime.
No change to representative geometry, parent data, final readback or mathematics.
"""
from pathlib import Path
from collections import defaultdict
import hashlib,json,time,struct
import numpy as np
from .common import parent_module,require,canonical_hash
from .io import mkdir
from . import visum_startup as legacy
from .diagfast_geometry import verify_same_mode,SCHEMA,close_reference

def write_json(*a,**k):return legacy.write_json(*a,**k)
def write_npz(*a,**k):return legacy.write_npz(*a,**k)
def sha256(*a,**k):return legacy.sha256(*a,**k)

def _matrix(*a,**k):return legacy._matrix(*a,**k)
def _new_list(*a,**k):return legacy._new_list(*a,**k)
def _bounded_rows(*a,**k):return legacy._bounded_rows(*a,**k)
def _add_parents_with_precision(*a,**k):return legacy._add_parents_with_precision(*a,**k)
def _network(*a,**k):return legacy._network(*a,**k)
def _segments(*a,**k):return legacy._segments(*a,**k)
def _call(*a,**k):return legacy._call(*a,**k)
def _cleanup_store(*a,**k):return legacy._cleanup_store(*a,**k)
retry_policy=legacy.retry_policy

def capture(visum,cfg,folder,control,opt,pre,*,telemetry):
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
            audit=collector.mode_audits[mode]
            geometry_checks.append({'dseg':ds['norm_code'],'check':'FULL_REPRESENTATIVE',
                'verification':'ORIGINAL_COLLECTOR_FULL','mode':mode,
                'geometry_routes':audit['geometry_routes'],
                'geometry_link_children':audit['geometry_link_children'],
                'geometry_raw_rows':audit['geometry_raw_rows'],
                'representative_geometry_sha256':audit['representative_geometry_sha256']})
            if opt['full_geometry_check']:
                # Original main parent import already proved keys and per-OD parity.
                # Compare every same-mode geometry against the exact representative.
                for ds in groups[mode][1:]:
                    obj=_new_list(visum,'CreatePrTPathLinkList',ds['code'],control,opt)
                    try:
                        proof=verify_same_mode(collector,mode,ds['norm_code'],
                            _bounded_rows(obj,two.GEOMETRY_COLUMNS,st,control,opt,
                                'FULL_GEOMETRY_CHECK',dseg=ds['code']),telemetry)
                        geometry_checks.append(proof)
                    finally:
                        del obj
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
        close_reference(collector,control)
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
        write_json(folder/'GEOMETRY_PROOF.json',{'schema':SCHEMA,'full':opt['full_geometry_check'],'checks':geometry_checks})
        return path,folder/'SNAPSHOT_EVIDENCE.json'
    finally:
        if collector is not None:
            close_reference(collector,control)
            _cleanup_store(collector,None,control)
