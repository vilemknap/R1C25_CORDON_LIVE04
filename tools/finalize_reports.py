"""Derive reports from actual stored evidence; no tests or model runs here."""
from pathlib import Path
import json,xml.etree.ElementTree as ET
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cordon2025.common import ROOT,write_json,read_config,deployment_gate,sha256


def junit(path):
    root=ET.parse(path).getroot();cases=list(root.iter('testcase'))
    failures=[{'name':t.attrib.get('name'),'class':t.attrib.get('classname'),
               'message':t.find('failure').attrib.get('message','')} for t in cases if t.find('failure') is not None]
    errors=sum(t.find('error') is not None for t in cases);skipped=sum(t.find('skipped') is not None for t in cases)
    return {'tests':len(cases),'passed':len(cases)-len(failures)-errors-skipped,'failed':len(failures),
       'errors':errors,'skipped':skipped,'failures':failures,'source':str(path.relative_to(ROOT)),
       'evidence_sha256':sha256(path)}


def finalize():
    ev=ROOT/'docs/evidence'
    baseline=junit(ev/'parent_baseline.xml');focused=junit(ev/'CP05_focused.xml')
    rawparent=junit(ev/'CP05_parent_unmodified_suite_expected_identity_failure.xml')
    compatible=junit(ev/'CP05_parent_compatibility.xml')
    compatible['explicitly_deselected']=1
    assert baseline['failed']==0 and focused['failed']==0 and compatible['failed']==0
    assert rawparent['failed']==1 and rawparent['passed']==782
    assert 'V24915_RUNTIME_BUNDLE_INVALID' in rawparent['failures'][0]['message']
    bench=[json.loads((ev/f'benchmark_{n}k.json').read_text()) for n in (20,100)]
    demo=json.loads((ROOT/'OFFLINE_RESULTS/CP05_SYNTHETIC_FINAL/DEMO_SUMMARY.json').read_text())
    audit=json.loads((ROOT/'data/audited/AUTHORITY_AUDIT.json').read_text())
    fork=json.loads((ev/'FORK_SOURCE_DELTA.json').read_text())
    result={'schema':'R1_CORDON_2025_OFFLINE_RESULT_V1','status':'OFFLINE_IMPLEMENTED_TESTED_LIVE_BLOCKED',
      'parent_version':'2.4.9.15','baseline_tests':baseline,'focused_tests':focused,
      'unchanged_parent_suite_on_modified_fork':rawparent,'parent_compatibility_suite':compatible,
      'legacy_full_suite_all_passed':False,'legacy_failure_classification':'EXPECTED_PRISTINE_DEPLOYMENT_HASH_REJECTION_NOT_RELAXED',
      'new_offline_tests_all_passed':True,'synthetic_demo_status':demo['status'],
      'static_authority_status':audit['status'],'compile_status':'PASS',
      'source_delta':fork,'gate':deployment_gate(read_config(),False),
      'c17_physical_pair_allocation':'PRODUCTION_DISABLED','real_2025_paths_tested':False,
      'TG_TD_live_realization':'NOT_VERIFIED','live_visum_tested':False,'production_ready':False,'apply_permitted':False,
      'checkpoint_scope':'LOCAL_ISOLATED_2025_ONLY','packaging_verification':'SEPARATE_FINAL_ZIP_VERIFIER_RECEIPT'}
    write_json(ROOT/'FINAL_STATUS.json',result)
    implementation={'origin_prompt_sha256':sha256(ROOT/'data/source/DEVELOPMENT_PROMPT.txt'),
        'module_evidence':{
         'authority':{'file':'cordon2025/authority.py','tests':'tests/test_authority.py','real_workbooks':True},
         'path_operator':{'file':'cordon2025/incidence.py','tests':'tests/test_incidence.py','reference_oracles':['original_15A2_core','readonly_2025_V1'],'actual_2025_cache':False},
         'C17':{'file':'cordon2025/budget.py','tests':'tests/test_budget.py','reference_oracle':'independent_SciPy_SLSQP','physical_allocation':False},
         'optimizer':{'file':'cordon2025/optimizer.py','tests':'tests/test_optimizer.py','backend':'existing_parent_solve_guidance_FISTA'},
         'realizability':{'file':'cordon2025/feasibility.py','tests':'tests/test_feasibility.py','basis':'synthetic_or_explicit_audited_local','no_basis':'NOT_VERIFIED'},
         'safety':{'file':'cordon2025/common.py','tests':'tests/test_hardening.py','old_deployment_guard':'MUST_REJECT_FORK'}},
        'modified_parent_modules':fork['modified'],'apply_permitted':False,'live_visum_tested':False}
    write_json(ROOT/'IMPLEMENTATION_EVIDENCE.json',implementation)
    checks=[
     ('01','16/32 map, exact directions',['test_actual_mapping','test_same_linkno_opposite_direction']),
     ('02','Two explicit unapproved hypotheses',['test_decode_once_mode_scope_and_fixed','test_real_unapproved_requires_explicit_scenario']),
     ('03','Repeat audit',['test_decode_once_mode_scope_and_fixed']),
     ('04','DSeg separate, geometry unapproved',['test_mode_identity_not_inferred','test_dseg_mode_authority_independent_of_matching_two_tables']),
     ('05','Fixed prediction not actuator',['test_decode_once_mode_scope_and_fixed','test_frozen_actuator_rejected']),
     ('06','Path volume/share parity, unsupported new OD',['test_bad_parity','test_epoch_support_and_zero','test_sparse_adjoint_and_abs_relative_change_equivalence']),
     ('07','Actual D1-D2-D3 audit',['test_actual_lineage']),
     ('08','Shared station/category/global credits',['test_station_shared_across_relations_and_reverse','test_global_tighter_than_station_caps']),
     ('09','No unrestricted per-pair tolerance',['test_actual_C17_not_double_counted','test_disabled_and_unapproved_no_relaxation']),
     ('10','Signed loss, bounds, regularization',['test_parent_solver_signed_cordon_loss','test_shared_C17_joint_solver_and_independent_oracle']),
     ('11','Infeasible actuator patterns',['test_opposing_cycle_has_zero_marginal_error_but_cannot_be_realized']),
     ('12','CAL/VALID isolation',['test_validation_never_used','test_role_split_and_aggregation']),
     ('13','Category, year, bridge gate',['test_config_rejects_scope_or_write_switch','test_all_approval_flags_still_do_not_allow_v1_apply']),
     ('14','Missing cache cannot pass live',['test_nonexistent_cache_fails_not_live_pass']),
     ('15','Offline no model writes',['test_no_live_import_needed_in_clean_process','test_parent_config_and_controller_bytes_unchanged','test_old_2022_entrypoint_refuses_modified_fork_identity'])]
    actual=[t.attrib['name'] for t in ET.parse(ev/'CP05_focused.xml').getroot().iter('testcase')]
    # Resolve names from the real suite, never emit invented evidence as PASS.
    for i,(num,label,names) in enumerate(checks):
        missing=[n for n in names if not any(a==n or a.startswith(n+'[') for a in actual)]
        checks[i]={'id':num,'requirement':label,'test_names':names,'status':'TEST_NAMES_NEED_RECONCILIATION' if missing else 'PASS','unresolved_test_names':missing}
    assert not any(c['unresolved_test_names'] for c in checks), 'ACCEPTANCE_TEST_EVIDENCE_MISSING'
    write_json(ROOT/'ACCEPTANCE_MATRIX.json',checks)
    testtext=f'''# Test report - R1 2025 offline V1

Evidence se tyka skutecne provedenych prikazu, nikoli starych slovnich reportu.

| Sada | Passed | Skipped | Failed | Poznamka |
|---|---:|---:|---:|---|
| Pristine parent V24915 | {baseline['passed']} | {baseline['skipped']} | 0 | Puvodni ZIP pred zmenami |
| Nove offline testy | {focused['passed']} | {focused['skipped']} | 0 | Import/autoritity/incidence/C17/solver/feasibility/safety |
| Cela NEZMENENA parent sada nad forkem | {rawparent['passed']} | {rawparent['skipped']} | {rawparent['failed']} | Originalni deployment test odmitl dve zamerne zmeny |
| Parent kompatibilita | {compatible['passed']} | {compatible['skipped']} | 0 | 1 explicitne vyrazeny identity test, jinak nezmenene testy |

Jediny FAIL plne stare sady je
`test_v24915_config_runtime_bundle_and_lineage_are_hash_locked`:
`V24915_RUNTIME_BUNDLE_INVALID`, SIZE_MISMATCH presne u `r1_15a2_core.py`
a `r1_15a2_two_mode_v238.py`. Neni vydavan za PASS ani automaticky tise
preskocen. Log a JUnit jsou zachovany v docs/evidence. Puvodni runtime
manifest/guard jsme NEPREPSALI, aby stary 2022 entrypoint tuto vetev nespustil.
Novy test vyzaduje jeho spravne odmitnuti. Nova release identita ma vlastni
SOURCE_MANIFEST a verify_release.py. To je rozliseni vydani, ne uvolneni guardu.

## Minimalni acceptance

ACCEPTANCE_MATRIX.json mapuje 15 bodu zadani na konkretni spustene testy.
Dve protichudne synteticke cycle patterns maji marginalni chybu 0, shadow
objective ~3.8e-22, ale full-OD realizacni RMSE ~20 vozidel. Obe jsou spravne
INFEASIBLE_TG_TD v uvedene synteticke aktuatorove soustave. Feasible control
ma full-OD RMSE < 1e-8. Pro skutecny model bez response authority vracime
TG_TD_REALIZATION_NOT_VERIFIED; marginalni projekce to nesmi obejit.

C17 projekce je porovnana s nezavislym SLSQP resenim; joint optimizer take.
Parita incidence je porovnana s originalnim jadrem 15A2 i read-only V1.
Test importu aktivne zakazuje moduly COM. Compileall vsech Python modulu
nove vetve a parent stromu byl proveden s rc=0.

## Opakovani

```text
python -m pytest tests -q
python tools/parent_compatibility.py
python -m compileall -q cordon2025 tools verify_release.py parent
python -m cordon2025 demo --run-name NOVY_TESTOVACI_RUN
```

Spusteni cele puvodni sady `cd parent; python -m pytest tests -q` ma zamerne
vyvolat vyse vysvetleny identity FAIL. Nespousti zive procedury.

## Zachovana evidence oprav

CP02_attempt1/2: opravy fixture/oracle kontraktu; CP03_attempt1: odhaleni
nutnosti kontrolovat i korekcni vektory Dykstrovy projekce; CP04_attempt1:
prilis prisny test ignoroval nenulove minimum L1/L2, nahrazen analytickym
optimum check. Puvodni logy nebyly smazany. CP05 velky benchmark prvne
nedodal vysledek v casovem limitu; nasledny merici proces byl dokonceny.
Zadne z techto pokusu nevydavame za uspesny run.

**Nebylo testovano:** live Visum/COM, realna 2025 path cache, zivy TG/TD run,
trial assignment, acceptance nebo rollback 2025, schvalena survey semantika,
fyzicke prirazeni C17 ani rocni most. Jejich stav zustava BLOCKED/NOT_VERIFIED.
'''
    (ROOT/'TEST_REPORT.md').write_text(testtext,encoding='utf-8')
    rows=[]
    for b in bench:
        x=b['measurement'];rows.append(f"| {x['geometries']:,} | {x['segment_volume_rows']:,} | {x['ordered_link_occurrences']:,} | {x['incidence_seconds']:.3f} | {x['solver_seconds']:.3f} | {x['measure_process_peak_RSS_MiB']:.1f} |")
    perf='''# Performance report - SYNTHETIC ONLY

Mereni na explicitne konstruovanych cestach ve formatu V24915 SQLite. Nejde
o vytvareni alternativnich cest pro realny model. Prumerna delka je ~49 hran;
16 station IDs, dva mody a 12 demand segmentu s nezavislymi Vol(AP).
Tvorba fixture a mereni probehly v oddelenych procesech. Peak RSS z mereni
proto nezahrnuje predchozi vyrobu fixture. Jeden BLAS/OMP thread.

| Geometrie | Objemove radky DSeg | Vyskyt hran | Incidence s | Solver s | Peak RSS MiB |
|---:|---:|---:|---:|---:|---:|
'''+ '\n'.join(rows)+'''

Velka uloha ma 200 000 mutable OD promennych a 666 624 nenulovych clenu
all-pairs operatoru. Dekodovano presne 100 000 geometrii, nikoli 12x tolik
ani 240x tolik. Soucasne vznikaji OBE hypotezy. Per-DSeg a per-OD parita PASS.
Solver je puvodni FISTA nad nove sestavenou kordonovou ulohou a konvergoval
podle ulozeneho KKT/gradient mapping kriterium. Nejde o Visum assignment.

C17 polytope je v tomto velkem sparse benchmarku DISABLED. Jeho joint
konvergence/projekce je overena samostatnymi malymi testy a demo. Neni zde
mereni vykonu C17 na plne realne uloze ani tvrzeni o zrychleni realneho R1.

Prvni kombinovany pokus pro 100k skoncil tool timeoutem bez mericiho reportu.
Fixture se dokoncilo. Nasledujici SAMOSTATNE mereni ze stejneho snapshotu
probehl s rc=0; jeho log/JSON jsou autorita techto cisel. Root cause prvniho
preruseni nebyla prokazana a nebyl oznacen jako PASS.

Reprodukce do noveho izolovaneho adresare (ne do existujici cache):

```text
python tools/benchmark.py --count 20000 --work-dir OFFLINE_RESULTS/BENCH_NOVY_20K --report OFFLINE_RESULTS/BENCH_NOVY_20K.json
python tools/benchmark.py --count 100000 --work-dir OFFLINE_RESULTS/BENCH_NOVY_100K --report OFFLINE_RESULTS/BENCH_NOVY_100K.json
```

Velke fixture databaze nejsou nutne pro spusteni baliku; jsou reprodukovatelne
generatorem. Do release patri merene logy/JSON a male end-to-end SQLite demo.
'''
    (ROOT/'PERFORMANCE_REPORT.md').write_text(perf,encoding='utf-8')
    print(json.dumps({'focused':focused['passed'],'missing_acceptance_test_names':[c for c in checks if c['unresolved_test_names']]}))

if __name__=='__main__':finalize()
