"""LIVE04.12 OPMAP1: the cordon run on the legacy 43-op and on the 2026-11 53-op procedure sequence.

Layouts are the ones of the OPMAP1 tests of R1_15A2_V24917_v7 (branch
claude-opmap1-procseq-roles-20261111).  Synthetic mock only - not native PTV Visum evidence."""
import pytest

from cordon2025.common import ContractError, parent_module
from cordon2025 import live04_opmap as om
from cordon2025.live04_v7 import verify_donor_files

FINAL = ("EXOG_EE_CF,EXOG_EE_CL,EXOG_EE_CS,EXOG_EE_CS_noT,EXOG_EE_CW,EXOG_EE_CW_noT,LNV,"
         "NATIVE_CF,NATIVE_CL,NATIVE_CS,NATIVE_CS_noT,NATIVE_CW,NATIVE_CW_noT,NV")
CSCW = "NATIVE_CS,NATIVE_CS_noT,NATIVE_CW,NATIVE_CW_noT"


class Params:
    def __init__(self, dseg):
        self.dseg = dseg

    def AttValue(self, name):
        assert name == "DSEGSET"
        return self.dseg


class Op:
    def __init__(self, typ, active=1, comment="", dseg=None):
        self.typ, self.active, self.comment = typ, active, comment
        self.PrTAssignmentParameters = Params(dseg) if dseg is not None else None

    def AttValue(self, name):
        return {"OPERATIONTYPE": self.typ, "ACTIVE": self.active, "COMMENT": self.comment, "NAME": ""}[name]


def new_layout():
    ops = [Op(9, comment="reset before TG"), Op(75), Op(65, comment="14A COUTRY_ADD Preset"), Op(75),
           Op(75), Op(45), Op(75), Op(65, comment="OSRM times"), Op(75), Op(46), Op(75),
           Op(65, comment="Foreign Matrix Post Processing"), Op(75), Op(75), Op(65, comment="kappa audit"),
           Op(65, comment="kappa-band"), Op(75, comment="R1 20D"), Op(65), Op(75), Op(91), Op(75),
           Op(65, comment="Matrix Symmetrization"), Op(9, comment="reset after demand"), Op(75),
           Op(101, dseg="LNV,NV"), Op(101, dseg="NATIVE_CF,NATIVE_CL"), Op(101, dseg=CSCW),
           Op(101, dseg=FINAL), Op(65, comment="GEH (EXOG_EE_CF, ...)"), Op(75)]
    ops += [Op(103, active=0) for _ in range(8)] + [Op(103) for _ in range(6)]
    ops += [Op(9, active=0), Op(101, active=0, dseg="LNV,NV"), Op(101, active=0, dseg=FINAL + ",R1_OA"),
            Op(75, active=0), Op(1, active=0), Op(101, active=0, dseg=FINAL), Op(65, active=0),
            Op(75, active=0), Op(107, active=0)]
    assert len(ops) == 53
    return ops


def legacy_layout():
    ops = [Op(9), Op(75), Op(65, active=0), Op(75), Op(45), Op(46), Op(75), Op(65), Op(75), Op(65),
           Op(65), Op(91), Op(75), Op(65), Op(9), Op(75), Op(101, dseg="LNV,NV"),
           Op(101, dseg="NATIVE_CF,NATIVE_CL"), Op(101, dseg=CSCW), Op(101, dseg=FINAL),
           Op(65, comment="GEH"), Op(75, active=0)]
    ops += [Op(103) for _ in range(14)] + [Op(9, active=0), Op(101, active=0), Op(101, active=0),
                                           Op(75, active=0), Op(1, active=0), Op(101, active=0),
                                           Op(65, active=0)]
    assert len(ops) == 43
    return ops


class Coll:
    def __init__(self, ops):
        self.ops = ops

    @property
    def GetAll(self):
        return tuple(self.ops)


class Visum:
    def __init__(self, ops):
        self.Procedures = type("P", (), {})()
        self.Procedures.Operations = Coll(ops)


CFG = {"supply": {"assignment_operations": [{"no": 20, "operation_type": 101}],
                  "gap_readback": {"operation_no": 20, "source": "PRT_ASS_QUALITY_LIST"}},
       "performance": {"v24915_perf1": {"phase_specific_procseq": {
           "safe_post_assignment_operations": [{"position": 21, "operation_type": 65}]}}}}


def test_donor_pins_include_the_opmap1_hunks():
    pins = verify_donor_files()
    assert 'r1_15a2_procseq_roles_v24917.py' in pins
    assert parent_module('r1_15a2_procseq_roles_v24917').RELEASE == 'R1_15A2_V24917_OPMAP1_20261111'


