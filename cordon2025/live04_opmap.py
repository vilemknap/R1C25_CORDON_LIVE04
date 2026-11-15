"""LIVE04.12 OPMAP1: procedure-sequence roles of the live 2025 model.

The donor (v7 @ 7b4c681) and the LIVE01-04 layers were written against the legacy
43-operation 09C sequence: TG 5, TD 6, resets 1 / 15, partial assignments 17-19,
joint 14-DSeg assignment 20, GEH script 21.  Since 2026-11 the R1 models nest the
demand steps in more groups, so the same roles can sit at other positions.

The role resolution itself is the user's OPMAP1 module
(``parent/r1_15a2_procseq_roles_v24917.py``, verbatim from R1_15A2_V24917_v7 branch
``claude-opmap1-procseq-roles-20261111``):

* a model whose roles sit at the legacy positions maps to the identity - nothing
  changes compared with LIVE04.11.1;
* otherwise every role is found by its signature (operation type, ACTIVE, exact
  DSEGSET, order TG < TD < reset < assignments); a missing or ambiguous role fails
  closed with ``OPMAP1_*``.  Nothing is guessed and no operation is changed.

``scope`` installs the OPMAP1 translation on the donor entry points used by the
cordon run (assignment-scope authority V239/V240, PERF1 phase plan, supply_visum
assignment plan and GAP readback) for ONE run and restores them on exit.  Unlike the
donor ``install`` it is idempotent per configuration (a configuration that was already
translated is never translated twice) and it skips the FineCDF dynamic-skim hook,
which the LIVE04 donor bridge does not have.
"""
from contextlib import contextmanager
import functools
from pathlib import Path

from .common import parent_module, require, write_json

SCHEMA = 'LIVE04_OPMAP1_V1'
LEGACY_TG, LEGACY_TD = 5, 6
_MARK = '__live04_opmap1__'


def roles_module():
    return parent_module('r1_15a2_procseq_roles_v24917')


def resolve(visum):
    """Role map of the live sequence; raises a ContractError-compatible failure."""
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
    require(tg, 'OPMAP1_NO_ACTIVE_TG')
    return tg[0], int(info['td_position'])


def live_position(visum, legacy_no):
    return int(roles_module().live_position(visum, int(legacy_no)))


def live_cfg(visum, cfg):
    """Configuration with the role positions on the live sequence (identity on legacy).

    Idempotent: a configuration that already carries ``opmap1_roles`` is returned as is,
    so nested wrapped calls never translate a live position a second time."""
    if not isinstance(cfg, dict) or cfg.get('opmap1_roles'):
        return cfg
    return roles_module().live_cfg(visum, cfg)


def approved_live_positions(visum, cfg):
    rules = (live_cfg(visum, cfg).get('supply') or {}).get('assignment_operations') or []
    return sorted(int(r['no']) for r in rules)


def _cfg_first(orig):
    @functools.wraps(orig)
    def call(visum, cfg, *args, **kwargs):
        return orig(visum, live_cfg(visum, cfg), *args, **kwargs)
    setattr(call, _MARK, orig)
    return call


def _gap(orig):
    roles = roles_module()

    @functools.wraps(orig)
    def call(visum, spec):
        if isinstance(spec, dict) and spec.get('opmap1_live_operation_no'):
            return orig(visum, spec)
        live = roles.live_spec(visum, spec)
        if live is not spec and isinstance(live, dict):
            live = dict(live, opmap1_live_operation_no=True)
        return orig(visum, live)
    setattr(call, _MARK, orig)
    return call


def _scope_audit(orig):
    roles = roles_module()

    @functools.wraps(orig)
    def audit(visum):
        if roles._is_legacy_layout(roles._rows(visum)):
            return orig(visum)
        expected = parent_module('r1_15a2_assignment_authority_v239').EXPECTED
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
    """Install the wrappers; returns (patched names, restore callable).  Re-entrant."""
    saved = []
    for mod, name, wrap in _targets():
        cur = getattr(mod, name)
        if getattr(cur, _MARK, None) is not None:
            continue
        saved.append((mod, name, cur))
        setattr(mod, name, wrap(cur))

    def restore():
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
              'operation_count': info['operation_count'], 'patched': patched,
              'policy': 'LEGACY_LAYOUT_IDENTITY;OTHER_LAYOUTS_RESOLVED_BY_ROLE_SIGNATURE_FAIL_CLOSED;'
                        'NO_PROCEDURE_SEQUENCE_CHANGE'}
    if folder is not None:
        write_json(Path(folder) / 'OPMAP1_ROLES.json', status)
    try:
        yield status
    finally:
        restore()
