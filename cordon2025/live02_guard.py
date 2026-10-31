"""Enforced LIVE02 write policy between the donor TG transaction and Visum.

Allowed mutations (everything else raises LIVE02_WRITE_FORBIDDEN):
* Net.Zones.SetMultiAttValues(<one of the 9 TG attributes>, rows[, False])
* <Procedures.Operations item>.SetAttValue('ACTIVE', 0|1)   (phase plan, restored)
* Procedures.Execute()                                     (native TG->TD->assignment)
* Workbench.Lists.Create*List / list.AddColumn / list.SetObjects (read lists)
* LIVE03 only (audit.td_writes): <TripDistributionParameters ...>.SetAttValue(<b or c>, number)

Matrix SetValues, TD/TG parameter objects, LoadVersion/SaveVersion, network
edits and any Add/Remove/Delete are rejected before reaching COM.
The audit trail is written to WRITE_AUDIT.jsonl.
"""
from __future__ import annotations
import json
import time
from pathlib import Path
from .live01_visum import is_com_method
from .live02_config import GENERATION_ATTRS

MUTATING_PREFIXES = ('Set', 'Save', 'Load', 'Execute', 'Add', 'Remove', 'Delete', 'Run', 'Create',
                     'Insert', 'Init', 'Clear', 'Import', 'Merge', 'Write')
READ_LIST_FACTORIES = ('CreatePrTPathList', 'CreatePrTPathLinkList', 'CreatePrTAssQualityList')
NON_MUTATING = {'SaveToArray'}  # bounded list export is a read
# LIVE03: gravity b/c of the TD DStrat parameters (donor TD_B_ATTRS/TD_C_ATTRS), never PARA_A.
TD_PARAMETER_ATTRS = frozenset(a.upper() for a in ('PARA_B', 'Para_B', 'ParaB', 'PARAM_B', 'ParamB', 'ParameterB', 'B',
                                                   'PARA_C', 'Para_C', 'ParaC', 'PARAM_C', 'ParamC', 'ParameterC', 'C'))


class WriteForbidden(PermissionError):
    pass


class WriteAudit:
    def __init__(self, path=None, allowed_zone_attrs=None):
        self.path = Path(path) if path else None
        self.allowed_zone_attrs = {str(a).upper() for a in (allowed_zone_attrs or GENERATION_ATTRS)}
        self.events = []
        self.counts = {}
        self.td_writes = False

    def record(self, kind, label, **details):
        event = {'t': time.time(), 'kind': kind, 'label': label}
        event.update(details)
        self.events.append(event)
        self.counts[kind] = self.counts.get(kind, 0) + 1
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open('a', encoding='utf-8') as f:
                f.write(json.dumps(event, ensure_ascii=True, default=str) + '\n')

    def summary(self):
        return {'counts': dict(self.counts),
                'tg_attributes_written': sorted({e['attr'] for e in self.events if e['kind'] == 'ZONE_TG_WRITE'}),
                'td_parameter_writes': sum(1 for e in self.events if e['kind'] == 'TD_PARAMETER_WRITE'),
                'forbidden_attempts': [e for e in self.events if e['kind'] == 'FORBIDDEN'],
                'direct_od_matrix_writes': 0, 'load_version_calls': 0, 'save_version_calls': 0}


