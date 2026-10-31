# R1 2025 CORDON OPTIMIZER V2 - BUGFIX PORT (2026-10-22)

Stav: OFFLINE_BUGFIX_PORT_TESTED_LIVE_BLOCKED. Toto vydani aktualizuje existujici
kordonovy kalibrator V1 opravami ze dvou dodanych vetvi 15A2. Neni to zive
nakalibrovany model. Neni povoleno APPLY, COM pripojeni, trial assignment,
automaticky LoadVersion ani prime zapisy OD. Bezici kalibrace 2022 zustava mimo scope.

Zavislosti instaluj do samostatneho virtualniho prostredi, ne do Pythonu ziveho Visumu 2022.

## Co se zmenilo

- Robustni atomicke JSON/CSV/NPZ: kratke docasne nazvy, omezeny retry pri
  docasnem I/O zamku, hashovy readback, strict numericka data (NaN zakazano).
- Windows extended/UNC cesty na I/O hranici; kratky vychozi adresar ve Windows.
- Selhani telemetrie nemaskuje puvodni chybu; kriticka publikace nesmi tise selhat.
- Kontrola osmi semantickych hash polozek, site, demandu a parent stavu snapshotu.
  Chybejici evidence neni prohlasena za skutecny LIVE PASS.
- Dynamicky seznam a identita kordonovych pozorovani misto konstant PROFILE488.
- Zadny automaticky reuse/discovery stare cache. Explicitni dokoncena SQLite
  kopie zustava vstupem pro offline vypocet; to neni persistentni reuse assignmentu.
- Oddeleny vlastneny run root, exkluzivni zamek a kontrolovane checkpointy.
- CAL-only signed targeting a overene knihovni PERF2C/skim/readback API.
  Live targetovani profilu, controlery 2022 a jejich globalni activate() se nespousti.
- Nezavisly verifier hlida i necekane zbytkove Python soubory po chybnym overlay.

Matematika FISTA/deadband, C17, TG/TD realizovatelnosti a oba historicke
kordonove operatory zustaly zachovany. 52 novych donor knihoven ma presne
puvodni bajty, se zdroji v docs/update_v2/DONOR_LIBRARY_MANIFEST.json.
Puvodni parent/ soubory jsou shodne s Cordon V1; dve upravy oproti cistemu
V24915 byly vytvoreny uz ve V1 a nebyly timto portem prepsany.

## Bezpecne spusteni MIMO Visum

Rozbal do NOVE samostatne slozky. Neprepisuj 2022 ani puvodni V1.
Nespoustej historicke one-click skripty z parent/ v zivem modelu.

    python -m pip install -r requirements-tested.txt
    python verify_release.py
    python -m cordon2025 demo --run-name V2_SMOKE

Demo je oznaceno SYNTHETIC_DEMO_PASS: pouze synteticka data, nikoli intenzity R1.
Konzole vypise skutecny output. Windows default: %LOCALAPPDATA%/R1C25.
Na ostatnich platformach: OFFLINE_RESULTS v teto dodavce.
Volitelne --output-root musi byt nova prazdna nebo jiz vlastnena 2025 slozka.
Cizi existujici neprázdny adresar, existujici stejny run-name a soubezny zamek
jsou odmitnuty. Zamek se nikdy automaticky neprebira jako domnele zastaraly.

    python -m cordon2025 verify-run --run-directory C:/cesta/k/vytvorenemu/runu

verify-run overi kod, autority, vstupy a hashe artefaktu. Jde o overeni
handoffu pro novy explicitni offline vypocet ze stejnych vstupu. NENI to
resume iteraci FISTA ani navazani na zivy Visum assignment.

    python -m cordon2025 audit-inputs --run-name AUTORITY_V2
    python -m cordon2025 preflight --run-name PREFLIGHT_V2

Preflight bez skutecne cache zamerne vraci kod 2 a NO_2025_PATH_CACHE.
Nejde o numericke selhani. Naopak testovani nesmi takovou blokaci povysit na PASS.

## Skutecny explicitni snapshot 2025

    python -m cordon2025 inspect-cache --cache SNAPSHOT.sqlite --evidence SNAPSHOT.evidence.json --run-name INSPEKCE
    python -m cordon2025 propose --config CORDON_2025_CONFIG.json --cache SNAPSHOT.sqlite --evidence SNAPSHOT.evidence.json --allow-unapproved-scenario --run-name SCENAR

Pred propose je treba mit explicitni actuatable_zones, uplny DSeg scope,
objemovou paritu a konzistentni snapshot. Vse je stale offline.
--bounded-c17-scenario povoluje jen konzervativni scenarovy tolerancni ucet;
neni to schvaleni fyzickeho prirazeni C17 ke dvojicim stanovisť.
Nove expected_snapshot_semantics a expected_observation_roster jsou hashove
kontrakty, ne nahrada schvaleni observation semantics, site nebo roku.

## Overeni a historie

    python -m pytest tests -q
    python tools/parent_compatibility.py

Vlastni sada: 170 passed. Parent kompatibilita: 879 passed, 4 skipped,
1 explicitne deselected test vyzadujici byte-identicky puvodni V24915.
Puvodni guard zustal nezmeneny a porad spravne odmitne dva kordónove core
patche z V1. Nezmenena cela parent sada proto ma 1 expected identity failure;
neni to vydavano za all-pass. Kordonove testy overuji, ze guard stale odmita fork.

Puvodni reporty V1 jsou uchovany v docs/history_v1, puvodni CP v CHECKPOINTS
jsou historicke. Aktualni evidence je docs/update_v2. Vysledky z OFFLINE_RESULTS
pribalene z V1 jsou historicke synteticke ukazky; novy run dostava nove jmeno.

Zive Windows/Visum nebyly dostupne ani spousteny. Windows cesty, transientni
chyby, snapshot invalidace a rollback-readback jsou testovany simulaci.
Velky synteticky benchmark nemeri skutecny cas kalibrace R1.

Aktualizace nemeni data D1/D2/D3, C17, konfigurace/kontrolery 2022 ani jeji cache.
Dalsi live etapa vyzaduje autorizovany 2025 snapshot a drive definovane metodicke
brany; zadny dodany prepinac v teto verzi nedovoluje APPLY.
