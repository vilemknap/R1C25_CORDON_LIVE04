# R1 2025 – kordónová kalibrace LIVE04.3 (v7 @ 977cef4)

Kordónový kalibrátor TG + TD (ANPR průzkum 2026, FIRST_LAST + C17) portovaný na profilový kalibrátor
[`vilemknap/R1_15A2_V24917_v7`](https://github.com/vilemknap/R1_15A2_V24917_v7) @ `977cef4` (P2.5/A4),
s pamětí mezi cykly (LIVE04.1) a přenosem kalibrace 2022 → 2025 (TRANSFER2025, LIVE04.2).

- Start: `00_START_HERE_LIVE04_CZ.txt`, spuštění ve Visumu: `RUN_R1_2025_CORDON_LIVE04_V7_TG_TD_CYCLE.py`
- Příprava verze 2025: `RUN_R1_2022_EXPORT_CALIBRATED_PARAMETERS.py` → `RUN_R1_2025_IMPORT_AND_RECOMPUTE.py` → `RUN_R1_2025_LIVE04_READINESS.py`, návod `docs/transfer2025/TRANSFER2025_CZ.md`
- Návod: `LIVE04_RUNBOOK_CZ.md`
- Report: `docs/live04/LIVE04_IMPLEMENTATION_REPORT_CZ.md`, `docs/live04/LIVE04_1_MEMORY_CZ.md`
- LIVE04.3 (2026-11-01): domácí obálky W/S ADD_PROD 0,5–3,0 a ADD_ATT 0,5–5,0 (TG obálky, MOBILITY2/MOBILITYZONE1, plot atrakce); report kap. 7
- Integrita: `python verify_release.py` (SOURCE_MANIFEST.json, release `R1_2025_CORDON_LIVE04_3_ENVELOPE_P3_A5_20261101`)
- Offline regrese: `LIVE04_TEST_RESULTS.txt` (934 passed, 20 skipped, 0 failed; syntetický mock, nejde o nativní důkaz z PTV Visum)

Stav: `TECHNICAL_TRIAL`, `production_ready=false`, nativně ve Visumu zatím neověřeno.
