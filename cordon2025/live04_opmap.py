"""LIVE04.12 OPMAP1: procedure-sequence roles of the live 2025 model.

The donor (v7 @ 7b4c681) and the LIVE01-04 layers were written against the legacy
43-operation 09C sequence: TG 5, TD 6, resets 1 / 15, partial assignments 17-19,
joint 14-DSeg assignment 20, GEH script 21.  Since 2026-11 the R1 models nest the
demand steps in more groups, so the same roles can sit at other positions.

The role resolution is the user's OPMAP1 module
(``parent/r1_15a2_procseq_roles_v24917.py``, verbatim from R1_15A2_V24917_v7 branch
``claude-opmap1-procseq-roles-20261111``):

* a model whose roles sit at the legacy positions maps to the identity - nothing
  changes compared with LIVE04.11.1;
* otherwise every role is found by its signature (operation type, ACTIVE, exact
  DSEGSET, order TG < TD < reset < assignments); a missing or ambiguous role fails
  closed with ``OPMAP1_*``.  Nothing is guessed and no operation is changed.

LIVE04.12.1 SUE freight layout (R1_BASE_PROCEDURE_2025_SUE_V3_NODESVDF, user decision
2026-11-15 "zamer: nakladni jen SUE").  When the verbatim resolver rejects the layout,
one more signature is accepted - and only this one:

* freight = two consecutive active PrT assignments with DSEGSET exactly {LNV} and {NV}
  (stochastic SUE), in place of one {LNV, NV} assignment;
* the final joint assignment (GAP/COUNT authority) = exactly the 12 passenger DSegs
  (EXOG_EE_* + NATIVE_*); LNV/NV volumes of the SUE operations are its preload.  The
  cordon observations, capture and objective use the same 12 passenger DSegs;
* no active reset before TG is required (RESET_PRE absent); the reset between TD and
  the first assignment (RESET_POST) is required exactly once, as before.

Every other role rule (one active TG, one active TD, order, exact DSEGSET of the
passenger partial assignments) is unchanged.  In this layout the donor configuration
is translated for the run: assignment rule 20 -> live position with the live 12-DSeg
scope, and ``supply.freight_dsegs`` is empty inside the assignment-plan check (freight
is not part of the final authority; it is still executed in every recomputation).

``scope`` installs the translation on the donor entry points used by the cordon run
(assignment-scope authority V239/V240, PERF1 phase plan, supply_visum assignment plan
and GAP readback, and the role resolver used by the LONG mask) for ONE run and
restores them on exit.  It is idempotent per configuration.
"""
from contextlib import contextmanager
import copy
import functools
from pathlib import Path

from .common import parent_module, require, write_json

SCHEMA = 'LIVE04_OPMAP1_V2'
LEGACY_TG, LEGACY_TD = 5, 6
SUE_MODE = 'RESOLVED_BY_SIGNATURE_LIVE04_SUE_FREIGHT_SPLIT'
_MARK = '__live04_opmap1__'
_PATCH = {'depth': 0, 'saved': None}


def roles_module():
    return parent_module('r1_15a2_procseq_roles_v24917')


# ------------------------------------------------------------------ resolver
def _sue_final_scope(roles):
    return frozenset(roles.ASSIGNMENT_DSEGS['ASG_FINAL'] - {'LNV', 'NV'})


