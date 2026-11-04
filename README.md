# R1 2025 – kordónová kalibrace LIVE04.8.1 (v7 @ 7b4c681)

Kordónový kalibrátor TG + TD (ANPR průzkum 2026, FIRST_LAST + C17) portovaný na profilový kalibrátor
[`vilemknap/R1_15A2_V24917_v7`](https://github.com/vilemknap/R1_15A2_V24917_v7) @ `977cef4` (P2.5/A4),
s pamětí mezi cykly (LIVE04.1) a přenosem kalibrace 2022 → 2025 (TRANSFER2025, LIVE04.2).

- Start: `00_START_HERE_LIVE04_CZ.txt`, spuštění ve Visumu: `RUN_R1_2025_CORDON_LIVE04_V7_TG_TD_CYCLE.py`
- Příprava verze 2025: `RUN_R1_2022_EXPORT_CALIBRATED_PARAMETERS.py` → `RUN_R1_2025_IMPORT_AND_RECOMPUTE.py` → `RUN_R1_2025_LIVE04_READINESS.py`, návod `docs/transfer2025/TRANSFER2025_CZ.md`
- Návod: `LIVE04_RUNBOOK_CZ.md`
- Report: `docs/live04/LIVE04_IMPLEMENTATION_REPORT_CZ.md`, `docs/live04/LIVE04_1_MEMORY_CZ.md`
- LIVE04.3 (2026-11-01): domácí obálky W/S ADD_PROD 0,5–3,0 a ADD_ATT 0,5–5,0 (TG obálky, MOBILITY2/MOBILITYZONE1, plot atrakce); report kap. 7
- LIVE04.4 (2026-11-01): port v7 @ 7b4c681 – trip generation bez CATCH_UP (REFINE ±5 %), měřený zónový refit a STEP1_PRED_AUDIT; SupplyMix (ADDVAL1) řízený kordonovými řádky v sudých cyklech; GEH limity a severity SEVRELAX3 na 136 kordonových řádcích; `docs/live04/LIVE04_4_V7_7B4C681_CZ.md`, report kap. 8
- LIVE04.4.1 (2026-11-03): `RUN_R1_2025_RECOMPUTE_FOR_LIVE04_BASE.py` – příprava verze 2025, ve které už jsou koeficienty (bez exportu/importu): kontrola 32 hran stanic, jeden přepočet v7 s LONG maskou (vzniknou cesty), nová `…_LIVE04_BASE_….ver`, READINESS; `docs/transfer2025/TRANSFER2025_CZ.md`
- LIVE04.4.2 (2026-11-03): síť 2026-11-03 – stanice SDP15 přemapována na hrany rozdělených pásů 9800634 (9900317→9900312) a 9800637 (9900314→9900318); ostatních 30 hran beze změny; `docs/network_20261103/REVIEWED_CHANGES.json`
- LIVE04.5 (2026-11-03): obálky koeficientů W/S rozšířeny – ADD_PROD 0,5–3,15, ADD_ATT 0,5–5,5 (obálky TG, pás MOBILITY2/MOBILITYZONE1, plot atrakce, donorový ATTRACTION_BAND); `mg_max_ratio = 3,15` je deklarovaná odchylka od v7; SCHOOL/LONG/ZAHR beze změny
- LIVE04.5.1–5.3 (2026-11-04): prediktor ukotvený na zachycených řádcích (mřížka objemů cest 0,001); tolerantní ověření rollbacku řádků po přesné shodě snapshotu; trial s nedostatečnou konvergencí (ASSIGNMENT_NOT_TIGHT) se odmítne a krok zmenší; při zastavení se uloží poslední přijatý stav; tichý běh ve Visumu (potlačení varování procedur s přesným obnovením, výstup Pythonu do PYTHON_CONSOLE.log, SILENT_MODE.json)
- LIVE04.6–7.1 (2026-11-04): rychlejší zachycení pokusů – geometrie cest se čte jen pro reprezentativní DSeg a ostatní DSegy se ověří intenzitami VOLVEH_DSEG na 32 hranách stanic (CAPTURE_TIMING.json); epocha geometrie – při stejné množině cest se geometrie přehraje a ověří intenzitami na všech hranách (GEOMETRY_EPOCH_CHECK.json, max 3 opakování); zrychlené zachycení smí kandidáta jen odmítnout nebo řídit hledání – před přijetím se vždy pořídí nezávislé plné zachycení a o přijetí se rozhoduje na něm (ACCEPTANCE_CONFIRM.json); regrese dokazuje protipříklad 1→2+3→4 vs 1→4+3→2 (stejné intenzity, jiná FIRST_LAST)
- LIVE04.8 (2026-11-04): checkpointy – po každém bloku se změnou se uloží `CHECKPOINTS/…_LIVE04_CKPT_Cxx_<blok>_<hash>.ver` + `.CHECKPOINT.json` (posledních `keep_last`); `RUN_R1_2025_CORDON_LIVE04_CONTINUE.py` naváže z checkpointu nebo z verze uložené při zastavení na dalším bloku s kotvami původního běhu (generation reference, baseline ADDVAL1; RUN_ANCHORS.json)
- LIVE04.8.1 (2026-11-04): oprava modelu bez cest – sondy prediktoru jen s poptávkou (operace 1/15 mažou výsledky přidělení) po bloku nebo při zastavení vyvolají přepočet přidělení s ověřením ekvivalence (ASSIGNMENT_REPAIR.json) a `.ver` se bez cest neuloží; navázání i z ručně uložené a přepočítané verze podle hashe přijatého stavu (ACCEPTED_STATE_MATCH); spouštěče zcela tiché (výstup do `%LOCALAPPDATA%\R1C25_BOOT\LAST_LAUNCHER_OUTPUT.txt`)
- Integrita: `python verify_release.py` (SOURCE_MANIFEST.json, release `R1_2025_CORDON_LIVE04_8_1_ASSIGNMENT_REPAIR_20261104`)
- Offline regrese: `LIVE04_TEST_RESULTS.txt` (LIVE04.8.1 po vydání: 1011 passed, 20 skipped, 0 failed; syntetický mock, nejde o nativní důkaz z PTV Visum)

Stav: `TECHNICAL_TRIAL`, `production_ready=false`, nativně ve Visumu zatím neověřeno.
