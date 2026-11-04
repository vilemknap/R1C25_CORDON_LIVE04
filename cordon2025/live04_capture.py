"""LIVE04.6 trial capture (overlay of the LIVE01-protected visum_startup.capture).

visum_startup.py stays byte-identical (LIVE01 protected source).  This module is the
same capture with two speedups, everything else (per-OD parity, matrix/path/network
drift checks, final readback) unchanged:

* geometry_proof='STATION_LINK_VOLUME_CROSSCHECK': the representative DSeg's full
  path-link hierarchy is still read for every mode; the other same-mode DSegs are
  proven by VOLVEH_DSEG(code,AP) on the 32 station links instead of re-reading the
  whole hierarchy per DSeg.  Any mismatch / unreadable attribute -> the original
  full proof in the same capture (fail-closed as before).
* the FINAL_PATH_READBACK digests are returned as the path-volume signature, so the
  evaluator does not read all parent lists a third time.
"""
from __future__ import annotations
from collections import defaultdict
from pathlib import Path
import hashlib
import json
import struct
import sys
import time
import numpy as np
from .common import ROOT, require, parent_module, canonical_hash
from .io import write_json, write_npz, sha256, mkdir, exception_text
from .authority import mapping
from .visum_startup import (retry_policy, _call, _bounded_rows, _columns, _network, _segments, _matrix, _new_list,
                            _add_parents_with_precision, _geometry_equal, _cleanup_store)


STATION_CROSSCHECK='STATION_LINK_VOLUME_CROSSCHECK'
GEOMETRY_PROOF_MODES=('FULL',STATION_CROSSCHECK)
STOP_EXCEPTIONS=('UserStopRequested','TimeBudgetReached','DesignStopRequested','KeyboardInterrupt')
CROSSCHECK_ATOL=1.0
CROSSCHECK_RTOL=1e-3


def _station_link_volumes(visum,dsegs,control,opt,cache):
    """Visum VOLVEH_DSEG(code,AP) on the station links, one bulk read per DSeg."""
    com=parent_module('r1_15a2_com_compat')
    stations,_=mapping(ROOT/'data/audited/STATION_MAPPING.csv')
    missing=[d for d in dsegs if d['norm_code'] not in cache.get('dsegs',{})]
    if missing:
        collection=_call(lambda:visum.Net.Links,control,opt,'NET_LINKS_PROPERTY')
        names=('NO','FROMNODENO','TONODENO')+tuple('VOLVEH_DSEG(%s,AP)'%d['code'] for d in missing)
        rows=_columns(collection,names,control,opt)
        found=set()
        for r in rows:
            key=tuple(com.exact_int(r[k],k) for k in ('NO','FROMNODENO','TONODENO'))
            if key not in stations:continue
            found.add(key)
            for d in missing:
                cache.setdefault('dsegs',{}).setdefault(d['norm_code'],{})[key]=com.finite_float(
                    r['VOLVEH_DSEG(%s,AP)'%d['code']],'VOLVEH_DSEG')
        require(found==set(stations),'CROSSCHECK_STATION_LINKS_NOT_IN_NETWORK')
    return stations,{d['norm_code']:cache['dsegs'][d['norm_code']] for d in dsegs}


def _all_link_volumes(visum,dsegs,control,opt,cache):
    """Visum VOLVEH_DSEG(code,AP) on every network link (bulk reads)."""
    com=parent_module('r1_15a2_com_compat')
    missing=[d for d in dsegs if d['norm_code'] not in cache.get('all',{})]
    if missing:
        collection=_call(lambda:visum.Net.Links,control,opt,'NET_LINKS_PROPERTY')
        names=('NO','FROMNODENO','TONODENO')+tuple('VOLVEH_DSEG(%s,AP)'%d['code'] for d in missing)
        rows=_columns(collection,names,control,opt)
        for r in rows:
            key=tuple(com.exact_int(r[k],k) for k in ('NO','FROMNODENO','TONODENO'))
            for d in missing:
                cache.setdefault('all',{}).setdefault(d['norm_code'],{})[key]=com.finite_float(
                    r['VOLVEH_DSEG(%s,AP)'%d['code']],'VOLVEH_DSEG')
    return {d['norm_code']:cache['all'][d['norm_code']] for d in dsegs}