def _resolve_sue(roles, rows, first_error):
    """The one extra layout: split SUE freight + 12-DSeg joint passenger assignment."""
    com = parent_module('r1_15a2_com_compat')
    pos, typ = roles._pos, roles._type
    active = [r for r in rows if int(r['active'])]
    tg = [pos(r) for r in active if typ(r) == com.TG]
    td = [pos(r) for r in active if typ(r) == com.TD]
    if len(td) != 1:
        raise roles.OpmapError('OPMAP1_EXPECTED_ONE_ACTIVE_TD_FOUND_%d' % len(td))
    td_pos = td[0]
    asg = [r for r in active if typ(r) == com.ASSIGNMENT_PRT]
    by_scope = {}
    for r in asg:
        by_scope.setdefault(roles.dsegset(r), []).append(pos(r))

    def one(scope, label):
        hits = by_scope.get(frozenset(scope), [])
        if len(hits) != 1:
            raise roles.OpmapError('OPMAP1_SUE_ROLE_%s_FOUND_%d;first=%s' % (label, len(hits), first_error))
        return hits[0]
    lnv, nv = one({'LNV'}, 'LNV'), one({'NV'}, 'NV')
    cf = one(roles.ASSIGNMENT_DSEGS['ASG_CF_CL'], 'ASG_CF_CL')
    cs = one(roles.ASSIGNMENT_DSEGS['ASG_CS_CW'], 'ASG_CS_CW')
    final = one(_sue_final_scope(roles), 'ASG_FINAL_12')
    freight = sorted((lnv, nv))
    if freight[1] - freight[0] != 1:
        raise roles.OpmapError('OPMAP1_SUE_FREIGHT_NOT_CONSECUTIVE:%s' % freight)
    known = set(freight) | {cf, cs, final}
    if any(pos(r) not in known for r in asg):
        raise roles.OpmapError('OPMAP1_SUE_UNEXPECTED_ACTIVE_ASSIGNMENT:%s' % sorted(pos(r) for r in asg))
    order = [freight[0], freight[1], cf, cs, final]
    if order != sorted(order) or order[0] <= td_pos:
        raise roles.OpmapError('OPMAP1_SUE_ASSIGNMENT_ORDER:%s;td=%d' % (order, td_pos))
    pre = [pos(r) for r in active if typ(r) == roles.RESET_TYPE and tg and pos(r) < min(tg)]
    post = [pos(r) for r in active if typ(r) == roles.RESET_TYPE and td_pos < pos(r) < order[0]]
    if len(pre) > 1:
        raise roles.OpmapError('OPMAP1_ROLE_RESET_PRE_FOUND_%d' % len(pre))
    if len(post) != 1:
        raise roles.OpmapError('OPMAP1_ROLE_RESET_POST_FOUND_%d' % len(post))
    out = {'RESET_PRE': pre[0] if pre else None, 'RESET_POST': post[0], 'ASG_FREIGHT': freight[0],
           'ASG_CF_CL': cf, 'ASG_CS_CW': cs, 'ASG_FINAL': final, 'POST_GEH': None}
    nxt = [r for r in rows if pos(r) > final and typ(r) != com.GROUP]
    if nxt and typ(nxt[0]) == com.EXECUTE_SCRIPT:
        text = (str(nxt[0].get('comment', '')) + ' ' + str(nxt[0].get('name', ''))).upper()
        if any(t in text for t in roles.POST_GEH_TOKENS):
            out['POST_GEH'] = pos(nxt[0])
    legacy_to_live = {roles.LEGACY[k]: v for k, v in out.items() if v is not None}
    scopes = {lnv: frozenset({'LNV'}), nv: frozenset({'NV'}), cf: roles.ASSIGNMENT_DSEGS['ASG_CF_CL'],
              cs: roles.ASSIGNMENT_DSEGS['ASG_CS_CW'], final: _sue_final_scope(roles)}
    return {'schema': 'R1_15A2_OPMAP1_ROLES_V1', 'release': roles.RELEASE, 'mode': SUE_MODE,
            'roles': out, 'legacy_to_live': legacy_to_live, 'operation_count': len(rows),
            'td_position': td_pos, 'tg_positions': tg, 'freight_positions': freight,
            'freight_split': {'LNV': lnv, 'NV': nv}, 'final_scope': sorted(_sue_final_scope(roles)),
            'live_scopes': {int(k): sorted(v) for k, v in scopes.items()},
            'verbatim_resolver_error': str(first_error)}