def _policy(label, name, args, audit):
    """Return the audit kind for an allowed mutating call, else raise."""
    if label.endswith('.Net.Zones') and name == 'SetMultiAttValues':
        attr = args[0] if args else None
        if isinstance(attr, str) and attr.upper() in audit.allowed_zone_attrs:
            audit.record('ZONE_TG_WRITE', label, attr=attr, rows=len(args[1]) if len(args) > 1 else None)
            return
    elif ('.Procedures.Operations.' in label and 'Parameters' not in label
          and name == 'SetAttValue'):
        if args and str(args[0]).upper() == 'ACTIVE' and len(args) == 2 and int(args[1]) in (0, 1):
            audit.record('OPERATION_ACTIVE_FLAG', label, value=int(args[1]))
            return
    elif (getattr(audit, 'td_writes', False) and '.TripDistributionParameters' in label and name == 'SetAttValue'
          and len(args) == 2 and isinstance(args[0], str) and args[0].upper() in TD_PARAMETER_ATTRS
          and isinstance(args[1], (int, float)) and not isinstance(args[1], bool) and args[1] == args[1]):
        audit.record('TD_PARAMETER_WRITE', label, attr=args[0], value=float(args[1]))
        return
    elif label.endswith('.Procedures') and name == 'Execute' and not args:
        audit.record('PROCEDURES_EXECUTE', label)
        return
    elif label.endswith('.Workbench.Lists') and name in READ_LIST_FACTORIES:
        audit.record('READ_LIST_CREATE', label, list=name)
        return
    elif '.Workbench.Lists.' in label and name in ('AddColumn', 'SetObjects'):
        return
    audit.record('FORBIDDEN', label, method=name, args=repr(args)[:200])
    raise WriteForbidden('LIVE02_WRITE_FORBIDDEN:%s.%s' % (label, name))


_PRIMITIVE = (str, bytes, int, float, bool, complex, type(None))


def _plain(seq, depth=0):
    """Homogeneous primitive sequence (checked on every element of the outer level)."""
    for item in seq:
        if isinstance(item, _PRIMITIVE):
            continue
        if isinstance(item, (list, tuple)) and depth < 2:
            if all(isinstance(x, _PRIMITIVE) for x in item):
                continue
            if _plain(item, depth + 1):
                continue
        return False
    return True


class GuardedCOM:
    """Transparent read proxy; mutating calls must pass the LIVE02 policy."""
    __slots__ = ('_obj', '_label', '_audit')

    def __init__(self, obj, label='Visum', audit=None):
        object.__setattr__(self, '_obj', obj)
        object.__setattr__(self, '_label', label)
        object.__setattr__(self, '_audit', audit if audit is not None else WriteAudit())

    def __setattr__(self, name, value):
        self._audit.record('FORBIDDEN', self._label, method='__setattr__:' + name)
        raise WriteForbidden('LIVE02_PROPERTY_WRITE_FORBIDDEN:%s.%s' % (self._label, name))

    def _wrap(self, value, label):
        if value is None or isinstance(value, (str, bytes, int, float, bool, complex)):
            return value
        if type(value).__module__ == 'numpy':
            return value
        if isinstance(value, (list, tuple)) and _plain(value):
            return value  # fast path: matrices / GetMultiAttValues rows
        if isinstance(value, list):
            return [self._wrap(v, '%s[%d]' % (label, i)) for i, v in enumerate(value)]
        if isinstance(value, tuple):
            return tuple(self._wrap(v, '%s[%d]' % (label, i)) for i, v in enumerate(value))
        if isinstance(value, dict):
            return {k: self._wrap(v, '%s[%s]' % (label, k)) for k, v in value.items()}
        return GuardedCOM(value, label, self._audit)

    def __getattr__(self, name):
        if name == '_oleobj_':
            # Bounded raw OLE invokes are read paths used by the original capture.
            return getattr(self._obj, name)
        label = self._label + '.' + name
        value = getattr(self._obj, name)
        if is_com_method(value):
            mutating = name.startswith(MUTATING_PREFIXES) and name not in NON_MUTATING
            def call(*args, **kwargs):
                if mutating:
                    _policy(self._label, name, args, self._audit)
                return self._wrap(value(*args, **kwargs), label + '()')
            call.__name__ = name
            return call
        return self._wrap(value, label)

    def __iter__(self):
        for i, v in enumerate(self._obj):
            yield self._wrap(v, '%s[%d]' % (self._label, i))

    def __len__(self):
        return len(self._obj)

    def __getitem__(self, key):
        return self._wrap(self._obj[key], '%s[%s]' % (self._label, key))

    def __repr__(self):
        return '<GuardedCOM %s>' % self._label


def unwrap(value):
    return object.__getattribute__(value, '_obj') if isinstance(value, GuardedCOM) else value
