"""Independent per-OD parity against sealed matrix snapshots, not path-derived totals."""
from pathlib import Path,PurePosixPath
import numpy as np
import json
import sqlite3
from contextlib import closing
from .common import require,parent_core,sha256,canonical_hash
from .parity import ParityPolicy, compare, lattice_error


def check_matrix_authorities(cache,evidence,od_volumes,selected_codes,path_counts=None):
    records=evidence.get('od_matrix_authorities')
    if records is None:return None
    core=parent_core();codes=[core.norm_code(r['dseg']) for r in records]
    require(len(codes)==len(set(codes)) and set(codes)==set(selected_codes),'EXTERNAL_MATRIX_SCOPE_MISMATCH')
    root=Path(cache).resolve().parent;reports=[]
    record=evidence.get('path_matrix_parity_policy')
    policy=ParityPolicy.from_record(record) if record is not None else ParityPolicy.legacy()
    with closing(sqlite3.connect(Path(cache).resolve().as_uri()+'?mode=ro',uri=True)) as db:
        meta=dict(db.execute('SELECT key,value FROM metadata'))
        if record is not None:
            require(canonical_hash(record)==evidence.get('path_matrix_parity_policy_sha256'), 'PARITY_POLICY_SHA_MISMATCH')
            require(json.loads(meta.get('path_matrix_parity_policy','null'))==record,'PARITY_POLICY_CACHE_MISMATCH')
        else:
            require('path_matrix_parity_policy' not in meta,'PARITY_POLICY_EVIDENCE_MISSING')
        original={core.norm_code(ds):ds for ds, in db.execute('SELECT dseg FROM segments')}
        require(set(codes).issubset(original),'EXTERNAL_MATRIX_SCOPE_MISMATCH')
        lattice={code:lattice_error(db,original[code],policy) for code in codes}
        counts={(core.norm_code(ds),int(o),int(d)):int(n) for ds,o,d,n in db.execute(
            'SELECT v.dseg,g.orig,g.dest,COUNT(*) FROM volumes v JOIN geometry g ON g.gid=v.gid GROUP BY v.dseg,g.orig,g.dest')}
    if path_counts is not None:
        require(all(path_counts.get(k)==n for k,n in counts.items() if k[0] in selected_codes),'PARITY_PATH_COUNT_MISMATCH')
    for code,rec in zip(codes,records):
        rel=PurePosixPath(rec['path'])
        require(not rel.is_absolute() and '..' not in rel.parts and '\\' not in str(rel),'EXTERNAL_MATRIX_PATH_INVALID')
        path=root.joinpath(*rel.parts)
        require(root in path.resolve().parents and not any((root/Path(*rel.parts[:i])).is_symlink() for i in range(1,len(rel.parts)+1)),'EXTERNAL_MATRIX_PATH_INVALID')
        require(path.is_file() and sha256(path)==rec['sha256'],'EXTERNAL_MATRIX_SHA_MISMATCH')
        with np.load(path,allow_pickle=False) as data:
            values=np.asarray(data['values'],dtype=float);zones=data['zone_nos']
        require(zones.ndim==1 and np.issubdtype(zones.dtype,np.integer) and len(zones)==len(set(zones)) and (zones>0).all(),'EXTERNAL_MATRIX_ZONE_IDENTITY')
        require(values.shape==(len(zones),len(zones)) and np.isfinite(values).all() and (values>=0).all(),'EXTERNAL_MATRIX_VALUES_INVALID')
        ix={int(z):i for i,z in enumerate(zones)};reconstructed=np.zeros_like(values)
        for (ds,o,d),vol in od_volumes.items():
            if ds!=code:continue
            require(o in ix and d in ix,'EXTERNAL_MATRIX_PATH_ZONE_MISSING')
            reconstructed[ix[o],ix[d]]=vol
        count_array=np.zeros_like(values,dtype=np.int64)
        for (ds,o,d),count in counts.items():
            if ds!=code:continue
            require(o in ix and d in ix,'EXTERNAL_MATRIX_PATH_ZONE_MISSING')
            count_array[ix[o],ix[d]]=count
        report=compare(values,reconstructed,count_array,zones,code,policy,max_lattice_error=lattice[code],enforce_aggregate_checks=record is not None)
        require(report['status']=='PASS','EXTERNAL_MATRIX_PER_OD_PARITY_FAIL:'+code+':'+','.join(report['failures']))
        require(sha256(path)==rec['sha256'],'EXTERNAL_MATRIX_CHANGED_DURING_READ')
        report.update(basis='INDEPENDENT_FULL_INTERZONAL_MATRIX',matrix_sha256=rec['sha256'],
            max_abs_error=report['max_abs_interzonal_error'],
            diagonal_error_reported_not_imputed=report['diagonal_error_not_hidden'])
        reports.append(report)
    return reports
