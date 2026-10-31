# R1 2025 – kordónová kalibrace LIVE04.1 (v7 @ 977cef4)

Kordónový kalibrátor TG + TD (ANPR průzkum 2026, FIRST_LAST + C17) portovaný na profilový kalibrátor
[`vilemknap/R1_15A2_V24917_v7`](https://github.com/vilemknap/R1_15A2_V24917_v7) @ `977cef4` (P2.5/A4),
s pamětí mezi cykly (LIVE04.1).

- Start: `00_START_HERE_LIVE04_CZ.txt`, spuštění ve Visumu: `RUN_R1_2025_CORDON_LIVE04_V7_TG_TD_CYCLE.py`
- Návod: `LIVE04_RUNBOOK_CZ.md`
- Report: `docs/live04/LIVE04_IMPLEMENTATION_REPORT_CZ.md`, `docs/live04/LIVE04_1_MEMORY_CZ.md`
- Integrita: `python verify_release.py` (SOURCE_MANIFEST.json, release `R1_2025_CORDON_LIVE04_1_V7_MEMORY_20261031`)
- Offline regrese: `LIVE04_TEST_RESULTS.txt` (919 passed, 20 skipped, 0 failed; syntetický mock, nejde o nativní důkaz z PTV Visum)

Stav: `TECHNICAL_TRIAL`, `production_ready=false`, nativně ve Visumu zatím neověřeno.
