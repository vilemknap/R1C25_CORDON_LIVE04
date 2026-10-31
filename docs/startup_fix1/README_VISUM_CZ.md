# R1 2025 CORDON AGGRESSIVE - STARTUP FIX1

## Co tato dodavka je a co neni

Toto je oprava agresivniho kordonoveho offline optimalizatoru a NOVY vstup
pro nacteni aktualne otevreneho modelu primo ve Visumu. Neni to hotovy zivy
kalibracni controller. Zadne TG, TD, assignment, SaveVersion, LoadVersion,
SetAttValue ani zmeny OD matic se nespousteji. APPLY zustava zakazan.

V referencnim profilovem kalibratoru ziva smycka existuje. Jeho spoustec ale
obsahuje CSD 2022/PROFILE488, nikoli kordonovou autoritu. Zkopirovat tento
spoustec nebo jen prepnout apply=true by nebyla korektni integrace.

## Prvni spusteni v modelu 2025

1. Rozbal cely novy ZIP do SAMOSTATNE kratke lokalni slozky, napr.
   %LOCALAPPDATA%\R1C25_APP. Neprepisuj verzi 2022 ani predchozi release.
   Nespoustej nic primo v ZIPu nebo v hlavnim profilovem kalibracnim adresari.
2. Otevri zamyslenou verzi modelu a site 2025 s ulozenymi aktualnimi PrT
   cestami. Modelovy rok neni cislo verze aplikace. Zdroj s tokenem 2022
   v ceste je odmitnut. Chybejici soubor aktualni .ver/.verx se neodhaduje.
3. Pres Scripts > Execute script file spust RUN_CORDON_2025_VISUM.py.
   Script pouzije pouze Visum/COM objekt predany touto instanci. Nevyhledava
   aktivni instanci pres ROT/GetActiveObject/Dispatch. Nevkladej jej do
   prave bezici Procedure Sequence a nespoustej v instanci kalibrace 2022.
4. Po PREFLIGHT_PASS lze stejnym zpusobem spustit RUN_CORDON_2025_CAPTURE.py.
   Ten preflight zopakuje, davkove nacte ulozene cesty pomoci existujiciho
   parseru 15A2, proveri objemy a geometrii a vytvori kordonovou diagnostiku.
   Neni treba predem vyrabet 15N CSV nebo rucne zadavat externi SQLite.
5. V konzoli bude output_directory. Ve Windows je standardni koren
   %LOCALAPPDATA%\R1C25; diagnostika problemu pri importu je v
   %LOCALAPPDATA%\R1C25_BOOT (pri nedostupnosti v uzivatelskem temp).

Pouzivej nove dva spoustece v koreni. RUN_CORDON_AGGRESSIVE_OFFLINE.py
nadale opravnene odmita spusteni s objektem Visum. Souborove spoustece v
parent/ jsou historicka evidence, ne alternativni vstup do modelu 2025.

## Prostredi

Podporovana cesta je Execute script file s 64bit Pythonem >=3.10 a NumPy.
Nezavisi na sys.argv hostitele ani na jeho aktualnim pracovnim adresari.
Python hub/jiny hostitel bez predaneho objektu Visum skonci diagnostikou.
Nic neinstaluje do Pythonu, nestahuje a samovolne nezveda opravneni.
Openpyxl je potreba pouze pro samostatny audit Excelu D1-D3; samotny start
ani nacteni cest jej nepotrebuje. SciPy/pytest jsou vyvojove testovaci
zavislosti, ne podminka tohoto startu.

## Co kontroluje

- Presnych 16 SDP / 32 smerovych klicu proti skutecne nactene siti,
  vcetne obou smeru linku a SDP16=2004231. Mapovani ze starsi site neni
  automaticky potvrzene na nove siti. Chybejici objekt = STOP, nikoli odhad.
- Vsech 12 pozadovanych OA NATIVE/EXOG_EE segmentu a jejich mode identity.
- Matice podle aktualniho poradi zon, platnost hodnot, SUM a plny hash.
- Vyhradne potvrzenou omezenou signaturu SaveToArray(FirstObject,LastObject).
  Zadne neomezene SaveToArray(), Dijkstra ani nahrazovani cest FlowBundle.