def _resolve_any(orig, source):
    roles = roles_module()
    rows = roles._rows(source)
    try:
        return orig(rows)
    except roles.OpmapError as exc:
        if 'ASG_FREIGHT_FOUND_0' not in str(exc) and 'ASG_FINAL_FOUND_0' not in str(exc) \
                and 'RESET_PRE_FOUND_0' not in str(exc):
            raise
        return _resolve_sue(roles, rows, exc)


def _expected_by_live(source):
    roles = roles_module()
    info = roles.resolve(source)
    if info['mode'] == SUE_MODE:
        return {int(k): frozenset(v) for k, v in info['live_scopes'].items()}
    return {int(info['roles'][r]): d for r, d in roles.ASSIGNMENT_DSEGS.items()}


@contextmanager
def _patched_resolver():
    """roles.resolve / expected_dsegs_by_live accept the SUE layout (re-entrant)."""
    roles = roles_module()
    if _PATCH['depth'] == 0:
        orig = roles.resolve
        _PATCH['saved'] = (orig, roles.expected_dsegs_by_live)
        roles.resolve = functools.wraps(orig)(lambda source: _resolve_any(orig, source))
        roles.expected_dsegs_by_live = _expected_by_live
    _PATCH['depth'] += 1
    try:
        yield roles
    finally:
        _PATCH['depth'] -= 1
        if _PATCH['depth'] == 0:
            roles.resolve, roles.expected_dsegs_by_live = _PATCH['saved']
            _PATCH['saved'] = None


def _ext(fn):
    @functools.wraps(fn)
    def call(*a, **k):
        with _patched_resolver():
            return fn(*a, **k)
    return call


# ------------------------------------------------------------------ helpers
@_ext
def resolve(visum):
    """Role map of the live sequence; a missing/ambiguous role is a ContractError."""
    roles = roles_module()
    try:
        return roles.resolve(visum)
    except roles.OpmapError as exc:
        require(False, str(exc))


def is_legacy(visum):
    return resolve(visum)['mode'] == 'LEGACY_IDENTITY'


def tg_td_positions(visum):
    """Expected (TG, TD) positions: (5, 6) on the legacy layout, else the live roles."""
    info = resolve(visum)
    if info['mode'] == 'LEGACY_IDENTITY':
        return LEGACY_TG, LEGACY_TD
    tg = [int(p) for p in info.get('tg_positions') or []]
    require(len(tg) == 1, 'OPMAP1_EXPECTED_ONE_ACTIVE_TG_FOUND_%d' % len(tg))
    return tg[0], int(info['td_position'])


@_ext
def live_position(visum, legacy_no):
    roles = roles_module()
    try:
        return int(roles.live_position(visum, int(legacy_no)))
    except roles.OpmapError as exc:
        require(False, str(exc))


@_ext
def expected_scopes(visum):
    """live position -> exact DSEGSET of every role assignment (partial + final)."""
    return roles_module().expected_dsegs_by_live(visum)


@_ext
def live_cfg(visum, cfg):
    """Configuration with the role positions on the live sequence (identity on legacy).

    Idempotent: a configuration that already carries ``opmap1_roles`` is returned as is,
    so nested wrapped calls never translate a live position a second time."""
    if not isinstance(cfg, dict) or cfg.get('opmap1_roles'):
        return cfg
    roles = roles_module()
    out = roles.live_cfg(visum, cfg)
    info = out.get('opmap1_roles') if out is not cfg else None
    if info and info['mode'] == SUE_MODE:
        out = dict(out)
        supply = copy.deepcopy(out.get('supply') or {})
        final = int(info['roles']['ASG_FINAL'])
        for rule in supply.get('assignment_operations') or []:
            if int(rule['no']) == final:
                rule['opmap1_configured_expected_dsegs'] = list(rule.get('expected_dsegs') or [])
                rule['expected_dsegs'] = list(info['final_scope'])
        supply['opmap1_freight_preload_dsegs'] = list(supply.get('freight_dsegs') or [])
        supply['opmap1_freight_preload_positions'] = list(info['freight_positions'])
        supply['freight_dsegs'] = []
        out['supply'] = supply
    return out


