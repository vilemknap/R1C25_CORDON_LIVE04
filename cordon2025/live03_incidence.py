"""LIVE03 path incidence: the unchanged LIVE01 streaming build extended by the
survey semantics (FIRST_LAST + C17 station rows) and the frozen share operator.

cordon2025/incidence.py is a protected LIVE01 source (BASE_SOURCE_MANIFEST) and
stays byte-identical; this module reuses its helpers (_snapshot_open,
station_pairs, Incidence, aggregate_observations) and contains an extended copy
of build_from_snapshot.  With cfg['enumeration_methods'] absent the result is
identical to incidence.build_from_snapshot (test_live03 checks parity).
"""
from __future__ import annotations
from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import groupby
from pathlib import Path
import hashlib
import json
import struct
import sys
from contextlib import ExitStack
import numpy as np
from .io import atomic_output
from .state import snapshot_semantics
from .common import require, parent_core, canonical_hash, sha256
from .incidence import (METHODS, Incidence, station_pairs, _snapshot_open, aggregate_observations)  # noqa: F401

FIRST_LAST='FIRST_LAST'
EXTENDED_METHODS=METHODS+(FIRST_LAST,)
C17_STATION=17
PROFILE_STATION=18   # LIVE04.9: station profile row (all crossings at s); LIVE04.10: side A of station s
PROFILE_STATION_B=19 # LIVE04.10: side B of station s (directional profiles)
PROFILE_IDS=(PROFILE_STATION,PROFILE_STATION_B)
DIRECTIONAL='DIRECTIONAL'


def station_sides(station_map):
    """LIVE04.10: directed station edge key -> side 0/1 (A/B = sorted (link_no, from_no, to_no) per station)."""
    by=defaultdict(list)
    for key,s in station_map.items():
        by[int(s)].append(tuple(int(x) for x in key))
    require(all(len(v)==2 for v in by.values()),'LIVE04_PROFILE_SIDES_NEED_TWO_EDGES_PER_STATION')
    out={}
    for s,keys in by.items():
        for i,k in enumerate(sorted(keys)):
            out[k]=i
    return out


def profile_mode(value):
    require(value in (False,True,DIRECTIONAL),'LIVE04_PROFILE_ROW_MODE')
    return value


def first_last_contributions(hits, station_rows=True, profile_rows=False, sides=None):
    """Survey-equivalent contributions of one saved path (row key, multiplicity).

    * no cordon hit                -> nothing
    * one hit at s                 -> (s, C17) x1   (isolated detection)
    * first != last                -> (first, last) x1, intermediate hits ignored
    * first == last (cyclic)       -> (s, C17) x2   (entry + exit crossing at s)
    Units of the C17 row are station crossings.
    LIVE04.9 profile_rows=True: additionally (s, PROFILE) x(number of hits at s) for
    EVERY hit (intermediate hits included) = the station link volume.
    LIVE04.10 profile_rows='DIRECTIONAL': (s, 18) / (s, 19) per station side
    (sides[i] = 0/1 of hit i) = the volume of each directed station edge.
    """
    if not hits:
        return ()
    prof = ()
    if profile_rows == DIRECTIONAL:
        require(sides is not None and len(sides) == len(hits), 'LIVE04_PROFILE_SIDES_MISSING')
        c = Counter(zip(hits, sides))
        prof = tuple(((s, PROFILE_IDS[k]), float(c[(s, k)])) for s, k in sorted(c))
    elif profile_rows:
        c = Counter(hits)
        prof = tuple(((s, PROFILE_STATION), float(c[s])) for s in sorted(c))
    first, last = hits[0], hits[-1]
    if len(hits) >= 2 and first != last:
        return (((first, last), 1.0),) + prof
    if not station_rows:
        return prof
    return (((first, C17_STATION), 1.0 if len(hits) == 1 else 2.0),) + prof


def side_contexts(hits, sides):
    """LIVE04.10 direction evidence of one path: consecutive hits at different stations.
    (s, side, 'DEP', t) at the earlier station s, (t, side, 'ARR', s) at the later one."""
    out = []
    for i in range(len(hits) - 1):
        a, b = hits[i], hits[i + 1]
        if a != b:
            out.append((a, sides[i], 'DEP', b))
            out.append((b, sides[i + 1], 'ARR', a))
    return out


