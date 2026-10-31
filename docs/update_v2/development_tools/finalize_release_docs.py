from pathlib import Path
import json,hashlib,shutil,csv,difflib,ast,sys
R=Path('/mnt/data/R1_CORDON_UPDATE_20261022');r=R/'release';base=R/'baseline/cordon_v1/R1_2025_CORDON_OPTIMIZER_V1_OFFLINE_20261019';d=r/'docs/update_v2';history=r/'docs/history_v1';history.mkdir(exist_ok=True)
RELEASE='R1_2025_CORDON_OPTIMIZER_V2_BUGFIX_PORT_20261022'
# Keep the original V1 reports, instead of presenting old numbers as V2 evidence.
for name in ['README_CZ.md','TEST_REPORT.md','PERFORMANCE_REPORT.md','FINAL_STATUS.json','IMPLEMENTATION_EVIDENCE.json','SOURCE_MANIFEST.json','SHA256SUMS.txt','API_GUIDE.md']:
    if not (history/name).exists():shutil.copy2(base/name,history/name)
cp='CP04_OFFLINE_INTEGRATION_REGRESSIONS_20261022';jp=R/'audit/DRIVE_JOURNAL.json';j=json.loads(jp.read_text())
if not any(x['checkpoint']==cp for x in j):
    x=json.loads((R/'checkpoints'/f'{cp}.zip.receipt.json').read_text());x.update(drive_verified=True,drive_id='1gC0MmvJsMFLS-VImL1nMxCteM80_6Xw5',drive_sha_sidecar_id='1nHPLhBjRWCzfiD_XG1ZcBozYzmQ_97PZ',verification_level='METADATA_NAME_SIZE_PARENT');j.append(x)
jp.write_text(json.dumps(j,indent=2))
# Exact V1->V2 source changes and full textual patches (not only a report).
changes=[];patch=[]
for p in sorted(base.rglob('*')):
    rel=p.relative_to(base)
    if not p.is_file() or '__pycache__' in rel.parts or '.pytest_cache' in rel.parts:continue
    q=r/rel
    if p.suffix=='.py' and q.exists() and p.read_bytes()!=q.read_bytes():
        changes.append({'path':rel.as_posix(),'before':hashlib.sha256(p.read_bytes()).hexdigest(),'after':hashlib.sha256(q.read_bytes()).hexdigest()})
        patch.extend(difflib.unified_diff(p.read_text(encoding='utf-8-sig').splitlines(True),q.read_text(encoding='utf-8-sig').splitlines(True),fromfile='V1/'+str(rel),tofile='V2/'+str(rel)))
(R/'audit/V1_V2_MODIFIED_PYTHON.json').write_text(json.dumps(changes,indent=2));(R/'audit/V1_V2_MODIFIED_PYTHON.diff').write_text(''.join(patch))
# Check science and original source data unchanged, including C17 policy implementation.
protected=['cordon2025/budget.py','cordon2025/feasibility.py','parent/r1_15a2_core.py','parent/r1_15a2_two_mode_v238.py','parent/r1_15a2_two_mode_adapter_v238.py','parent/r1_15a2_overnight_controller_v242.py']
records=[]
for name in protected:
    before=hashlib.sha256((base/name).read_bytes()).hexdigest();after=hashlib.sha256((r/name).read_bytes()).hexdigest();assert before==after,name
    records.append({'path':name,'sha256':after,'unchanged_vs_cordon_v1':True})