def _station_crosscheck(visum,db,dsegs,mode,control,opt,cache):
    """Station-link volume implied by the representative geometry vs Visum, per DSeg."""
    import zlib
    from array import array
    stations,visum_vol=_station_link_volumes(visum,dsegs,control,opt,cache)
    eids={(int(n),int(f),int(t)):int(e) for e,n,f,t in db.execute('SELECT eid,link_no,from_no,to_no FROM edges')}
    require(set(stations)<=set(eids),'CROSSCHECK_STATION_EDGES_MISSING')
    mode_gids={int(g) for (g,) in db.execute('SELECT gid FROM geometry WHERE mode=?',(mode,))}
    hits={}
    for key in stations:
        pairs=[]
        for (blob,) in db.execute('SELECT pairs FROM edge_postings WHERE eid=? ORDER BY chunk',(eids[key],)):
            a=array('I');a.frombytes(zlib.decompress(blob))
            if sys.byteorder!='little':a.byteswap()
            require(len(a)%2==0,'CROSSCHECK_CORRUPT_POSTING')
            pairs.extend((a[i],a[i+1]) for i in range(0,len(a),2) if a[i] in mode_gids)
        hits[key]=pairs
    rows=[];worst=0.0;status='PASS';positive=0.0
    for d in dsegs:
        vol={int(g):float(v) for g,v in db.execute('SELECT gid,volume FROM volumes WHERE dseg=?',(d['norm_code'],))}
        for key in sorted(stations):
            pred=float(sum(n*vol.get(g,0.0) for g,n in hits[key]))
            npos=sum(1 for g,n in hits[key] if vol.get(g,0.0)>0)
            actual=visum_vol[d['norm_code']][key]
            # 1 veh + Visum 0.001 path-volume lattice (<=0.0005 per positive path) + 0.1 %
            diff=abs(pred-actual);tol=CROSSCHECK_ATOL+0.0005*npos+CROSSCHECK_RTOL*max(abs(pred),abs(actual))
            positive+=abs(actual)
            worst=max(worst,diff/tol if tol else 0.0)
            ok=diff<=tol
            if not ok:status='MISMATCH'
            rows.append({'dseg':d['norm_code'],'link':list(key),'station':stations[key],'predicted':round(pred,4),
                         'visum':round(actual,4),'abs_diff':round(diff,4),'tolerance':round(tol,4),'pass':ok})
    if status=='PASS' and positive<=0.0:status='NO_STATION_VOLUME'
    bad=[r for r in rows if not r['pass']]
    return {'mode':mode,'status':status,'dsegs':[d['norm_code'] for d in dsegs],'representative':dsegs[0]['norm_code'],
            'station_links':len(stations),'compared':len(rows),'failed':len(bad),'worst_diff_to_tolerance':round(worst,6),
            'atol':CROSSCHECK_ATOL,'rtol':CROSSCHECK_RTOL,'attribute':'VOLVEH_DSEG(<code>,AP)',
            'failures':bad[:40]}


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
    proof_mode=str(opt.get('geometry_proof') or 'FULL');crosschecks=[];link_volume_cache={}
    epoch_cfg=opt.get('geometry_epoch') or None;epoch_records=[];epoch_reused=[];epoch_fresh=[]
    timing=defaultdict(float);t_phase=time.monotonic()
    def lap(name):
        nonlocal t_phase
        now=time.monotonic();timing[name]+=now-t_phase;t_phase=now
    parent_hash=canonical_hash({'network':report['network_sha256'],'matrices':report['matrix_audit']})
    matrix_dir=folder/'matrix_authority';mkdir(matrix_dir)
    try:
        collector=CordonCollector([],supply.SupplyPolicy(),parent_hash,links,path,st,control,geometry_only=True)
        edge_dictionary=canonical_hash(list(collector.edge_keys[1:]))
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
            lap('parents_and_matrices')
            ds=groups[mode][0]
            replayed=False
            if epoch_cfg and proof_mode==STATION_CROSSCHECK and opt['full_geometry_check']:
                # LIVE04.7 geometry epoch (see live04_epoch): replay only after an
                # all-link, all-DSeg volume proof against the CURRENT assignment.
                from . import live04_epoch as epm
                ok,why=epm.usable(epoch_cfg['dir'],mode,report['network_sha256'],edge_dictionary,
                                  collector.mode_audits[mode]['parent_keys_sha256'],epoch_cfg['max_reuse'])
                rec={'mode':mode,'usable':ok,'reason':why}
                if ok:
                    try:
                        codes=[d['norm_code'] for d in groups[mode]]
                        pred,npos,ekeys=epm.implied_link_volumes(epoch_cfg['dir'],collector.db,mode,codes)
                        rec.update(epm.all_link_crosscheck(pred,npos,ekeys,
                                   _all_link_volumes(visum,groups[mode],control,opt,link_volume_cache),codes))
                        del pred,npos
                    except Exception as exc:
                        if type(exc).__name__ in STOP_EXCEPTIONS:raise
                        rec.update(status='UNAVAILABLE',error=exception_text(exc)[:500])
                    lap('geometry_epoch_crosscheck')
                    if rec.get('status')=='PASS':
                        collector.add_geometry(mode,epm.replay_rows(epoch_cfg['dir'],mode))
                        replayed=True;epoch_reused.append(mode)
                        geometry_checks.extend({'dseg':d['norm_code'],'check':'EPOCH_REPLAY_ALL_LINK_VOLUME_MATCH'}
                                               for d in groups[mode])
                        lap('geometry_epoch_replay')
                epoch_records.append(rec);write_json(folder/'GEOMETRY_EPOCH_CHECK.json',epoch_records)
            if replayed:
                continue
            epoch_fresh.append(mode)
            obj=_new_list(visum,'CreatePrTPathLinkList',ds['code'],control,opt)
            collector.add_geometry(mode,_bounded_rows(obj,two.GEOMETRY_COLUMNS,st,control,opt,'GEOMETRY',dseg=ds['code']))
            del obj
            geometry_checks.append({'dseg':ds['norm_code'],'check':'FULL_REPRESENTATIVE'})
            lap('geometry_representative')
            need_full=bool(opt['full_geometry_check']) and len(groups[mode])>1
            if need_full and proof_mode==STATION_CROSSCHECK:
                # LIVE04.6: same-mode DSegs already share the exact parent key set
                # (FULL_PARENT_KEYS_DIFFER otherwise).  Instead of re-reading the
                # whole link hierarchy per DSeg, compare every DSeg's Visum link
                # volume on the 32 station links with the volume implied by the
                # representative geometry.  Any doubt -> the full proof below.
                try:
                    xc=_station_crosscheck(visum,collector.db,groups[mode],mode,control,opt,link_volume_cache)
                except Exception as exc:
                    if type(exc).__name__ in STOP_EXCEPTIONS:raise
                    xc={'mode':mode,'status':'UNAVAILABLE','error':exception_text(exc)[:500]}
                crosschecks.append(xc);write_json(folder/'GEOMETRY_CROSSCHECK.json',crosschecks)
                lap('geometry_station_crosscheck')
                if xc['status']=='PASS':
                    geometry_checks.extend({'dseg':d['norm_code'],'check':'STATION_LINK_VOLUME_MATCH'}
                                           for d in groups[mode][1:])
                    need_full=False
                else:
                    xc['fallback']='FULL_SAME_MODE_GEOMETRY_PROOF'
                    write_json(folder/'GEOMETRY_CROSSCHECK.json',crosschecks)
            if need_full:
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
                lap('geometry_full_proof')
        # Check for source changes, including assignment path volumes with stable OD.
        final_signature={}
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
            # LIVE04.6: identical digest protocol to live02_evaluation.path_volume_signature
            # (same COM row order, same sum), so the evaluator needs no 3rd parent read.
            final_signature[ds['norm_code']]={'paths':len(returned),'volume_sum':float(sum(returned.values())),
                                              'keys_and_volumes_sha256':hh.hexdigest()}
        zones2,links2,nh2=_network(visum,control,opt)
        require(nh2==report['network_sha256'] and zones2==zones,'NETWORK_CHANGED_DURING_CAPTURE')
        dsegs2=_segments(visum,cfg,control,opt)
        require([(d['code'],d['mode']) for d in dsegs2]==[(d['code'],d['mode']) for d in dsegs],'DSEG_SCOPE_CHANGED_DURING_CAPTURE')
        api=parent_module('r1_15a2_live_api_audit')
        require(_call(lambda:api.current_version_file(visum),control,opt,'FINAL_CURRENT_VERSION')==source,
                'OPEN_MODEL_CHANGED_DURING_CAPTURE')
        sums={d:float(a['saved_path_volume_sum']) for d,a in collector.parents.items()}
        lap('final_readback')
        crosschecked=any(c.get('check')=='STATION_LINK_VOLUME_MATCH' for c in geometry_checks)
        if not opt['full_geometry_check']:identity='PROVISIONAL_REPRESENTATIVE_ONLY'
        elif epoch_reused:identity='EPOCH_REPLAY_ALL_LINK_VOLUME_CROSSCHECKED_THIS_CAPTURE'
        elif crosschecked:identity='STATION_LINK_VOLUME_CROSSCHECKED_THIS_CAPTURE'
        else:identity='FULL_SAME_MODE_GEOMETRY_COMPARED_THIS_CAPTURE'
        collector.db.execute('UPDATE metadata SET value=? WHERE key=?',(identity,'geometry_identity'))
        from .parity import from_options
        parity_policy=from_options(opt).record()
        collector.db.execute('INSERT INTO metadata VALUES(?,?)',('path_matrix_parity_policy',json.dumps(parity_policy,sort_keys=True)))
        collector.db.execute('INSERT INTO metadata VALUES(?,?)',('capture_complete','true'))
        collector.db.commit()
        mode_keys={m:{'parent_keys_sha256':a['parent_keys_sha256']} for m,a in collector.mode_audits.items()}
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
            'geometry_identity_basis':identity,'geometry_proof_mode':proof_mode,
            'final_path_volume_signature':final_signature,
            'geometry_epoch':{'enabled':bool(epoch_cfg),'reused_modes':epoch_reused,'fresh_modes':epoch_fresh,
                              'checks':epoch_records,'edge_dictionary_sha256':edge_dictionary,
                              'mode_audits':mode_keys},
            'geometry_station_crosschecks':crosschecks,
            'capture_timing_seconds':{k:round(v,3) for k,v in timing.items()},
            'apply_permitted':False,'live_calibration_verified':False}
        write_json(folder/'SNAPSHOT_EVIDENCE.json',evidence)
        write_json(folder/'GEOMETRY_PROOF.json',{'full':opt['full_geometry_check'],'checks':geometry_checks,
                   'identity':identity,'station_crosschecks':crosschecks})
        write_json(folder/'CAPTURE_TIMING.json',{k:round(v,3) for k,v in timing.items()})
        return path,folder/'SNAPSHOT_EVIDENCE.json'
    finally:
        if collector is not None:_cleanup_store(collector,None,control)
