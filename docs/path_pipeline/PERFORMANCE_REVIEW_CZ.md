# Rychlejší zachycení cest kordónového kalibrátoru

Základ: `vilemknap/R1C25_CORDON_LIVE04`, větev `live04-11-1-opmap1`,
commit `99a7a576b29faa95c6c1f81ded191eb6c44ae07d` (LIVE05.5, opravy OPMAP1).

## Co je implementované

`cordon2025/live04_pipeline.py` překrývá další čtení na původním COM vlákně
se zpracováním předchozí dávky. Jeden worker používá stávající parser
`live04_fastgeom.add_geometry` a vlastní SQLite připojení vytvořené a zavřené
na workeru. Původní připojení zůstává na původním vlákně, během zpracování je
neaktivní. Nastavení foreign_keys, synchronous a cache_size se přebírá přesně;
journal_mode ani četnost commitů se nemění.

Čtecí strana nadále používá původní `bounded_rows`: stejné rozsahy, kontrolu
opakovaných stránek, TypeInfo, rozpočty a retry. Do workeru putují jen nezávislé
n-tice skalárů. COM objekty, čtecí generátor ani traceback čtecí chyby se na něj
nepředávají. Pořadí řádků a vazba rodič–potomek přes hranice stránek zůstávají
zachované. Překrytí se používá pouze pro nativní COM geometrii; přehrávání ověřené epochy z disku zůstává sekvenční, protože tam čekání na COM chybí. Fronta má jeden slot; nejvýše jedna dávka se zpracovává a druhá se
čte nebo čeká. Vnitřní omezení velikosti nativních stránek zůstává původní.

Všechny checkpointy workeru obsluhuje původní vlákno, včetně STOP. Před návratem
nebo předáním chyby je worker ukončen a připojení zavřené. Chyba nevytvoří
`capture_complete` ani `SNAPSHOT_EVIDENCE.json`; vlastní publikování důkazů
zůstává až za původními kontrolami celého zachycení.

Krátké dávky vyžadují potvrzení převzetí hlavním vláknem před začátkem parsování.
Bez této synchronizace je kvůli GIL možné prakticky sekvenční provádění i se
dvěma vlákny. Test potvrzuje skutečné překrytí, nikoli jen existenci workeru.

## Použití

Spouštěč zůstává `RUN_R1_2025_CORDON_LIVE04_V7_TG_TD_CYCLE.py`.
V nové kopii balíku je `evaluation.geometry_pipeline = true`. Hodnota `false`
v `CORDON_LIVE04_CONFIG.json` vrací sekvenční zpracování. Starší konfigurace bez
klíče používají `false`; nejde o automatickou změnu běžícího procesu. Soubor
`provenance/live04_user_config/CORDON_LIVE04_CONFIG.RELEASE_DEFAULT.json`
obsahuje stejnou novou výchozí konfiguraci. Změna se načte při příštím spuštění.

Velikost COM stránky zůstává 1024 a rychlý parser zůstává zapnutý. Geometrie
a objemy se nadále ověřují původní metodou. Cílová funkce, FIRST_LAST,
EXACT_TWO_HITS, C17, ochrany NDS/ASD/K, přijetí, rollback ani nativní TG/TD,
přidělení a LONG maska se touto změnou neupravují. Do rodičovských zdrojů `parent/`
ani do chráněného `visum_startup.py` nebylo zasahováno.

## Jak změřit skutečný přínos

`CAPTURE_TIMING.json` a `SNAPSHOT_EVIDENCE.json` dál obsahují původní časy fází.
Nový `GEOMETRY_PIPELINE_TIMING.json` má pro každý stream:

- celkový čas;
- čtení a oddělení řádků na COM vlákně;
- aktivní čas workeru, oddělený od čekání na data a kontrolu;
- počet dávek a řádků, velikost dávky a kapacitu fronty.

Časy souběžných fází se nesčítají do wall time. Čtení zahrnuje i přesun řádků
z původního iterátoru a kontrolu skalárů; nejde o čistou COM latenci.
Pokud nativní COM implementace neuvolní GIL nebo pokud převáží CPU práce bez
čekání, může se přínos zmenšit nebo obrátit. Automatický přepínač režimu během
zachycení neexistuje. Čistě CPU scénář je proto součástí offline benchmarku.

Reprodukce mimo Visum, s požadovanými závislostmi:

```
python tools/benchmark_geometry_pipeline.py --routes 12000 --length 70 --read-ms 6 --repeats 3 --output blocking.json
python tools/benchmark_geometry_pipeline.py --routes 12000 --length 70 --read-ms 0 --repeats 3 --output cpu.json
```

Jde o syntetický blokující čteč; příprava dat a rodičovských objemů je mimo
měřený interval. Měří se celý současný parser, zápisy, komprese a commity SQLite.
Po každém běhu se provede quick_check a foreign_key_check, porovnají se bajty
celé výsledné databáze přes SHA-256. Nejde o měření nativního Visumu ani o
kalibraci skutečného modelu. Konkrétní výsledky jsou v `evidence/BENCHMARK_*.json`.

## Dodané starší logy

`evidence/INPUT_AUDIT.json` uvádí hashe všech 18 příloh a shrnutí skutečných
záznamů. Běh skončil na `USER_STOP_REQUESTED`; jeho vlastní readback potvrdil
shodu s posledním přijatým stavem. Proběhly dvě přijaté Generation a jeden
SupplyMix. Obě TD skončily bez kandidáta. Starý progress uvádí stránku 256.
Přílohy neobsahují aktuální úplný časový profil zachycení. Časy 66–71 minut,
odhady 20 minut a 3–4 minut úspory z vloženého textu nejsou tímto auditem
nezávisle ověřená měření a nejsou slibem nové verze.

## Další místa pro měření

| Místo | Možnost | Podmínka |
|---|---|---|
| `parents_and_matrices` | Sdílet pole načtená v preflightu při zachycení stejného stavu | Zachovat závěrečné nezávislé čtení a identitu celé epochy; nejdříve změřit podíl času. |
| Výpočet all-link důkazu | Omezit opakované rozbalování stejných edge postings mezi módy | Zachovat násobnost průjezdů, nulové objemy a přesné porovnání; vyhodnotit paměť. |
| Staging SQLite | Porovnat náklad commitů a indexů s validovaným publikačním modelem | Samostatný benchmark na velkém store; tato úprava durability nemění. |
| Filtrování cest podle pozorování | Snížit počet čtených řádků | Vyžaduje jiný důkaz úplnosti a správné obnovení filtru; zde neimplementováno. |

Dosavadní optimalizace 10.2–10.7 už základní větev obsahovala. Nejsou znovu
vydávány za nové zrychlení.
