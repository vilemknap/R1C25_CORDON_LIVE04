"""Read-only bridge to pinned donor contracts, always reading this injected model."""
from pathlib import Path
import hashlib
import os
import re
import numpy as np
from .common import ROOT,require,parent_module,canonical_hash,read_json,finite
from .io import write_json,sha256
from .visum_startup import _call,_matrix,_network,_segments,preflight
from . import com_busy
from .live01_config import donor_config,calculation_config

# No callable outside this set is exposed to the inherited read-only audits.
READ_METHODS=frozenset(('AttValue','GetMultiAttValues','GetValues','GetAll','Item','ItemByKey',
    'TripGenerationDStratParameters','TripGenerationDStratParas',
    'TripDistributionDStratParameters','TripDistributionDStratParas','DStratParameters','DStratParas'))


def is_com_method(value):
    """True only for a bound method/function, never for a (callable) COM object."""
    import inspect
    if getattr(value,'_oleobj_',None) is not None:
        return False
    return inspect.ismethod(value) or inspect.isfunction(value) or inspect.isbuiltin(value)


class ReadOnlyObject:
    """Wrap donor COM access with per-read retry and an enforced mutation denylist.

    This facade is only used by the donor read contracts, not path-list creation.
    The legacy path reader retains its original COM/list implementation.
    """
    def __init__(self,obj,control,options,label='Visum'):
        object.__setattr__(self,'_obj',obj);object.__setattr__(self,'_control',control)
        object.__setattr__(self,'_options',options);object.__setattr__(self,'_label',label)
    def __setattr__(self,name,value):
        raise ValueError('LIVE01_COM_WRITE_FORBIDDEN:'+name)
    def _wrap(self,value,label):
        if value is None or isinstance(value,(str,bytes,int,float,bool,np.generic,np.ndarray)):
            return value
        if isinstance(value,list):return [self._wrap(x,label) for x in value]
        if isinstance(value,tuple):return tuple(self._wrap(x,label) for x in value)
        if isinstance(value,dict):return {k:self._wrap(x,label) for k,x in value.items()}
        return ReadOnlyObject(value,self._control,self._options,label)
    def __getattr__(self,name):
        if name.startswith(('Set','Save','Load','Execute','Add','Remove','Delete','Run','Create')):
            raise ValueError('LIVE01_COM_WRITE_FORBIDDEN:'+name)
        label=self._label+'.'+name
        value=_call(lambda:getattr(self._obj,name),self._control,self._options,label)
        # LIVE02 FIX1: pywin32 CDispatch objects define __call__ (DISPID_VALUE),
        # so callable() is True for returned COM *objects* such as Visum.Net.
        # Use the donor com_compat.member_value rule: an object carrying
        # _oleobj_ is a COM object property; only real Python callables are methods.
        if is_com_method(value):
            require(name in READ_METHODS,'LIVE01_COM_CALL_NOT_AUTHORIZED:'+name)
            def read(*args,**kwargs):
                return self._wrap(_call(lambda:value(*args,**kwargs),self._control,self._options,label),label)
            return read
        return self._wrap(value,label)
    def __iter__(self):
        return iter(self._wrap(_call(lambda:list(self._obj),self._control,self._options,self._label+'.iter'),self._label))


def normalized_mode(value):
    return parent_module('r1_15a2_core').norm_code(value)


def validate_motorways(links):
    from .authority import mapping
    stations,_=mapping(ROOT/'data/audited/STATION_MAPPING.csv')
    evidence=[]
    for key,station in sorted(stations.items()):
        if station not in (1,3,15,16):continue
        require(key in links,'LIVE01_MOTORWAY_MAPPING_MISSING')
        modes={normalized_mode(v) for v in links[key]['tsys']}
        require('C' in modes and 'C_NOT' not in modes,'LIVE01_MOTORWAY_MODE_CONTRACT:'+str(station))
        evidence.append({'station':station,'link':list(key),'C':True,'C_NOT':False})
    require(len(evidence)==8,'LIVE01_MOTORWAY_SCOPE')
    return evidence


def expected_bindings():
    return read_json(ROOT/'provenance/live01/CORDON_LIVE_DONOR_CONTRACT.json')['matrices']['assignment_od_by_normalized_dseg']


def validate_bindings(audit):
    bindings=expected_bindings()
    require(set(audit)==set(bindings),'LIVE01_OD_DSEG_BINDING_SCOPE')
    for code,no in bindings.items():
        require(audit[code]['matrix_no']==no,'LIVE01_OD_MATRIX_BINDING_MISMATCH:'+code)
        require(audit[code]['matrix_shape']==[681,681],'LIVE01_OD_MATRIX_DIMENSIONS:'+code)
    return {code:dict(audit[code],binding='DemandSegment.ODMatrix') for code in sorted(bindings)}


