"""Frozen trip-distance authority (2026-11-17): Visum DIS skims instead of OSRM 9697.

``RUN_R1_2025_FREEZE_SKIM_DISTANCES.py`` copies the PrT DIS skims of the six native
car segments of one saved, fully computed version into DATA matrices 9720..9725
(intrazonal diagonal from 9697, because DIS has no intrazonal distance) and writes
two IDP blends: 9726 = WORK/SCHOOL (CW and CW_noT weighted by the OD split ratio
9231) and 9727 = SERVICE (CS and CS_noT weighted by 9233).  The matrices are
frozen: they never follow the assignment of a trial.

Consumers in the calibrator:
* LONG post-TD mask (v7 >= 80 km): ``long_post_td_mask.distance_matrix_no`` -
  the donor ``r1_15a2_long_support_distance_v24917.read_current`` reads the
  matrix bound here (9721 = NATIVE_CL, the segment that carries LONG demand);
* IDP guard / IDP-aware TD step: ``idp_guard.distance_matrices`` maps every
  FineCDF component to its own distance matrix.

9697 (OSRM) stays in the model unchanged for provenance.  Its absence of
change is not checked here; LIVE01 still reads it.
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
from .common import require, parent_module
from .io import write_json

SCHEMA = 'R1C25_FROZEN_DISTANCE_AUTHORITY_V1'
OSRM = (9697, 'R1_OSRM_DIST_KM')
SEGMENTS = ('NATIVE_CF', 'NATIVE_CL', 'NATIVE_CS', 'NATIVE_CS_NOT', 'NATIVE_CW', 'NATIVE_CW_NOT')
FROZEN = {9720 + i: 'R1_BASE_DIS_%s_KM' % s for i, s in enumerate(SEGMENTS)}
FROZEN[9726] = 'R1_BASE_DIS_IDP_WORK_KM'
FROZEN[9727] = 'R1_BASE_DIS_IDP_SERV_KM'
CODES = {**FROZEN, OSRM[0]: OSRM[1]}
LONG_ALLOWED = {OSRM, (9721, FROZEN[9721])}
# FineCDF v1.9 component -> frozen distance (prefix match on "<key>" or "<key>_...")
IDP_DEFAULT = {'WORK': 9726, 'SCHOOL': 9726, 'SERV': 9727, 'LONG_COMPOSITE': 9721}

_DONOR = 'r1_15a2_long_support_distance_v24917'
_DONOR_DEFAULT = None


def bind_long_distance(no, code):
    """Point the donor LONG support reader at matrix ``no`` (module globals, read at call time)."""
    global _DONOR_DEFAULT
    no, code = int(no), str(code)
    require((no, code) in LONG_ALLOWED, 'LIVE04_LONG_DISTANCE_NOT_ALLOWED:%d:%s' % (no, code))
    mod = parent_module(_DONOR)
    if _DONOR_DEFAULT is None:
        _DONOR_DEFAULT = (mod.MATRIX_NO, mod.MATRIX_CODE, mod.DISTANCE_BASIS)
        require(_DONOR_DEFAULT[:2] == OSRM, 'LIVE04_LONG_DISTANCE_DONOR_DEFAULT_CHANGED')
    mod.MATRIX_NO = no
    mod.MATRIX_CODE = code
    mod.DISTANCE_BASIS = 'FIXED_OSRM_DIST_KM_9697' if no == OSRM[0] else 'FROZEN_VISUM_DIS_%d' % no
    return {'matrix_no': no, 'matrix_code': code, 'distance_basis': mod.DISTANCE_BASIS}


def bound_long_distance():
    mod = parent_module(_DONOR)
    return int(mod.MATRIX_NO), str(mod.MATRIX_CODE)


def idp_component_map(keys, mapping):
    """Resolve the configured prefix map to {component: matrix_no}; every component exactly once."""
    out = {}
    for k in keys:
        hits = [int(no) for p, no in mapping.items() if k == p or k.startswith(p + '_')]
        require(len(hits) == 1, 'LIVE04_IDP_DISTANCE_MAP:%s:%d' % (k, len(hits)))
        require(hits[0] in CODES, 'LIVE04_IDP_DISTANCE_UNKNOWN_MATRIX:%s:%d' % (k, hits[0]))
        out[k] = hits[0]
    return out


def validate_mapping(mapping):
    require(isinstance(mapping, dict) and mapping, 'LIVE04_IDP_DISTANCE_MAP_FORMAT')
    for p, no in mapping.items():
        require(isinstance(p, str) and p and isinstance(no, int) and not isinstance(no, bool) and no in CODES,
                'LIVE04_IDP_DISTANCE_MAP_ENTRY:%s' % p)


def read_distance(visum, no, n):
    """One distance matrix by number with its pinned CODE; finite, >= 0, n x n."""
    m = visum.Net.Matrices.ItemByKey(int(no))
    require(m is not None, 'DISTANCE_MATRIX_MISSING:%d' % no)
    code = str(m.AttValue('CODE')).strip().upper()
    require(code == CODES[int(no)], 'DISTANCE_MATRIX_CODE:%d:%s (run RUN_R1_2025_FREEZE_SKIM_DISTANCES.py)'
            % (no, code))
    arr = np.array(m.GetValues(), dtype=np.float64, copy=True)
    require(arr.shape == (n, n) and np.isfinite(arr).all() and (arr >= 0).all(), 'DISTANCE_MATRIX_INVALID:%d' % no)
    return arr


def configured(cfg):
    """Matrices the LIVE04 config reads: {matrix_no: [roles]}."""
    out = {}
    lm = cfg['v7']['long_post_td_mask']
    if lm.get('enabled'):
        out.setdefault(int(lm['distance_matrix_no']), []).append('LONG_POST_TD_MASK')
    idp = cfg.get('idp_guard') or {}
    if idp.get('enabled'):
        for p, no in (idp.get('distance_matrices') or {'ALL': OSRM[0]}).items():
            out.setdefault(int(no), []).append('IDP:' + p)
    return out


def preflight(visum, cfg, n, folder=None):
    """Run start: every configured distance matrix exists with its CODE and valid values."""
    rows = []
    for no, roles in sorted(configured(cfg).items()):
        try:
            arr = read_distance(visum, no, n)
        except Exception as exc:
            rows.append({'matrix_no': no, 'roles': roles, 'status': 'FAIL', 'error': str(exc)[:300]})
            continue
        off = ~np.eye(n, dtype=bool)
        rows.append({'matrix_no': no, 'code': CODES[no], 'roles': roles, 'status': 'PASS',
                     'offdiag_min_km': float(arr[off].min()) if n > 1 else None,
                     'mean_km': float(arr.mean()), 'diag_mean_km': float(arr.diagonal().mean())})
    out = {'schema': SCHEMA, 'status': 'PASS' if all(r['status'] == 'PASS' for r in rows) else 'FAIL',
           'matrices': rows, 'long_bound': list(bound_long_distance())}
    if folder is not None:
        write_json(Path(folder) / 'DISTANCE_AUTHORITY.json', out)
    bad = [r for r in rows if r['status'] != 'PASS']
    require(not bad, 'DISTANCE_AUTHORITY_PREFLIGHT:' + ';'.join('%d:%s' % (r['matrix_no'], r['error']) for r in bad)[:600])
    return out