@dataclass
class FrozenShare:
    """Row volume per unit OD demand on the CURRENT saved paths (all dsegs, all OD).

    model_row = sum_k share_k * Q[dseg_k, orig_k, dest_k].  Exact for the current
    assignment; a prediction for new demand only under frozen route choice.
    ODs whose current volume is zero have no route shares (``unsupported``).
    """
    row: np.ndarray
    dseg: np.ndarray
    orig: np.ndarray
    dest: np.ndarray
    share: np.ndarray
    codes: tuple
    n_rows: int
    supported_od: dict               # dseg code -> set((orig, dest)) with q>0

    def predict(self, matrices, zone_nos):
        """matrices: {dseg code: ndarray[n,n] on zone_nos axis} -> row vector."""
        zone_nos = np.asarray(zone_nos, dtype=np.int64)
        cache = self.__dict__.get('_axis_cache')
        if cache is None or not np.array_equal(cache[0], zone_nos):
            order = np.argsort(zone_nos); sorted_nos = zone_nos[order]
            def index(nos):
                pos = np.searchsorted(sorted_nos, nos)
                require(np.all(pos < len(sorted_nos)) and np.all(sorted_nos[np.minimum(pos, len(sorted_nos)-1)] == nos), 'FROZEN_SHARE_ZONE_AXIS_MISMATCH')
                return order[pos]
            cache = (zone_nos.copy(), index(self.orig), index(self.dest))
            self.__dict__['_axis_cache'] = cache
        oi, di = cache[1], cache[2]
        q = np.zeros(len(self.share))
        for k, code in enumerate(self.codes):
            sel = self.dseg == k
            if np.any(sel):
                require(code in matrices, 'FROZEN_SHARE_MATRIX_MISSING:' + code)
                q[sel] = np.asarray(matrices[code], dtype=float)[oi[sel], di[sel]]
        return np.bincount(self.row, weights=self.share * q, minlength=self.n_rows)


def _supported(q, codes):
    out = {c: set() for c in codes}
    for (c, o, d), v in q.items():
        if v > 0 and c in out:
            out[c].add((int(o), int(d)))
    return out


