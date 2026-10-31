"""Read-only bounded-memory LEGACY/FAST comparison. Never repairs data."""
from __future__ import annotations
from pathlib import Path
from itertools import zip_longest
from contextlib import closing
from urllib.parse import quote
import hashlib,json,sqlite3,struct
import numpy as np
from .common import require
from .io import read_json,sha256,write_json

TABLES=('edges','geometry','volumes','segments','metadata','profile_hits','driver_markets','edge_postings')
SORT={'edges':'eid','geometry':'mode,orig,dest,path_index','volumes':'gid,dseg',
      'segments':'dseg','metadata':'key','profile_hits':'gid,profile_index',
      'driver_markets':'mode,orig,dest','edge_postings':'eid,chunk'}

def _connect(p):
    require(Path(p).is_file(),'PARITY_SOURCE_MISSING')
    require(not any(Path(str(p)+s).exists() for s in ('-wal','-shm','-journal')),'PARITY_ACTIVE_SQLITE')
    con=sqlite3.connect('file:'+quote(str(Path(p).resolve()).replace('\\','/'),safe='/:')+'?mode=ro',uri=True)
    try:
        con.execute('PRAGMA query_only=ON')
        require(con.execute('PRAGMA quick_check').fetchone()[0]=='ok','PARITY_SQLITE_INTEGRITY_FAIL')
        return con
    except BaseException:
        try:con.close()
        except Exception:pass
        raise

def _feed(h,row):
    for v in row:
        if v is None:b=b'N'
        elif isinstance(v,bytes):b=b'B'+v
        elif isinstance(v,float):b=b'F'+struct.pack('<d',v)
        elif isinstance(v,int):b=b'I'+str(v).encode('ascii')
        else:b=b'S'+str(v).encode('utf-8')
        h.update(struct.pack('<Q',len(b)));h.update(b)

def compare_sql(left,right):
    out=[]
    with closing(_connect(left)) as a,closing(_connect(right)) as b:
        for table in TABLES:
            schema_a=list(a.execute('PRAGMA table_info('+table+')'))
            schema_b=list(b.execute('PRAGMA table_info('+table+')'))
            if schema_a!=schema_b or not schema_a:
                out.append({'table':table,'equal':False,'reason':'SCHEMA_DIFFERENT_OR_MISSING'});continue
            query='SELECT * FROM '+table+' ORDER BY '+SORT[table]
            h1=hashlib.sha256();h2=hashlib.sha256();count=0;first=None
            for x,y in zip_longest(a.execute(query),b.execute(query)):
                count+=1
                if x is not None:_feed(h1,x)
                if y is not None:_feed(h2,y)
                if x!=y and first is None:
                    first={'row_number':count,'reason':'VALUE_OR_ROW_COUNT_DIFFERENT'}
            out.append({'table':table,'equal':first is None,'compared_rows':count,
                'left_digest':h1.hexdigest(),'right_digest':h2.hexdigest(),'first_mismatch':first})
    return {'status':'PARITY_PASS' if all(x['equal'] for x in out) else 'PARITY_FAIL','tables':out}


def _lines(path,replacements):
    with Path(path).open(encoding='utf-8-sig') as f:
        for line in f:
            for old,new in replacements:line=line.replace(old,new)
            yield line

def compare_text(left,right,left_replace=(),right_replace=()):
    h1=hashlib.sha256();h2=hashlib.sha256();first=None;count=0
    for x,y in zip_longest(_lines(left,left_replace),_lines(right,right_replace)):
        count+=1
        if x is not None:h1.update(x.encode())
        if y is not None:h2.update(y.encode())
        if x!=y and first is None:first=count
    return {'equal':first is None,'lines':count,'first_mismatch_line':first,
            'left_canonical_sha256':h1.hexdigest(),'right_canonical_sha256':h2.hexdigest()}


