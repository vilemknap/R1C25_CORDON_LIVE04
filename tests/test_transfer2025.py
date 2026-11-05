"""TRANSFER2025: 2022 -> 2025 parameter transfer and LIVE04 readiness (synthetic hosts only)."""
import json
import numpy as np
import pytest
from fake_live04 import Live04Visum
from cordon2025.common import ContractError, canonical_hash, read_json
from cordon2025 import transfer2025 as tr
from cordon2025.live02_guard import WriteForbidden

OPT = {'min_free_disk_gib': 0, 'com_retry_initial_delay_seconds': 0., 'com_retry_max_delay_seconds': 0.}
FAST = {'readiness_after_import': False}


def calibrated_2022(tmp_path):
    a = Live04Visum(tmp_path / 'm2022')
    src = tmp_path / 'm2022' / 'R1_2022_SYNTHETIC_CALIBRATED.ver'
    src.write_bytes(b'calibrated 2022'); a.IO.CurrentVersionFile = str(src)
    for r in a.Net.Zones.rows[:50]:
        r['ADD_PROD_W'] = 1.2; r['ADD_ATT_S'] = 0.9
    for code, st in a.ops[5].TripDistributionParameters.strata.items():
        if 'WORK' in code:
            st.GravitationParameters.values['PARA_B'] += 0.1
            st.GravitationParameters.values['PARA_C'] *= 1.1
    for r in a.Net.Links.rows[:3]:
        r['ADDVAL1'] = 2.0
    a.writes.clear(); a.allowed_writes.clear()
    return a


def export(tmp_path):
    a = calibrated_2022(tmp_path)
    e = tr.export_parameters(a, output_root=tmp_path / 'out')
    assert e['status'] == 'EXPORTED' and not a.allowed_writes and not a.writes
    return a, e


def rewrite(path, fn):
    data = read_json(path); fn(data)
    data.pop('content_sha256'); data['content_sha256'] = canonical_hash(data)
    path.write_text(json.dumps(data), encoding='utf-8')


def zones(v, attrs=('ADD_PROD_W', 'ADD_ATT_S', 'ADD_PROD_S')):
    return {a: [float(r[a]) for r in v.Net.Zones.rows] for a in attrs}


def td(v):
    return {c: dict(s.GravitationParameters.values) for c, s in v.ops[5].TripDistributionParameters.strata.items()}


def test_export_import_recompute_save_and_ready(tmp_path):
    a, e = export(tmp_path)
    assert e['zones'] == 681 and e['nonzero_addval1_links'] == 3 and e['model_writes'] == 0
    b = Live04Visum(tmp_path / 'm2025')
    opened = b.IO.CurrentVersionFile
    r = tr.import_and_recompute(b, output_root=tmp_path / 'out', options=OPT)
    assert r['status'] == 'IMPORTED_RECOMPUTED_SAVED' and r['readiness'] == 'READY_FOR_LIVE04'
    assert r['writes'] == {'zone_values': 100, 'td_components': 5, 'addval1_links': 3}
    # parameters of 2025 now equal the calibrated 2022 ones
    assert zones(b) == zones(a) and td(b) == td(a)
    assert [r_['ADDVAL1'] for r_ in b.Net.Links.rows[:3]] == [2.0, 2.0, 2.0]
    # one masked recompute, LONG clean, new version saved, open file untouched
    f = tr.Path(r['folder'])
    plan = read_json(f / 'RECOMPUTE' / 'LONG_MASK_EXECUTION_PLAN.json')
    assert [p[0] for p in plan['phases']] == ['THROUGH_TD', 'REALIZATION', 'ASSIGNMENT_SKIMS']
    assert r['long_support_clean'] and '_LIVE04_BASE_' in r['saved_version']['path']
    assert b.saved_versions == [r['saved_version']['path']] and tr.Path(opened).read_bytes() == b'SYNTHETIC_NOT_A_VISUM_VERSION'
    km = b.km >= 80.0
    assert not np.any(b.component[9111].values[~km]) and not np.any(b.component[9305].values[~km])
    audit = r['write_audit']
    assert not audit['forbidden_attempts'] and audit['addval1_writes'] == 3 and audit['save_version_calls'] == 1
    assert audit['direct_od_matrix_writes'] == 0 and not b.writes
    assert (f / 'TRANSFER_PLAN.json').exists()
    ready = sorted(tr.Path(tmp_path / 'out').glob('READINESS_*/00_RESULT.json'))
    checks = {c['check']: c for c in read_json(ready[-1])['checks']}
    assert checks['PARAMETERS_EQUAL_EXPORT']['status'] == 'PASS'
    # LIVE04.10.1: no path capture in READINESS by default (the calibration captures its own baseline);
    # the observation contract incl. the station profile sign table is checked statically.
    assert 'CORDON_BASELINE_CAPTURE' not in checks
    assert checks['OBSERVATION_CONTRACT']['status'] == 'PASS'


