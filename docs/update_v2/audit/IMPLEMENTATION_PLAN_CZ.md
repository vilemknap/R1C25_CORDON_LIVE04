# R1 2025 CORDON V2 - audit a checkpoint plan (2026-10-22)

Zadani: prenest opravy z obou dodanych 2022 vetvi do oddeleneho offline
kordonoveho kalibratoru. Puvodni data, jednotky, C17 politika, obe hypotezy
incidence a blokace APPLY zustavaji zachovany. Zadna ziva instance Visumu.

## Overeny vychozi stav
- Cordon V1: 981 ZIP members; 86 focused tests PASS v tomto behu.
- Puvodni V24915: 731 souboru. Cordon V1 meni core.deadband a doplnuje
  offline hook two_mode; legacy SHA256SUMS.txt v podstromu parent chybi.
- Resume donor: 947 souboru; oproti parentu 245 pridanych / 29 odstranenych /
  1 zmeneny test. Puvodni root produkcni .py jsou byte-identicke.
- Fresh donor: 1011 souboru; 309 pridanych / 29 odstranenych / 1 zmeneny test.
- Fresh vs resume: 71 pridanych / 7 odstranenych / 3 zmenene soubory.
  Dva zmenene moduly jsou I/O a telemetry; treti je navod.
- Tyto jsou aditivni overlay vetve, nikoliv nove kopie matematickeho core.
  Nelze provest slepe prepsani parent/ ani aktivovat vsechny monkey-patche.

## Prenosova strategie
1. Zachovat obe Cordon V1 core zmeny a 2025 CAL/VALID, scope a C17.
2. Prevest knihovni moduly novych vetvi s provenienci. Z novych publikacnich
   knihoven volat jen ciste utility; globalni activate() pro 2022 se NESPOUSTI.
3. IOFIX3/PATHFIX3 je sirsi nez PATHFIX1 v resume donoru a ma prioritu pro I/O.
   Ve vlastnim 2025 writeru zachovat prisne allow_nan=False a CSV schema,
   neprebirat tichy default=str nebo ignorovani neznamych sloupcu.
4. GATEFIX2 prenest jako parametricke rostery a kontroly identity, nikoliv
   hodnoty 488/488/0. SEMRELOAD1 jako presne porovnani semantiky a povinne
   znovuotevreni snapshotu; offline V2 nikdy samo nevola LoadVersion.
5. Prenest presne PERF2C snapshot/readback API do 2025 kompatibilni vrstvy
   s testy fallbacku a invalidace. Ziva enumerace je stale odlozena.
6. V24916 FlowBundle/skim targeting je podpurna diagnostika, nikoliv
   nova autorita orientovaneho kordonoveho proudu. Nespoustet profilove
   2022 targety nebo A0004/488 handoff.
7. Persistentni cross-run cache reuse defaultne zakazat. Explicitni
   dokoncena read-only kopie SQLite zustava platnym offline vstupem.
   To neni rozpor: format SQLite != automaticky reuse stareho assignmentu.

## Checkpointy
CP00 audit, inventare SHA256, baseline testy, tento plan; backup vstupu.
CP01 aditivni port knihoven a meritka provenience; bez zmen autorit.
CP02 integrace I/O, short paths, atomicke JSON/CSV/NPZ a bezpecky finalizer;
     fault injection, strict numerical schema a zadne globalni patche.
CP03 semantic snapshot/cache contract, oddelene run/lock, dynamic gate,
     presna PERF2C compatibility a read-only targeting; testy invalidace.
CP04 kordony/C17/solver parity, CLI hardening, resume offline checkpoints,
     testy proti kombinovanym chybam, vsechny donor relevantni regrese.
CP05 kompletni offline regrese, synteticky perf, clean unzip, nezavisly
     verifier, finalni ZIP + SHA256 + readback Drive.

Kazdy CP ma immutable ZIP, SHA256 sidecar a overeni Drive ID/size/checksum.
Zaverecny stav neznamena LIVE_PASS nebo PRODUCTION_READY.
