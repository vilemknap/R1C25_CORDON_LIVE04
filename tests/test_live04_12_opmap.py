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


# ---------------------------------------------------------------- LIVE04.12.1 SUE freight layout
PASS12 = ("EXOG_EE_CF,EXOG_EE_CL,EXOG_EE_CS,EXOG_EE_CS_noT,EXOG_EE_CW,EXOG_EE_CW_noT,"
          "NATIVE_CF,NATIVE_CL,NATIVE_CS,NATIVE_CS_noT,NATIVE_CW,NATIVE_CW_noT")


def sue_layout():
    """R1_BASE_PROCEDURE_2025_SUE_V3_NODESVDF_aktualni.xml (2026-11-15, 61 operations)."""
    G, S, E = 75, 65, 20
    ops = [Op(G), Op(S, comment="R1 00 - truck speeds"), Op(G), Op(S, comment="R1 00b - truck surcharge"),
           Op(G), Op(E, comment="R1_TOLL"), Op(E, comment="R1_TOLL"), Op(E, comment="R1_TOLL"),
           Op(G), Op(S, comment="14A COUTRY_ADD Preset"), Op(G), Op(G), Op(45), Op(G), Op(S, comment="OSRM"),
           Op(G), Op(46), Op(G), Op(S, comment="Foreign Matrix Post Processing"), Op(G), Op(G),
           Op(S, comment="kappa audit"), Op(S, comment="kappa-band"), Op(G, comment="R1 20D"), Op(S), Op(G),
           Op(91, comment="kappa-fixed"), Op(G), Op(S, comment="Matrix Symmetrization"),
           Op(9, comment="reset after demand"), Op(G), Op(101, dseg="LNV"), Op(101, dseg="NV"),
           Op(101, dseg="NATIVE_CF,NATIVE_CL"), Op(101, dseg=CSCW), Op(101, dseg=PASS12),
           Op(S, active=0, comment="GEH (EXOG_EE_CF, ...)"), Op(G)]
    ops += [Op(103, active=0) for _ in range(8)] + [Op(103) for _ in range(6)]
    ops += [Op(9, active=0), Op(101, active=0, dseg="LNV,NV"), Op(101, active=0, dseg=FINAL + ",R1_OA_CAL_2022"),
            Op(G, active=0), Op(107, active=0), Op(101, active=0, dseg=FINAL + ",R1_OA_CAL_2022"),
            Op(S, active=0), Op(G, active=0), Op(1, active=0)]
    assert len(ops) == 61
    return ops


def test_sue_layout_resolved_with_split_freight_and_12_dseg_final():
    v = Visum(sue_layout())
    info = om.resolve(v)
    assert info['mode'] == om.SUE_MODE
    assert info['roles']['RESET_PRE'] is None and info['roles']['RESET_POST'] == 30
    assert info['freight_positions'] == [32, 33] and info['roles']['ASG_FINAL'] == 36
    assert om.tg_td_positions(v) == (13, 17)
    assert om.live_position(v, 15) == 30 and om.live_position(v, 20) == 36
    assert {k: sorted(s) for k, s in om.expected_scopes(v).items()}[32] == ['LNV']
    assert len(om.expected_scopes(v)[36]) == 12
    # the verbatim resolver is untouched outside the LIVE04 scope
    roles = parent_module('r1_15a2_procseq_roles_v24917')
    with pytest.raises(roles.OpmapError, match='ASG_FREIGHT_FOUND_0'):
        roles.resolve(v)


def test_sue_live_cfg_and_assignment_authority():
    v = Visum(sue_layout())
    cfg = {"supply": {"assignment_operations": [{"no": 20, "operation_type": 101,
                                                 "expected_dsegs": sorted(FINAL.upper().split(','))}],
                      "freight_dsegs": ["LNV", "NV"],
                      "gap_readback": {"operation_no": 20, "source": "PRT_ASS_QUALITY_LIST"}}}
    live = om.live_cfg(v, cfg)
    rule = live['supply']['assignment_operations'][0]
    assert rule['no'] == 36 and len(rule['expected_dsegs']) == 12 and 'LNV' not in rule['expected_dsegs']
    assert live['supply']['freight_dsegs'] == [] and live['supply']['opmap1_freight_preload_positions'] == [32, 33]
    assert live['supply']['gap_readback']['operation_no'] == 36
    assert cfg['supply']['freight_dsegs'] == ['LNV', 'NV']          # original untouched
    a239 = parent_module('r1_15a2_assignment_authority_v239')
    patched, restore = om.install()
    try:
        rep = a239.audit_assignment_scope(v)
    finally:
        restore()
    assert rep['passes'], rep['failures']
    assert rep['selected_trial_assignment_operations'] == [20] and rep['gap_operation_live_no'] == 36
    assert [(d['no'], d['live_no']) for d in rep['verified_operations']] == [(17, 32), (17, 33), (18, 34), (19, 35), (20, 36)]
    bad = sue_layout()
    bad[33].PrTAssignmentParameters = Params("NATIVE_CF")              # CF_CL scope broken
    with pytest.raises(ContractError, match='OPMAP1_SUE_ROLE_ASG_CF_CL_FOUND_0'):
        om.resolve(Visum(bad))
    bad = sue_layout()
    bad[53].active = 1                                                 # a second active LNV,NV operation (54)
    with pytest.raises(ContractError, match='OPMAP1_SUE_UNEXPECTED_ACTIVE_ASSIGNMENT'):
        om.resolve(Visum(bad))


