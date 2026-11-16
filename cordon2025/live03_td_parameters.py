"""Bind TD freeze checks to the immediate, verified native write readback.

The donor write/persistence contract permits 1e-8 representation error.  Its
freeze guard is exact.  Record the stored values *before* recomputation, then
keep that exact guard for the entire native trial.  No donor source is changed.
"""
from __future__ import annotations
import copy
import math
from pathlib import Path
from .common import require, parent_module
from .io import write_json, exception_text

WRITE_TOLERANCE = 1.0e-8  # existing r1_15a2_visum_parameters write/readback limit


def _number(value):
    require(not isinstance(value, bool) and value is not None,
            'LIVE03_TD_INVALID_PARAMETER_NUMBER')
    value = float(value)
    require(math.isfinite(value), 'LIVE03_TD_INVALID_PARAMETER_NUMBER')
    return value


def _index(rows):
    out = {}
    for row in rows:
        key = row['component']
        require(key and key not in out, 'LIVE03_TD_DUPLICATE_COMPONENT:' + str(key))
        out[key] = row
    return out


def parameter_diff(expected, live):
    """Small, exact field diff; include missing/extra components and statuses."""
    e, a = _index(expected), _index(live)
    out = []
    for comp in sorted(set(e) | set(a)):
        er, ar = e.get(comp), a.get(comp)
        if er is None or ar is None:
            out.append({'component': comp, 'field': 'component',
                        'expected': er, 'live': ar})
            continue
        for key in sorted(set(er) | set(ar)):
            if er.get(key) != ar.get(key):
                item = {'component': comp, 'field': key,
                        'expected': er.get(key), 'live': ar.get(key)}
                if key in ('current_b', 'current_c') and er.get(key) is not None and ar.get(key) is not None:
                    item['delta'] = float(ar[key]) - float(er[key])
                out.append(item)
    return out


def expected_parameters(before, rows):
    expected = copy.deepcopy(before['td_values'])
    by = _index(expected)
    _index(rows)
    for row in rows:
        comp = row['component']
        require(comp in by, 'LIVE03_TD_UNKNOWN_COMPONENT:' + comp)
        for p in ('b', 'c'):
            require(_number(row['current_' + p]) == _number(by[comp]['current_' + p]),
                    'LIVE03_TD_EXPECTED_OLD_CHANGED:' + comp + ':' + p)
            by[comp]['current_' + p] = _number(row['candidate_' + p])
    return expected


def bind_write_readback(before, requested, live):
    """Return effective candidate rows, accepting only bounded setter error.

    All untargeted values and statuses remain exact.  The returned rows are a
    copy; planner rows retain their original values for the search audit.
    """
    expected = expected_parameters(before, requested)
    actual = _index(live)
    requested_by = _index(requested)
    require(set(actual) == set(_index(expected)), 'LIVE03_TD_WRITE_COMPONENT_SET_CHANGED')
    for row in live:
        require(row.get('status') == 'OK', 'LIVE03_TD_WRITE_INVALID_STATUS:' + row['component'])
        _number(row['current_b']); _number(row['current_c'])
    differences = parameter_diff(expected, live)
    for diff in differences:
        require(diff['component'] in requested_by and diff['field'] in ('current_b', 'current_c'),
                'UNREQUESTED_TD_PARAMETER_CHANGE_AT_WRITE')
        require(abs(diff['delta']) <= WRITE_TOLERANCE, 'LIVE03_TD_WRITE_READBACK_OUTSIDE_TOLERANCE')
    effective = []
    for row in requested:
        got = actual[row['component']]
        require(got['current_b'] >= 0 and got['current_c'] < 0,
                'LIVE03_TD_WRITE_READBACK_OUTSIDE_PARAMETER_DOMAIN')
        effective.append(dict(row, requested_b=row['candidate_b'], requested_c=row['candidate_c'],
                              candidate_b=got['current_b'], candidate_c=got['current_c']))
    return effective, differences


def capture_write_readback(adapter, before, requested, folder):
    """Read once immediately after the donor write, before any procedure runs."""
    vp = parent_module('r1_15a2_visum_parameters')
    live = [{k: row.get(k) for k in ('component', 'current_b', 'current_c', 'status')}
            for row in vp.read_td_parameter_state(adapter.visum)['rows']]
    audit = {'schema': 'LIVE03_TD_WRITE_READBACK_V1', 'status': 'CHECKING',
             'write_tolerance': WRITE_TOLERANCE, 'requested': requested, 'live': live}
    try:
        audit['differences'] = parameter_diff(expected_parameters(before, requested), live)
        actual, differences = bind_write_readback(before, requested, live)
        audit.update(status='VERIFIED', differences=differences, effective=actual,
                     representation_changes=len(differences))
    except Exception as exc:
        audit.update(status='FAILED', error=exception_text(exc))
        write_json(Path(folder) / 'TD_PARAMETER_WRITE_READBACK.json', audit)
        raise
    write_json(Path(folder) / 'TD_PARAMETER_WRITE_READBACK.json', audit)
    return actual, {'status': audit['status'], 'representation_changes': len(differences),
                    'write_tolerance': WRITE_TOLERANCE}


def assert_trial_freeze(base, before, after, block, actual, candidate, cfg, folder):
    """Run the unchanged donor guard and record exactly which TD fields differ."""
    audit = {'schema': 'LIVE03_TD_PARAMETER_FREEZE_V1', 'status': 'CHECKING',
             'basis': 'EXACT_IMMEDIATE_NATIVE_WRITE_READBACK',
             'differences': parameter_diff(expected_parameters(before, actual), after['td_values'])}
    try:
        base.assert_freeze(before, after, block, rows=actual, candidate=candidate, cfg=cfg)
    except Exception as exc:
        audit.update(status='FAILED', error=exception_text(exc))
        write_json(Path(folder) / 'TD_PARAMETER_FREEZE.json', audit)
        raise
    audit['status'] = 'VERIFIED'
    write_json(Path(folder) / 'TD_PARAMETER_FREEZE.json', audit)
