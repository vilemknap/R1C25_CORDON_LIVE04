# Test report - R1 2025 offline V1

Evidence se tyka skutecne provedenych prikazu, nikoli starych slovnich reportu.

| Sada | Passed | Skipped | Failed | Poznamka |
|---|---:|---:|---:|---|
| Pristine parent V24915 | 783 | 4 | 0 | Puvodni ZIP pred zmenami |
| Nove offline testy | 86 | 0 | 0 | Import/autoritity/incidence/C17/solver/feasibility/safety |
| Cela NEZMENENA parent sada nad forkem | 782 | 4 | 1 | Originalni deployment test odmitl dve zamerne zmeny |
| Parent kompatibilita | 782 | 4 | 0 | 1 explicitne vyrazeny identity test, jinak nezmenene testy |

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