def compare_runs(left,right,*,output=None):
    left,right=Path(left),Path(right);records=[]
    ev1=read_json(left/'SNAPSHOT_EVIDENCE.json');ev2=read_json(right/'SNAPSHOT_EVIDENCE.json')
    # Verify both frozen sources instead of granting authority to filename aliases.
    for folder,ev in ((left,ev1),(right,ev2)):
        require(ev.get('completed') is True and ev.get('geometry_full_identity_proven') is True,
                'PARITY_CAPTURE_INCOMPLETE')
        require(sha256(folder/'p.sqlite')==ev['cache_sha256'],'PARITY_CACHE_HASH_MISMATCH')
        require(sha256(folder/'OD_PARITY.json')==ev['external_od_parity_sha256'],'PARITY_OD_REPORT_HASH_MISMATCH')
        for rec in ev['od_matrix_authorities']:
            name=Path(rec['path'])
            require(not name.is_absolute() and '..' not in name.parts,'PARITY_UNSAFE_MATRIX_PATH')
            require(sha256(folder/name)==rec['sha256'],'PARITY_MATRIX_HASH_MISMATCH')
    sql=compare_sql(left/'p.sqlite',right/'p.sqlite')
    records.append({'artifact':'p.sqlite','equal':sql['status']=='PARITY_PASS','sql':sql})
    for k in ('network_sha256','demand_sha256','dseg_totals','model_year','basis','category','source_version',
              'path_matrix_parity_policy','assignment_freshness','apply_permitted','od_matrix_authorities'):
        records.append({'artifact':'SNAPSHOT_EVIDENCE.'+k,'equal':ev1.get(k)==ev2.get(k)})
    proof1=read_json(left/'GEOMETRY_PROOF.json');proof2=read_json(right/'GEOMETRY_PROOF.json')
    for p,e in ((proof1,ev1),(proof2,ev2)):
        require(p['checks']==e['full_geometry_checks'] and p['full'] is True,'PARITY_PROOF_EVIDENCE_MISMATCH')
        require(len(p['checks'])==12 and len({x['dseg'] for x in p['checks']})==12,'PARITY_PROOF_SCOPE_MISMATCH')
    records.append({'artifact':'GEOMETRY_PROOF','equal':[(x['dseg'],x['check']) for x in proof1['checks']]==[(x['dseg'],x['check']) for x in proof2['checks']]})
    # Only provenance digests of semantically compared SQL/evidence may differ.
    replace1=[(ev1['cache_sha256'],'<PARITY_EQUIVALENT_CACHE_SHA>'),(sha256(left/'SNAPSHOT_EVIDENCE.json'),'<PARITY_EQUIVALENT_EVIDENCE_SHA>')]
    replace2=[(ev2['cache_sha256'],'<PARITY_EQUIVALENT_CACHE_SHA>'),(sha256(right/'SNAPSHOT_EVIDENCE.json'),'<PARITY_EQUIVALENT_EVIDENCE_SHA>')]
    paths=['PREFLIGHT.json','OD_PARITY.json','STATION_MAPPING_CHECK.json','STATION_HITS.csv','RUN_REPORT.json']
    for method in ('ALL_ORDERED_UNIQUE_PAIRS','EXACT_TWO_HITS'):
        paths += [method+'/'+f for f in ('OBSERVATION_ROSTER.json','TARGETING_CONTEXT.json','INCIDENCE_METADATA.json','DIRECTED_DIAGNOSTICS/INCIDENCE_METADATA.json')]
        for sub in ('','DIRECTED_DIAGNOSTICS/'):
            name=method+'/'+sub+'INCIDENCE.npz'
            with np.load(left/name,allow_pickle=False) as a,np.load(right/name,allow_pickle=False) as b:
                values={k:bool(k in b.files and a[k].dtype==b[k].dtype and a[k].shape==b[k].shape and np.array_equal(a[k],b[k])) for k in a.files}
                records.append({'artifact':name,'equal':set(a.files)==set(b.files) and all(values.values()),'arrays':values})
    for name in paths:
        diff=compare_text(left/name,right/name,replace1,replace2)
        records.append({'artifact':name,**diff})
    result={'schema':'CORDON_DIAGFAST_PARITY_V1','status':'PARITY_PASS' if all(x['equal'] for x in records) else 'PARITY_FAIL',
        'artifacts':records,'allowed_normalizations':['geometry-proof backend metadata (full scope retained)',
        'cache/evidence content hashes ONLY after independent semantic comparison'],
        'numerical_tolerance':0,'apply_permitted':False,'native_acceptance_certified':False}
    if output:write_json(output,result)
    return result
