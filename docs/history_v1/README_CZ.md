# R1 2025 - kordonovy optimalizator V1 (OFFLINE)

**Stav:** implementovano a offline otestovano. Neni to hotova ziva kalibrace
modelu 2025. V teto verzi neni prikaz APPLY, pripojeni COM ani trial assignment.

Vyvoj vychazi ze skutecneho 15A2 V2.4.9.15. Ve slozce `parent/` je uplny
731souborovy rodicovsky strom se DVEMA zamerne upravenymi moduly v oddelenem
forku. Ostatnich 729 puvodnich souboru zustalo byte-for-byte zachovano.
Bezici kalibrace 2022, jeji konfigurace, cache ani instance Visumu nebyly pouzity.

## Co je skutecne implementovano

- Import a opakovatelny audit D1/D2/D3 vcetne puvodnich bunek a SHA256 zdroju.
- Streaming geometrie a samostatnych objemu demand segmentu z dokoncene
  SQLite cache ve formatu 15A2. Jedna geometrie se dekoduje jednou pro obe
  historicke hypotezy kordonu, nikoli znovu pro kazdou dvojici SDP.
- Orientovana incidence, kontrola opakovanych stanic, nulovych sekvenci,
  objemove parity, presnych smerovych hran a rozdeleni fixed/mutable.
- R1 SparseOperator a puvodni FISTA resic pro relativni OD guidance, rozsireny
  o volitelnou intervalovou ztratu. Vychozi matematika 2022 se nemeni.
- Oddeleny C17 ucet a explicitne povolovana konzervativni SCENAROVA relaxace.
  Skutecne prirazovani neznamych vozidel k fyzickym relacim je zakazano.
- Volani puvodni projekce `project_guidance_to_add` a dostupnost hashove
  uzamceneho FineCDF reference modulu. Projekce souctu neni vydavana za
  realizaci cele OD matice. Uplny response model TG/TD se kontroluje zvlast.
- CLI, synteticka end-to-end ukazka, dva protichudne nerealizovatelne pripady,
  86 novych testu, benchmark 20 000 a 100 000 geometrii a checkpointy.

## Spusteni mimo Visum

Rozbal balik do NOVE slozky pro 2025. Nespoustej nic z `parent/` v otevrenem
modelu 2022. Nove prikazy se spousteji z korene tohoto baliku obycejnym Pythonem:

```text
python -m pip install -r requirements-tested.txt
python verify_release.py
python -m cordon2025 demo --run-name MOJE_OFFLINE_UKAZKA
python -m pytest tests -q
```

`requirements-tested.txt` zachycuje verze pouzite pri tomto overeni v Linuxu
(Python 3.13.5); neni to tvrzeni o overeni jejich instalace ve Windows/Visumu.
NumPy a SciPy se pouzivaji pouze lokalne. Openpyxl cte originalni sešity bez
jejich prepisu nebo prepocitavani formulí.

Kazdy run vytvori NOVY adresar `OFFLINE_RESULTS/<run-name>/`. Opakovani stejného
jmena skonci chybou, aby neprepsalo dukazy. V zadnem prikazu se nehleda aktivni
Visum ani existujici 2022 run root. Cesty k cache jsou vzdy zadavany explicitne.

```text
python -m cordon2025 audit-inputs --run-name MOJE_KONTROLA_AUTORIT
python -m cordon2025 preflight --run-name MOJE_PREFLIGHT_2025
```

Preflight bez cache vrati stav `NO_2025_PATH_CACHE` a kod 2; to je ocekavana
blokace, nikoli numericky problem. Pouze `demo` vytvari synteticke cesty a
synteticke cile. Skutecne workbookove cile se za synteticke intenzity nevydavaji.

## Budouci skutecna cache: pouze explicitni offline scenar

Pred pouzitim cti `2025_NETWORK_AND_PATH_CACHE_PREFLIGHT.md`. Musi jit o kopii
stabilni, dokoncene SQLite, bez WAL/SHM/journal souboru. Priloz evidence JSON.