def test_zone_set_mismatch_stops_before_any_write(tmp_path):
    _, e = export(tmp_path)
    rewrite(tr.Path(e['file']), lambda d: d['zones'].pop())
    b = Live04Visum(tmp_path / 'm2025'); z0 = zones(b)
    with pytest.raises(ContractError, match='TRANSFER_ZONE_SET_DIFFERS'):
        tr.import_and_recompute(b, output_root=tmp_path / 'out', options=OPT, config_overrides=FAST)
    res = read_json(sorted(tr.Path(tmp_path / 'out').glob('IMPORT_*/00_RESULT.json'))[-1])
    assert res['status'] == 'IMPORT_FAILED' and res['model_state'] == 'UNCHANGED_NO_WRITE'
    assert zones(b) == z0 and not b.allowed_writes and b.executions == 0


def test_matching_zones_only_policy_transfers_common_zones(tmp_path):
    _, e = export(tmp_path)
    rewrite(tr.Path(e['file']), lambda d: d['zones'].remove(15))   # zone 15 = second zone (row 1)
    b = Live04Visum(tmp_path / 'm2025')
    r = tr.import_and_recompute(b, output_root=tmp_path / 'out', options=OPT,
                                config_overrides=dict(FAST, zone_policy='MATCHING_ZONES_ONLY', save_new_version=False))
    assert r['plan']['zones']['only_in_2025'] == [15] and r['status'] == 'IMPORTED_RECOMPUTED'
    assert b.Net.Zones.rows[1]['ADD_PROD_W'] == 1.0 and b.Net.Zones.rows[0]['ADD_PROD_W'] == 1.2


def test_tampered_export_and_same_source_are_rejected(tmp_path):
    a, e = export(tmp_path)
    path = tr.Path(e['file'])
    data = read_json(path); data['td'][0]['b'] += 1.0
    path.write_text(json.dumps(data), encoding='utf-8')
    b = Live04Visum(tmp_path / 'm2025')
    with pytest.raises(ContractError, match='TRANSFER_EXPORT_CONTENT_HASH'):
        tr.import_and_recompute(b, output_root=tmp_path / 'out', options=OPT, config_overrides=FAST)
    rewrite(path, lambda d: None)
    with pytest.raises(ContractError, match='TRANSFER_TARGET_IS_THE_2022_SOURCE'):
        tr.import_and_recompute(a, output_root=tmp_path / 'out', options=OPT, config_overrides=FAST)
    assert not b.allowed_writes and not a.allowed_writes


def test_unmatched_addval1_links(tmp_path):
    _, e = export(tmp_path)
    rewrite(tr.Path(e['file']), lambda d: d['addval1'].update({'1:2:3': 4.0}))
    b = Live04Visum(tmp_path / 'm2025')
    with pytest.raises(ContractError, match='TRANSFER_ADDVAL1_LINKS_MISSING_IN_2025:1'):
        tr.import_and_recompute(b, output_root=tmp_path / 'out', options=OPT,
                                config_overrides=dict(FAST, addval1_policy='FAIL_ON_UNMATCHED_NONZERO'))
    assert not b.allowed_writes
    r = tr.import_and_recompute(b, output_root=tmp_path / 'out', options=OPT,
                                config_overrides=dict(FAST, save_new_version=False))
    assert r['plan']['addval1']['unmatched_nonzero_in_2025'] == 1 and r['writes']['addval1_links'] == 3