for p in (base/'data').rglob('*'):
    if p.is_file():
        q=r/p.relative_to(base);assert p.read_bytes()==q.read_bytes(),p
        records.append({'path':p.relative_to(base).as_posix(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'unchanged_vs_cordon_v1':True})
(R/'audit/PROTECTED_SCIENCE_AND_DATA.json').write_text(json.dumps(records,indent=2))
# Compile current files without generating bytecode inside the release.
compiled=[]
for folder in ['cordon2025','parent','tests','tools']:
    for p in sorted((r/folder).rglob('*.py')):
        if '__pycache__' in p.parts:continue
        compile(p.read_bytes(),str(p),'exec');compiled.append(p.relative_to(r).as_posix())
compile((r/'verify_release.py').read_bytes(),'verify_release.py','exec');compiled.append('verify_release.py')
(R/'audit/COMPILE_REPORT.json').write_text(json.dumps({'status':'PASS','python':sys.version,'files_compiled':len(compiled),'files':compiled},indent=2))
manifest=json.loads((d/'DONOR_LIBRARY_MANIFEST.json').read_text())
# Explicitly identify what is integrated, what is library-only, and what is excluded.
port=[
 {'family':'IOFIX3/IOFIX4 + PATHFIX3','runtime_status':'ACTIVE_OFFLINE','implementation':'cordon2025/io.py','source':'Fresh donor long-path and retry primitives; stricter cordon serializer','tests':'test_v2_io.py'},
 {'family':'GATEFIX2','runtime_status':'ACTIVE_ADAPTED_OFFLINE','implementation':'cordon2025/state.py::observation_roster','source':'Dynamic cordon identity, not PROFILE488 hardcode','tests':'test_v2_state_targeting.py'},
 {'family':'SEMRELOAD1','runtime_status':'ACTIVE_ADAPTED_OFFLINE','implementation':'cordon2025/state.py::snapshot_semantics','source':'Eight hashes including aggregate; reject mismatch, never LoadVersion','tests':'test_v2_state_targeting.py'},
 {'family':'FRESH0 isolation / CACHE_DISABLED / NO_WALLCLOCK','runtime_status':'ACTIVE_OFFLINE','implementation':'cordon2025/session.py, state.py','source':'Owned short root, exclusive lock, explicit completed input only','tests':'test_v2_session.py'},
 {'family':'PERF1/PERF2/PERF2C snapshot and readback','runtime_status':'LIBRARY_PORT_MOCK_VERIFIED_LIVE_DISABLED','implementation':'parent exact-byte libraries + state.readback_manager','source':'Exact snapshot, invalidation, fallback and diagnostic hash tests. No live adapter activation','tests':'97 unchanged donor tests in parent/tests; test_v2_state_targeting.py'},
 {'family':'V24916 targeting / skim','runtime_status':'CAL_ONLY_OFFLINE_GUIDANCE; LIVE_PROFILE_TARGETING_DISABLED','implementation':'cordon2025/targeting.py','source':'Sparse path pressure, sealed distances, mutable family only','tests':'test_v2_state_targeting.py'},
 {'family':'A0004/CYCLE3/PROFILE488/2022 oneclick','runtime_status':'NOT_PORTED_AS_RUN_CONFIGURATION','implementation':'None','source':'Must not replace 2025 scope, run authority or checkpoint','tests':'test_v2_port_identity.py'},
]
(d/'INTEGRATION_MATRIX.json').write_text(json.dumps(port,indent=2))
status={'release':RELEASE,'status':'OFFLINE_BUGFIX_PORT_TESTED_LIVE_BLOCKED','apply_permitted':False,'production_ready':False,'live_visum_tested':False,'native_windows_tested':False,
        'own_tests':{'passed':170,'failed':0},'parent_compatibility':{'passed':879,'skipped':4,'deselected':1},
        'raw_parent_suite':{'passed':879,'skipped':4,'failed':1,'failure':'Legacy exact V24915 package identity refuses two intentional V1 core patches; original guard unchanged'},
        'unchanged_donor_regressions_in_merged_tree':97,'exact_byte_added_libraries':len(manifest),'numerical_parity_arrays':40,
        'protected_science_and_data':True,'open_gates':['NO_REAL_2025_PATH_CACHE_IN_THIS_RUN','OBSERVATION_SEMANTICS_UNAPPROVED','YEAR_BRIDGE_2026_2025_UNAPPROVED','GEOMETRY_AND_NETWORK_APPROVAL_REQUIRED','C17_PRODUCTION_ALLOCATION_DISABLED','LIVE_TG_TD_NOT_VERIFIED','APPLY_FORBIDDEN'],
        'clean_unzip_evidence':'Delivered separately in FINAL_VERIFICATION.json after final ZIP creation'}
(r/'FINAL_STATUS.json').write_text(json.dumps(status,indent=2))
(r/'IMPLEMENTATION_EVIDENCE.json').write_text(json.dumps({'release':RELEASE,'integration':port,'modified_existing_python':changes,'protected_files':records,'live_visum_tested':False,'apply_permitted':False},indent=2))
readme='''# R1 2025 CORDON OPTIMIZER V2 - BUGFIX PORT (2026-10-22)

Stav: OFFLINE_BUGFIX_PORT_TESTED_LIVE_BLOCKED. Toto vydani aktualizuje existujici
kordonovy kalibrator V1 opravami ze dvou dodanych vetvi 15A2. Neni to zive
nakalibrovany model. Neni povoleno APPLY, COM pripojeni, trial assignment,
automaticky LoadVersion ani prime zapisy OD. Bezici kalibrace 2022 zustava mimo scope.

Zavislosti instaluj do samostatneho virtualniho prostredi, ne do Pythonu ziveho Visumu 2022.

## Co se zmenilo

- Robustni atomicke JSON/CSV/NPZ: kratke docasne nazvy, omezeny retry pri
  docasnem I/O zamku, hashovy readback, strict numericka data (NaN zakazano).
- Windows extended/UNC cesty na I/O hranici; kratky vychozi adresar ve Windows.
- Selhani telemetrie nemaskuje puvodni chybu; kriticka publikace nesmi tise selhat.
- Kontrola osmi semantickych hash polozek, site, demandu a parent stavu snapshotu.
  Chybejici evidence neni prohlasena za skutecny LIVE PASS.
- Dynamicky seznam a identita kordonovych pozorovani misto konstant PROFILE488.
- Zadny automaticky reuse/discovery stare cache. Explicitni dokoncena SQLite
  kopie zustava vstupem pro offline vypocet; to neni persistentni reuse assignmentu.
- Oddeleny vlastneny run root, exkluzivni zamek a kontrolovane checkpointy.
- CAL-only signed targeting a overene knihovni PERF2C/skim/readback API.
  Live targetovani profilu, controlery 2022 a jejich globalni activate() se nespousti.
- Nezavisly verifier hlida i necekane zbytkove Python soubory po chybnym overlay.

Matematika FISTA/deadband, C17, TG/TD realizovatelnosti a oba historicke
kordonove operatory zustaly zachovany. 52 novych donor knihoven ma presne
puvodni bajty, se zdroji v docs/update_v2/DONOR_LIBRARY_MANIFEST.json.
Puvodni parent/ soubory jsou shodne s Cordon V1; dve upravy oproti cistemu
V24915 byly vytvoreny uz ve V1 a nebyly timto portem prepsany.

## Bezpecne spusteni MIMO Visum

Rozbal do NOVE samostatne slozky. Neprepisuj 2022 ani puvodni V1.
Nespoustej historicke one-click skripty z parent/ v zivem modelu.

    python -m pip install -r requirements-tested.txt
    python verify_release.py
    python -m cordon2025 demo --run-name V2_SMOKE

Demo je oznaceno SYNTHETIC_DEMO_PASS: pouze synteticka data, nikoli intenzity R1.
Konzole vypise skutecny output. Windows default: %LOCALAPPDATA%/R1C25.
Na ostatnich platformach: OFFLINE_RESULTS v teto dodavce.
Volitelne --output-root musi byt nova prazdna nebo jiz vlastnena 2025 slozka.
Cizi existujici neprázdny adresar, existujici stejny run-name a soubezny zamek
jsou odmitnuty. Zamek se nikdy automaticky neprebira jako domnele zastaraly.

    python -m cordon2025 verify-run --run-directory C:/cesta/k/vytvorenemu/runu

verify-run overi kod, autority, vstupy a hashe artefaktu. Jde o overeni
handoffu pro novy explicitni offline vypocet ze stejnych vstupu. NENI to
resume iteraci FISTA ani navazani na zivy Visum assignment.

    python -m cordon2025 audit-inputs --run-name AUTORITY_V2
    python -m cordon2025 preflight --run-name PREFLIGHT_V2

Preflight bez skutecne cache zamerne vraci kod 2 a NO_2025_PATH_CACHE.
Nejde o numericke selhani. Naopak testovani nesmi takovou blokaci povysit na PASS.

## Skutecny explicitni snapshot 2025

    python -m cordon2025 inspect-cache --cache SNAPSHOT.sqlite --evidence SNAPSHOT.evidence.json --run-name INSPEKCE
    python -m cordon2025 propose --config CORDON_2025_CONFIG.json --cache SNAPSHOT.sqlite --evidence SNAPSHOT.evidence.json --allow-unapproved-scenario --run-name SCENAR

Pred propose je treba mit explicitni actuatable_zones, uplny DSeg scope,
objemovou paritu a konzistentni snapshot. Vse je stale offline.
--bounded-c17-scenario povoluje jen konzervativni scenarovy tolerancni ucet;
neni to schvaleni fyzickeho prirazeni C17 ke dvojicim stanovisť.
Nove expected_snapshot_semantics a expected_observation_roster jsou hashove
kontrakty, ne nahrada schvaleni observation semantics, site nebo roku.

## Overeni a historie

    python -m pytest tests -q
    python tools/parent_compatibility.py

Vlastni sada: 170 passed. Parent kompatibilita: 879 passed, 4 skipped,
1 explicitne deselected test vyzadujici byte-identicky puvodni V24915.
Puvodni guard zustal nezmeneny a porad spravne odmitne dva kordónove core
patche z V1. Nezmenena cela parent sada proto ma 1 expected identity failure;
neni to vydavano za all-pass. Kordonove testy overuji, ze guard stale odmita fork.

Puvodni reporty V1 jsou uchovany v docs/history_v1, puvodni CP v CHECKPOINTS
jsou historicke. Aktualni evidence je docs/update_v2. Vysledky z OFFLINE_RESULTS
pribalene z V1 jsou historicke synteticke ukazky; novy run dostava nove jmeno.

Zive Windows/Visum nebyly dostupne ani spousteny. Windows cesty, transientni
chyby, snapshot invalidace a rollback-readback jsou testovany simulaci.
Velky synteticky benchmark nemeri skutecny cas kalibrace R1.

Aktualizace nemeni data D1/D2/D3, C17, konfigurace/kontrolery 2022 ani jeji cache.
Dalsi live etapa vyzaduje autorizovany 2025 snapshot a drive definovane metodicke
brany; zadny dodany prepinac v teto verzi nedovoluje APPLY.
'''
# Non-ASCII text is introduced only via existing source naming; docs are UTF-8.
(r/'README_CZ.md').write_text(readme,encoding='utf-8')
(r/'API_GUIDE.md').write_text('''# V2 API additions

Original incidence/solve/feasibility API retained. No default solver math changed.

- cordon2025.io: atomic_output, write_json, write_csv, write_npz, copy_verified,
  safe_failure_report, telemetry_json, native_path. No global donor activate().
- cordon2025.state: snapshot_semantics, observation_roster, diagnostic_reference_hash,
  readback_manager. Declared semantic hashes do not prove a live COM read.
- cordon2025.targeting: path_targeting_report, seal_distance_context, td_component_context.
  CAL-only search evidence; no replacement of actual ordered cordon incidence.
- cordon2025.session: RunSession, verify_run. Immutable inputs and offline checkpoint
  verification; no implicit cache discovery, no solver-iteration restoration.

Future live integration must separately authorize snapshot collection, current
DSeg scope, state identity, windows COM and candidate acceptance. Retained donor
live classes are library-only and must not be blindly activated with 2022 profiles.
''')
perf=json.loads((R/'audit/PERFORMANCE_COMPARISON.json').read_text());b=perf['baseline_v1'];v=perf['updated_v2']
(r/'PERFORMANCE_REPORT.md').write_text(f'''# V2 synthetic performance comparison

Same exact generated SQLite, 100,000 geometries, 600,000 segment-volume rows,
4,899,808 ordered link occurrences and 200,000 mutable OD variables. Independent
measurement processes, one run per version, same environment Python {v['python']}.

| Measurement | Original V1 | Updated V2 |
|---|---:|---:|
| Incidence seconds | {b['incidence_seconds']:.6f} | {v['incidence_seconds']:.6f} |
| Solver seconds | {b['solver_seconds']:.6f} | {v['solver_seconds']:.6f} |
| Peak RSS MiB | {b['measure_process_peak_RSS_MiB']:.3f} | {v['measure_process_peak_RSS_MiB']:.3f} |
| Solver iterations | {b['solver_iterations']} | {v['solver_iterations']} |

Objectives and KKT values are exactly equal. Input hash: {v['source_cache_sha256']}.
Geometry decoded once, both historical incidence hypotheses produced.
C17 relaxation is disabled in this large-scale test; its separate synthetic
joint-solver tests still run. Results do not estimate live Visum time. Single-run
timing differences are not a statistical speedup claim. The earlier V1 figures
from another runtime are historical, not the baseline for this comparison.
''')
tests='''# V2 test report - actual executions 2026-10-22

| Suite | Result |
|---|---|
| Original cordon V1 baseline | 86 passed |
| Resume donor complete suite | 927 passed, 4 skipped |
| Fresh donor complete suite | 993 passed, 4 skipped |
| CP01 merged cordon | 90 passed |
| CP02 IO/finalizer | 110 passed |
| CP03 semantic/targeting | 139 passed |
| CP03 source-identity hardening first attempt | 140 passed, 1 failed (legacy error-code text compatibility) |
| CP03B fixed error-code compatibility | 141 passed |
| CP04 own session/end-to-end tests | 162 passed |
| Added unchanged donor tests on merged parent | 97 passed |
| Full raw merged parent | 879 passed, 4 skipped, 1 legacy package-identity failure |
| Parent compatibility, explicit identity deselection | 879 passed, 4 skipped, 1 deselected |
| CP05 full own suite including verifier | 170 passed |
| Authority workbook re-audit | STATIC_PASS |
| Independent original V1 vs V2 demos | 40 arrays exactly equal; numerical summaries equal |
| Large synthetic same-input comparison | identical solver objective/KKT; OFFLINE_SOLVER_PASS |

The first CP05 own-suite command was interrupted by a 30-second tool-call limit
before a result; it is not counted as PASS. The complete rerun returned rc=0.
The legacy parent identity test remains unchanged; it refuses exactly the two
intentional V1 core modifications. Its failure is reported, not hidden, and the
new cordon suite tests that refusal. No historical identity manifest was forged.

170 own tests include 84 additional tests relative to V1. The 97 donor tests
are part of the 879 compatibility total, not an additional independent count.
Fault injections include locks, ENOSPC, failed publication, corrupt readback,
nonfinite data, stale snapshots, wrong domain hashes, changed code/input,
concurrent roots, symlinks, immutable C17/frozen scope and CAL/VALID isolation.
Original two opposing TG/TD infeasibility counterexamples remain in the suite.

Clean-unzip/re-run evidence and remote readback are generated AFTER final packaging
and delivered as a separate final verification receipt. No live Visum or native
Windows execution is claimed. All production APPLY gates remain closed.
'''
(r/'TEST_REPORT.md').write_text(tests)
# Copy audit artifacts and logs, leaving large synthetic SQLite outside the delivery.
for p in (R/'audit').rglob('*'):
    if p.is_file():
        dest=d/'audit'/p.relative_to(R/'audit');dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
(d/'development_tools').mkdir(exist_ok=True)
for p in (R/'tools').glob('*.py'):shutil.copy2(p,d/'development_tools'/p.name)
# Final detailed report with explicit carried/inactive distinctions.
inputs=json.loads((R/'audit/INPUT_ARCHIVES.json').read_text());comp=json.loads((R/'audit/COMPARISON.json').read_text())
text=['# Detailni audit a implementacni report V2\n','## 1. Autority a smer portu\n']
for k,a in inputs.items():text.append(f"- {k}: {a['file']}; {a['files']} files, {a['bytes']} bytes; SHA256 `{a['sha256']}`.\n")
text+=['\nOba donory jsou aditivni vrstvy nad stejnym parentem. Puvodni matematicke root moduly se neprepisovaly. Cordon V1 upravoval dva core moduly, ktere zustaly v portu byte-identicke.\n','## 2. Trojcestne porovnani\n']
for k,a in comp.items():text.append(f"- {k}: changed={len(a['changed'])}, added={len(a['added'])}, removed={len(a['removed'])}; changed: {', '.join(a['changed'])}.\n")
text+=['\nFresh ma vyssi prioritu pro long-path I/O; resume poskytuje kontrolni SEMRELOAD/GATEFIX principy. Source filename, model year a network identity nejsou zamenitelne.\n','## 3. Aktivni implementace vs knihovni prenos\n']
for a in port:text.append(f"### {a['family']}\nStatus: **{a['runtime_status']}**.\nImplementace: `{a['implementation']}`.\n{a['source']}. Evidence: `{a['tests']}`.\n")
text+=['\n## 4. Explicitni neprenesene casti\n','Neaktivuji se nove donor one-clicky, hardcoded 488 roster, A0004/CYCLE3 recovery path, CSD calibration authority, automaticke pripojeni/LoadVersion, profile-only FlowBundle count cil nebo globalni activate(). Sest nevhodnych modulu bylo vyrazeno pri CP01; dalsi dva run-bound dependency moduly pri CP03B. Zbyva 52 exact-byte knihoven. PORT_DECISIONS obsahuje rozhodnuti po souborech.\n','## 5. Zachovani matematiky a dat\n','C17/budget.py, feasibility.py a oba jiz upravene parent core moduly jsou shodne s V1. D1/D2/D3 a cely data strom jsou shodne. Dve diagnosticke incidence zustavaji oddelene, neni zavedena koncova definice z rekonstrukce SDP4. Tolerance C17 neni neomezena a produkcni redistribuce zustava zakazana.\n','## 6. Obnova, chyba a write safety\n','Novy session checkpoint kontroluje code/config/authority/input fingerprints a hash publikovanych artefaktu. Nenahrazuje Visum checkpoint. verify-run je overeni pro opakovany explicitni offline run, nikoli pokracovani iteraci solveru. Zamek se neprebira automaticky; puvodni chyba ma prednost pred chybou finalizeru. Na disk nesmi byt oznacen dokoncenym checkpoint, pokud selze kriticky zapis/readback.\n','## 7. Neuzavrene hranice\n','Zadny realny 2025 SQLite snapshot nebyl novymi donory dodan jako nova kalibracni autorita. Prubeh zustava offline, bez ziveho Visumu a bez schvaleni observation semantics, year bridge, site/geometrie nebo C17 parove alokace. Windows paths jsou simulovane; nativni Win32 COM testy nebyly provedeny.\n','## 8. Testy\n',tests,'\n## 9. Checkpoint recovery\n','CP00 na Drive obsahuje vsechny ctyri vstupni ZIP archivy. CP01/02/03B/04 obsahuji stav kodu a audit. Pro obnovu z incremental CP pouzij puvodni Cordon V1 z CP00 a NEJNOVEJSI code overlay, ne libovolny rozpracovany 2022 strom. Pro standardni pouziti pouzij finalni uplny V2 ZIP rozbaleny do prazdne slozky. CP03 prvni lokalni snapshot selhal na kompatibilite chyboveho kodu; byl nasledovan CP03B, nikoli vydavan za PASS. Historicka evidence zustava uchovana.\n','## 10. Disk a Drive dukazy\n','Prubezne CP ZIPy byly lokalne znovu otevreny a CRC/SHA overeny. Drive readback potvrdil ID, jmeno, velikost a parent; konektor nevratil cloud checksum. SHA sidecary byly nahrany samostatne. Zaverecny remote hash, pokud dostupny z raw downloadu, je uveden pouze v FINAL_VERIFICATION.json.\n']
(r/'AUDIT_REPORT_CZ.md').write_text('\n'.join(text))
print('docs built; compiled',len(compiled),'protected',len(records),'modified existing python',len(changes))