- Kontrolu kazde mezizonove OD bunky proti objemu ulozenych cest.
- Uplne porovnani linkovych sekvenci segmentu uvnitr kazdeho modu pred
  oznacenim sdilene geometrie za prokazanou; C a C_noT se nikdy neslevaji.
- Opakovane cteni matic, trasovych klicu/objemu a site na konci exportu.
- Rozpocty disku/SQLite, kratke vystupni cesty, same-thread COM,
  atomicke publikovani a kooperativni zastaveni souborem STOP_REQUESTED.

Plne overeni geometrie vyzaduje vice cteni nez pouzi dva reprezentanty.
Neni to druhy produkcni exportni algoritmus: pouziva puvodni kolektor,
parser a SQLite schema 15A2. Zakladni velikost davky je 256 radku.
Pri neshode geometrii se sdileni NEVYNUCUJE; beh se zastavi s jasnym duvodem.
Pouze rychly reprezentativni scenar by zustal PROVISIONAL, nikoli potvrzeny.

Pred ctenim dense matice se kontroluje limit 10 milionu bunek. Jde o limit
poctu bunek, nikoli zaruku celkove pameti: Python/COM mohou mit vyssi reziji.

## Vystupy

PREFLIGHT.json; STATION_MAPPING_CHECK.json; 00_RESULT.json;
OD_PARITY.json; GEOMETRY_PROOF.json; SNAPSHOT_EVIDENCE.json;
p.sqlite; matrix_authority/*.npz; STATION_HITS.csv;
ALL_ORDERED_UNIQUE_PAIRS/ a EXACT_TWO_HITS/ s maticemi incidence,
modelovymi proudy, referencnimi cili a diagnostikou; RUN_CHECKPOINT.json.

Budou vykazany obe historicke interpretace relaci, nikoli potichu schvalena
jedna z nich. Nepouziva se pravidlo rekonstrukce vypadku SDP4. C17 ani
symetrizace D3 se nezmeni. Read-only start neprovede korekci OD.

Checkpoint je overitelny snapshot. Pri preruseni se nevydava za dokonceny
ani za obnoveny solver/assignment. Dalsi spusteni zalozi novy izolovany beh.
Zdrojove soubory a dokoncene vysledky jsou hashovane, ne sdilenou zivou cache.

## Zbyvajici blokace plne kalibrace

- Neni implementovana a zive overena transakce TG/TD -> assignment ->
  skutecny kordonovy objective -> ACCEPT/ROLLBACK.
- Neni dodana skutecna 2025 cesta pro nativni acceptance testy v tomto
  vyvojovem prostredi. Vsechny COM testy zde pouzily oznaceny simulator.
- Je treba uzavrit definici relaci, smerovou autoritu a rok 2026 -> 2025,
  pravidlo C17 a skutecne povolene generacni/distribucni aktualizace.
- Dokonceny export nedokazuje cerstvost assignmentu vzhledem ke vsem
  turn/connector/supply parametrum. Site hash zde pokryva poradi zon,
  smerove klice linku a TSys; neni uplnym hashem vsech impedanci.

PREFLIGHT_PASS neznamena CALIBRATED. VISUM_SAVED_PATH_DIAGNOSTICS_COMPLETE
znamena nacteni a diagnostiku ulozenych cest, nikoli novy assignment.

## Offline overeni

python verify_release.py
python -m pytest -q tests
python RUN_CORDON_AGGRESSIVE_OFFLINE.py demo

338 kordonovych testu proslo; pridano 85 pripadu. Profilovy referencni balik
prosel 961 testy se 4 skipy. U rodice forku plna sada = 879 passed,
4 skipped a 1 expected historical-identity FAILURE; originalni manifest
V24915 nebyl prepsan, a proto opravneny fork odmitne. Kompatibilitni sada
s explicitne vyrazenou touto jednou kontrolou = 879 passed / 4 skipped.
Viz TEST_REPORT.md, AUDIT_REPORT.md a FINAL_VERIFICATION pro aktualni dukazy.
