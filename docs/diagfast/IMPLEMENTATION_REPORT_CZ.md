# R1 2025 CORDON COM DIAGFAST EXACT V1

## Rozsah a vychozi zdroje
Samostatna read-only vetev nad presne pinovanym PERF01 V1. Nezavisly FIX3
oracle i vsechny puvodni rodicovske soubory, solver, konfigurace a datove
autority zustaly beze zmeny. Nejde o spusteni zive kalibrace.

## Implementace
- `diagfast_pages.py`: explicitni 256/512/1024 pro parent a geometry proud.
  Pouziva puvodni `bounded_rows`, TypeInfo, cursor, same-range COM retry a
  capacity-only downshift. Autotune je zakazany. Vychozi FAST je 256.
- `diagfast_geometry.py`: uplny key-based streaming proof proti existujici
  SQL referenci. Kontroluje presny uint32 blob, SHA, pocet linku, druh
  geometrie, topologii, indexaci, coverage, znovuotevrene a chybejici trasy.
  Ulozeni porovnane geometrie do dalsi proof SQLite jiz neni potreba.
- `diagfast_capture.py`: uzky deklarovany fork jedine funkce capture.
  Dva reprezentanti zustavaji na originalnim parseru. Vsech 12 parent scan,
  12 final path readback a 36 maticovych GetValues jsou zachovane. Opakovany
  import parentu z HLAVNI sqlite do docasne proof sqlite byl odstranen,
  protoze to nebylo nezavisle nove COM cteni; nezavisla parita zustava.
- `diagfast_runtime.py`: reverzibilni scoped overlay; originalni moduly se
  po uspechu i chybe obnovi. Zadny profilovy launcher se neaktivuje.
- `diagfast_telemetry.py` / `diagfast_sql.py`: RAM agregace po fazich, pocet
  provider Invoke, GetValues, volani SQL, casove spany, per-DSeg pocitadla,
  kumulovane velikosti legacy scratch souboru, explicitni hashovaci I/O.
  SQL execute timing pokryva volani/initial step; navazujici iterace kurzoru
  patri do parseroveho casu. Jde o popsanou hranici mereni, ne dokonaly
  vnitrni profiler SQLite. Native wire bytes nelze od provideru precist a
  jsou NOT_MEASURED. Procesove I/O je k dispozici jen s psutil.
- `diagfast_parity.py`: streamovane porovnani vsech osmi SQL tabulek,
  presne float/dtype/shape hodnoty NPZ, STATION_HITS, metadata, roster a
  targeting. Velke JSON soubory porovnava po radcich, ne dvojim json.load.
- `diagfast_harness.py`: izolovane parove behy, stridani poradi, hash
  kopie .ver pred/po, oddelene vysledky, fail-closed strojovy diff.

## Co se nemenilo
RPDI/OA, 2025/2026, 120 relaci a CAL/VALID 108/12, obe definice dvojic SDP,
C17, frozen EXOG, TG/TD, FISTA, agresivita, IPF, assignment, APPLY i dopravni
sit. Kontrola plne site se neomezuje na 32 stanovist. Nepouziva se sample-only
geometry proof. Zero-volume i zero-link cesty zustavaji soucasti identity.
PERF01 zustava pro jediny stejny sealed snapshot, nikoli jako autorita po
novem assignmentu.

## Zamerne nevydavano za implementaci
Volitelne selektivni QA 32 linku je OFF / NOT_IMPLEMENTED. Kompaktni vystup
primo v native capture nebyl aktivovan: pro PARITY_AUDIT se zachovava puvodni
STATION_HITS a metadata; kompaktní opakovany offline vystup poskytuje PERF01.
Automaticky prechod CELEHO backendu pri chybe je vypnuty. Pri technicke
nekompatibilite lze explicitne spustit LEGACY do nove slozky; chyba dat se
nikdy nevydava za uspesny fallback. Neni povoleno automaticke prevzeti
castene cache. Capacity downshift jedne COM stranky zustava automaticky.

## Hranice dokazu
Linux a synteticky injektovany COM provider nejsou PTV Visum. Nativni
paired acceptance a full replay finalni 664272896-byte R1 sqlite zustavaji
NOT_RUN. Stary mistni 30MB soubor neni teto referenci rovny. Stav vydani
muze byt READY_FOR_LIVE_PARITY, nikoli PRODUCTION_VERIFIED.

## Telemetrie a checkpointy
DIAGFAST_TIMING.json se vytvari az po ukonceni puvodniho checkpointu.
DIAGFAST_AUDIT_SEAL.json spojuje hash tohoto reportu s puvodnim checkpointem.
Puvodni checkpoint se kvuli casovani neprepisuje. Pri chybe zustava stejny
primarni exception; telemetry failure ho nesmi nahradit.

## Zaverecny hardening a realna reference
Optionalni psutil/resource a velikost souboru nesmeji shodit nebo preznacit
run. Zaver publikace telemetry je ochrannym try/finally kontextem se
zachovanim primarni vyjimky. Comparator uzavira read-only sqlite i kdyz
selze pocatecni kontrola integrity.
Dokoncena realna reference nyni byla nalezena na Google Drive. Vsech 12
OD matrix_authority bylo stazeno a SHA overeno. p.sqlite (664272896 bytes)
konektor odmitl HTTP 413 kvuli limitu 268435456 bytes. Proto neni zde
provedeno uplne prehrani R1; REAL_REFERENCE_ACCESS.json doklada presny stav.
Pro native overeni je pripraveny PARITY_AUDIT a LIVE_VISUM_ACCEPTANCE.py.