def approved_live_positions(visum, cfg):
    rules = (live_cfg(visum, cfg).get('supply') or {}).get('assignment_operations') or []
    return sorted(int(r['no']) for r in rules)


# ------------------------------------------------------------------ assignment scope
def sue_assignment_scope(visum):
    """V239 report for the SUE layout, in legacy role numbering ([20] selected)."""
    roles = roles_module()
    try:
        info = resolve(visum)
    except Exception as exc:
        return {'schema': 'R1_15A2_ASSIGNMENT_SCOPE_AUTHORITY_V239', 'passes': False, 'failures': [str(exc)],
                'verified_operations': [], 'selected_trial_assignment_operations': [], 'gap_operation_no': 20}
    rows = roles._rows(visum)
    by = {roles._pos(r): r for r in rows}
    want = {int(k): frozenset(v) for k, v in info['live_scopes'].items()}
    legacy_of = {info['freight_split']['LNV']: 17, info['freight_split']['NV']: 17,
                 info['roles']['ASG_CF_CL']: 18, info['roles']['ASG_CS_CW']: 19, info['roles']['ASG_FINAL']: 20}
    details, failures = [], []
    for live in sorted(want):
        row = by[live]
        got = roles.dsegset(row)
        ok = got == want[live] and int(row['active']) == 1
        details.append({'no': legacy_of[live], 'live_no': live, 'expected_dsegs': sorted(want[live]),
                        'live_dsegs': sorted(got), 'type': roles._type(row), 'active': int(row['active']),
                        'comment': row.get('comment', ''), 'status': 'PASS' if ok else 'DSEGSET_MISMATCH'})
        if not ok:
            failures.append('OP_%d_LIVE_%d_DSEGSET' % (legacy_of[live], live))
    return {'schema': 'R1_15A2_ASSIGNMENT_SCOPE_AUTHORITY_V239', 'passes': not failures, 'failures': failures,
            'verified_operations': details,
            'selected_trial_assignment_operations': [20] if not failures else [],
            'selection_reason': 'OPMAP1_SUE: ROLE 20 = FINAL JOINT 12-DSEG PASSENGER ASSIGNMENT AT LIVE %d; '
                                'LNV/NV SUE AT %s ARE ITS PRELOAD' % (info['roles']['ASG_FINAL'],
                                                                     info['freight_positions']),
            'gap_operation_no': 20, 'gap_operation_live_no': int(info['roles']['ASG_FINAL']),
            'required_full_scope': list(info['final_scope']),
            'numbering': 'LEGACY_ROLE_NUMBERS_WITH_LIVE_POSITIONS', 'opmap1': info}


# ------------------------------------------------------------------ wrappers
def _cfg_first(orig):
    @functools.wraps(orig)
    def call(visum, cfg, *args, **kwargs):
        return orig(visum, live_cfg(visum, cfg), *args, **kwargs)
    setattr(call, _MARK, orig)
    return call


def _gap(orig):
    @functools.wraps(orig)
    def call(visum, spec):
        if isinstance(spec, dict) and spec.get('opmap1_live_operation_no'):
            return orig(visum, spec)
        with _patched_resolver() as roles:
            live = roles.live_spec(visum, spec)
        if live is not spec and isinstance(live, dict):
            live = dict(live, opmap1_live_operation_no=True)
        try:
            return orig(visum, live)
        except Exception as exc:
            # LIVE05.4: in the SUE layout the quality list also carries the LNV/NV SUE rows (and the
            # partial assignments); two of them can end with the same last iteration.  Only the
            # diagnostic per-scope summary trips over that - the GAP authority (final 12-DSeg scope)
            # is unaffected, so it is read again with the ambiguity recorded instead of raised.
            if not str(exc).startswith('QUALITY_LIST_AMBIGUOUS_SCOPE_ITERATION:'):
                raise
            if resolve(visum)['mode'] != SUE_MODE:
                raise
            return _gap_sue(visum, live, str(exc))
    setattr(call, _MARK, orig)
    return call


