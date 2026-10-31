# Testy DIAGFAST EXACT V1

- Zdrojovy PERF01 baseline: 573 passed.
- Vysledna plna suite tests/: 715 passed, 0 failed (447.51 s pytest).
- Novych 142 pripadu (strankovani, streaming, integrace, fault injection, patch guards).
- Parent plny beh: 879 passed, 4 skipped, 1 failed.
- Parent kompatibilita: 879 passed, 4 skipped, 1 deselected.

Neuspesny rodicovsky test test_v24915_config_runtime_bundle_and_lineage_are_hash_locked
zamerne odmita 4 historicky upravene soubory forku. DIAGFAST parent NEMENI.
Plny neuspesny i presne filtrovany kompatibilitni log jsou v raw/.
Zadny takovy test nebyl prepsan na PASS.

Novy rozsireny benchmark: 12 kompletnich runu, 12/12 PARITY_PASS.
Overhead: dalsich 6 runu RAW_LEGACY/TIMED_LEGACY, presna parita PASS.
Testy falesneho COM nepredstavuji native Visum. Zadny assignment ani APPLY.
Skutecny replay parity stareho NATIVE_CW vstupu je zdedeny numericky test;
NEJDE o dostupnost kompletniho finalniho 664MB R1 p.sqlite.

Puvodni pokusy pred opravou testovaciho fixture (retry enabled), preruseny
200s runtime test a benchmark guard CHECKPOINT_CODE_CHANGED jsou v raw/.
Zapocteny PASS se vztahuji pouze k dokoncene plne suite a finalnimu benchmarku.

Konecne clean-unzip, patch a bootstrap smoke jsou dolozeny oddelene
RELEASE_FINAL_VERIFICATION.json.

## Finalni opakovani po hardeningu telemetrie
715 passed in 452.83 s (samostatna nemenne zmrazena zdrojova kopie).
Sedm dodatecnych negativnich pripadu: psutil/resource nedostupnost, chyba
stat, selhani vytvareni telemetry reportu po uspechu a behem primarni chyby,
pro oba backendy. Merici kod nesmi prepsat primarni exception.
Detaily: raw/final_full_tests.status.json, raw/telemetry_safety.txt.
Nativni a uplny real SQLite replay zustavaji NOT_RUN, nikoli PASS.
