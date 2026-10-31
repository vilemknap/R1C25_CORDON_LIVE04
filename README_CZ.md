# Aktualni vydani: STARTUP FIX3 PRACTICAL (2026-10-23)

Pouzij **START_HERE_VISUM_2025_CZ.txt**. Aktualni zmeny, limity a testy jsou v **docs/fix3/**. Nize ponechana historie popisuje drivejsi verze a neni autoritou aktualnich vychozich limitu. Vsechny puvodni numericke testy zustaly v regresi. FIX3 je read-only startup/capture + offline optimizer, ne plna ziva kalibrace.

---

# Aktualni vydani: STARTUP FIX2 COMBUSY (2026-10-23)

Nejprve cti **START_HERE_VISUM_2025_CZ.txt**. Tento release obnovuje nejpozdejsi
checkpoint B03/STARTUP_FIX1 a pridava opravene retry cteni podle dodaneho 24915
hotfixu. Aktualni audit a testy jsou **STARTUP_FIX2_AUDIT_CZ.md** a
**STARTUP_FIX2_TEST_REPORT.md**; strojovy stav je **FINAL_STATUS.json**.

K dispozici jsou dva read-only vstupy ve Visumu, nikoli automaticky zivy
kalibrator. APPLY/TG/TD/assignment/SaveVersion/LoadVersion se nespousteji.
Pri instalaci rozbal do nove slozky, nemichej soubory predchozich vydani.

---

## Historicka dokumentace podkladoveho offline optimalizatoru

# Dulezite: aktualni vydani STARTUP FIX1 (2026-10-23)

Prvni cteni: **START_HERE_VISUM_2025_CZ.txt** a **docs/startup_fix1/**.
Novy Visum vstup je READ-ONLY PREFLIGHT/CAPTURE, nikoli zivy APPLY.
Nize ponechana dokumentace popisuje historickou offline vyvojovou vetev.

---

# R1 2025 CORDON AGGRESSIVE V1

Samostatna agresivni OFFLINE varianta kordonoveho kalibratoru nad V2 BUGFIX PORT.
Stav: OFFLINE_IMPLEMENTED_TESTED_LIVE_BLOCKED. Nepripojuje Visum, nemeni jeho
matice, nespousti assignment ani APPLY. Bezi mimo Visum v novem Python procesu.

## Spusteni

Rozbalte cely ZIP do NOVE slozky. Neprepisujte bezici model 2022, profilovy
kalibrator ani puvodni kordon V2. Doporucena je kratka cesta mimo OneDrive.
Pouzijte Python a zavislosti z requirements-tested.txt v oddelenem prostredi.

    python -m pip install -r requirements-tested.txt
    python verify_release.py
    python RUN_CORDON_AGGRESSIVE_OFFLINE.py demo

Windows RUN_CORDON_AGGRESSIVE_DEMO.cmd spousti jen oznacenou syntetickou ukazku.
Nejde o tlacitko pro skutecnou kalibraci modelu. Spoustec odmitne globalni Visum,
COM nebo priznak beziciho 15A2. Nemuze pokracovat v bezicim 2022 procesu.
Vystupy: kratky izolovany root %LOCALAPPDATA%/R1C25 ve Windows, nebo slozka
OFFLINE_RESULTS v tomto baliku mimo Windows. --run-name musi byt novy.

Pro ukazku jine faze:

    python RUN_CORDON_AGGRESSIVE_OFFLINE.py demo --outer-cycle 7
    python RUN_CORDON_AGGRESSIVE_OFFLINE.py demo --outer-cycle 19

## Fazovane nastaveni ze zdrojove profilove varianty FIX1

| Explicitni selector | Faze | Relativni OD navrh | ADD log krok | Family global log | Salary absolutni krok |
|---|---|---:|---:|---:|---:|
| 1-6 | SIGNED_EXPLORE | +/-20 % | +/-0.12 | +/-0.10 | +/-0.10 |
| 7-18 | SIGNED_REFINE | +/-14 % | +/-0.08 | +/-0.06 | +/-0.08 |
| 19-100 | DISTRIBUTION_FOCUS | +/-8 % | +/-0.05 | +/-0.03 | +/-0.05 |

Jde o maximalni kroky; puvodni tvrde meze, soft-envelope a bilance je mohou
zmensit. Logaritmicky krok 0.12 neznamena presne 12 procent. Salary se meni
aditivne. Standardni konfigurace CORDON_2025_CONFIG.json zustava beze zmeny.

--outer-cycle je v teto offline dodavce VYBER POLITIKY PRO JEDEN NAVRH. Neni to
spusteni 100 cyklu Visumu ani automaticky adaptivni controller. Faze 19-100
ma mensi OD kroky nez standard V2, protoze ma slouzit pozdejsimu zpresnovani.
Skutecna distribuce TG/TD v modelu se v tomto baliku nespousti.

## Co funguje

- Puvodni FISTA solver dostava fazove meze OD, ne jen informativni metadata.
- 6 TG meritek: 1, .75, .5, .25, .125, .0625. Hodnoti se stejna CAL uloha.
  Kandidat vyzaduje kladny pokles cile alespon 1e-5 relativne a nezhorsenou
  kordonovou datovou ztratu. Holdout se nepouziva pro vyber ani optimalizaci.
- Rozpocet C17 se resi pro vychozi x=0 i pro kazde alternativni meritko.
  Pouhe vycerpani C17 pri nezmenene poptavce se neoznaci za zlepseni modelu.
- Pokud je dodana explicitni lokalni baze TG/TD aktuatoru, kontroluji se jeji
  identity, tvrde meze a plny OD residual. Prilis velky krok se zmensuje.
  Bez takove baze je vystup shadow navrh a realizace je NOT_VERIFIED.
- S explicitnim exportem zonalnich parametru funguje puvodni signed design
  TG koeficientu, soft/hard meze a produkcne-atrakcni rebalancovani.
  Navrzene TG koeficienty samy o sobe NEPROKAZUJI realizaci cele OD korekce.
- API pro TD ma 7 meritek: 1,.5,.25,.125,.0625,.03125,.015625. Vyhodnocuje
  explicitne dodany lokalni Jacobian a pripadne dodane chyby komponent.
  Agregovany pokles musi byt alespon .0005; zhorseni komponent nejvyse .10.
  Nativni TD/IPF se nespousti a jeho tolerance se nijak neuvolnuji.

## Co se nezmenilo

C17 zustava UNAPPROVED ve vychozim nastaveni. Agresivita nezvetsuje jeji
stanovistni ani globalni budget, statistickou toleranci, epsilon, ridge nebo L1.
NATIVE_CL/CF a EXOG_EE jsou zahrnuty v predikci, ale nejsou nove odemceny pro zmeny.
Puvodni OA scope, CAL/VALID rozdeleni, dvojice protismeru, skutecne path geometry,
IOFIX4/PATHFIX/SEMRELOAD guardy a izolace vystupu zustavaji. Zadna GEH20/30
vyjimka ani 488-profilova autorita se do kordonoveho objective neprenasi.
Zadna nova semantika multi-SDP cest nebyla schvalena.

## Skutecny snapshot - pouze offline scenar

Nejprve je potreba dokoncena, oddelene zkopirovana SQLite skutecnych cest
2025, proveniencni evidence a aktualni mapovani site. Neni dovoleno cist
aktivni WAL databazi, hledat automaticky cache 2022 nebo vymyslet cesty.
Upravte KOPII surove agresivni konfigurace mimo release; seznam
actuatable_zones vyplnte podle skutecnych opravnene menitelnych zon.

    python -m cordon2025 inspect-cache --config C:/R1C25/config.json --cache C:/R1C25/snapshot.sqlite --evidence C:/R1C25/snapshot.json
    python -m cordon2025 propose --config C:/R1C25/config.json --cache C:/R1C25/snapshot.sqlite --evidence C:/R1C25/snapshot.json --allow-unapproved-scenario --outer-cycle 1

Volitelne --zone-parameters C:/R1C25/zone_parameters.csv poskytne vstup pro
OFFLINE navrh TG parametru. Sloupce a API popisuje API_GUIDE.md.
--bounded-c17-scenario je SAMOSTATNY, vychozim stavem vypnuty experiment.
Nezpristupnuje produkcni APPLY a nic nepricita do zdrojove D3.
CLI zatim nema importer TG/TD Jacobianu; jeho predani je dostupne pres Python API.

## Kontrola a vysledky

RELATION_BEFORE_AFTER.csv a OD_GUIDANCE.csv jsou LINEARIZED vysledky, nikoliv
novy assignment. AGGRESSIVE_TRIALS.csv uvadi vsech 6 meritek; AGGRESSIVE_REPORT.json
vybranou fazi, meritko, C17 ledger, chyby a pravdivy stav realizace.
TG_TD_PROJECTION.json obsahuje projekci P/A a volitelny design parametru.
FULL_OD_FEASIBILITY.json bez baze vraci TG_TD_REALIZATION_NOT_VERIFIED.
AGGRESSIVE_EFFECTIVE_CONFIG.json obsahuje skutecne pouzitou fazovou konfiguraci.

    python -m cordon2025 verify-run --run-directory C:/R1C25/konkretni_beh

verify-run overuje checkpoint a jeho hashe. Neobnovuje FISTA iterace ani Visum.

## Dukazy a historie

TEST_REPORT.md, PERFORMANCE_REPORT.md, AUDIT_REPORT_CZ.md a docs/aggressive/
patri k teto dodavce. SYNTHETIC_EVIDENCE obsahuje jen testovaci data.
Historicke CHECKPOINTS a dokumentace V1/V2 jsou zachovany jako provenance,
nikoliv jako nove zive dukazy. Aktualni checkpointy jsou CHECKPOINTS_AGGRESSIVE.
Ciste rozbaleni a finalni hash doklada samostatny final verification JSON.

Produkce zustava blokovana do overeni skutecneho snapshotu, semantiky relaci,
geometrie segmentu, smeru, reference 2026->2025 a zive TG/TD/assignment integrace.