def _frozen_share(arrays, q, codes, n_rows, totals, numeric, supported):
    row, dseg, orig, dest = (np.frombuffer(a, dtype=np.int32).astype(np.int64) for a in arrays[:4])
    vol = np.frombuffer(arrays[4], dtype=float).copy()
    # Combine duplicate (row, OD) contributions (several paths of one OD on one row).
    if len(row):
        key = np.stack([row, dseg, orig, dest], axis=1)
        uniq, inv = np.unique(key, axis=0, return_inverse=True)
        vol_u = np.bincount(inv.ravel(), weights=vol, minlength=len(uniq))
    else:
        uniq = np.zeros((0, 4), dtype=np.int64); vol_u = vol
    q_u = np.array([q[(codes[int(k)], int(o), int(d))] for k, o, d in uniq[:, 1:]], dtype=float)
    require(np.all(q_u > 0), 'FROZEN_SHARE_ZERO_OD_WITH_POSITIVE_PATH_VOLUME')
    fz = FrozenShare(uniq[:, 0].copy(), uniq[:, 1].copy(), uniq[:, 2].copy(), uniq[:, 3].copy(),
                     vol_u / q_u if len(uniq) else vol_u, tuple(codes), int(n_rows), supported)
    recon = np.bincount(fz.row, weights=fz.share * q_u, minlength=n_rows) if len(uniq) else np.zeros(n_rows)
    require(np.allclose(recon, totals, atol=numeric['internal_sum_atol'], rtol=numeric['internal_sum_rtol']), 'FROZEN_SHARE_RECONSTRUCTION_FAIL')
    return fz


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
    methods=tuple(cfg.get('enumeration_methods') or METHODS)
    require(set(methods).issubset(EXTENDED_METHODS) and len(set(methods))==len(methods),'UNKNOWN_ENUMERATION_METHOD')
    station_rows=bool(cfg.get('first_last_station_rows',True))
    profile_rows=profile_mode(cfg.get('first_last_profile_rows',False))
    full_share=tuple(cfg.get('full_share_methods') or ())
    require(set(full_share).issubset(methods),'FULL_SHARE_METHOD_NOT_ENUMERATED')
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
        require(C17_STATION not in stations and not set(PROFILE_IDS)&set(stations),'C17_ID_COLLIDES_WITH_STATION')
        side_of=station_sides(station_map) if profile_rows==DIRECTIONAL else {}
        eid_side={eid:side_of[key] for eid,key in edges.items() if key in side_of}
        ctx_vol=defaultdict(float)
        keys_by={m:list(pairs) for m in methods}
        if FIRST_LAST in methods and station_rows:
            keys_by[FIRST_LAST]=list(pairs)+[(s,C17_STATION) for s in stations]
        if FIRST_LAST in methods and profile_rows:
            keys_by[FIRST_LAST]=keys_by[FIRST_LAST]+([(s,PROFILE_STATION) for s in stations] if profile_rows!=DIRECTIONAL else
                                                     [(s,p) for s in stations for p in PROFILE_IDS])
        index_by={m:{key:i for i,key in enumerate(keys_by[m])} for m in methods}
        totals={m:np.zeros(len(keys_by[m])) for m in methods};mtotals={m:np.zeros(len(keys_by[m])) for m in methods}
        per_dseg={m:{c:np.zeros(len(keys_by[m])) for c in codes} for m in methods}
        code_index={c:i for i,c in enumerate(codes)}
        from array import array
        fs={m:(array('i'),array('i'),array('i'),array('i'),array('d')) for m in full_share}
        entries={m:defaultdict(float) for m in methods};q=defaultdict(float);npaths=Counter();mutable_keys=set()
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
            sides=[eid_side[e] for e in eids if e in eid_station] if eid_side else None
            ctx=side_contexts(hits,sides) if sides else ()
            pr,repeat=station_pairs(hits,cfg.get('repeat_policy','EXCLUDE_FLAGGED'))
            # (row index, multiplicity) per method; legacy methods keep their exclusion rule.
            contrib={m:tuple((index_by[m][pair],1.0) for pair in pr[m]) for m in methods if m in pr}
            if FIRST_LAST in methods:
                contrib[FIRST_LAST]=tuple((index_by[FIRST_LAST][k],w) for k,w in first_last_contributions(hits,station_rows,profile_rows,sides))
                metrics['first_last_max_station_multiplicity']=max(metrics['first_last_max_station_multiplicity'],max(Counter(hits).values()) if hits else 0)
                metrics['first_last_single_hit_geometry']+=int(len(hits)==1)
                metrics['first_last_cyclic_geometry']+=int(len(hits)>=2 and hits[0]==hits[-1])
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
                for cx in ctx:ctx_vol[cx]+=v
                if count:covered_vol[code]+=v
                elif o!=d:zero_inter[code]+=v
                if excluded:metrics['excluded_segment_volume']+=v
                key=(code,int(o),int(d));q[key]+=v;npaths[key]+=1
                act=(code in mut and (policy=='ALL_MUTABLE_RELATIONS' or (o in active and d in active)))
                if act:mutable_keys.add(key)
                for meth,items in contrib.items():
                    for ix,w in items:
                        vw=v*w;totals[meth][ix]+=vw;per_dseg[meth][code][ix]+=vw
                        if act:
                            mtotals[meth][ix]+=vw
                            if v:entries[meth][(ix,key)]+=vw
                        if meth in fs and v:
                            a=fs[meth];a[0].append(ix);a[1].append(code_index[code]);a[2].append(int(o));a[3].append(int(d));a[4].append(vw)
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
        contract={'mapping':sorted([*k,int(v)] for k,v in station_map.items()),'methods':methods,
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
               'profile_sides':{str(s):[list(k) for k,_ in sorted(((k,i) for k,i in side_of.items() if station_map[k]==s),key=lambda x:x[1])] for s in stations} if side_of else None,
               'profile_side_contexts':[[s,sd,role,t,float(v)] for (s,sd,role,t),v in sorted(ctx_vol.items())] if side_of else None,
               'all_od_totals':[{'dseg':c,'orig':o,'dest':d,'volume':v} for (c,o,d),v in sorted(q.items())]}
        result={};supported=None
        for meth in methods:
            triples=[(r,var_index[k],v) for (r,k),v in sorted(entries[meth].items()) if k in var_index and v]
            rr=np.array([t[0] for t in triples],dtype=np.int64);cc=np.array([t[1] for t in triples],dtype=np.int64);vv=np.array([t[2] for t in triples],dtype=float)
            op=core.SparseOperator(rr,cc,vv,len(keys_by[meth]),len(var_keys))
            share=core.SparseOperator(rr,cc,vv/qvec[cc] if len(cc) else vv.copy(),len(keys_by[meth]),len(var_keys))
            bound=max(2.0,float(metrics['first_last_max_station_multiplicity'])) if meth==FIRST_LAST else 1.0
            require(np.all(share.values>=0) and np.all(share.values<=bound+1e-10),'PAIR_SHARE_OUT_OF_BOUNDS')
            require(np.allclose(op.forward(np.ones(len(var_keys))),mtotals[meth],atol=numeric['internal_sum_atol'],rtol=numeric['internal_sum_rtol']),'MUTABLE_PREDICTION_PARITY_FAIL')
            rows=[{'observation_type':{C17_STATION:'KORDON_C17_STATION',PROFILE_STATION:'KORDON_STATION_PROFILE',PROFILE_STATION_B:'KORDON_STATION_PROFILE'}.get(b,'KORDON_PAIR'),'category':'OA','origin_station':a,'destination_station':b,
              'role':'DIAGNOSTIC','method':meth,'basis':'RPDI','model':float(totals[meth][i]),
              'per_dseg':{c:float(per_dseg[meth][c][i]) for c in codes}} for i,(a,b) in enumerate(keys_by[meth])]
            frozen=None
            if meth in fs:
                if supported is None:
                    supported=_supported(q,codes)
                frozen=_frozen_share(fs[meth],q,codes,len(keys_by[meth]),totals[meth],numeric,supported)
            inc=Incidence(rows,variables,basevars,qvec,op,share,totals[meth],mtotals[meth],totals[meth]-mtotals[meth],dict(audit,method=meth,nnz=len(vv),semantic_snapshot=state_audit,cross_run_cache_reuse=False))
            inc.frozen=frozen
            result[meth]=inc
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