def test_recompute_failure_restores_parameters(tmp_path):
    _, e = export(tmp_path)
    b = Live04Visum(tmp_path / 'm2025'); z0 = zones(b); t0 = td(b)
    b.fail_execute_on = {1}
    with pytest.raises(Exception):
        tr.import_and_recompute(b, output_root=tmp_path / 'out', options=OPT, config_overrides=FAST)
    res = read_json(sorted(tr.Path(tmp_path / 'out').glob('IMPORT_*/00_RESULT.json'))[-1])
    assert res['status'] == 'IMPORT_FAILED' and set(res['restore'].values()) == {'RESTORED'}
    assert res['model_state'] == 'PARAMETERS_RESTORED_DEMAND_MAY_BE_RECOMPUTED_REOPEN_THE_COPY'
    assert zones(b) == z0 and td(b) == t0 and [r_['ADDVAL1'] for r_ in b.Net.Links.rows[:3]] == [0.0, 0.0, 0.0]
    assert not b.saved_versions


def test_readiness_flags_unmasked_long_without_writing(tmp_path):
    b = Live04Visum(tmp_path / 'm2025', masked_start=False)
    r = tr.readiness(b, output_root=tmp_path / 'out', options=OPT, baseline_capture=False)
    checks = {c['check']: c['status'] for c in r['checks']}
    assert r['status'] == 'NOT_READY' and r['failed'] == ['LONG_SUPPORT_MASKED']
    assert checks['OPERATIONS_TD_17_20'] == 'PASS' and checks['MATRIX_SOURCE_TYPES'] == 'PASS'
    assert checks['NO_MODEL_WRITE'] == 'PASS' and not b.allowed_writes and b.executions == 0


def test_transfer_guard(tmp_path):
    b = Live04Visum(tmp_path / 'm2025')
    audit = tr.TransferWriteAudit(); g = tr.TransferGuardedCOM(b, 'Visum', audit)
    link = list(g.Net.Links.GetAll)[0]
    with pytest.raises(WriteForbidden):
        link.SetAttValue('ADDVAL1', 1)                   # permission closed
    audit.addval_writes = True
    link.SetAttValue('ADDVAL1', 1)
    with pytest.raises(WriteForbidden):
        link.SetAttValue('TYPENO', 1)
    with pytest.raises(WriteForbidden):
        g.Net.Zones.SetMultiAttValues('ADD_PROD_W', [(1, 2.0)], False)   # zone attrs closed by default
    target = tmp_path / 'NEW_LIVE04_BASE.ver'
    with pytest.raises(WriteForbidden):
        g.IO.SaveVersion(str(target))
    audit.save_target = target
    with pytest.raises(WriteForbidden):
        g.IO.SaveVersion(str(tmp_path / 'OTHER.ver'))
    g.IO.SaveVersion(str(target))
    assert audit.summary()['addval1_writes'] == 1 and audit.summary()['save_version_calls'] == 1


def test_transfer_config_guards():
    for over, err in (({'zone_policy': 'X'}, 'TRANSFER_ZONE_POLICY'),
                      ({'attribute_groups': {'ws_coefficients': False}}, 'TRANSFER_REQUIRED_GROUP_DISABLED'),
                      ({'recompute': False}, 'TRANSFER_SAVE_REQUIRES_RECOMPUTE')):
        with pytest.raises(ContractError, match=err):
            tr.load_transfer_config(overrides=over)


def test_transfer_launchers(tmp_path):
    import RUN_R1_2025_LIVE04_READINESS as entry
    assert entry.main({})['reason'] == 'VISUM_NOT_INJECTED'
    import cordon_transfer_bootstrap as bootstrap
    a = calibrated_2022(tmp_path)
    result = bootstrap.launch({'Visum': a}, 'EXPORT', output_root=tmp_path / 'out')
    assert result['status'] == 'EXPORTED', result


