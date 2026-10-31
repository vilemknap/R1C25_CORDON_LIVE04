R1 2025 CORDON COM DIAGFAST EXACT V1
==================================
Samostatna cteci optimalizace nad PERF01. Neni to ziva TG/TD kalibrace.

STANDARDNI, PUVDODNI CHOVANI
RUN_CORDON_2025_CAPTURE.py zustal byte-identical a pouziva LEGACY.
Nic nemusis prepinat v bezici 2022 kalibraci ani ve starem baliku.

NOVA FAST VETEV (nejprve jen na samostatne kopii modelu 2025)
Scripts -> Execute script file -> RUN_CORDON_2025_CAPTURE_DIAGFAST.py
Vychozi stranka 256; zrychleni tvori streaming proof bez 10 docasnych SQLite.
Vetsi stranky jsou explicitne podporovane API `diagfast_runtime.run` pres
fast_options (512/1024), ale nejsou automaticky vybrane pred native testem.

PRESNE POROVNANI
RUN_CORDON_2025_PARITY_AUDIT.py = jeden uplny par LEGACY + FAST256.
LIVE_VISUM_ACCEPTANCE.py = 3 pary pro kazdou z 256/512/1024, celkem 18 capture.
RUN_CORDON_2025_CAPTURE_LEGACY_TIMED.py = instrumentovana puvodni cesta.

VYSTUPY
%LOCALAPPDATA%\R1C25\VISUM_CAPTURE_DIAGNOSTICS_<id>\
Paritni audit: %LOCALAPPDATA%\R1C25\DIAGFAST_PARITY_<id>\
Boot chyby: %LOCALAPPDATA%\R1C25_BOOT\<id>\
Rozlis konecny 00_RESULT.json od prubezneho 00_PROGRESS.json.
Novy DIAGFAST_TIMING.json a DIAGFAST_AUDIT_SEAL.json jsou merici sidecary.
GEOMETRY_PROOF ma ve FAST verzovane V2 metadata a kompatibilni checks/full.
Originalni model, matice, .ver a referencni cache se neprepisuji.

PERF01
Nad dokoncenou novou cache nadale funguje build-offline / require-verified-hit.
Po novem assignmentu je potreba nove overeni epoch, ne stary HIT podle jmena.
Tato verze neodebira ani oslabuje schvalovaci gates C17, roku nebo metodiky.

PATCH-ONLY
Rozbal PATCH do oddelene slozky. Priklad mimo Visum:
python APPLY_DIAGFAST_PATCH.py --base-zip "R1_2025_CORDON_PERF01_V1_20261023.zip" --output "C:\R1C25_DIAGFAST"
Zdrojovy ZIP musi mit SHA ze zadani; output nesmi existovat. Alternativne
--base-tree s presne odpovidajici cistou PERF01 slozkou. Puvodni vetev zustane
nedotcena. Zpet se vratis spustenim puvodniho launcheru v puvodni slozce.

TESTOVANI MIMO VISUM
python verify_release.py
python -m pytest tests -q
python tools\diagfast_benchmark.py --output "C:\R1C25_DIAGFAST_BENCH" --routes 3000 --zones 681 --repetitions 3
Benchmark je SYNTHETICKY COM provider, nikoli rychlost skutecneho Visumu.
Podrobnosti: docs\diagfast\LIVE_VISUM_ACCEPTANCE_CZ.md