def _gap_sue(visum, spec, first_error):
    """Donor assignment_gap_evidence (PRT_ASS_QUALITY_LIST) with the per-scope summary tolerant
    to ties of other assignments; the exact operation scope keeps every donor check."""
    import re
    sv = parent_module('r1_15a2_supply_visum')
    com, Err = sv.com, sv.SupplyContractError
    require(str(spec.get('source', '')).strip().upper() == 'PRT_ASS_QUALITY_LIST', 'OPMAP1_SUE_GAP_SOURCE')
    position = sv.integer(spec.get('operation_no', 0))
    rows = com.operation_rows(visum)
    if position <= 0 or position > len(rows):
        raise Err('QUALITY_OPERATION_POSITION_UNAVAILABLE')
    op = rows[position - 1]
    if op['position'] != position or op['type'] != com.ASSIGNMENT_PRT or not op['active']:
        raise Err('QUALITY_OPERATION_NOT_ACTIVE_PRT')
    split = lambda t: [x.strip("\"' ").upper() for x in re.split(r"[,;{}\s]+", t) if x.strip("\"' ")]
    scope_text = com.object_property(op['object'], 'PrTAssignmentParameters').AttValue('DSEGSET')
    parts = split(scope_text) if isinstance(scope_text, str) else []
    if not parts or len(parts) != len(set(parts)):
        raise Err('QUALITY_DSEG_SCOPE_AMBIGUOUS')
    required = frozenset(parts)
    quality = com.object_property(com.object_property(com.object_property(visum, 'Workbench'), 'Lists'),
                                  'CreatePrTAssQualityList')
    for column in ('DSEGCODE', 'ITERATION', 'GAP'):
        quality.AddColumn(column)
    count = com.exact_int(com.member_value(getattr(quality, 'NumActiveElements')), 'QUALITY_ROWS')
    if count <= 0 or count > 50000:
        raise Err('QUALITY_LIST_INVALID_ROW_COUNT')
    exact, scopes = [], {}
    for first in range(1, count + 1, 400):
        last = min(count, first + 399)
        page = list(quality.SaveToArray(first, last))
        if len(page) != last - first + 1:
            raise Err('QUALITY_LIST_INCOMPLETE_PAGE')
        for ix, rec in enumerate(page, first):
            if len(rec) != 3:
                raise Err('QUALITY_LIST_INVALID_WIDTH:%d' % ix)
            raw_code, raw_iter, raw_gap = rec
            if not isinstance(raw_code, str) or not raw_code.strip():
                raise Err('QUALITY_LIST_EMPTY_DSEG_CODE')
            tokens = split(raw_code)
            if not tokens or len(tokens) != len(set(tokens)):
                raise Err('QUALITY_LIST_AMBIGUOUS_DSEG_CODE')
            iteration = com.exact_int(raw_iter, 'QUALITY_ITERATION')
            gap = com.finite_float(raw_gap, 'QUALITY_GAP')
            if iteration < 1 or gap < 0:
                raise Err('QUALITY_LIST_INVALID_VALUE')
            obj = {'row': ix, 'iteration': iteration, 'gap': gap}
            scopes.setdefault(','.join(sorted(tokens)), []).append(obj)
            if frozenset(tokens) == required:
                exact.append(obj)
    if not exact:
        raise Err('QUALITY_LIST_NO_EXACT_OPERATION_SCOPE')
    max_iter = max(r['iteration'] for r in exact)
    winners = [r for r in exact if r['iteration'] == max_iter]
    if len(winners) != 1:
        raise Err('QUALITY_LIST_LAST_ITERATION_NOT_UNIQUE')
    selected = winners[0]
    latest, ambiguous = {}, []
    for key, cand in scopes.items():
        m = max(r['iteration'] for r in cand)
        ties = [r for r in cand if r['iteration'] == m]
        if len(ties) == 1:
            latest[key] = {'iteration': m, 'gap': ties[0]['gap']}
        else:
            latest[key] = {'iteration': m, 'gap': None, 'tied_rows': len(ties),
                           'gaps': [r['gap'] for r in ties]}
            ambiguous.append(key)
    return {'source': 'PRT_ASS_QUALITY_LIST', 'operation_no': position,
            'operation_dsegs': sorted(required), 'quality_rows': count,
            'exact_scope_rows': len(exact), 'iteration': max_iter,
            'quality_row': selected['row'], 'gap': selected['gap'],
            'latest_gap_by_scope': latest, 'ambiguous_other_scopes': sorted(ambiguous),
            'opmap1_sue_tolerant_reason': first_error,
            'freshness': 'UNVERIFIED_HISTORICAL_UNLESS_READ_AFTER_SUCCESSFUL_EXPLICIT_ASSIGNMENT'}


