"""Lossless typed cache codec; one shared OD audit, no pickle or object dtype."""
from __future__ import annotations
from collections.abc import Sequence
from pathlib import Path
import dataclasses
import json
import zipfile
import numpy as np
from .common import require, parent_core, canonical_hash, write_json, write_npz
from .io import native_path
from .perf01_identity import strict_json, clean_path

ARRAY_NAMES={'row','col','through','share','q','model','mutable','fixed'}


class JsonRows(Sequence):
    """Lazy read-only legacy records over verified column arrays.

    Iteration/indexing is compatible with all_od_totals; JSON materialization is
    explicit via the release's encoder or export_legacy, never four default dumps.
    """
    def __init__(self,columns,dictionaries=None):
        self.columns=dict(columns)
        self.dictionaries=dictionaries or {}
        for key,labels in self.dictionaries.items():
            require(key in self.columns and len(set(labels))==len(labels) and all(isinstance(x,str) for x in labels),
                    'PERF01_TABLE_DICTIONARY_INVALID')
            arr=self.columns[key]
            require(arr.dtype.kind in 'iu' and (not len(arr) or (arr.min()>=0 and arr.max()<len(labels))),
                    'PERF01_TABLE_DICTIONARY_INDEX')
        lengths={len(x) for x in self.columns.values()}
        require(len(lengths)==1,'PERF01_TABLE_COLUMN_LENGTH_MISMATCH')
        self.length=next(iter(lengths))
        for v in self.columns.values():v.flags.writeable=False
    def __len__(self):return self.length
    def __getitem__(self,i):
        if isinstance(i,slice):return [self[j] for j in range(*i.indices(len(self)))]
        if i<0:i+=len(self)
        if i<0 or i>=len(self):raise IndexError(i)
        return {key:(self.dictionaries[key][int(array[i])] if key in self.dictionaries else array[i].item()) for key,array in self.columns.items()}
    def __iter__(self):
        for i in range(len(self)):yield self[i]
    def to_list(self):return list(self)


def legacy_value(value):
    if isinstance(value,JsonRows):return value.to_list()
    if isinstance(value,dict):return {k:legacy_value(v) for k,v in value.items()}
    if isinstance(value,list):return [legacy_value(v) for v in value]
    return value


def json_default(value):
    if isinstance(value,JsonRows):return value.to_list()
    raise TypeError('NOT_JSON_SERIALIZABLE:'+type(value).__name__)


def read_arrays(path,expected=None):
    p=clean_path(path)
    with zipfile.ZipFile(native_path(p)) as archive:
        members=archive.infolist()
        require(len({i.filename for i in members})==len(members),'PERF01_NPZ_DUPLICATE_MEMBER')
        require(all(i.filename.endswith('.npy') and '/' not in i.filename and '\\' not in i.filename for i in members),'PERF01_NPZ_MEMBER_INVALID')
        require(sum(i.file_size for i in members)<=4*1024**3,'PERF01_NPZ_UNCOMPRESSED_LIMIT')
    with np.load(native_path(p),allow_pickle=False) as data:
        require(expected is None or set(data.files)==set(expected),'PERF01_NPZ_FIELDS_MISMATCH')
        arrays={}
        for key in data.files:
            value=data[key]
            require(not value.dtype.hasobject and value.ndim==1,'PERF01_NPZ_DTYPE_OR_DIM_INVALID')
            require(value.dtype.kind in 'iufUSb','PERF01_NPZ_DTYPE_INVALID')
            if value.dtype.kind in 'iuf':require(np.all(np.isfinite(value)),'PERF01_NPZ_NONFINITE')
            value.flags.writeable=False;arrays[key]=value
    return arrays


def _table(rows,fields):
    result={};dictionaries={}
    for field,kind in fields:
        if kind.startswith('U'):
            labels=sorted({r[field] for r in rows});ix={v:i for i,v in enumerate(labels)}
            require(len(labels)<32768,'PERF01_TOO_MANY_DICTIONARY_VALUES')
            dictionaries[field]=labels
            result[field]=np.fromiter((ix[r[field]] for r in rows),dtype='<i2',count=len(rows))
        else:
            result[field]=np.fromiter((r[field] for r in rows),dtype=kind,count=len(rows))
    return result,dictionaries