def test_sue_supply_cold_plan_and_demand_plan(monkeypatch):
    sm = parent_module('r1_15a2_supply_mix_v24917')
    inv = _plan_inventory(sue_layout())
    out = sm.cold_supply_plan({"inventory": inv, "approved_assignment_positions": [36],
                               "selected_operation_positions": [36]}, {}, 15)
    info = out["v24917_supplymix_plan"]
    assert info["applied"] and info["reset_position"] == 30
    assert {30, 32, 33, 34, 35, 36} <= set(out["selected_operation_positions"])   # freight SUE re-runs after reset
    from cordon2025 import live03_predictor as pr
    perf1 = parent_module('r1_15a2_acceleration_v24915p1')
    sel = [r['no'] for r in inv if r['active'] and r['no'] <= 36]
    monkeypatch.setattr(perf1, 'phase_recompute_plan',
                        lambda visum, cfg, block: {'inventory': inv, 'selected_operation_positions': sel, 'mode': 'X'})
    plan = pr.demand_plan(Visum(sue_layout()), CFG, 'GENERATION')
    assert plan['first_approved_assignment'] == 36
    assert plan['skipped_other_assignments_in_prefix'] == [32, 33, 34, 35]
    assert {13, 17} <= set(plan['selected_operation_positions'])
    assert 30 not in plan['selected_operation_positions']
    assert 30 in plan['skipped_assignment_resets_in_prefix']


class _Quality:
    def __init__(self, rows):
        self.rows = rows

    def AddColumn(self, c):
        pass

    @property
    def NumActiveElements(self):
        return len(self.rows)

    def SaveToArray(self, first, last):
        return [tuple(r) for r in self.rows[first - 1:last]]


def test_sue_gap_tolerates_tied_freight_rows_but_keeps_the_final_scope_checks():
    """LIVE05.4 (live run 2026-11-15: QUALITY_LIST_AMBIGUOUS_SCOPE_ITERATION:LNV)."""
    pass12 = PASS12
    rows = [("LNV", 1, 0.02), ("LNV", 1, 0.03), ("NV", 1, 0.01), (pass12, 1, 0.5), (pass12, 2, 0.01)]
    v = Visum(sue_layout())
    v.Workbench = type("W", (), {})()
    v.Workbench.Lists = type("L", (), {})()
    v.Workbench.Lists.CreatePrTAssQualityList = _Quality(rows)
    sv = parent_module('r1_15a2_supply_visum')
    spec = {"operation_no": 20, "source": "PRT_ASS_QUALITY_LIST"}
    patched, restore = om.install()
    try:
        out = sv.assignment_gap_evidence(v, spec)
        assert out['operation_no'] == 36 and out['gap'] == 0.01 and out['iteration'] == 2
        assert out['ambiguous_other_scopes'] == ['LNV'] and out['latest_gap_by_scope']['NV']['gap'] == 0.01
        v.Workbench.Lists.CreatePrTAssQualityList = _Quality(rows + [(pass12, 2, 0.02)])
        with pytest.raises(Exception, match='QUALITY_LIST_LAST_ITERATION_NOT_UNIQUE'):
            sv.assignment_gap_evidence(v, spec)
    finally:
        restore()
    v.Workbench.Lists.CreatePrTAssQualityList = _Quality(rows)
    with pytest.raises(Exception, match='QUALITY_LIST_AMBIGUOUS_SCOPE_ITERATION:LNV'):
        sv.assignment_gap_evidence(v, dict(spec, operation_no=36))       # donor outside the LIVE04 scope


