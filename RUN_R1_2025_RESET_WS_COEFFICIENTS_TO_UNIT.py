"""Reset the domestic W/S Generation coefficients to 1 for a new LIVE04 reference base.

User decision 2026-11-19: the next calibration starts from coefficients 1.  LIVE04.14 captures
its run reference (centrality, OD links, production shares) only from such a model
(generation_structure.reference_start_policy = REQUIRE_UNIT_WS_ON_ACTUATABLE_DOMESTIC_ZONES).

Workflow (same Visum instance, never LoadVersion):
  1. Open an ISOLATED COPY of the 2025 version (name rule of CORDON_LIVE04_CONFIG.json
     isolated_copy_guard, the same as RECOMPUTE / FREEZE).
  2. Run this script: it writes ADD_PROD_W, ADD_PROD_S, ADD_ATT_W, ADD_ATT_S = 1 on every
     generating domestic zone (NOT_ZAHR >= 0.5) and verifies the readback.  Foreign zones are
     untouched.  ADD_SALARY only when RESET_ADD_SALARY = True below.
     Zone classes (review cc3c3c4 N3, reported separately):
       GENERATING_DOMESTIC         NOT_ZAHR = 1, AMDY_EXTERNI_ZONA = 0          -> reset to 1
       EXTERNAL_DISTRICT           NOT_ZAHR = 1, AMDY_EXTERNI_ZONA = 1, with
                                   population / FP production (608-618)        -> reset to 1
       STRUCTURAL_ZERO             NOT_ZAHR = 1, POP_ZP = 0, FP_1_WORK_* and
                                   FP_2_SERVICE_* = 0 and all W/S coefficients
                                   exactly 0 (646-649)                          -> KEPT at 0
       a zone with a W/S generation base and a coefficient <= 0 is ambiguous: the script stops
       before any write and lists it (UNIT_RESET_AMBIGUOUS_NON_POSITIVE_COEFFICIENT).
  3. Run RUN_R1_2025_RECOMPUTE_FOR_LIVE04_BASE.py: full recompute (TG, TD, assignment,
     skims) and a NEW *_LIVE04_BASE_*.ver with a sealed *.LIVE04_BASE_RECEIPT.json next to it.
     The frozen distances 9720-9727 are DATA and stay.
  4. Start the calibration from that *_LIVE04_BASE_*.ver.  LIVE04 refuses a fresh run whose
     opened .ver, W/S coefficients or person OD 9101-9117 differ from the receipt (step 3 skipped,
     coefficients changed again, another file).

This script never saves a .ver.  The previous values of every changed zone are written to
%LOCALAPPDATA%\\R1C25_UNIT_BASE_PREP\\ (JSON report + CSV for an audit / manual undo).
Status STOPPED_BEFORE_ANY_WRITE: nothing changed.  MODEL_MAY_BE_CHANGED_CLOSE_WITHOUT_SAVING:
close Visum without saving.  RESET_IN_OPEN_MODEL_RUN_RECOMPUTE_BEFORE_SAVE: continue with step 3.
"""
from __future__ import annotations
import csv
import hashlib
import json
import os
import traceback
import uuid
from datetime import datetime
from pathlib import Path

RESET_ADD_SALARY = False          # True: ADD_SALARY -> 1 as well (W attraction via salary)
EXPECTED_ZONES = 681
WS_ATTRIBUTES = ('ADD_PROD_W', 'ADD_PROD_S', 'ADD_ATT_W', 'ADD_ATT_S')
DOMESTIC_ATTR = 'NOT_ZAHR'
AMDY_EXTERNAL_ATTR = 'AMDY_EXTERNI_ZONA'          # optional: reporting only
POPULATION_ATTR = 'POP_ZP'
FP_GROUPS = ('E_C', 'E_noC', 'noE_C', 'noE_noC', 'stud')   # = r1_15a2_mobility_zone_v24917.GROUPS
FP_ATTRIBUTES = tuple(p + g for p in ('FP_1_WORK_', 'FP_2_SERVICE_') for g in FP_GROUPS)
TOL = 1e-12