def script_references(operation_rows, source):
    """Use donor's SCRIPTFILE/FORMULA fields; no guessed mutating COM probes."""
    result=[]
    for row in operation_rows:
        op=row['object'];candidates=[]
        for name in ('SCRIPTFILE','ScriptFile','SCRIPTFILENAME','ScriptFileName',
                     'FILE','File','FILENAME','FileName','FORMULA','Formula'):
            try:value=op.AttValue(name)
            except Exception:continue
            if isinstance(value,str) and value.strip().strip('"').lower().endswith(('.py','.pys')):
                candidates.append((name,value.strip().strip('"')))
        hinted=any(token in (row.get('comment','')+' '+row.get('name','')).upper()
                   for token in ('20B','.PY','PYTHON'))
        require(candidates or not hinted,'LIVE01_SCRIPT_REFERENCE_UNREADABLE:OP'+str(row['no']))
        seen=set()
        for name,raw in candidates:
            path=Path(os.path.expandvars(raw))
            if not path.is_absolute():path=Path(source).parent/path
            require(path.is_file(),'LIVE01_PROCEDURE_SCRIPT_MISSING:'+str(path))
            if str(path) in seen:continue
            seen.add(str(path))
            result.append({'operation':row['no'],'attribute':name,'path':str(path),'sha256':sha256(path)})
    return result


def audit_current_tg(vp,proxy,cfg):
    """Run the exact donor function with an axis-aware read helper namespace.

    The original audit uses rt.zone_numbers() which requires literal 1..681.
    Only that read helper is adapted: LIVE01 validates 681 unique actual IDs.
    No module global is patched, no TG formula/schema check is removed.
    """
    import types
    com=parent_module('r1_15a2_com_compat')
    class AxisRuntime:
        def zone_numbers(self,visum,retry_policy=None):
            values,_=com.zone_identity(visum,retry_policy=com_busy.NO_RETRY)
            require(len(values)==681,'LIVE01_ZONE_COUNT_MISMATCH')
            return values
        def __getattr__(self,name):return getattr(vp.rt,name)
    original=vp.audit_trip_generation_contract
    namespace=dict(original.__globals__,rt=AxisRuntime())
    return types.FunctionType(original.__code__,namespace,original.__name__,original.__defaults__,original.__closure__)(proxy,cfg)


