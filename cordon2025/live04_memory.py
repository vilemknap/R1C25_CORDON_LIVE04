"""LIVE04.1 run memory between cycles (prediction only, never acceptance).

What is kept from one cycle to the next (one cordon run, in memory, audited to
the run folder after every block as RUN_MEMORY.json + RUN_MEMORY_TD_J.npz):

* TD_CORDON: the Broyden-updated Jacobian of the cordon rows (every method)
  with respect to the grouped b/c parameters, including the rank-1 correction
  from the measured full trial.  The next TD block starts from it and verifies
  it with ONE native probe along the planned first step; if the probe disagrees
  beyond ``td_verify_tolerance`` the block falls back to the full per-parameter
  Jacobian (the LIVE04 behaviour).
* GENERATION: the route-choice correction measured by the last full trial,
  c = (measured - frozen-path prediction) / scale per cordon row and per unit
  norm of the step direction (zonal log steps).  It is reused only for a
  similar direction (cosine >= ``tg_min_direction_cosine``), scaled to the new
  step norm and damped by ``tg_correction_weight * tg_correction_decay**(age-1)``.
* GENERATION: the measured curvature of the native nodes,
  |n(1) - 2 n(0.5) + m0| / |n(1) - m0|.  Below ``tg_single_node_curvature`` the
  next block probes only the largest node (piecewise-linear prediction).

Entries older than ``max_age_cycles`` are ignored.  Memory never changes the
acceptance authority: every step is still a full native trial with the cordon
gate, mobility, LONG and IDP guards and the verified rollback.
"""
from __future__ import annotations
import math
from pathlib import Path
import numpy as np
from .io import write_json, mkdir

SCHEMA = 'LIVE04_1_RUN_MEMORY_V1'


def direction_from_rows(rows, bd=None):
    """Zonal log-step direction of a Generation proposal (scale 1)."""
    out = {}
    for r in rows or []:
        out['%s|%s|%d' % (r['family'], r['role'], int(r['zone_no']))] = float(r.get('log_step', 0.0) or 0.0)
    for key, step in ((bd or {}).get('steps') or {}).items():
        out['BND|' + str(key)] = float(step)
    return {k: v for k, v in out.items() if v}


def _norm(d):
    return math.sqrt(sum(v * v for v in d.values()))


def _cosine(a, b):
    na, nb = _norm(a), _norm(b)
    if na <= 0 or nb <= 0:
        return 0.0
    return sum(v * b.get(k, 0.0) for k, v in a.items()) / (na * nb)