def save_bundle(folder,variants):
    from .incidence import METHODS
    first=variants[METHODS[0]]
    # Audit and tables are required to be identical across methods, except these keys.
    perkeys={'method','nnz'}
    common={k:v for k,v in first.audit.items() if k not in perkeys and k!='all_od_totals'}
    for name in METHODS[1:]:
        other=variants[name]
        require(common=={k:v for k,v in other.audit.items() if k not in perkeys and k!='all_od_totals'},'PERF01_SHARED_AUDIT_MISMATCH')
        require(other.variables==first.variables and other.projection_base_variables==first.projection_base_variables,'PERF01_SHARED_VARIABLE_MISMATCH')
        require(other.audit['all_od_totals'] is first.audit['all_od_totals'] or
                other.audit['all_od_totals']==first.audit['all_od_totals'],'PERF01_SHARED_OD_MISMATCH')
    folder=Path(folder)
    fields=(('dseg','U64'),('orig','<i8'),('dest','<i8'),('volume','<f8'))
    od_arrays,od_dict=_table(first.audit['all_od_totals'],fields)
    write_npz(folder/'ALL_OD_TOTALS.npz',**od_arrays)
    del od_arrays
    # Variables can be substantial, but are only stored/loaded once for both methods.
    vf=(('dseg_code','U64'),('family','U16'),('origin','<i8'),('destination','<i8'),('q_current','<f8'),('path_count','<i8'))
    arrays={};variable_dict={}
    for prefix,rows,fs in [('v_',first.variables,(('variable_index','<i8'),)+vf),('b_',first.projection_base_variables,vf)]:
        encoded,labels=_table(rows,fs)
        arrays.update({prefix+k:v for k,v in encoded.items()})
        variable_dict.update({prefix+k:v for k,v in labels.items()})
    write_npz(folder/'VARIABLE_TABLES.npz',**arrays)
    del arrays,encoded
    write_json(folder/'SHARED_AUDIT.json',{'schema':'CORDON_PERF01_SHARED_AUDIT_V1','audit':common,
                'od_table':{'file':'ALL_OD_TOTALS.npz','rows':len(first.audit['all_od_totals'])},
                'od_dictionaries':od_dict,'variable_dictionaries':variable_dict})
    for method in METHODS:
        inc=variants[method]
        write_npz(folder/(method+'.npz'),row=inc.operator.row_idx,col=inc.operator.col_idx,
                  through=inc.operator.values,share=inc.share_operator.values,q=inc.q_current,
                  model=inc.model,mutable=inc.mutable,fixed=inc.fixed)
        write_json(folder/(method+'.json'),{'schema':'CORDON_PERF01_METHOD_V1','method':method,
                     'rows':inc.rows,'audit':{k:inc.audit[k] for k in perkeys}})


def validate_result(inc):
    from .incidence import validate_roles
    core=parent_core();nr=len(inc.rows);nc=len(inc.variables);op=inc.operator;sh=inc.share_operator
    require(op.n_rows==nr and op.n_cols==nc,'PERF01_OPERATOR_SHAPE')
    require(len(inc.q_current)==nc and all(len(a)==nr for a in (inc.model,inc.mutable,inc.fixed)), 'PERF01_VECTOR_SHAPE')
    require(op.row_idx.dtype.kind in 'iu' and op.col_idx.dtype.kind in 'iu','PERF01_INDEX_DTYPE')
    require(len(op.row_idx)==len(op.col_idx)==len(op.values)==len(sh.values),'PERF01_SPARSE_LENGTH')
    require(not len(op.values) or (op.row_idx.min()>=0 and op.row_idx.max()<nr and op.col_idx.min()>=0 and op.col_idx.max()<nc),'PERF01_INDEX_RANGE')
    require(all(np.isfinite(a).all() for a in (op.values,sh.values,inc.q_current,inc.model,inc.mutable,inc.fixed)),'PERF01_NONFINITE')
    require(np.all(op.values>=0) and np.all(sh.values>=0) and np.all(inc.q_current>0),'PERF01_NEGATIVE_OR_ZERO_SPARSE')
    for i,v in enumerate(inc.variables):
        require(v['variable_index']==i and v['q_current']==inc.q_current[i] and v['path_count']>0,'PERF01_VARIABLE_CONTRACT')
    # Original cold arithmetic is retained; no additional relaxed tolerances.
    require(np.array_equal(inc.model-inc.mutable,inc.fixed),'PERF01_FIXED_PARITY')
    require(np.array_equal(op.values/inc.q_current[op.col_idx] if len(op.values) else op.values,sh.values),'PERF01_SHARE_PARITY')
    require(all(np.isfinite(row['model']) and row['model']==float(inc.model[i]) for i,row in enumerate(inc.rows)),'PERF01_ROW_MODEL_PARITY')
    validate_roles(inc.rows)
    return inc


