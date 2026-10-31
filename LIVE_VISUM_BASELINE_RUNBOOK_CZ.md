R1 2025 CORDON LIVE01 - NAVOD KE SPUSTENI
=======================================

Co tato verze dela
------------------
Precte aktualne otevreny model R1 2025, overi TG/TD a assignment rozhrani
z profiloveho donora, exportuje jeho ulozene cesty a vypocte navrh TG
parametru na CELU kordonovou matici. Vsech 120 paru je CAL, zadny VALID.
Navrhy se ZATIM NEZAPISUJI do modelu. Zapis a kalibracni cyklus patri LIVE02.

Instalace
---------
Rozbal FULL ZIP do nove kratke lokalni slozky, napr. C:\R1C25_CODE\LIVE01.
Kod neumistuj do vystupniho korene %LOCALAPPDATA%\R1C25_LIVE01.
Nekopiruj jej pres starsi instalaci. Neprepisuj bezici profilovy kalibrator.
Vsechny soubory v ZIPu ponech pohromade.
Pouzij Python 3.10+ 64bit ve Visumu; vypocet vyzaduje NumPy a SciPy.
Verze offline testovaciho prostredi jsou v requirements-tested.txt.
Skript sam neinstaluje balicky a nemeni prostredi Visumu. Modelove procedury (napr. 20B)
musi mit dostupne soubory podle existujicich odkazu v modelu.

Spusteni ve Visumu
------------------
1. Otevri samostatnou kopii funkcniho modelu R1 2025 s vypoctenym assignmentem
   a ulozenymi cestami. Behem behu neprovadej zadne zmeny modelu/procedur.
2. Scripts -> Execute script file:
      RUN_R1_2025_CORDON_LIVE_BASELINE.py
3. Nespoustej zaroven jiny kalibrator ve stejne instanci/interpretu.
   Skript nic nevyhledava pres Dispatch/ROT a neotevira jiny .ver.

Pro tento native vstup se nekopiruji stare logy ani p.sqlite do instalace.
LIVE01 zatim porizuje cerstvy plny LEGACY capture; muze tedy znovu nacitat
velke mnozstvi cest. PERF01/DIAGFAST jsou zachovany jako samostatne funkce,
ale nenahrazuji dukaz aktualnich cest po novem assignmentu.

Vystupy ve Windows
------------------
%LOCALAPPDATA%\R1C25_LIVE01\LIVE01_BASELINE_<id>\
Uvodni bootstrap chyby:
%LOCALAPPDATA%\R1C25_BOOT\<id>\00_LIVE01_BOOT_RESULT.json

Dulezite soubory behu:
00_RESULT.json, 00_PROGRESS.json, MODEL_READBACK.json, ZONE_ACTUATORS.json,
OD_SEGMENT_BINDINGS.json, WHOLE_MATRIX_AUTHORITY_AUDIT.json,
WHOLE_MATRIX_DIAGNOSTICS.csv, WHOLE_MATRIX_ROLE_AND_OBJECTIVE_PROOF.json,
SOURCE_FINGERPRINT.json, FINAL_STATE_READBACK.json, PROPOSED_TG_CANDIDATES.json,
BASELINE_AND_PROPOSAL_CONTRACT.json a RUN_CHECKPOINT.json.
Obe metody maji samostatne podslozky s SOLVER_REPORT, OD_GUIDANCE,
WHOLE_MATRIX_TRANSFORM_TRACE a PROPOSED_TG_CANDIDATES.

Vyklad vysledku
---------------
NATIVE_READONLY_BASELINE_PASS znamena uspesne cteni a navrh, NIKOLIV
provedenou kalibraci. apply_permitted=false, assignment_executed=false,
native_candidate_accepted=false. Zadny production PASS.
MOCK_READONLY_BASELINE_PASS je pouze synteticky test.
TG_TD_REALIZATION_NOT_VERIFIED neni chyba cteni; bez noveho nativniho
prepocitu nelze potvrdit skutecny efekt matematickeho navrhu.

Finalni RPDI CSV se nemeni. Zachovana je puvodni BIDIRECTIONAL_SUM
reprezentace obou smeru na strane modelu i targetu. Vsechny zdrojove
bunky a efektivni hodnoty lze zkontrolovat v transform trace.

Zastaveni a chyba
-----------------
Pro kontrolovane zastaveni vytvor soubor STOP_REQUESTED v pracovni slozce
konkretniho behu. Prave probihajici nativni COM volani nelze nasilne prerusit.
Po chybe posli 00_RESULT, 00_PROGRESS, 99_TRACEBACK nebo TRACEBACK,
COM_READ_RETRY a bootstrap log. Neopravuj stav rucnim prepisem completed.
Po padu zacni novy beh; nejde o pokracovani od poloviny enumerace.
Nikdy automaticky nemaž zamek jineho beziciho procesu. Opušteny zamek
res pouze po overeni, ze zadny proces uz nepokracuje, nebo pouzij novy
explicitne oddeleny vystupni koren.

Samostatne offline overeni dodavky
---------------------------------
V Pythonu 3.10+ 64bit s potrebnymi balicky, mimo Visum:
    python verify_release.py
    python -m pytest tests -q
Fake test neni native akceptace. Testy a simulace nic nepripojuji.

Co zatim NENI implementovano
---------------------------
Zapis TG/TD kandidata, recompute, novy assignment, prijeti/odmitnuti,
parametricky rollback, automaticka zivá iterace. To je navazujici LIVE02.