class RunMemory:
    def __init__(self, cfg, folder=None):
        self.cfg = dict(cfg)
        self.folder = Path(folder) if folder else None
        self.cycle = 0
        self.td = None            # {'names', 'J': {m: array}, 'cycle', 'source'}
        self.tg = None            # {'direction', 'norm', 'correction': {m: array}, 'cycle', 'scale'}
        self.curvature = None     # {'value', 'cycle'}
        self.events = []

    # ------------------------------------------------------------ cycle
    def begin_cycle(self, cycle):
        self.cycle = int(cycle)

    def _fresh(self, entry):
        return entry is not None and 0 <= self.cycle - int(entry['cycle']) <= int(self.cfg['max_age_cycles'])

    def _event(self, kind, **kw):
        self.events.append(dict(kind=kind, cycle=self.cycle, **kw))

    # --------------------------------------------------------------- TD
    def td_jacobian(self, names, rows_by_method):
        if not (self.cfg['enabled'] and self.cfg['td_jacobian_reuse']) or not self._fresh(self.td):
            return None
        if list(self.td['names']) != list(names):
            self._event('TD_JACOBIAN_NOT_REUSED', reason='PARAMETER_SPACE_CHANGED')
            return None
        if set(self.td['J']) != set(rows_by_method) or any(self.td['J'][m].shape[0] != n for m, n in rows_by_method.items()):
            self._event('TD_JACOBIAN_NOT_REUSED', reason='ROW_AXIS_CHANGED')
            return None
        return {m: J.copy() for m, J in self.td['J'].items()}

    def td_idp_jacobian(self, names, n_components):
        """LIVE04.10.5: IDP guard Jacobian stored with the TD Jacobian (same probes), or None."""
        if not (self.cfg['enabled'] and self.cfg['td_jacobian_reuse']) or not self._fresh(self.td):
            return None
        F = self.td.get('idp')
        if F is None or list(self.td['names']) != list(names) or F.shape != (2 * int(n_components), len(names)):
            return None
        return F.copy()

    def store_td(self, names, J, source, idp=None):
        if not self.cfg['enabled']:
            return
        self.td = {'names': list(names), 'J': {m: np.array(v, dtype=float, copy=True) for m, v in J.items()},
                   'cycle': self.cycle, 'source': source,
                   'idp': None if idp is None else np.array(idp, dtype=float, copy=True)}
        self._event('TD_JACOBIAN_STORED', source=source)

    # --------------------------------------------------------------- TG
    def node_fractions(self, fractions):
        fractions = list(fractions or [])
        if (self.cfg['enabled'] and len(fractions) > 1 and self._fresh(self.curvature)
                and self.curvature['value'] <= float(self.cfg['tg_single_node_curvature'])):
            self._event('TG_SINGLE_NODE', curvature=self.curvature['value'])
            return [max(fractions)]
        return fractions

    def record_curvature(self, nodes, m0, method):
        if not self.cfg['enabled'] or 1.0 not in nodes or 0.5 not in nodes:
            return None
        n1, nh, base = (np.asarray(nodes[1.0][method]), np.asarray(nodes[0.5][method]), np.asarray(m0[method]))
        den = float(np.linalg.norm(n1 - base))
        if den <= 1e-12:
            return None
        value = float(np.linalg.norm(n1 - 2.0 * nh + base)) / den
        self.curvature = {'value': value, 'cycle': self.cycle}
        self._event('TG_CURVATURE', value=value)
        return value

    def tg_correction(self, direction):
        """Route-choice correction per unit scale for this direction, or None."""
        if not (self.cfg['enabled'] and self.cfg['tg_route_correction']) or not self._fresh(self.tg):
            return None, None
        age = self.cycle - int(self.tg['cycle'])
        if age < 1:
            return None, None
        cos = _cosine(direction, self.tg['direction'])
        info = {'cosine': cos, 'age': age, 'source_cycle': self.tg['cycle']}
        if cos < float(self.cfg['tg_min_direction_cosine']):
            self._event('TG_CORRECTION_NOT_USED', **info)
            return None, dict(info, used=False)
        weight = float(self.cfg['tg_correction_weight']) * float(self.cfg['tg_correction_decay']) ** (age - 1)
        factor = weight * _norm(direction) / max(self.tg['norm'], 1e-300)
        info.update(used=True, weight=weight, norm_ratio=_norm(direction) / max(self.tg['norm'], 1e-300))
        self._event('TG_CORRECTION_USED', **info)
        return {m: factor * c for m, c in self.tg['correction'].items()}, info

    def record_tg_correction(self, direction, scale, measured, prior):
        """measured/prior: {method: rows} at this scale; prior = prediction WITHOUT memory."""
        if not self.cfg['enabled'] or scale <= 0 or not direction:
            return
        corr = {m: (np.asarray(measured[m], dtype=float) - np.asarray(prior[m], dtype=float)) / float(scale)
                for m in measured}
        self.tg = {'direction': dict(direction), 'norm': _norm(direction), 'correction': corr,
                   'cycle': self.cycle, 'scale': float(scale)}
        self._event('TG_CORRECTION_STORED', scale=float(scale),
                    l2={m: float(np.linalg.norm(c)) for m, c in corr.items()})

    # ------------------------------------------------------------ audit
    def summary(self):
        return {'schema': SCHEMA, 'config': self.cfg, 'cycle': self.cycle,
                'td': None if self.td is None else {'names': self.td['names'], 'cycle': self.td['cycle'],
                                                   'source': self.td['source'],
                                                   'idp_jacobian': self.td.get('idp') is not None},
                'tg': None if self.tg is None else {'cycle': self.tg['cycle'], 'scale': self.tg['scale'],
                                                   'direction_size': len(self.tg['direction']), 'norm': self.tg['norm']},
                'curvature': self.curvature, 'events': self.events}

    # ------------------------------------------------------------ state (LIVE04.14 continuation)
    STATE_SCHEMA = 'LIVE04_1_RUN_MEMORY_STATE_V1'

    def state(self):
        """Complete learned state (JSON) for the state-bound memory snapshots."""
        def arr(a):
            return None if a is None else np.asarray(a, dtype=float).tolist()
        td = None if self.td is None else {
            'names': list(self.td['names']), 'J': {m: arr(J) for m, J in self.td['J'].items()},
            'cycle': int(self.td['cycle']), 'source': self.td['source'], 'idp': arr(self.td.get('idp'))}
        tg = None if self.tg is None else {
            'direction': dict(self.tg['direction']), 'norm': float(self.tg['norm']),
            'correction': {m: arr(c) for m, c in self.tg['correction'].items()},
            'cycle': int(self.tg['cycle']), 'scale': float(self.tg['scale'])}
        return {'schema': self.STATE_SCHEMA, 'td': td, 'tg': tg,
                'curvature': None if self.curvature is None else dict(self.curvature)}

    def load_state(self, state):
        """Restore a saved state; (ok, reason).  Every entry is validated (finite arrays)."""
        if not isinstance(state, dict) or state.get('schema') != self.STATE_SCHEMA:
            return False, 'SCHEMA'
        try:
            td, tg = state.get('td'), state.get('tg')
            if td is not None:
                J = {m: np.asarray(v, dtype=float) for m, v in td['J'].items()}
                idp = None if td.get('idp') is None else np.asarray(td['idp'], dtype=float)
                if not all(np.isfinite(a).all() and a.ndim == 2 for a in J.values()) or \
                        (idp is not None and not np.isfinite(idp).all()):
                    return False, 'TD_NONFINITE'
                td = dict(td, J=J, idp=idp)
            if tg is not None:
                corr = {m: np.asarray(v, dtype=float) for m, v in tg['correction'].items()}
                if not all(np.isfinite(a).all() for a in corr.values()):
                    return False, 'TG_NONFINITE'
                tg = dict(tg, correction=corr)
        except (KeyError, TypeError, ValueError):
            return False, 'MALFORMED'
        self.td, self.tg = td, tg
        self.curvature = state.get('curvature')
        self._event('RUN_MEMORY_RESTORED', td=td is not None, tg=tg is not None)
        return True, 'LOADED'

    def save(self):
        if self.folder is None:
            return
        mkdir(self.folder)
        write_json(self.folder / 'RUN_MEMORY.json', self.summary())
        if self.td is not None:
            arrays = {m: J for m, J in self.td['J'].items()}
            if self.td.get('idp') is not None:
                arrays['IDP_GUARD_FEATURES'] = self.td['idp']
            np.savez(self.folder / 'RUN_MEMORY_TD_J.npz', **arrays)