def read_donor_state(visum,zones,folder,control,opt,live):
    """Read schema/values without constructing the mutating donor trial adapter."""
    proxy=ReadOnlyObject(visum,control,opt)
    cfg=donor_config(live)
    vp=parent_module('r1_15a2_visum_parameters');com=parent_module('r1_15a2_com_compat')
    from .live01_donor_scope import zone_state_rows,generation_actuator_zone_scope
    from .common import parent_core
    # Detect positional drift. Different iteration order in attr columns is OK
    # if COM row keys still bind unambiguously to the verified Zone.NO axis.
    current,indices=com.zone_identity(proxy,retry_policy=com_busy.NO_RETRY)
    require(current==zones,'LIVE01_ZONE_AXIS_CHANGED')
    tg=audit_current_tg(vp,proxy,cfg)
    require(tg['passes'],'TG_CONTRACT_MISSING:'+','.join(tg['failures']))
    selected=[r for r in tg['operation_rows'] if r.get('selected')]
    require(len(selected)==1 and selected[0]['index']==5,'LIVE01_TG_OPERATION_POSITION')
    zrows,attrs=zone_state_rows(proxy,zones,cfg,zone_indices=indices,retry_policy=com_busy.NO_RETRY)
    eligible,scope=generation_actuator_zone_scope(proxy,zones,cfg,folder,zone_indices=indices,retry_policy=com_busy.NO_RETRY)
    scope_rows=read_json(folder/'00_ZONE_ACTUATOR_SCOPE_SUMMARY.json')
    for r in zrows:
        for name in attrs:finite(r[name],name,nonnegative=False)
    assignment=parent_module('r1_15a2_assignment_authority_v239').audit_assignment_scope(proxy)
    require(assignment['passes'],'LIVE01_ASSIGNMENT_SCOPE:'+','.join(assignment['failures']))
    td=vp.read_td_parameter_state(proxy)
    selected=[r for r in td['operation_rows'] if r.get('selected')]
    require(len(selected)==1 and selected[0]['index']==6,'LIVE01_TD_OPERATION_POSITION')
    expected=read_json(ROOT/'provenance/live01/TD_COMPONENT_REGISTRY_FROM_DONOR.json')
    require(len(td['rows'])==16 and set(td['objects'])==set(expected),'LIVE01_TD_COMPONENT_SCOPE')
    tdrows=[]
    for r in td['rows']:
        require(r['status']=='OK','LIVE01_TD_PARAMETER_UNREADABLE:'+r['component'])
        grav=td['objects'][r['component']]['grav']
        name,a,mode=vp._read_any(grav,('PARA_A','Para_A','ParaA','A'))
        row=dict(r,current_a=finite(a,'PARA_A',nonnegative=False),a_attr=name,a_mode=mode)
        finite(row['current_b'],'PARA_B',nonnegative=False);finite(row['current_c'],'PARA_C',nonnegative=False)
        tdrows.append(row)
    # Validate source TD set: exactly 16 domestic codes, optionally FOREIGN.
    required={v['dstrat_code'].upper() for v in expected.values()}
    raw_tokens=[x.strip("'\"").upper() for x in re.split(r'[,;{}\s]+',selected[0]['dstratset']) if x.strip("'\"")]
    require(len(raw_tokens)==len(set(raw_tokens)),'LIVE01_TD_DUPLICATE_SOURCE_STRATUM')
    tokens=com.code_set(selected[0]['dstratset'])
    require(tokens in (required,required|{'4_FOREIGN'}),'LIVE01_TD_SOURCE_SET_NOT_16_OR_17')
    operations=com.operation_rows(proxy)
    require(operations[4]['type']==45 and operations[5]['type']==46,'LIVE01_PROCEDURE_IDENTITY')
    source=parent_module('r1_15a2_live_api_audit').current_version_file(proxy)
    scripts=script_references(operations,source)
    # Preserve source schema and report configured quality without executing.
    quality={}
    for row in operations:
        if row['no']==20:
            params=row['object'].PrTAssignmentParameters
            for name in ('MAXGAP','MAXGAPREL','MAXNUMITERATIONS'):
                try:quality[name]=params.AttValue(name)
                except Exception:pass
    tdparams=operations[5]['object'].TripDistributionParameters
    foreign_stratum,_=vp._dstrat_object(tdparams,'4_FOREIGN',('TripDistribution',))
    require(foreign_stratum is not None,'LIVE01_FOREIGN_STRATUM_UNREADABLE')
    foreign_grav=foreign_stratum.GravitationParameters
    foreign_params={}
    for key,names in [('a',('PARA_A','Para_A','ParaA','A')),('b',vp.TD_B_ATTRS),('c',vp.TD_C_ATTRS)]:
        attr,val,mode=vp._read_any(foreign_grav,names)
        foreign_params[key]={'value':finite(val,'FOREIGN_'+key,nonnegative=False),'attr':attr,'mode':mode}
    component_matrices=[]
    for component,r in expected.items():
        mat=proxy.Net.Matrices.ItemByKey(r['matrix_no'])
        require(com.exact_int(mat.AttValue('NO'),'TD_MATRIX_NO')==r['matrix_no'],'LIVE01_COMPONENT_MATRIX_IDENTITY')
        component_matrices.append({'component':component,'matrix_no':r['matrix_no'],'sum':finite(mat.AttValue('SUM'),'TD_MATRIX_SUM')})
    # Matrix 9116 is a protected component, not an assignment-only proxy.
    foreign=proxy.Net.Matrices.ItemByKey(9116)
    foreign_values=np.asarray(foreign.GetValues(),dtype='<f8')
    require(foreign_values.shape==(len(zones),len(zones)) and np.isfinite(foreign_values).all() and (foreign_values>=0).all(),'LIVE01_FOREIGN_MATRIX_INVALID')
    require(com.exact_int(foreign.AttValue('NO'),'Matrix.NO')==9116,'LIVE01_FOREIGN_MATRIX_IDENTITY')
    foreign_hash=hashlib.sha256(np.ascontiguousarray(foreign_values).tobytes()).hexdigest()
    protected_inputs={}
    for no in (9001,9697):
        mat=proxy.Net.Matrices.ItemByKey(no)
        require(com.exact_int(mat.AttValue('NO'),'PROTECTED_MATRIX_NO')==no,'LIVE01_PROTECTED_MATRIX_IDENTITY')
        values=np.asarray(mat.GetValues(),dtype='<f8')
        require(values.shape==(len(zones),len(zones)) and np.isfinite(values).all(),'LIVE01_PROTECTED_MATRIX_INVALID:'+str(no))
        if no==9697:require((values>=0).all(),'LIVE01_NEGATIVE_DISTANCE_MATRIX')
        protected_inputs[str(no)]={'shape':list(values.shape),'sha256':hashlib.sha256(np.ascontiguousarray(values).tobytes()).hexdigest(),'source':'CURRENT_MODEL_NO_HISTORIC_2022_CELL_PATCH'}
    inventory=[{k:v for k,v in r.items() if k!='object'} for r in operations]
    # Record freight bindings/values as protected source, not part of OA target.
    freight={}
    for code in ('LNV','NV'):
        ds=proxy.Net.DemandSegments.ItemByKey(code)
        _,a=_matrix({'object':ds,'code':code},len(zones),control,opt);freight[code]=a
    state={'schema':'LIVE01_DONOR_READBACK_V1','zone_rows':zrows,'zone_attributes':attrs,
           'zone_nos':zones,'tg_contract':tg,'actuatable_zones':eligible,'scope_summary':scope,
           'td_rows':tdrows,'foreign_td_parameters':foreign_params,'component_matrices':component_matrices,'td_source_set':sorted(tokens),'assignment':assignment,'assignment_quality':quality,
           'assignment_quality_status':'CONFIGURED_FIELDS_READ' if quality else 'QUALITY_FIELDS_NOT_EXPOSED_READONLY',
           'operations':inventory,'script_references':scripts,'foreign_matrix_sha256':foreign_hash,
           'freight_matrices':freight,'protected_input_matrices':protected_inputs,'technical_architecture_assumption':'USER_APPROVED_2022_EQUALS_2025_SCHEMA',
           'numeric_source':'CURRENT_INJECTED_2025_MODEL','writes_enabled':False}
    state['state_sha256']=canonical_hash(state)
    return state