def sha_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def copy_guard(source):
    """Same isolated-copy rule as RECOMPUTE / FREEZE (CORDON_LIVE04_CONFIG.json)."""
    cfg = json.loads((Path(__file__).resolve().parent / 'CORDON_LIVE04_CONFIG.json').read_text(encoding='utf-8'))
    guard = cfg['isolated_copy_guard']
    name = source.name.upper()
    for token in guard['forbidden_version_name_tokens']:
        if token.upper() in name:
            raise RuntimeError('UNIT_RESET_FORBIDDEN_MODEL_VERSION_NAME:' + token)
    if not any(t.upper() in name for t in guard['required_version_name_tokens_any']):
        raise RuntimeError('UNIT_RESET_OPEN_MODEL_IS_NOT_AN_ISOLATED_COPY (name must contain one of %s)'
                           % guard['required_version_name_tokens_any'])
    return [t for t in guard['required_version_name_tokens_any'] if t.upper() in name]


def _out_dir():
    out = Path(os.environ.get('LOCALAPPDATA') or Path.home()) / 'R1C25_UNIT_BASE_PREP'
    out.mkdir(parents=True, exist_ok=True)
    return out


def _write(path, report):
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def _number(value):
    return int(round(float(value)))


def _values(zones, attr, n):
    """(com_index, value) rows of ALL zones; every value finite (fail closed)."""
    rows = list(zones.GetMultiAttValues(attr, False))
    if len(rows) != n:
        raise RuntimeError('UNIT_RESET_ZONE_COUNT:%s:%d' % (attr, len(rows)))
    out = []
    for index, raw in rows:
        if raw is None or raw == '':
            raise RuntimeError('UNIT_RESET_BLANK_VALUE:%s:index=%s' % (attr, index))
        value = float(raw)
        if value != value or value in (float('inf'), float('-inf')):
            raise RuntimeError('UNIT_RESET_NONFINITE_VALUE:%s:index=%s' % (attr, index))
        out.append((int(index), value))
    return out


