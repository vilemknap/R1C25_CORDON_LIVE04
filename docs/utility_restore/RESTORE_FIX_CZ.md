# Oprava návratu po nativní sondě TG/TD

Aktualizace 16. 11.: navazující [oprava COM kontextu a předávání vstupů](COM_CONTEXT_FIX_20261116_CZ.md)
vychází z `fc38895` a zachovává dodatečné opravy vloženého skriptu.

Základ: `live05-8-integrated`, commit `8f0f4d509bbe9315edac2dd926d1018bd3098094`.
Nová větev: `codex/cordon-utility-restore-fix-20261115`.

## Prokázané nálezy

Dodané logy končí `LIVE03_DEMAND_RESTORE_SNAPSHOT_DIFFERS`, bez přijatého kroku.
Samotný běh označil stav modelu jako neověřený. V důkazu je současně
`snapshot_equal=false` a `matrix_hash_equal=false`. Není tedy bezpečné pokračovat
z tohoto otevřeného stavu ani ho vydávat za přijatý model.

Dodaný skript operace 15 (`provenance/utility_restore/OPERATION_15_SOURCE.json`, bezeztrátově gzip+base64; čitelná kopie je `OPERATION_15_READABLE.txt`,
SHA-256 `c86fc648a5995e6b2e2dfad712cdf1ed57f5f262573f3c4a2330483466775ce1`)
používá **předchozí** hodnotu každé utility:

```
U_new = 0.5 * U_old + 0.5 * (M9002 * clip(TTC / TT0, 1, 4))
```

Opakované spuštění tedy není idempotentní ani při stejných skimech a stejných
koeficientech. Navíc WORK/SERVICE průměrují poměry pomocí vah 9301–9304, které
předchozí sonda změní. Pouhé vrácení ADD/ZAHR/b/c proto neobnovuje všechny vstupy.
Chyba je reprodukovaná testem, který skutečně spouští dodaný skript na malé
syntetické COM náhradě. Nejde o odvozenou napodobeninu jeho algoritmu.

Poptávkový prefix zároveň spouštěl reset přidělení typu 9 (v logu pozice 30),
ačkoliv frozen-path prediktor má uložené cesty zachovat. Neodvozujeme z toho,
že tento reset nutně vymaže uložené DATA skimy TTC/TT0; to přílohy nedokazují.
Samostatná chyba byla i v obraně LONG masky: kontrolovala assignment 100,
ale ne stochastic/SUE 101.

Inventář navíc deklaruje, že krok rozdělení vozidel podle dálniční známky čte
časy minulého assignmentu. Přijatá časová epocha je proto součástí pomocného
transakčního stavu, ne volně přepočítávaný vedlejší vstup.

## Výsledné chování

Nový `live04_utility_state.py` zachytí **jeden** přijatý rodičovský stav:

- 16 DATA utility matic 9700–9715 s přesnými kódy a TD referencemi;
- deset DATA skimů TTC/TT0 pro NATIVE_CW, NATIVE_CW_NOT, NATIVE_CS,
  NATIVE_CS_NOT a NATIVE_CL;
- pořadí zón, čísla/bindingy matic a jejich hashe, včetně hashe celého stavu.

Navíc se čtecím způsobem zachytí čtyři váhové OD matice 9301–9304. Jejich hashe musejí souhlasit s přijatým nativním snapshotem. Kopie polí zůstávají neměnné v paměti; nevytváří se historie všech sond.
Samotná přijatá pomocná pole mají pro 681 zón přibližně 96 MB, čtyři čtecí váhová pole dalších 15 MB, navíc jsou dočasná čtení.
Nové hashe jsou součástí snapshotu i `state_hash`, takže změna utility nebo
zdrojového skimu už nemůže projít jako shodný stav.

1. **Sonda / skutečný kandidát:** začíná ze stejné přijaté utility a stejné
   přijaté časové epochy. Aktualizační skript se spustí, pokud jej vybraný
   nativní plán obsahuje. Jeho tlumení a poměrový výpočet se nemění. Nový skript
   si uvnitř kalibrátoru převezme také referenční váhy přijatého rodiče.
   Výsledek vnitřních TD sond tak nezávisí na pořadí předchozích sond;
   k dosažení toho se nezapisují žádné váhové OD matice.
2. **Vrácení koeficientů rodiče:** obnoví se přesně zachycené utility a skimy;
   skript aktualizace utility se pro tento přepočet vynechá. TG/TD a realizace
   OD poptávku znovu vypočítají nativně, včetně původní LONG masky ≥80 km.
3. **Plný rollback:** po nativním assignmentu/skimech se původní pomocná epocha
   znovu obnoví. Původní důkaz ekvivalence assignmentu/cest zůstává povinný.
4. **Přijetí:** nový ověřený stav utility i časů se stane rodičem dalšího bloku.
   Iterativní korekce se tedy nezmrazuje pro celý kalibrační běh.
5. **Demand-only:** neprovádí reset ani žádný assignment typu 100/101.
   Uložené cesty zůstávají a odpadá oprava assignmentu vyvolaná samotnou sondou.

Pomocný stav se zapisuje jen v úzkém obnovovacím scope. Guard povolí pouze přesné
hashe zachycených hodnot, vektor 2D float64 a `add=False`. Utility musejí mít
správné kódy, typ SKIM/ZONE/DATA; skimy navíc správný CODE a DSeg. Skimová čísla
nesmějí být vázána jako OD demand segmentu. Žádný obecný zápis OD matic, přepsání
M9002 nebo zápis FORMULA agregátu 9305 se nepovoluje. Původní výjimka pro LONG
masku zůstává oddělená a beze změn.

