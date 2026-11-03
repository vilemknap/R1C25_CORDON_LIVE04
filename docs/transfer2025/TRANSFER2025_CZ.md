# TRANSFER2025 – přenos kalibrace 2022 → 2025 a kontrola před LIVE04

Skripty připraví verzi 2025, na které rovnou poběží kordónová kalibrace LIVE04. Do kopie 2025 přenesou parametry z profilové kalibrace 2022, jednou přepočtou model postupem v7 včetně ořezu LONG pod 80 km, výsledek uloží jako novou verzi a bez zápisu zkontrolují, že LIVE04 má vše, co potřebuje.

## Postup ve Visumu
Každý krok spouštěj v **čerstvé instanci Visumu**. V instanci, kde běžela profilová kalibrace v7, jsou načtené moduly `r1_15a2_*` z jiné složky a bootstrap se tam zastaví (`TRANSFER_FOREIGN_PROFILE_MODULE_COLLISION`).

| Krok | Otevřená verze | Skript | Zapisuje? |
|---|---|---|---|
| 1. EXPORT | kalibrovaná verze 2022 (poslední přijatý stav po cyklu 06) | `RUN_R1_2022_EXPORT_CALIBRATED_PARAMETERS.py` | nic |
| 2. IMPORT | **kopie** modelu 2025 (název obsahuje `LIVE04`/`KOPIE`/`COPY`/`TEST`/`TRIAL`/`CALIB`, nesmí obsahovat `2022`) | `RUN_R1_2025_IMPORT_AND_RECOMPUTE.py` | parametry + jeden přepočet + nová verze |
| 2b. RECOMPUTE (místo kroků 1–2, když už koeficienty v kopii jsou) | **kopie** modelu 2025 se zkalibrovanými koeficienty | `RUN_R1_2025_RECOMPUTE_FOR_LIVE04_BASE.py` | jen přepočet + nová verze, žádné parametry |
| 3. READINESS (volitelně znovu) | libovolná verze 2025 | `RUN_R1_2025_LIVE04_READINESS.py` | nic |

Výstupy: `%LOCALAPPDATA%\R1C25_TRANSFER2025\<EXPORT|IMPORT|READINESS>_<id>\00_RESULT.json`.

IMPORT si vezme **nejnovější** export z té složky. Konkrétní soubor nastavíš v `TRANSFER_2025_CONFIG.json → parameter_file`.

## Co se přenáší
| Skupina | Atributy | Výchozí |
|---|---|---|
| `ws_coefficients` | ADD_PROD_W, ADD_ATT_W, ADD_PROD_S, ADD_ATT_S | ano (povinné) |
| `zahr_coefficients` | ZAHR_PROD_WORK, ZAHR_ATR_WORK, ZAHR_PROD_SERV, ZAHR_ATR_SERV | ano (povinné) |
| `salary` | ADD_SALARY | ano (povinné) |
| `long_school` | ADD_PROD_L, ADD_ATT_L, ADD_PROD_SCH, ADD_ATT_SCH | ano; pokud je model 2022 nemá, zůstanou hodnoty 2025 |
| `boundary_pa_volumes` | P09F4/A09F4 hraničních zón (objemy, ne koeficienty) | **ne** (2025 má vlastní data) |
| TD | gravitační b/c všech 16 komponent | ano |
| ADDVAL1 | hodnota každé hrany podle klíče NO:FROMNODENO:TONODENO | ano |

Přenášejí se **parametry**, ne matice. Poptávka 2025 se z nich přepočte na socioekonomice a síti 2025.

**Zóny** se párují podle čísla NO:
- výchozí politika `REQUIRE_IDENTICAL_ZONE_SET` se zastaví, pokud se množiny zón liší;
- `MATCHING_ZONES_ONLY` přenese jen společné zóny a ostatní nechá s hodnotami 2025.

**Hrany** se párují podle klíče:
- výchozí politika `MATCHING_LINK_KEYS_ONLY` přenese jen hrany, které existují v obou modelech, a nalezené hrany 2022 s nenulovým ADDVAL1, které v síti 2025 chybí, vypíše;
- `FAIL_ON_UNMATCHED_NONZERO` se v takovém případě zastaví ještě před prvním zápisem.

## IMPORT krok za krokem
1. **Ověření exportu.** Schéma a hash obsahu (upravený soubor se odmítne). Cílová verze nesmí být zdroj 2022 a musí splnit pravidla pro název kopie z LIVE04.
2. **Plán zápisů.** Celý plán (`TRANSFER_PLAN.json`) vznikne **před prvním zápisem**: jen hodnoty, které se opravdu liší.
3. **Zápisy.** Zone atributy, TD b/c a ADDVAL1, každý se zpětným čtením. Guard povolí zápis jen přesně plánovaných atributů.
4. **Jeden přepočet** postupem v7 (plán PERF1 GENERATION):
   - TG → TD → ořez LONG osob → 20A/20B → ořez LONG vozidel → přiřazení 17–19 a 20;
   - pak kontrola, že žádná operace parametry nepřepsala, a že je podpora LONG čistá (≥ 80 km na 9697).