def reset(visum):
    source = Path(str(visum.IO.CurrentVersionFile))
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    out = _out_dir()
    path = out / ('UNIT_RESET_RESULT_%s.json' % stamp)
    attrs = WS_ATTRIBUTES + (('ADD_SALARY',) if RESET_ADD_SALARY else ())
    report = {'schema': 'R1C25_UNIT_WS_RESET_V1', 'run_token': uuid.uuid4().hex, 'status': 'STARTED',
              'source_version': str(source), 'source_exists': source.is_file(), 'attributes': list(attrs),
              'reset_add_salary': RESET_ADD_SALARY, 'save_version_called': False, 'changed': {}}
    wrote = False
    try:
        if not report['source_exists'] or source.suffix.lower() != '.ver':
            raise RuntimeError('UNIT_RESET_OPEN_A_SAVED_VER_FIRST')
        if '2022' in source.name:
            raise RuntimeError('UNIT_RESET_ONLY_2025_MODEL')
        report['copy_guard'] = copy_guard(source)
        report['source_sha256'] = sha_file(source)
        zones = visum.Net.Zones
        nos = _values(zones, 'NO', EXPECTED_ZONES)
        no_by_index = {i: _number(v) for i, v in nos}
        if len(set(no_by_index.values())) != EXPECTED_ZONES:
            raise RuntimeError('UNIT_RESET_ZONE_NUMBERS_NOT_UNIQUE')
        domestic = {i for i, v in _values(zones, DOMESTIC_ATTR, EXPECTED_ZONES) if v >= 0.5}
        if not domestic:
            raise RuntimeError('UNIT_RESET_NO_DOMESTIC_ZONE')
        before = {a: dict(_values(zones, a, EXPECTED_ZONES)) for a in attrs}
        pop = dict(_values(zones, POPULATION_ATTR, EXPECTED_ZONES))
        fp = {i: 0.0 for i in no_by_index}
        for a in FP_ATTRIBUTES:
            for i, v in _values(zones, a, EXPECTED_ZONES):
                fp[i] += v
        try:
            amdy_ext = {i for i, v in _values(zones, AMDY_EXTERNAL_ATTR, EXPECTED_ZONES) if v >= 0.5}
            report['amdy_external_attribute'] = True
        except Exception:
            amdy_ext, report['amdy_external_attribute'] = set(), False
        # review cc3c3c4 N3: a zone with no W/S generation base whose W/S coefficients are all 0 is a
        # structural zero (auxiliary zone) - kept, never reset, never an error
        structural = {i for i in domestic if pop[i] == 0 and fp[i] == 0
                      and all(before[a][i] == 0 for a in WS_ATTRIBUTES)}
        bad = sorted((no_by_index[i], a, before[a][i]) for i in domestic - structural for a in attrs if before[a][i] <= 0)
        if bad:
            raise RuntimeError('UNIT_RESET_AMBIGUOUS_NON_POSITIVE_COEFFICIENT:%s (zone has population or FP '
                               'production, or only some W/S coefficients are 0; decide its meaning first)' % bad[:8])
        targets = domestic - structural
        report.update(domestic_zones=len(domestic), foreign_zones_untouched=EXPECTED_ZONES - len(domestic),
                      zone_classes={
                          'GENERATING_DOMESTIC': len(targets - amdy_ext),
                          'EXTERNAL_DISTRICT': sorted(no_by_index[i] for i in targets & amdy_ext),
                          'STRUCTURAL_ZERO_KEPT': sorted(no_by_index[i] for i in structural)},
                      structural_zero_zones=sorted(no_by_index[i] for i in structural))
        rows_csv = []
        for a in attrs:
            changed = sorted(i for i in targets if abs(before[a][i] - 1.0) > TOL)
            vals = [before[a][i] for i in changed]
            report['changed'][a] = {'zones': len(changed), 'min_before': min(vals) if vals else None,
                                    'max_before': max(vals) if vals else None}
            rows_csv += [{'attribute': a, 'zone_no': no_by_index[i], 'com_index': i, 'value_before': before[a][i],
                          'value_after': 1.0} for i in changed]
        with open(out / ('UNIT_RESET_PREVIOUS_VALUES_%s.csv' % stamp), 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=['attribute', 'zone_no', 'com_index', 'value_before', 'value_after'])
            w.writeheader(); w.writerows(rows_csv)
        report['previous_values_csv'] = str(out / ('UNIT_RESET_PREVIOUS_VALUES_%s.csv' % stamp))
        report['status'] = 'PREFLIGHT_PASS'
        _write(path, report)

        for a in attrs:
            changed = [i for i in sorted(targets) if abs(before[a][i] - 1.0) > TOL]
            if not changed:
                continue
            wrote = True
            zones.SetMultiAttValues(a, tuple((i, 1.0) for i in changed))
        # readback: every reset zone exactly 1, foreign + structural zones unchanged, zone order unchanged
        if dict((i, _number(v)) for i, v in _values(zones, 'NO', EXPECTED_ZONES)) != no_by_index:
            raise RuntimeError('UNIT_RESET_ZONE_ORDER_CHANGED')
        for a in attrs:
            after = dict(_values(zones, a, EXPECTED_ZONES))
            off = [no_by_index[i] for i in targets if abs(after[i] - 1.0) > TOL]
            moved = [no_by_index[i] for i in after if i not in targets and after[i] != before[a][i]]
            if off or moved:
                raise RuntimeError('UNIT_RESET_READBACK:%s:not_one=%s:untouched_changed=%s' % (a, off[:5], moved[:5]))
        if sha_file(source) != report['source_sha256']:
            raise RuntimeError('UNIT_RESET_SOURCE_VERSION_CHANGED')
        report['status'] = 'RESET_IN_OPEN_MODEL_RUN_RECOMPUTE_BEFORE_SAVE'
        report['next_step'] = ('RUN_R1_2025_RECOMPUTE_FOR_LIVE04_BASE.py (same Visum instance); LIVE04 accepts only '
                               'the *_LIVE04_BASE_*.ver with its sealed receipt')
        _write(path, report)
        _write(out / 'UNIT_RESET_RESULT_LAST.json', report)
        return report
    except BaseException:
        report['status'] = 'MODEL_MAY_BE_CHANGED_CLOSE_WITHOUT_SAVING' if wrote else 'STOPPED_BEFORE_ANY_WRITE'
        report['error'] = traceback.format_exc()[-2000:]
        _write(path, report)
        _write(out / 'UNIT_RESET_RESULT_LAST.json', report)
        raise


if __name__ == '__main__':
    reset(Visum)  # noqa: F821  (injected by PTV Visum)
