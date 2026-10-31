"""Synthetic fixtures only. No production routing or reconstruction."""
from pathlib import Path
import hashlib,json,sqlite3,struct
from collections import defaultdict
from .common import sha256,write_json,parent_core
from .incidence import SCHEMA

def chain_mapping(n=4):
    return {(100+i,i,i+1):i for i in range(1,n+1)} | {(100+i,i+1,i):i for i in range(1,n+1)}

def create_cache(path, paths, *, station_count=4, geometry_proven=True, station_map=None, extra_edges=()):
    """paths: iterable(mode, origin, dest, index, ordered directed keys, volumes dict)."""
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():raise ValueError('FIXTURE_PATH_EXISTS')
    mapping=chain_mapping(station_count) if station_map is None else dict(station_map)
    ed=sorted(set(mapping).union(extra_edges));eid={k:i+1 for i,k in enumerate(ed)}
    con=sqlite3.connect(path)
    con.executescript('''PRAGMA foreign_keys=ON;
CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE segments(dseg TEXT PRIMARY KEY,mode TEXT NOT NULL,audit_json TEXT NOT NULL);
CREATE TABLE geometry(gid INTEGER PRIMARY KEY,mode TEXT NOT NULL,orig INTEGER NOT NULL,dest INTEGER NOT NULL,path_index INTEGER NOT NULL,edge_ids BLOB,edge_count INTEGER,sequence_sha256 TEXT,geometry_kind TEXT,UNIQUE(mode,orig,dest,path_index));
CREATE TABLE volumes(gid INTEGER NOT NULL REFERENCES geometry(gid),dseg TEXT NOT NULL REFERENCES segments(dseg),volume REAL NOT NULL,PRIMARY KEY(gid,dseg)) WITHOUT ROWID;
CREATE TABLE edges(eid INTEGER PRIMARY KEY,link_no INTEGER NOT NULL,from_no INTEGER NOT NULL,to_no INTEGER NOT NULL);
''')
    con.executemany('INSERT INTO metadata VALUES(?,?)',[('schema',SCHEMA),('parent_hash','SYNTHETIC_STATE'),('geometry_identity','FULL_IDENTITY_SYNTHETIC_TEST_ONLY' if geometry_proven else 'PROVISIONAL_SAME_MODE_GEOMETRY_NOT_FULLY_VERIFIED'),('apply_permitted','false')])
    con.executemany('INSERT INTO edges VALUES(?,?,?,?)',[(v,*k) for k,v in eid.items()])
    sums=defaultdict(float);od=defaultdict(float);counts=defaultdict(int);modes={};n=0
    for n,(mode,o,d,pi,edges,volumes) in enumerate(paths,1):
        blob=struct.pack('<%dI'%len(edges),*[eid[k] for k in edges])
        con.execute('INSERT INTO geometry VALUES(?,?,?,?,?,?,?,?,?)',(n,mode,o,d,pi,blob,len(edges),hashlib.sha256(blob).hexdigest(),'LINK_SEQUENCE' if edges else 'ZERO_LINK_INTERZONAL_NO_ADDVAL1_EFFECT'))
        for c,vol in volumes.items():
            c=parent_core().norm_code(c)
            if c not in modes:
                con.execute('INSERT INTO segments VALUES(?,?,?)',(c,mode,'{}'));modes[c]=mode
            assert modes[c]==mode
            con.execute('INSERT INTO volumes VALUES(?,?,?)',(n,c,vol))
            sums[c]+=vol;od[(c,o,d)]+=vol;counts[c]+=1
        if n%10000==0:con.commit()
    for c,count in counts.items():con.execute('UPDATE segments SET audit_json=? WHERE dseg=?',(json.dumps({'parent_rows':count,'matrix_total':sums[c]}),c))
    con.commit();con.close()
    evidence={'schema':'CORDON_FROZEN_CACHE_EVIDENCE_V1','completed':True,'model_year':2025,'basis':'RPDI','category':'OA','origin':'SYNTHETIC_TEST_FIXTURE','cache_sha256':sha256(path),'network_sha256':hashlib.sha256(json.dumps(ed).encode()).hexdigest(),'demand_sha256':hashlib.sha256(json.dumps(sorted((str(k),v) for k,v in od.items())).encode()).hexdigest(),'dseg_totals':dict(sums),'od_totals':[{'dseg':c,'orig':o,'dest':d,'volume':v} for (c,o,d),v in sorted(od.items())],'geometry_full_identity_proven':geometry_proven}
    write_json(path.with_suffix('.evidence.json'),evidence)
    return mapping,evidence

def config(codes):
    return {'apply':False,'category':'OA','selected_dsegs':codes,
      'mutable_dsegs':[c for c in codes if c.startswith('NATIVE_') and parent_core().family_from_dseg(c) in ('WORK','SERVICE')],
      'mutable_relation_policy':'ALL_MUTABLE_RELATIONS','repeat_policy':'EXCLUDE_FLAGGED'}