def test_tg_td_positions_legacy_and_new_layout():
    assert om.tg_td_positions(Visum(legacy_layout())) == (5, 6)
    assert om.tg_td_positions(Visum(new_layout())) == (6, 10)
    assert om.live_position(Visum(new_layout()), 15) == 23
    assert om.approved_live_positions(Visum(new_layout()), CFG) == [28]
    assert om.approved_live_positions(Visum(legacy_layout()), CFG) == [20]


def test_ambiguous_layout_fails_closed_as_contract_error():
    ops = new_layout()
    ops[45].active = 1
    with pytest.raises(ContractError, match='OPMAP1_ROLE_ASG_FREIGHT_FOUND_2'):
        om.tg_td_positions(Visum(ops))


def test_live_cfg_is_idempotent():
    v = Visum(new_layout())
    once = om.live_cfg(v, CFG)
    assert once['supply']['assignment_operations'][0]['no'] == 28
    assert om.live_cfg(v, once) is once                  # never translated twice
    assert om.live_cfg(Visum(legacy_layout()), CFG) is CFG
    assert CFG['supply']['assignment_operations'][0]['no'] == 20


def test_scope_wraps_donor_entry_points_once_and_restores(tmp_path):
    perf1 = parent_module('r1_15a2_acceleration_v24915p1')
    sv = parent_module('r1_15a2_supply_visum')
    a239 = parent_module('r1_15a2_assignment_authority_v239')
    orig = (perf1.phase_recompute_plan, sv.assignment_plan, sv.assignment_gap_evidence, a239.audit_assignment_scope)
    seen = []
    fake = lambda visum, cfg, block=None: seen.append(cfg['supply']['assignment_operations'][0]['no']) or {}
    perf1.phase_recompute_plan = fake
    try:
        v = Visum(new_layout())
        with om.scope(v, tmp_path) as st:
            assert st['mode'] == 'RESOLVED_BY_SIGNATURE' and st['roles']['ASG_FINAL'] == 28
            with om.scope(v) as inner:                    # nested scope: nothing wrapped twice
                assert inner['patched'] == []
            perf1.phase_recompute_plan(v, CFG, 'GENERATION')
            perf1.phase_recompute_plan(v, om.live_cfg(v, CFG), 'GENERATION')
            rep = a239.audit_assignment_scope(v)
            assert rep['passes'] and rep['gap_operation_live_no'] == 28
        assert seen == [28, 28]
        assert (tmp_path / 'OPMAP1_ROLES.json').is_file()
        assert perf1.phase_recompute_plan is fake
        assert (sv.assignment_plan, sv.assignment_gap_evidence, a239.audit_assignment_scope) == orig[1:]
        with om.scope(Visum(legacy_layout())) as st:
            assert st['mode'] == 'LEGACY_IDENTITY'
            perf1.phase_recompute_plan(Visum(legacy_layout()), CFG)
        assert seen[-1] == 20
    finally:
        perf1.phase_recompute_plan = orig[0]


def _plan_inventory(ops):
    return [{"no": i, "type": op.typ, "active": op.active, "comment": op.comment} for i, op in enumerate(ops, 1)]


def test_supplymix_cold_reset_follows_the_live_layout():
    sm = parent_module('r1_15a2_supply_mix_v24917')
    base = {"inventory": _plan_inventory(new_layout()), "approved_assignment_positions": [28],
            "selected_operation_positions": [28]}
    info = sm.cold_supply_plan(base, {}, 15)["v24917_supplymix_plan"]
    assert info["applied"] and info["reset_position"] == 23
    base = {"inventory": _plan_inventory(legacy_layout()), "approved_assignment_positions": [20],
            "selected_operation_positions": [20]}
    info = sm.cold_supply_plan(base, {}, 15)["v24917_supplymix_plan"]
    assert info["applied"] and info["reset_position"] == 15


def test_demand_plan_cuts_before_the_live_joint_assignment(monkeypatch):
    from cordon2025 import live03_predictor as pr
    perf1 = parent_module('r1_15a2_acceleration_v24915p1')
    inv = _plan_inventory(new_layout())
    sel = [r['no'] for r in inv if r['active'] and 2 <= r['no'] <= 28]
    monkeypatch.setattr(perf1, 'phase_recompute_plan',
                        lambda visum, cfg, block: {'inventory': inv, 'selected_operation_positions': sel, 'mode': 'X'})
    out = pr.demand_plan(Visum(new_layout()), CFG, 'GENERATION')
    assert out['first_approved_assignment'] == 28
    assert max(out['selected_operation_positions']) < 25          # no partial assignment 25-27
    assert 6 in out['selected_operation_positions'] and 10 in out['selected_operation_positions']
    assert out['skipped_other_assignments_in_prefix'] == [25, 26, 27]