def model_preflight(visum,live,folder,control,opt):
    require(visum is not None,'VISUM_NOT_INJECTED')
    mathcfg=calculation_config(live)
    pre=preflight(visum,mathcfg,folder,control,opt)
    report,source,zones,links,dsegs=pre
    require(len(zones)==live['expected_zone_count'],'LIVE01_ZONE_COUNT_MISMATCH')
    require(report['source_year_hint_2025'],'LIVE01_MODEL_2025_PATH_NOT_IDENTIFIED')
    report['motorway_checks']=validate_motorways(links)
    bindings=validate_bindings(report['matrix_audit'])
    state=read_donor_state(visum,zones,folder,control,opt,live)
    state['source_version']=str(source)
    state['source_file_sha256']=sha256(source)
    state['network_sha256']=report['network_sha256']
    state['od_segment_bindings']=bindings
    state['current_model_fingerprint']=canonical_hash({k:v for k,v in state.items() if k!='current_model_fingerprint'})
    write_json(folder/'MODEL_READBACK.json',state)
    write_json(folder/'ZONE_ACTUATORS.json',{'rows':state['zone_rows'],'scope':state['scope_summary'],'actuatable_zones':state['actuatable_zones']})
    write_json(folder/'OD_SEGMENT_BINDINGS.json',bindings)
    return pre,state


def verify_end_state(visum,live,folder,control,opt,pre,state):
    """Independent source readback, including OA values and current model pointer.

    Never replace this with a sum-only check or a previously cached donor state.
    Geometry is certified by this invocation's full capture, not by these hashes.
    This readback does not certify a later assignment or a state after return.
    """
    proxy=ReadOnlyObject(visum,control,opt)
    source=parent_module('r1_15a2_live_api_audit').current_version_file(proxy)
    require(str(source)==state['source_version'],'LIVE01_CURRENT_VERSION_POINTER_CHANGED')
    require(sha256(state['source_version'])==state['source_file_sha256'],'LIVE01_SOURCE_VERSION_FILE_CHANGED')
    zones,links,network_hash=_network(visum,control,opt)
    require(zones==pre[2] and network_hash==pre[0]['network_sha256'],
            'LIVE01_NETWORK_OR_ZONE_AXIS_CHANGED')
    segments=_segments(visum,calculation_config(live),control,opt)
    summary=lambda rows:[{k:r[k] for k in ('code','norm_code','mode')} for r in rows]
    require(summary(segments)==summary(pre[4]),'LIVE01_DSEG_IDENTITY_CHANGED')
    matrix_audit={}
    for ds in segments:
        _,audit=_matrix(ds,len(zones),control,opt)
        matrix_audit[ds['norm_code']]=audit
    require(canonical_hash(matrix_audit)==canonical_hash(pre[0]['matrix_audit']),
            'LIVE01_OA_MATRIX_STATE_CHANGED')
    after=read_donor_state(visum,zones,folder,control,opt,live)
    require(after['state_sha256']==state['state_sha256'],'LIVE01_TG_TD_OR_PROC_CHANGED_DURING_BASELINE')
    return {'schema':'LIVE01_END_STATE_READBACK_V2',
            'status':'DONOR_AND_OA_CURRENT_STATE_UNCHANGED',
            'before_sha256':state['state_sha256'],'after_sha256':after['state_sha256'],
            'oa_matrix_audit_sha256':canonical_hash(matrix_audit),
            'network_sha256':network_hash,'source_version':str(source),
            'native_assignment_executed':False,'new_assignment_verified':False,
            'scope':'CURRENT_SOURCE_PARAMETERS_MATRICES_NETWORK_NOT_FUTURE_PATH_EPOCH'}