def _scope_audit(orig):
    @functools.wraps(orig)
    def audit(visum):
        roles = roles_module()
        if roles._is_legacy_layout(roles._rows(visum)):
            return orig(visum)
        info = resolve(visum)
        if info['mode'] == SUE_MODE:
            return sue_assignment_scope(visum)
        expected = parent_module('r1_15a2_assignment_authority_v239').EXPECTED
        with _patched_resolver():
            return roles.role_assignment_scope(visum, expected)
    setattr(audit, _MARK, orig)
    return audit


def _targets():
    a239 = parent_module('r1_15a2_assignment_authority_v239')
    a240 = parent_module('r1_15a2_trial_adapter_v240')
    perf1 = parent_module('r1_15a2_acceleration_v24915p1')
    sv = parent_module('r1_15a2_supply_visum')
    return [(a239, 'audit_assignment_scope', _scope_audit), (a240, 'audit_assignment_scope', _scope_audit),
            (perf1, 'phase_recompute_plan', _cfg_first), (sv, 'assignment_plan', _cfg_first),
            (sv, 'assignment_gap_evidence', _gap)]


def install():
    """Install the wrappers and the extended resolver; returns (patched names, restore)."""
    saved = []
    for mod, name, wrap in _targets():
        cur = getattr(mod, name)
        if getattr(cur, _MARK, None) is not None:
            continue
        saved.append((mod, name, cur))
        setattr(mod, name, wrap(cur))
    resolver = _patched_resolver()
    resolver.__enter__()

    def restore():
        resolver.__exit__(None, None, None)
        for mod, name, cur in reversed(saved):
            setattr(mod, name, cur)
    return ['%s.%s' % (m.__name__, n) for m, n, _ in saved], restore


@contextmanager
def scope(visum, folder=None):
    """OPMAP1 for ONE cordon run: resolve the roles, install, restore on exit."""
    info = resolve(visum)
    patched, restore = install()
    status = {'schema': SCHEMA, 'release': roles_module().RELEASE, 'mode': info['mode'],
              'roles': info['roles'], 'legacy_to_live': {str(k): v for k, v in info['legacy_to_live'].items()},
              'td_position': info.get('td_position', LEGACY_TD),
              'tg_positions': info.get('tg_positions', [LEGACY_TG]),
              'freight_positions': info.get('freight_positions'),
              'final_scope': info.get('final_scope'),
              'operation_count': info['operation_count'], 'patched': patched,
              'policy': 'LEGACY_LAYOUT_IDENTITY;OTHER_LAYOUTS_RESOLVED_BY_ROLE_SIGNATURE_FAIL_CLOSED;'
                        'SUE_FREIGHT_SPLIT_12_DSEG_FINAL_ACCEPTED_USER_DECISION_20261115;'
                        'NO_PROCEDURE_SEQUENCE_CHANGE'}
    if folder is not None:
        write_json(Path(folder) / 'OPMAP1_ROLES.json', status)
    try:
        yield status
    finally:
        restore()
