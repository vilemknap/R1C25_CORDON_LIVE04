"""LIVE04 write policy = LIVE03 policy + the v7-authorized LONG post-TD mask.

The only new permission (audit.long_mask_writes, from write_policy):
    <Net.Matrices.ItemByKey(N)>.SetValues(<2-D float64 numpy array>, False)
for N in the LONG person matrices 9111..9115 and the LONG vehicle components
9291..9295 (donor r1_15a2_long_post_td_mask_v24917.apply_group).  The FORMULA
aggregate 9305, the frozen foreign matrix 9116, every demand-segment OD matrix
and every other matrix remain forbidden, as do all other LIVE02/LIVE03 rules.
To make the matrix number visible to the policy, ItemByKey on the matrix
collection carries its key in the audit label.
"""
from __future__ import annotations
import re
from .live02_guard import GuardedCOM, WriteAudit, WriteForbidden, _policy as _live03_policy, _plain, MUTATING_PREFIXES, \
    NON_MUTATING
from .live01_visum import is_com_method

LONG_PERSON_MATRICES = (9111, 9112, 9113, 9114, 9115)
LONG_VEHICLE_COMPONENTS = (9291, 9292, 9293, 9294, 9295)
LONG_MASK_WRITABLE = frozenset(LONG_PERSON_MATRICES + LONG_VEHICLE_COMPONENTS)
_MATRIX_LABEL = re.compile(r'\.Net\.Matrices\.ItemByKey\((\d+)\)\(\)$|\.Net\.Matrices\.ItemByKey\((\d+)\)$')


class Live04WriteAudit(WriteAudit):
    def __init__(self, path=None, allowed_zone_attrs=None):
        super().__init__(path, allowed_zone_attrs)
        self.long_mask_writes = False

    def summary(self):
        out = super().summary()
        out['long_mask_matrix_writes'] = sum(1 for e in self.events if e['kind'] == 'LONG_MASK_MATRIX_WRITE')
        out['long_mask_matrices_written'] = sorted({e['matrix_no'] for e in self.events
                                                    if e['kind'] == 'LONG_MASK_MATRIX_WRITE'})
        # Demand-segment OD matrices are still never written directly.
        out['direct_od_matrix_writes'] = 0
        return out


def _matrix_no(label):
    m = _MATRIX_LABEL.search(label)
    if not m:
        return None
    return int(m.group(1) or m.group(2))


def _policy(label, name, args, audit):
    if name == 'SetValues':
        no = _matrix_no(label)
        if (no is not None and no in LONG_MASK_WRITABLE and getattr(audit, 'long_mask_writes', False)
                and len(args) == 2 and args[1] is False and type(args[0]).__module__ == 'numpy'
                and getattr(args[0], 'ndim', 0) == 2 and str(getattr(args[0], 'dtype', '')) == 'float64'):
            import numpy as np
            a = args[0]
            if np.isfinite(a).all() and not np.any(a < 0):
                audit.record('LONG_MASK_MATRIX_WRITE', label, matrix_no=no, shape=list(a.shape),
                             total=float(a.sum()))
                return
        audit.record('FORBIDDEN', label, method=name, args=repr(args)[:200])
        raise WriteForbidden('LIVE04_MATRIX_WRITE_FORBIDDEN:%s.%s' % (label, name))
    return _live03_policy(label, name, args, audit)


class Live04GuardedCOM(GuardedCOM):
    """GuardedCOM whose children are of the same class and whose matrix labels carry the key.

    Subclasses may widen the policy only by overriding POLICY (one audited function)."""
    __slots__ = ()
    POLICY = staticmethod(_policy)

    def _wrap(self, value, label):
        if value is None or isinstance(value, (str, bytes, int, float, bool, complex)):
            return value
        if type(value).__module__ == 'numpy':
            return value
        if isinstance(value, (list, tuple)) and _plain(value):
            return value
        if isinstance(value, list):
            return [self._wrap(v, '%s[%d]' % (label, i)) for i, v in enumerate(value)]
        if isinstance(value, tuple):
            return tuple(self._wrap(v, '%s[%d]' % (label, i)) for i, v in enumerate(value))
        if isinstance(value, dict):
            return {k: self._wrap(v, '%s[%s]' % (label, k)) for k, v in value.items()}
        return type(self)(value, label, self._audit)

    def __getattr__(self, name):
        if name == '_oleobj_':
            return getattr(self._obj, name)
        label = self._label + '.' + name
        value = getattr(self._obj, name)
        if is_com_method(value):
            mutating = name.startswith(MUTATING_PREFIXES) and name not in NON_MUTATING
            keyed = name == 'ItemByKey' and self._label.endswith('.Net.Matrices')

            def call(*args, **kwargs):
                if mutating:
                    type(self).POLICY(self._label, name, args, self._audit)
                out = value(*args, **kwargs)
                if keyed and len(args) == 1:
                    try:
                        return self._wrap(out, '%s(%d)' % (label, int(args[0])))
                    except (TypeError, ValueError):
                        pass
                return self._wrap(out, label + '()')
            call.__name__ = name
            return call
        return self._wrap(value, label)

    def __iter__(self):
        for i, v in enumerate(self._obj):
            yield self._wrap(v, '%s[%d]' % (self._label, i))

    def __getitem__(self, key):
        return self._wrap(self._obj[key], '%s[%s]' % (self._label, key))

    def __repr__(self):
        return '<Live04GuardedCOM %s>' % self._label