```text
python -m cordon2025 inspect-cache --cache C:\R1_2025_OFFLINE\SNAPSHOT.sqlite --evidence C:\R1_2025_OFFLINE\SNAPSHOT.evidence.json --run-name CACHE_INSPEKCE
```

Inspekce ma vsechny segmenty pevne, a tak nevyzaduje seznam zonalnich
aktuatoru. Pro skutecny offline navrh musi byt v oddelene konfiguraci 2025
vyplnen presny seznam `actuatable_zones`, nikoli prevzaty seznam z roku 2022.
Konfigurace zustava `apply=false`, `mode=OFFLINE_PROPOSAL`.

```text
python -m cordon2025 propose --config CORDON_2025_CONFIG.json --cache C:\R1_2025_OFFLINE\SNAPSHOT.sqlite --evidence C:\R1_2025_OFFLINE\SNAPSHOT.evidence.json --allow-unapproved-scenario --run-name KORDON_SCENAR
```

Doplnkove `--bounded-c17-scenario` zapina pouze tolerancni ucet popsany v
`C17_ACCOUNTING_SPEC.md`. Neni to schvaleni fyzicke redistribuce C17.
Bez explicitniho scenaroveho prepinace neschvalena semantika solver blokuje.
Ani se vsemi prepinaci nebo approval flags tato V1 nikdy nepovoli APPLY.

## Jak cist vysledky

`before_saved_path_prediction` je predikce konkretni hypotezy z ulozeneho
assignmentu (ve demo runu ze syntetickeho fixture). `after_LINEARIZED` je
POUZE aproximace po shadow OD korekci pri fixnich podilech cest. Neni to
vysledek noveho assignmentu. `SYNTHETIC_FEASIBLE_TG_TD` doklada jen presny
synteticky model uvedenych aktuatoru; neni to dukaz moznosti realizace ve Visumu.

`OFFLINE_SOLVER_PASS` znamena numerickou konvergenci kontrolovanou gradientovym
mapovanim obou bloku, nikoli automaticky dostatecnou shodu se vsemi cily.
Nedosazene cile a nepohyblive casti jsou v radkovych flazich. VALIDATION se
nikdy nepouziva k optimalizaci ani k cerpani C17. Holdout je interni vyvojovy;
neni nezavislou terenni validaci a spolecne zpracovane D3 hodnoty koreluji.

## Zachovane blokace

Chybi skutecna 2025 path cache a overeni site, uplne geometricke identity
segmentu, smerove interpretace, pozorovane definice relace, prevodu roku 2026
na referenci 2025, fyzicke alokace C17 a ziveho TG/TD response modelu.
Obe historicke definice relaci jsou zatim DIAGNOSTIC_ONLY; netvrdime, ze jedna
cesta musi patrit prave jedne dvojici. Metodika rekonstrukce vypadku SDP4
neni algoritmem enumerace v tomto baliku.

## Dulezite k regresnim testum puvodniho vydani

Pristine V24915: 783 passed, 4 skipped. Cela puvodni sada nad forkem byla
rovnez spustena: 782 passed, 4 skipped a JEDEN FAIL testu byte-identickeho
V24915 deploymentu. Ocekavane odmitl presne dve zdrojove zmeny. Jeho manifest
ani produkcni pojistka nebyly prepsany. Tento dukaz je ulozen beze zmeny.

`python tools/parent_compatibility.py` spousti beze zmen vsechny zbyle testy:
782 passed, 4 skipped, 1 explicitne deselected. Novy test navic vyzaduje,
aby puvodni deployment guard fork i nadale odmitl. Integritu NOVEHO 2025
vydani overuje `verify_release.py` a jeho vlastni manifest. Nezamenuj to za
cisty produkcni V24915 balik a nespoustej puvodni entrypointy z `parent/`.

Podrobnosti: TEST_REPORT.md, PERFORMANCE_REPORT.md, OBSERVATION_SEMANTICS_DECISION.md,
C17_ACCOUNTING_SPEC.md, IMPLEMENTATION_EVIDENCE.json a LIVE_VISUM_NEXT_GATE_CZ.md.