# ---------------------------------------------------------------- RECOMPUTE (coefficients already in place)
def test_recompute_base_without_export_writes_no_parameter_and_is_ready(tmp_path):
    b = Live04Visum(tmp_path / 'm2025', masked_start=False)
    for r in b.Net.Zones.rows[:50]:
        r['ADD_PROD_W'] = 1.2                              # coefficients transferred earlier by the user
    b.writes.clear(); b.allowed_writes.clear()
    z0 = zones(b); t0 = td(b); a0 = [r_['ADDVAL1'] for r_ in b.Net.Links.rows]
    opened = b.IO.CurrentVersionFile
    r = tr.recompute_base(b, output_root=tmp_path / 'out', options=OPT)
    assert r['status'] == 'RECOMPUTED_SAVED' and r['readiness'] == 'READY_FOR_LIVE04', r
    assert r['parameters_imported'] is False and r['station_links']['all_present']
    assert zones(b) == z0 and td(b) == t0 and [r_['ADDVAL1'] for r_ in b.Net.Links.rows] == a0
    assert not list(tr.Path(tmp_path / 'out').glob('EXPORT_*'))
    assert r['long_support_clean'] and '_LIVE04_BASE_' in r['saved_version']['path']
    assert b.saved_versions == [r['saved_version']['path']]
    assert tr.Path(opened).read_bytes() == b'SYNTHETIC_NOT_A_VISUM_VERSION'
    km = b.km >= 80.0
    assert not np.any(b.component[9111].values[~km]) and not np.any(b.component[9305].values[~km])
    audit = r['write_audit']
    assert audit['addval1_writes'] == 0 and audit['save_version_calls'] == 1 and not audit['forbidden_attempts']
    assert audit['direct_od_matrix_writes'] == 0 and not b.writes
    ready = sorted(tr.Path(tmp_path / 'out').glob('READINESS_*/00_RESULT.json'))
    checks = {c['check']: c['status'] for c in read_json(ready[-1])['checks']}
    assert 'PARAMETERS_EQUAL_EXPORT' not in checks and 'CORDON_BASELINE_CAPTURE' not in checks
    assert checks['OBSERVATION_CONTRACT'] == 'PASS'
    # the capture can still be requested explicitly
    again = tr.readiness(b, output_root=tmp_path / 'out2', options=OPT, baseline_capture=True)
    caps = {c['check']: c for c in again['checks']}
    assert caps['CORDON_BASELINE_CAPTURE']['status'] == 'PASS', caps['CORDON_BASELINE_CAPTURE']
    assert set(caps['CORDON_BASELINE_CAPTURE']['detail']) == {'FIRST_LAST', 'EXACT_TWO_HITS', 'ALL_ORDERED_UNIQUE_PAIRS'}


def test_recompute_base_missing_station_link_stops_before_any_write(tmp_path):
    b = Live04Visum(tmp_path / 'm2025')
    from cordon2025.authority import mapping
    stations, _ = mapping(tr.ROOT / 'data/audited/STATION_MAPPING.csv')
    key = next(k for k, s in stations.items() if s == 2)
    b.Net.Links.rows[:] = [r_ for r_ in b.Net.Links.rows
                           if (int(r_['NO']), int(r_['FROMNODENO']), int(r_['TONODENO'])) != key]
    with pytest.raises(Exception, match='STATION_LINKS_MISSING'):
        tr.recompute_base(b, output_root=tmp_path / 'out', options=OPT, config_overrides=FAST)
    res = read_json(sorted(tr.Path(tmp_path / 'out').glob('RECOMPUTE_*/00_RESULT.json'))[-1])
    assert res['model_state'] == 'UNCHANGED_NO_WRITE' and b.executions == 0 and not b.saved_versions


def test_recompute_base_rejects_unmarked_or_2022_name(tmp_path):
    b = Live04Visum(tmp_path / 'm2025')
    for name in ('R1_CSD22_kal_2025.ver', 'R1_2022_KOPIE.ver'):
        p = tmp_path / 'm2025' / name; p.write_bytes(b'x'); b.IO.CurrentVersionFile = str(p)
        with pytest.raises(Exception, match='LIVE02_'):
            tr.recompute_base(b, output_root=tmp_path / 'out', options=OPT, config_overrides=FAST)
    assert b.executions == 0 and not b.saved_versions


def test_recompute_base_launcher(tmp_path):
    import RUN_R1_2025_RECOMPUTE_FOR_LIVE04_BASE as entry
    assert entry.main({})['reason'] == 'VISUM_NOT_INJECTED'
