"""Exact donor functions extracted from HOTFIX2; no launcher/side effects.
Source and function hashes are in provenance/live01/EXACT_FUNCTIONS.json.
"""
from pathlib import Path
from .common import parent_module
from .io import write_csv, write_json

def compact_error(exc):
    from .io import exception_text
    return exception_text(exc)

def __getattr__(name):
    raise AttributeError(name)

# These are library imports only; no COM operation is performed on import.
mb = parent_module("r1_15a2_multiblock")
rt = parent_module("r1_15a2_runtime_v1")

def zone_state_rows(visum, zones, cfg, zone_indices=None, retry_policy=None):
    required = list(cfg.get("tg_dependency_contract", {}).get("required_zone_attributes", []))
    required.extend(mb.GENERATION_ATTRS)
    required.extend([
        cfg.get("salary", {}).get("income_attr", "AV_INCOME"),
        cfg.get("zahr", {}).get("domestic_mask_attr", "NOT_ZAHR"),
    ])
    attrs = []
    seen = set()
    for name in required:
        name = mb.sval(name).strip()
        if name and name not in seen:
            seen.add(name); attrs.append(name)
    values = {}
    errors = []
    for name in attrs:
        try:
            values[name] = rt.read_zone_attr_strict(
                visum, name, zones, zone_indices=zone_indices, retry_policy=retry_policy)
        except Exception as exc:
            errors.append({"attr": name, "error": compact_error(exc)})
    if errors:
        raise RuntimeError("Required generation zone attributes are unreadable: %s" % errors)
    rows = []
    for i, z in enumerate(zones):
        row = {"zone_no": int(z)}
        for name in attrs:
            row[name] = float(values[name][i])
        rows.append(row)
    return rows, attrs

def generation_actuator_zone_scope(visum, zones, cfg, out_dir, zone_indices=None, retry_policy=None):
    """Resolve zones for which the current TG formulas expose a real actuator.

    Domestic zones use ADD_*; ZAHR zones require both ZAHR_SUSED and POP_ZP to
    be positive.  Explicit exclusions apply to both branches.  This scope is fed
    into the path-incidence variable builder so excluded endpoints cannot create
    unimplementable OD guidance.
    """
    zrows, _attrs = zone_state_rows(
        visum, zones, cfg, zone_indices=zone_indices, retry_policy=retry_policy)
    zcfg = cfg.get("zahr", {})
    mask_attr = mb.sval(zcfg.get("domestic_mask_attr", "NOT_ZAHR"))
    neighbour_attr = mb.sval(zcfg.get("neighbour_attr", "ZAHR_SUSED"))
    population_attr = mb.sval(zcfg.get("population_attr", "POP_ZP"))
    threshold = float(zcfg.get("domestic_threshold", 0.5))
    excluded = set(int(x) for x in cfg.get("explicit_excluded_zone_nos", []) or [])
    excluded.update(int(x) for x in zcfg.get("explicit_excluded_zone_nos", []) or [])
    eligible = []
    rows = []
    for row in zrows:
        z = int(row["zone_no"])
        domestic = float(mb.fval(row.get(mask_attr), 0.0) or 0.0) >= threshold
        if z in excluded:
            active = False; reason = "EXPLICIT_EXCLUSION"
        elif domestic:
            active = True; reason = "DOMESTIC_ADD_BRANCH"
        else:
            neigh = float(mb.fval(row.get(neighbour_attr), 0.0) or 0.0)
            pop = float(mb.fval(row.get(population_attr), 0.0) or 0.0)
            active = neigh > 0.0 and pop > 0.0
            reason = "ZAHR_BRANCH_ACTIVE" if active else "ZAHR_FORMULA_BASE_INACTIVE"
        if active:
            eligible.append(z)
        rows.append({"zone_no": z, "domestic_branch": int(domestic), "generation_actuatable": int(active), "reason": reason})
    write_csv(Path(out_dir) / "00_ZONE_ACTUATOR_SCOPE.csv", rows)
    summary = {"zone_count": len(rows), "eligible_zone_count": len(eligible), "excluded_zone_count": len(rows)-len(eligible), "passes": bool(eligible)}
    write_json(Path(out_dir) / "00_ZONE_ACTUATOR_SCOPE_SUMMARY.json", summary)
    if not eligible:
        raise RuntimeError("No generation-actuatable zones resolved")
    return eligible, summary