def load_bundle(folder):
    from .incidence import Incidence,METHODS
    folder=Path(folder);core=parent_core()
    shared=strict_json(folder/'SHARED_AUDIT.json')
    require(shared.get('schema')=='CORDON_PERF01_SHARED_AUDIT_V1','PERF01_SHARED_SCHEMA')
    od=read_arrays(folder/'ALL_OD_TOTALS.npz',{'dseg','orig','dest','volume'})
    require(od['dseg'].dtype.kind in 'iu' and all(od[k].dtype.kind in 'iu' for k in ('orig','dest')) and od['volume'].dtype.kind=='f','PERF01_OD_DTYPE')
    require((od['volume']>=0).all() and (od['orig']>0).all() and (od['dest']>0).all(),'PERF01_OD_INVALID')
    rows=JsonRows(od,shared["od_dictionaries"])
    require(len(rows)==shared['od_table']['rows'],'PERF01_OD_ROW_COUNT')
    vf=['dseg_code','family','origin','destination','q_current','path_count']
    expected={'v_'+k for k in ['variable_index',*vf]}|{'b_'+k for k in vf}
    table=read_arrays(folder/'VARIABLE_TABLES.npz',expected)
    labels=shared['variable_dictionaries']
    for prefix in ('v_','b_'):
        for key in ('origin','destination','path_count'):
            require(table[prefix+key].dtype.kind in 'iu' and (table[prefix+key]>0).all(),'PERF01_VARIABLE_DTYPE')
        require(table[prefix+'q_current'].dtype.kind=='f' and (table[prefix+'q_current']>=0).all(),'PERF01_VARIABLE_Q_INVALID')
    require(table['v_variable_index'].dtype.kind in 'iu','PERF01_VARIABLE_INDEX_DTYPE')
    variables=list(JsonRows({k[2:]:v for k,v in table.items() if k.startswith('v_')},
                           {k[2:]:v for k,v in labels.items() if k.startswith('v_')}))
    basevars=list(JsonRows({k[2:]:v for k,v in table.items() if k.startswith('b_')},
                          {k[2:]:v for k,v in labels.items() if k.startswith('b_')}))
    audit=dict(shared['audit'],all_od_totals=rows)
    result={}
    for method in METHODS:
        meta=strict_json(folder/(method+'.json'));arrays=read_arrays(folder/(method+'.npz'),ARRAY_NAMES)
        require(meta.get('schema')=='CORDON_PERF01_METHOD_V1' and meta.get('method')==method,'PERF01_METHOD_SCHEMA')
        op=core.SparseOperator(arrays['row'],arrays['col'],arrays['through'],len(meta['rows']),len(variables))
        sh=core.SparseOperator(arrays['row'],arrays['col'],arrays['share'],len(meta['rows']),len(variables))
        inc=Incidence(meta['rows'],variables,basevars,arrays['q'],op,sh,arrays['model'],arrays['mutable'],arrays['fixed'],dict(audit,**meta['audit']))
        require(inc.audit['method']==method and inc.audit['nnz']==len(op.values),'PERF01_METHOD_AUDIT_MISMATCH')
        require(np.all(sh.values<=1+1e-10),'PAIR_SHARE_OUT_OF_BOUNDS')
        result[method]=validate_result(inc)
    return result


def export_legacy(inc,folder):
    """Explicit original schema, including large OD audit. Not used on warm default."""
    clone=dataclasses.replace(inc,audit=legacy_value(inc.audit))
    clone.save(folder)