def test_supplymix_cold_chain_keeps_the_run_start_role_map(tmp_path):
    """2026-11-19 live stop LONGMASK_ASSIGNMENT_AUTHORITY_MISMATCH: the SUPPLY_ADDVAL1 cold
    chain activates only reset 30 .. joint assignment 36 (+ groups). TG 13 / TD 17 are then
    inactive and the active-only resolver could not translate legacy 20 -> 36."""
    roles = parent_module('r1_15a2_procseq_roles_v24917')
    sm = parent_module('r1_15a2_supply_mix_v24917')
    com = parent_module('r1_15a2_com_compat')
    ops = sue_layout()
    v = Visum(ops)
    with om.scope(v, tmp_path):
        inv = _plan_inventory(ops)
        cold = sm.cold_supply_plan({"inventory": inv, "approved_assignment_positions": [36],
                                    "selected_operation_positions": [36]}, {}, 15)
        selected = set(cold["selected_operation_positions"])
        for pos, op in enumerate(ops, 1):          # what activate_operation_plan does natively
            op.active = 1 if pos in selected else 0
        assert 13 not in selected and 17 not in selected
        rows = com.operation_rows(v)
        tr = roles.translator(rows)
        assert tr(20) == 36 and tr(15) == 30
        active_asg = {int(r['no']) for r in rows if r['active'] and int(r['type']) == com.ASSIGNMENT_PRT}
        approved = {tr(int(rule['no'])) for rule in CFG['supply']['assignment_operations']}
        assert approved <= active_asg == {32, 33, 34, 35, 36}           # the LONGMASK authority check
        assert len(roles.expected_dsegs_by_live(rows)[36]) == 12
        # a changed definition (not only ACTIVE flags) still fails closed
        ops[16].comment = 'moved TD'
        with pytest.raises(roles.OpmapError):
            roles.translator(com.operation_rows(v))(20)
        ops[16].comment = ''
    # outside the run scope the cache is gone
    for op in ops:
        op.active = 1 if op.active else 0
    assert om._RUN['cache'] is None


def test_supplymix_cold_plan_from_full_fallback_uses_live_role_positions(tmp_path):
    """Operation-numbering audit 2026-11-19: a FULL_SEQUENCE_FALLBACK base plan has no
    approved positions; the cold plan then took legacy 20 from the raw configuration and
    failed with RESET_OPERATION_TYPE:65 on the SUE layout."""
    sm = parent_module('r1_15a2_supply_mix_v24917')
    ops = sue_layout()
    v = Visum(ops)
    full = {"inventory": _plan_inventory(ops), "mode": "FULL_SEQUENCE_FALLBACK",
            "selected_operation_positions": [i for i, op in enumerate(ops, 1) if op.active]}
    assert not sm.cold_supply_plan(full, CFG, 15)["v24917_supplymix_plan"]["applied"]   # raw cfg: legacy 20
    with om.scope(v, tmp_path):
        info = sm.cold_supply_plan(full, om.live_cfg(v, CFG), 15)["v24917_supplymix_plan"]
        assert info["applied"] and info["reset_position"] == 30 and info["joint_assignment"] == 36
        # the donor wrapper translates a raw configuration itself
        wrapped = sm._wrap_plan(lambda visum, cfg, block: dict(full))
        monkey = dict(sm.options(), enabled=True)
        orig_options = sm.options
        sm.options = lambda: monkey
        try:
            out = wrapped(v, CFG, sm.BLOCK)
        finally:
            sm.options = orig_options
        assert out["v24917_supplymix_plan"]["joint_assignment"] == 36


def test_gap_readback_under_cold_chain_flags_reads_the_live_final(tmp_path):
    """The GAP readback runs inside activate_operation_plan; with TG/TD inactive the role
    map comes from the run-start cache and legacy 20 is still the live 12-DSeg final 36."""
    sm = parent_module('r1_15a2_supply_mix_v24917')
    roles = parent_module('r1_15a2_procseq_roles_v24917')
    ops = sue_layout()
    v = Visum(ops)
    rows = [("LNV", 1, 0.02), ("NV", 1, 0.01), (PASS12, 1, 0.5), (PASS12, 2, 0.004)]
    v.Workbench = type("W", (), {})()
    v.Workbench.Lists = type("L", (), {})()
    v.Workbench.Lists.CreatePrTAssQualityList = _Quality(rows)
    sv = parent_module('r1_15a2_supply_visum')
    with om.scope(v, tmp_path):
        cold = sm.cold_supply_plan({"inventory": _plan_inventory(ops), "approved_assignment_positions": [36],
                                    "selected_operation_positions": [36]}, {}, 15)
        selected = set(cold["selected_operation_positions"])
        for pos, op in enumerate(ops, 1):
            op.active = 1 if pos in selected else 0
        assert roles.live_cfg(v, CFG)["supply"]["gap_readback"]["operation_no"] == 36
        out = sv.assignment_gap_evidence(v, CFG["supply"]["gap_readback"])
        assert out["operation_no"] == 36 and out["gap"] == 0.004 and out["iteration"] == 2
