"""Instrumented bounded reads, delegating ALL cursor/retry logic to pinned 15A2.

No new API guesses, no GetAll or unbounded SaveToArray. Larger pages are an
explicit opt-in; 256 remains the default until native paired acceptance.
"""
from __future__ import annotations
from .common import parent_module, require
from . import com_busy

DEFAULTS = {'fast_geometry_page_size':256, 'fast_parent_page_size':256,
            'auto_tune':False, 'instrumentation':True}

def settings(value=None):
    value=value or {}
    require(not set(value)-set(DEFAULTS),'UNKNOWN_DIAGFAST_SETTING')
    out=dict(DEFAULTS,**value)
    for key in ('fast_geometry_page_size','fast_parent_page_size'):
        require(type(out[key]) is int and out[key] in (256,512,1024),
                'UNBENCHMARKED_DIAGFAST_PAGE_SIZE:'+key)
    require(out['auto_tune'] is False,'AUTOTUNE_REQUIRES_NATIVE_CAPACITY_ACCEPTANCE')
    require(type(out['instrumentation']) is bool,'INVALID_DIAGFAST_INSTRUMENTATION')
    return out

class _MeasuredOle:
    def __init__(self, target, telemetry, label, dseg):
        self.target=target;self.telemetry=telemetry;self.label=label;self.dseg=dseg
    def GetTypeInfo(self):
        with self.telemetry.span(self.label+'.TYPEINFO'):
            return self.target.GetTypeInfo()
    def Invoke(self, *args):
        first,last=args[-2:]
        t=self.telemetry
        t.count(self.label+'.provider_invoke_attempts')
        t.count('provider_invoke_attempts')
        t.count('dseg.'+str(self.dseg)+'.'+self.label+'.provider_attempts')
        t.count(self.label+'.requested_page_size.'+str(last-first+1))
        with t.span(self.label+'.PROVIDER_INVOKE'):
            try:
                result=self.target.Invoke(*args)
            except BaseException as exc:
                t.count(self.label+'.provider_invoke_errors')
                t.sample({'stage':self.label,'dseg':self.dseg,'first':first,'last':last,
                          'exception_type':type(exc).__name__})
                raise
        t.count(self.label+'.successful_page_calls')
        t.count(self.label+'.returned_rows',0 if result is None else len(result))
        return result

class _MeasuredTarget:
    def __init__(self, target, telemetry, label, dseg):
        self.target=target;self.telemetry=telemetry;self.label=label;self.dseg=dseg
    @property
    def _oleobj_(self):
        ole=self.target._oleobj_
        return None if ole is None else _MeasuredOle(ole,self.telemetry,self.label,self.dseg)

def rows(obj,columns,st,control,opt,phase,*,telemetry,fast_options,backend,**details):
    two=parent_module('r1_15a2_two_mode_v238')
    current=dict(st)
    if backend=='FAST_EXACT':
        key='fast_parent_page_size' if columns==two.PARENT_COLUMNS else 'fast_geometry_page_size'
        current['page_size']=fast_options[key]
        # Original validation establishes strictly bounded, descending fallback.
        current=two.validated_settings(current)
    base=com_busy.BoundedReadTarget(obj,control,opt,phase)
    measured=_MeasuredTarget(base,telemetry,phase,details.get('dseg'))
    yield from two.bounded_rows(measured,columns,current,control,phase,**details)
