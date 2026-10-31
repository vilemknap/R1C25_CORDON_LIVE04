"""Streaming observation extension over a stable V24915 SQLite path snapshot.

The source is opened read-only. Geometry is decoded once per gid, never once per
station pair or segment. All counted values retain the exact demand segment.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import groupby
from pathlib import Path
from urllib.parse import quote
import hashlib
import json
import sqlite3
import struct
import sys
from contextlib import ExitStack
from .io import atomic_output, native_path
import numpy as np
from .common import write_npz
from .state import snapshot_semantics
from .io import mkdir
from .common import require, ContractError, sha256, parent_core, write_json, canonical_hash

METHODS=('ALL_ORDERED_UNIQUE_PAIRS','EXACT_TWO_HITS')
SCHEMA='R1_15A2_TWO_MODE_PATH_STORE_V238'

@dataclass
class Incidence:
    rows: list
    variables: list
    projection_base_variables: list
    q_current: np.ndarray
    operator: object                 # 15A2 SparseOperator: delta relative -> delta vehicles
    share_operator: object           # same structure: delta vehicles -> delta vehicles
    model: np.ndarray
    mutable: np.ndarray
    fixed: np.ndarray
    audit: dict

    def parent_contract(self):
        return {'profiles':self.rows,'variables':self.variables,
            'projection_base_variables':self.projection_base_variables,'q_current':self.q_current,
            'incidence':self.operator,'incidence_share':self.share_operator.values,
            'incidence_through':self.operator.values,
            'full_profile_model_from_paths':self.model,
            'mutable_profile_model_from_paths':self.mutable,
            'pair_observations':{'enabled':True,'observations':self.rows,
              'row_idx':self.operator.row_idx,'col_idx':self.operator.col_idx,'values':self.operator.values,
              'full_model':self.model,'mutable_model':self.mutable},
            'audit':self.audit}

    def save(self, folder):
        folder=Path(folder);mkdir(folder)
        write_npz(folder/'INCIDENCE.npz',row=self.operator.row_idx,col=self.operator.col_idx,
            through=self.operator.values,share=self.share_operator.values,q=self.q_current,
            model=self.model,mutable=self.mutable,fixed=self.fixed)
        # Explicit legacy save remains compatible with lazy shared PERF01 audit rows.
        from .perf01_codec import legacy_value, JsonRows
        audit = legacy_value(self.audit) if isinstance(self.audit.get("all_od_totals"), JsonRows) else self.audit
        write_json(folder/'INCIDENCE_METADATA.json',{'rows':self.rows,'variables':self.variables,
            'projection_base_variables':self.projection_base_variables,'audit':audit})

def station_pairs(hits, repeat_policy='EXCLUDE_FLAGGED'):
    require(repeat_policy in ('EXCLUDE_FLAGGED','FIRST_OCCURRENCE_DIAGNOSTIC'), 'UNKNOWN_REPEAT_POLICY')
    unique=list(dict.fromkeys(hits));repeat=len(unique)!=len(hits)
    pairs={m:() for m in METHODS}
    if repeat and repeat_policy=='EXCLUDE_FLAGGED':return pairs,True
    pairs['ALL_ORDERED_UNIQUE_PAIRS']=tuple((a,b) for i,a in enumerate(unique) for b in unique[i+1:])
    if not repeat and len(hits)==2:pairs['EXACT_TWO_HITS']=(tuple(hits),)
    return pairs,repeat

def _snapshot_open(path, evidence):
    p=Path(path).resolve()
    require(p.is_file(),'NO_2025_PATH_CACHE')
    require(not any(Path(str(p)+ext).exists() for ext in ('-wal','-shm','-journal')), 'LIVE_SQLITE_SIDECAR_PRESENT_COPY_COMPLETED_SNAPSHOT')
    require(evidence.get('completed') is True,'CACHE_SNAPSHOT_NOT_COMPLETE')
    require(evidence.get('model_year')==2025,'CACHE_MODEL_YEAR_NOT_2025')
    require(evidence.get('basis')=='RPDI' and evidence.get('category')=='OA','CACHE_BASIS_OR_CATEGORY_UNPROVEN')
    require(evidence.get('origin') in ('SYNTHETIC_TEST_FIXTURE','VISUM_SAVED_PATHS'), 'CACHE_ORIGIN_UNPROVEN')
    require(evidence.get('network_sha256') and evidence.get('demand_sha256'), 'CACHE_NETWORK_OR_DEMAND_ID_MISSING')
    digest=sha256(p);require(digest==evidence.get('cache_sha256'),'CACHE_SHA256_MISMATCH')
    con=sqlite3.connect('file:'+quote(str(p).replace(chr(92),'/'),safe='/:')+'?mode=ro',uri=True)
    con.execute('PRAGMA query_only=ON');con.execute('PRAGMA cache_size=-16384')
    try:
        require(con.execute('PRAGMA quick_check').fetchone()[0]=='ok','SQLITE_INTEGRITY_FAIL')
        required={'metadata':{'key','value'},'edges':{'eid','link_no','from_no','to_no'},
          'geometry':{'gid','mode','orig','dest','path_index','edge_ids','edge_count','sequence_sha256'},
          'volumes':{'gid','dseg','volume'},'segments':{'dseg','mode','audit_json'}}
        for name,cols in required.items():
            require(cols.issubset({x[1] for x in con.execute('PRAGMA table_info('+name+')')}),'SQLITE_SCHEMA_MISMATCH:'+name)
        require(dict(con.execute('SELECT key,value FROM metadata')).get('schema')==SCHEMA,'SQLITE_SCHEMA_VERSION_MISMATCH')
        require(not list(con.execute('PRAGMA foreign_key_check')), 'ORPHAN_SQLITE_REFERENCES')
        require(con.execute('SELECT 1 FROM volumes v LEFT JOIN geometry g ON g.gid=v.gid LEFT JOIN segments s ON s.dseg=v.dseg WHERE g.gid IS NULL OR s.dseg IS NULL LIMIT 1').fetchone() is None, 'ORPHAN_SQLITE_REFERENCES')
        return p,con,digest
    except BaseException:
        con.close();raise

def validate_roles(rows):
    seen={}
    for row in rows:
        pair=tuple(sorted((int(row['origin_station']),int(row['destination_station']))))
        role=row['role']
        require(role in ('CALIBRATION','VALIDATION','DIAGNOSTIC'), 'UNKNOWN_OBSERVATION_ROLE')
        require(pair not in seen or seen[pair]==role,'REVERSE_PAIR_CAL_VALID_LEAKAGE')
        seen[pair]=role

def build_from_snapshot(path, station_map, cfg, evidence, *, hits_output=None):
    if hits_output is not None:
        require(Path(hits_output).resolve() != Path(path).resolve(), 'OUTPUT_INPUT_COLLISION')
    core=parent_core()
    from .limits import numerical
    numeric=numerical(cfg)
    require(cfg.get('apply') is False,'V1_APPLY_FORBIDDEN')
    require(cfg.get('category')=='OA','V1_OA_ONLY')
    requested=list(cfg.get('selected_dsegs',[]))
    require(requested,'EXPLICIT_DSEG_SCOPE_REQUIRED')
    codes=[core.norm_code(x) for x in requested]
    require(len(set(codes))==len(codes),'DUPLICATE_DSEG_SCOPE')
    valid_families={'WORK','SERVICE','LONG','FOREIGN'}
    require(all(core.family_from_dseg(c) in valid_families and c.startswith(('NATIVE_','EXOG_EE_')) for c in codes),'UNVERIFIED_OA_DSEG_SCOPE')
    mut={core.norm_code(c) for c in cfg.get('mutable_dsegs',[])}
    require(mut.issubset(codes),'MUTABLE_DSEG_OUTSIDE_OBSERVATION_SCOPE')
    require(all(c.startswith('NATIVE_') and core.family_from_dseg(c) in ('WORK','SERVICE') for c in mut),'FROZEN_DSEG_ACTUATOR_FORBIDDEN')
    policy=cfg.get('mutable_relation_policy','BOTH_ENDPOINTS_ACTUATABLE')
    require(policy in ('ALL_MUTABLE_RELATIONS','BOTH_ENDPOINTS_ACTUATABLE'),'UNSUPPORTED_MUTABLE_RELATION_POLICY')
    zones=cfg.get('actuatable_zones')
    require(not mut or policy!='BOTH_ENDPOINTS_ACTUATABLE' or zones is not None,'ACTUATABLE_ZONE_AUTHORITY_MISSING')
    active=set(zones) if zones is not None else None
    p,db,digest=_snapshot_open(path,evidence)
    stream=None
    output_stack=ExitStack()
    try:
        meta=dict(db.execute('SELECT key,value FROM metadata'))
        state_audit=snapshot_semantics(evidence,cfg,meta)
        if cfg.get('actual_network_sha256') is not None:
            require(cfg['actual_network_sha256']==evidence['network_sha256'],'CACHE_NETWORK_IDENTITY_MISMATCH')
        segments={core.norm_code(c):(c,m,json.loads(a)) for c,m,a in db.execute('SELECT dseg,mode,audit_json FROM segments')}
        require(len(segments)==db.execute('SELECT COUNT(*) FROM segments').fetchone()[0],'CANONICAL_DSEG_COLLISION')
        require(set(codes).issubset(segments),'REQUIRED_DSEG_MISSING_FROM_CACHE')
        from r1_15a2_two_mode_v238 import EXPECTED_MODE_DSEGS
        require(all(c in EXPECTED_MODE_DSEGS.get(segments[c][1],()) for c in codes),'DSEG_MODE_AUTHORITY_MISMATCH')
        known_oa={c for c in segments if c.startswith(('NATIVE_','EXOG_EE_')) and core.family_from_dseg(c) in valid_families}
        require(not known_oa-set(codes),'OA_CACHE_SEGMENTS_OMITTED_FROM_SCOPE')
        # Explicit count audits catch removal of even a zero-volume segment/path row.
        for code in codes:
            original,_,a=segments[code]
            counts = [a[k] for k in ('path_rows', 'parent_rows', 'row_count') if k in a]
            require(all(not isinstance(v, bool) and float(v).is_integer() and v >= 0 for v in counts), 'INVALID_SEGMENT_COUNT_AUTHORITY:' + code)
            require(len(set(counts)) <= 1, 'CONFLICTING_SEGMENT_COUNT_AUTHORITY:' + code)
            expected = counts[0] if counts else None
            if expected is not None:
                require(int(expected)==db.execute('SELECT COUNT(*) FROM volumes WHERE dseg=?',(original,)).fetchone()[0], 'INCOMPLETE_SEGMENT_VOLUME_ROWS:'+code)
        edges={int(i):(int(ln),int(fr),int(to)) for i,ln,fr,to in db.execute('SELECT eid,link_no,from_no,to_no FROM edges')}
        require(len(edges)==len(set(edges.values())),'DUPLICATE_DIRECTIONAL_EDGE_IDENTITY')
        require(set(station_map).issubset(set(edges.values())),'MAPPING_EDGES_MISSING_FROM_CACHE')
        eid_station={eid:station_map[key] for eid,key in edges.items() if key in station_map}
        stations=sorted(set(station_map.values()));pairs=[(a,b) for a in stations for b in stations if a!=b]
        pair_index={key:i for i,key in enumerate(pairs)}
        totals={m:np.zeros(len(pairs)) for m in METHODS};mtotals={m:np.zeros(len(pairs)) for m in METHODS}
        per_dseg={m:{c:np.zeros(len(pairs)) for c in codes} for m in METHODS}
        entries={m:defaultdict(float) for m in METHODS};q=defaultdict(float);npaths=Counter();mutable_keys=set()
        metrics=Counter();dseg_vol=defaultdict(float);covered_vol=defaultdict(float);zero_inter=defaultdict(float)
        geometry_status=meta.get('geometry_identity','UNKNOWN')
        query=('SELECT g.gid,g.mode,g.orig,g.dest,g.path_index,g.edge_ids,g.edge_count,g.sequence_sha256,v.dseg,v.volume '
               'FROM geometry g JOIN volumes v ON v.gid=g.gid ORDER BY g.gid,v.dseg')
        if hits_output:
            import csv
            hp=Path(hits_output)
            stream=output_stack.enter_context(atomic_output(hp,newline='',encoding='utf-8'))
            writer=csv.writer(stream);writer.writerow(('gid','mode','orig','dest','path_index','station_hits','repeat_flag','excluded','edge_count'))
        for gid,group in groupby(db.execute(query),key=lambda r:r[0]):
            records=list(group);_,mode,o,d,pi,blob,count,seqhash,_,_=records[0]
            require(blob is not None and count is not None,'INCOMPLETE_NULL_GEOMETRY')
            require(len(blob)%4==0 and len(blob)//4==count,'INVALID_GEOMETRY_LENGTH')
            require(seqhash==hashlib.sha256(blob).hexdigest(),'GEOMETRY_HASH_MISMATCH')
            eids=struct.unpack('<%dI'%count,blob) if count else ()
            require(all(e in edges for e in eids),'UNKNOWN_GEOMETRY_EDGE')
            require(all(edges[a][2]==edges[b][1] for a,b in zip(eids,eids[1:])),'DISCONNECTED_SAVED_PATH')
            hits=[eid_station[e] for e in eids if e in eid_station]
            pr,repeat=station_pairs(hits,cfg.get('repeat_policy','EXCLUDE_FLAGGED'))
            excluded=repeat and cfg.get('repeat_policy','EXCLUDE_FLAGGED')=='EXCLUDE_FLAGGED'
            metrics['decoded_geometry']+=1;metrics['geometry_edge_count']+=count
            metrics['repeated_geometry']+=int(repeat);metrics['excluded_geometry']+=int(excluded)
            metrics['more_than_two_hits']+=int(len(hits)>2);metrics['zero_link_geometry']+=int(count==0)
            if stream:writer.writerow((gid,mode,o,d,pi,'>'.join(map(str,hits)),int(repeat),int(excluded),count))
            for rec in records:
                code=core.norm_code(rec[8]);v=float(rec[9])
                require(np.isfinite(v) and v>=0,'INVALID_SAVED_VOLUME')
                require(code in segments and segments[code][1]==mode,'SEGMENT_GEOMETRY_MODE_MISMATCH')
                if code not in codes:continue
                metrics['segment_path_rows']+=1;dseg_vol[code]+=v
                if count:covered_vol[code]+=v
                elif o!=d:zero_inter[code]+=v
                if excluded:metrics['excluded_segment_volume']+=v
                key=(code,int(o),int(d));q[key]+=v;npaths[key]+=1
                act=(code in mut and (policy=='ALL_MUTABLE_RELATIONS' or (o in active and d in active)))
                if act:mutable_keys.add(key)
                for meth,routepairs in pr.items():
                    for pair in routepairs:
                        ix=pair_index[pair];totals[meth][ix]+=v;per_dseg[meth][code][ix]+=v
                        if act:
                            mtotals[meth][ix]+=v
                            if v:entries[meth][(ix,key)]+=v
        expected_totals=evidence.get('dseg_totals')
        require(expected_totals is not None,'DSEG_VOLUME_PARITY_AUTHORITY_MISSING')
        normalized_totals={core.norm_code(c):float(v) for c,v in expected_totals.items()}
        require(len(normalized_totals)==len(expected_totals),'DUPLICATE_CANONICAL_DSEG_TOTAL')
        require(set(codes).issubset(normalized_totals),'DSEG_TOTAL_AUTHORITY_INCOMPLETE')
        for c in codes:
            require(np.isfinite(normalized_totals[c]) and normalized_totals[c]>=0,'INVALID_EXPECTED_VOLUME')
            require(abs(dseg_vol[c]-normalized_totals[c])<=max(numeric['internal_sum_atol'],numeric['internal_sum_rtol']*normalized_totals[c]),'DSEG_VOLUME_PARITY_FAIL:'+c)
        od_expected=evidence.get('od_totals')
        if od_expected is not None:
            em={(core.norm_code(r['dseg']),int(r['orig']),int(r['dest'])):float(r['volume']) for r in od_expected}
            require(len(em)==len(od_expected),'DUPLICATE_OD_AUTHORITY')
            require(set(em)==set(q),'OD_AUTHORITY_SUPPORT_MISMATCH')
            require(all(np.isfinite(em[k]) and abs(em[k]-v)<=max(numeric['internal_sum_atol'],numeric['internal_sum_rtol']*v) for k,v in q.items()),'OD_VOLUME_PARITY_FAIL')
        from .external_parity import check_matrix_authorities
        matrix_parity=check_matrix_authorities(p,evidence,q,codes,npaths)
        var_keys=sorted(k for k in mutable_keys if q[k]>0);var_index={key:i for i,key in enumerate(var_keys)}
        variables=[{'variable_index':i,'dseg_code':c,'family':core.family_from_dseg(c),'origin':o,'destination':d,'q_current':q[(c,o,d)],'path_count':npaths[(c,o,d)]} for i,(c,o,d) in enumerate(var_keys)]
        basevars=[{'dseg_code':c,'family':core.family_from_dseg(c),'origin':o,'destination':d,'q_current':v,'path_count':npaths[(c,o,d)]} for (c,o,d),v in sorted(q.items()) if c in mut]
        qvec=np.array([q[k] for k in var_keys])
        blocked=[]
        if evidence['origin']=='VISUM_SAVED_PATHS' and not state_audit['complete']:
            blocked.append('SEMANTIC_SNAPSHOT_NOT_SUPPLIED')
        if not evidence.get('geometry_full_identity_proven'):blocked.append('GEOMETRY_IDENTITY_UNAPPROVED')
        if od_expected is None and matrix_parity is None:blocked.append('PER_OD_EXTERNAL_VOLUME_PARITY_NOT_SUPPLIED')
        if metrics['excluded_geometry']:blocked.append('REPEATED_STATION_POLICY_DIAGNOSTIC')
        if sum(zero_inter.values())>0:blocked.append('POSITIVE_ZERO_LINK_INTERZONAL_REVIEW')
        contract={'mapping':sorted([*k,int(v)] for k,v in station_map.items()),'methods':METHODS,
            'repeat_policy':cfg.get('repeat_policy','EXCLUDE_FLAGGED'),'selected_dsegs':codes,
            'mutable_dsegs':sorted(mut),'mutable_relation_policy':policy,'actuatable_zones':sorted(active) if active is not None else None}
        audit={'mapping_sha256':canonical_hash(contract['mapping']),'incidence_contract_sha256':canonical_hash(contract),
               'status':'DIAGNOSTIC_PASS','origin':evidence['origin'],'cache_sha256':digest,
               'network_sha256':evidence['network_sha256'],'demand_sha256':evidence['demand_sha256'],
               'model_year':2025,'basis':'RPDI','category':'OA',
               'geometry_identity':geometry_status,'metrics':dict(metrics),'DSEG_VOLUME_PARITY':'PASS',
               'per_od_external_parity':'PASS' if od_expected is not None or matrix_parity is not None else 'NOT_SUPPLIED',
               'external_matrix_parity':matrix_parity,
               'dseg_volumes':dict(dseg_vol),'covered_volume_by_dseg':dict(covered_vol),
               'zero_link_interzonal_volume_by_dseg':dict(zero_inter),'selected_dsegs':codes,
               'mode_by_dseg':{c:segments[c][1] for c in codes},'blocked':blocked,
               'semantics_approved':False,'production_ready':False,'apply_permitted':False,
               'external_com_calls':0,'geometry_decode_policy':'ONCE_PER_GID',
               'all_od_totals':[{'dseg':c,'orig':o,'dest':d,'volume':v} for (c,o,d),v in sorted(q.items())]}
        result={}
        for meth in METHODS:
            triples=[(r,var_index[k],v) for (r,k),v in sorted(entries[meth].items()) if k in var_index and v]
            rr=np.array([t[0] for t in triples],dtype=np.int64);cc=np.array([t[1] for t in triples],dtype=np.int64);vv=np.array([t[2] for t in triples],dtype=float)
            op=core.SparseOperator(rr,cc,vv,len(pairs),len(var_keys))
            share=core.SparseOperator(rr,cc,vv/qvec[cc] if len(cc) else vv.copy(),len(pairs),len(var_keys))
            require(np.all(share.values>=0) and np.all(share.values<=1+1e-10),'PAIR_SHARE_OUT_OF_BOUNDS')
            require(np.allclose(op.forward(np.ones(len(var_keys))),mtotals[meth],atol=numeric['internal_sum_atol'],rtol=numeric['internal_sum_rtol']),'MUTABLE_PREDICTION_PARITY_FAIL')
            rows=[{'observation_type':'KORDON_PAIR','category':'OA','origin_station':a,'destination_station':b,
              'role':'DIAGNOSTIC','method':meth,'basis':'RPDI','model':float(totals[meth][i]),
              'per_dseg':{c:float(per_dseg[meth][c][i]) for c in codes}} for i,(a,b) in enumerate(pairs)]
            result[meth]=Incidence(rows,variables,basevars,qvec,op,share,totals[meth],mtotals[meth],totals[meth]-mtotals[meth],dict(audit,method=meth,nnz=len(vv),semantic_snapshot=state_audit,cross_run_cache_reuse=False))
        return result
    finally:
        primary = sys.exc_info()
        db.close()
        if primary[0] is not None:
            # Preserve the primary parsing error; failed diagnostics never publish.
            output_stack.__exit__(*primary)
        else:
            try:
                require(not any(Path(str(p)+ext).exists() for ext in ('-wal','-shm','-journal')), 'SOURCE_CACHE_SIDECAR_APPEARED_DURING_READ')
                require(sha256(p)==digest,'SOURCE_CACHE_CHANGED_DURING_READ')
            except BaseException:
                output_stack.__exit__(*sys.exc_info())
                raise
            output_stack.close()

def aggregate_observations(inc, targets, *, bidirectional=True, roles=None):
    """Aggregate algebra only, never infer survey axis orientation from symmetry."""
    core=parent_core();roles=roles or {};keys=[];index={};directed_to_row={}
    # Validate both declarations BEFORE coalescing directions; neither may disappear.
    validate_roles([{'origin_station':a,'destination_station':b,'role':role} for (a,b),role in roles.items()])
    for key, value in targets.items():
        require(not isinstance(value, (bool, np.bool_)), 'INVALID_OBSERVATION_TARGET:' + str(key))
        try:
            valid = np.isfinite(float(value)) and float(value) >= 0
        except (TypeError, ValueError, OverflowError):
            valid = False
        require(valid, 'INVALID_OBSERVATION_TARGET:' + str(key))
    for i,r in enumerate(inc.rows):
        pair=(r['origin_station'],r['destination_station'])
        key=tuple(sorted(pair)) if bidirectional else pair
        if key not in index:index[key]=len(keys);keys.append(key)
        directed_to_row[i]=index[key]
    rows=[];model=np.zeros(len(keys));mutable=model.copy()
    for key in keys:
        present = key in targets and (not bidirectional or (key[1],key[0]) in targets)
        y = float(targets[key]) if present else None
        if bidirectional and present:y += float(targets[(key[1],key[0])])
        role=roles.get(key,roles.get(tuple(sorted(key)),'DIAGNOSTIC'))
        require(present or role=='DIAGNOSTIC','MISSING_OBSERVATION_CANNOT_BE_CAL_OR_VALID')
        rows.append({'observation_type':'KORDON_PAIR','category':'OA','basis':'RPDI',
            'origin_station':key[0],'destination_station':key[1],'observed':y,
            'role':role,'aggregation':'BIDIRECTIONAL_SUM' if bidirectional else 'DIRECTED',
            'method':inc.audit['method'],'weight':1.0})
    validate_roles(rows)
    for old,new in directed_to_row.items():model[new]+=inc.model[old];mutable[new]+=inc.mutable[old]
    triples=defaultdict(float)
    for a,b,v in zip(inc.operator.row_idx,inc.operator.col_idx,inc.operator.values):triples[(directed_to_row[int(a)],int(b))]+=v
    rr=np.array([x[0] for x in sorted(triples)],dtype=np.int64);cc=np.array([x[1] for x in sorted(triples)],dtype=np.int64);vv=np.array([triples[x] for x in sorted(triples)])
    op=core.SparseOperator(rr,cc,vv,len(rows),len(inc.variables))
    sh=core.SparseOperator(rr,cc,vv/inc.q_current[cc] if len(cc) else vv.copy(),len(rows),len(inc.variables))
    for i,r in enumerate(rows):r['model']=float(model[i])
    return Incidence(rows,inc.variables,inc.projection_base_variables,inc.q_current,op,sh,model,mutable,model-mutable,
                     dict(inc.audit,aggregation='BIDIRECTIONAL_SUM' if bidirectional else 'DIRECTED'))

def check_epoch_support(inc, live_od_totals):
    """A support guard, NOT permission to treat linear reweighting as new assignment."""
    base={(r['dseg'],r['orig'],r['dest']):r['volume'] for r in inc.audit['all_od_totals']}
    for row in live_od_totals:
        key=(parent_core().norm_code(row['dseg']),int(row['orig']),int(row['dest']))
        val=float(row['volume']);require(np.isfinite(val) and val>=0,'INVALID_LIVE_OD')
        if val>0 and base.get(key,0)<=0:raise ContractError('PATH_EPOCH_NEW_POSITIVE_OD_REQUIRES_REENUMERATION')
    return {'support_guard':'PASS','new_assignment_verified':False,'prediction_label':'LINEARIZED_ONLY'}