Po částečně neúspěšném setteru se scope vždy uzavře a invaliduje se readback
cache. Selhání obnovy nadále zastaví kalibraci. Diagnostika nyní uvádí také,
zda souhlasí pomocný stav, která pole snapshotu a která OD čísla se liší.
STOP se při omezeném čtecím důkazu odloží stejně jako při původním zotavení,
a zůstane platný pro další akci.

## Instalace a spuštění

Rozbalit **celý nový balík** do nové složky a použít obvyklý launcher
`RUN_R1_2025_CORDON_LIVE04_V7_TG_TD_CYCLE.py`. **V operaci 15 změnit soubor
Run script na `RUN_R1_TD_UTILITY_TRANSACTIONAL.py` z tohoto balíku**, nebo jeho
obsahem nahradit dosavadní soubor. Původní dodaná kopie je bezeztrátově uložena
v provenienčním JSON a testy ověřují její původní SHA-256.

Doplněk 2026-11-16: procedura R1 má skripty vložené ve verzi
(`EXECUTESCRIPTPARA FILENAME="" USEINTERNALSCRIPTCODE="1"`). Kalibrátor proto čte kód
operace 15 z `Operation.ExecuteScriptParameters`: při vloženém kódu `INTERNALSCRIPTCODE`,
jinak soubor `FILENAME` (relativně ke .ver). Stačí tedy vložit celý obsah
`RUN_R1_TD_UTILITY_TRANSACTIONAL.py` jako vnitřní kód operace 15. Pokud kód ani soubor
nejdou přečíst, běh se zastaví s `TD_UTILITY_UPDATE_SCRIPT_REFERENCE_UNREADABLE:` a výpisem
toho, co se četlo.

Nový skript je samostatný (stdlib + NumPy), zachovává `LAMBDA = 0.5`,
`RATIO_MAX = 4.0` a dosavadní cold-start smlouvu. Mimo kalibrátor čte živé vstupy
stejně jako původní verze; testy potvrzují totožné utility a poptávku. Uvnitř
kalibrátoru přebírá pouze čtecí neměnné vstupy stejného modelu, zón a přijaté
epochy. Čísla/bindingy skimů stále kontroluje živě. Konkrétní LAMBDA a další
matematika zůstávají ve skriptu, nejsou duplikované v řídicím kódu.

Preflight ověřuje referenci souboru v operaci 15, verzi protokolu a hash jeho
zdroje. Starý soubor je odmítnut před změnou koeficientů. Hash skriptu je také
v identitě stavu; úprava jeho kódu během běhu je chyba. Krátkodobý kontext
se vždy odstraní a je vázaný na jedno synchronní nativní volání. Vložený skript
smí použít vlastní Python kontext či vlákno; předávají se pouze čistá data bez
COM proxy vnějšího volání. Nativní updater
musí potvrdit přesně jeden průchod s přijatými vstupy, jinak se krok nepřijme.
Obnova rodiče updater vynechá a žádné takové potvrzení nevyžaduje.

`evaluation.td_utility_update_position = 15` odpovídá dodané proceduře
(TG 13, utility skript 15, TD 17). Pokud se procedura přesune, upraví se toto
číslo; kalibrátor ověří, že jde o Run script před jediným aktivním TD se všemi
16 očekávanými utility referencemi. Části se bez existujících utility 9700–9715
neaktivují a původní modely s M9002 zůstávají na původní snapshotové smlouvě.
Částečná instalace utility, špatné reference, FORMULA zdroje, jiné osy a chybějící
či neinicializované časové skimy blokují běh před změnou kalibračních koeficientů.
Jednorázový cold start utility patří do přípravy modelu před kalibrací, včetně
následného nativního assignmentu a časových skimů.

Z neověřeného starého běhu se nenavazuje. Pro další pokus znovu otevřít ověřenou
`R1_VARIANTYBase_LIVE04_2025_LIVE04_BASE_2b3774f1.ver`, případně poslední ověřený
checkpoint. Starší checkpointy bez pomocné identity nejsou touto verzí potichu
prohlášeny za ekvivalentní.

Audit: `TD_UTILITY_BASELINE/TD_UTILITY_PARENT.json`,
`TD_UTILITY_TRANSACTION.json` v každém dotčeném přepočtu,
`TD_UTILITY_POST_RECOMPUTE_RESTORE.json` a rozšířený `DEMAND_RESTORE_PROOF.json`.
Výchozí intervaly, objective, přijetí, GEH/IDP/LONG guardy, v7 donorové zdroje,
ASD3 mapování, odkládání nezměněného TD i geometrická pipeline se nemění.

## Ověření a hranice

Testy zahrnují skutečný dodaný skript, opakované sondy, plný rollback,
znovupřijetí, přechod na nového rodiče, přepis skimů po assignmentu, chybný
scope/typ/ref/pořadí zón, částečně selhavší setter, úklid oprávnění a STOP.
Výsledky doplňuje samostatná regrese a celý syntetický kalibrační cyklus.
Přesné počty a logy jsou v `evidence/CHECKS.json`.

Živý model ani COM PTV Visumu zde není dostupný; oprava není prohlášením
bezchybnosti celého živého řetězce. Z příloh bez před/po obsahu všech matic nelze
rozložit skutečnou odchylku starého běhu na jednotlivé OD buňky. Oprava neobnovuje
neznámý stav libovolných jiných uživatelských skriptů; neobnovitelná změna je dál
viditelná v přesném důkazu a vede k zastavení, ne k přijetí slabší tolerance.

Velké syntetické cykly ověřují kompatibilitu řetězce se starým M9002 modelem. Aktivní větev 16 utility / 10 skimů se ověřuje na malé simulaci skutečného skriptu, včetně produkčních hooků adaptéru a prediktoru. PTV COM ani skutečný 681zónový model s těmito utility zde nebyl spuštěn.