5. **Nová verze** `<kopie>_LIVE04_BASE_<id>.ver` vedle kopie. Otevřený soubor se nepřepisuje a LoadVersion se nevolá.
6. **READINESS** na výsledku.

Při chybě po prvním zápisu se parametry vrátí na hodnoty před importem. Poptávka ale může zůstat přepočtená, takže kopii znovu otevři (`model_state = PARAMETERS_RESTORED_DEMAND_MAY_BE_RECOMPUTED_REOPEN_THE_COPY`).

## RECOMPUTE – bez importu koeficientů (od 2026-11-03)
Pro kopii 2025, ve které už koeficienty jsou (např. scénářová verze `R1_CSD22_kal_2025.ver` vytvořená z kalibrovaného 2022). Nepotřebuje export 2022 a nic z parametrů nezapisuje.

1. Ulož kopii pod názvem s `2025` a `KOPIE`/`COPY`/`TEST`/`TRIAL`/`CALIB`/`LIVE04`, bez `2022` (např. `R1_CSD22_kal_2025_KOPIE.ver`).
2. V čerstvém Visumu ji otevři a spusť `RUN_R1_2025_RECOMPUTE_FOR_LIVE04_BASE.py`.
3. Skript:
   - **před prvním zápisem** ověří, že síť obsahuje všech 32 směrových hran 16 kordonových stanic (`STATION_MAPPING.csv`); jinak skončí `RECOMPUTE_BASE_CORDON_STATION_LINKS_MISSING_IN_NETWORK` a model zůstane beze změny;
   - uloží snímek koeficientů zón, TD b/c a ADDVAL1 (`PARAMETERS_BEFORE.json`);
   - provede jeden přepočet v7 s ořezem LONG (stejně jako IMPORT) – tím vzniknou i uložené cesty;
   - ověří, že žádná procedura koeficienty, TD ani ADDVAL1 nezměnila, a že je podpora LONG čistá;
   - uloží novou verzi `<kopie>_LIVE04_BASE_<id>.ver` a spustí READINESS (bez kontroly shody s exportem).
4. Výsledek: `%LOCALAPPDATA%\R1C25_TRANSFER2025\RECOMPUTE_<id>\00_RESULT.json`, `status = RECOMPUTED_SAVED`, `readiness = READY_FOR_LIVE04`.

Zápisy: jen matice masky LONG (9111–9115, 9291–9295) a nová .ver; guard zakazuje zápis zónových atributů, TD i ADDVAL1.

## READINESS kontroluje (bez zápisu)
1. Piny release a donorů v7.
2. Preflight LIVE01: 681 zón, síť, demand segmenty, matice, uložené cesty.
3. Název kopie podle pravidel LIVE04.
4. Jednu aktivní operaci TD; operace 17, 18, 19 a 20 s DSEGSET podle v7.
   LIVE04.4: pro SupplyMix aktivní reset (op 15, typ 9) před společným přiřazením (`SUPPLYMIX_COLD_CHAIN`).
5. Typy matic: 9291–9295 DATA, 9305 FORMULA (čte se 9111–9115, 9116).
6. Čistou podporu LONG (osoby i vozidla ≥ 80 km).
7. Autoritu mobility: produkční poměr W/S, MOBILITYZONE1.
8. Shodu parametrů s exportem (po IMPORTu, nebo když je nastavený `parameter_file`).
9. Plný capture kordónu: cíl a GEH všech tří metod, tedy výchozí stav pro LIVE04.
10. Že během kontroly nedošlo k žádnému zápisu.

Výsledek `READY_FOR_LIVE04` znamená, že LIVE04 na otevřené verzi projde vstupními kontrolami. Jinak `NOT_READY` se seznamem nesplněných kontrol.

## Testy (synteticky, nejde o nativní důkaz z PTV)
`tests/test_transfer2025.py` pokrývá:
- celý tok export → import → přepočet → uložení → READY;
- rozdílnou množinu zón (stop před zápisem / jen společné zóny);
- upravený export;
- cíl = zdroj 2022;
- chybějící hrany ADDVAL1;
- chybu přepočtu (vrácení parametrů);
- nemaskovaný LONG v kontrole;
- guard (ADDVAL1, SaveVersion jen na schválenou cestu);
- konfiguraci;
- spouštěče.
