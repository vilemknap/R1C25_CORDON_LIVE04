# R1 2025 – kordónová kalibrace LIVE04: LIVE03 na profilovém kalibrátoru v7 @ 7b4c681

## Co LIVE04 dělá
Postup je stejný jako v LIVE03: TG + TD na pozorováních ze Sprievodné správy (FIRST_LAST + C17), nativní predikce na zmrazených cestách a TD_CORDON s guardem IDP. Pravidla Generation, SupplyMix, GEH/severity a LONG jsou ale převzatá **z v7 @ 7b4c681** (LIVE04.4, 2026-11-01; dříve 977cef4):

1. **TG:**
   - **bez CATCH_UP**, krok jedné zóny nejvýše **+5 % / −5 %** P/A efektu, až 6 nativních pokusů v bloku;
   - po prvním odmítnutém pokusu jeden **měřený zónový refit** směru (v7), audit predikce `STEP1_PRED_AUDIT.json` u každého pokusu;
   - obálky podle role: **P 0,5–3,15 a A 0,5–5,5** (LIVE04.5, rozhodnutí 2026-11-03; v7: 3,0 / 5,0), ZAHR 0,5–10, hranice 0,5–2;
   - MOBILITY2 (produkční pás 0,5–3,15 a plot atrakce W/S 0,5–5,5, vždy stejné jako obálky);
   - MOBILITYZONE1 (pevná reference AMDY FP pro každou zónu);
   - BDPA1 a STEP1 podle GENFIX2 (predikce finálního kandidáta, brána s mobilitou, zmenšení ×0,75 před zápisem, vlastnictví obnovy).
2. **SupplyMix (SUPPLY_ADDVAL1)** hned po Generation v cyklech 2, 4, 6…: ADDVAL1 na prokázaných větvích uložených cest řádků kordonu s vysokým GEH, až 24 skupin / 240 hran / 4 pokusy (kroky 4 / 3 / 2 / 1 ADDVAL1), studený přepočet reset op 15 → přiřazení, ověřený rollback.
3. **GEH limity a severity (SEVRELAX3) na kordonových řádcích** v každé bráně (plánovací i nativní): chráněný řádek < 5 → < 40, skok +50, nad GEH 60 nejvýše +30, rozpočty severity20/30 a GEH ≥ 40 podle bloku (TG 20 % / 25 % / 10, TD 40 % / 50 % / 25, SupplyMix 35 % / 45 % / 30).
4. **SCHOOL TG** zůstává pevné (AMDY). **LONG TG** je odložené, stejně jako ve v7 bez LONG cache.
5. **LONG post-TD maska ≥ 80 km** (OSRM 9697) se použije při každém nativním přepočtu: v pokusu, rollbacku, obnově i v nativních sondách bez assignmentu. 9305 = OD matice NATIVE_CL, takže maska je vidět i na kordónu.
6. Zápisy:
   - TG atributy zón;
   - TD b/c;
   - ADDVAL1 hran (SupplyMix, s readbackem);
   - matice masky 9111–9115 a 9291–9295 (jen numpy float64, Add=False, vždy s readbackem).
   Nezapisuje se do 9305, OD matic dsegů ani do ostatních matic. LoadVersion se nevolá a zdrojový .ver se nepřepisuje.

## Příprava a spuštění
1. Rozbal FULL ZIP do nové složky.
2. Ve Visumu, kde **neběží** profilová kalibrace v7, otevři **kopii** modelu R1 2025 s uloženými cestami.
   - Kopie má být uložená z běhu v7, tedy s již maskovaným LONG.
   - Název musí obsahovat `LIVE04`, `KOPIE`, `COPY`, `TEST`, `TRIAL` nebo `CALIB`.
3. Spusť Scripts → Execute script file → `RUN_R1_2025_CORDON_LIVE04_V7_TG_TD_CYCLE.py`.
4. Výstupy najdeš v `%LOCALAPPDATA%\R1C25_LIVE04\LIVE04_TGTD_<id>\`.
5. Bezpečné zastavení: v této složce vytvoř soubor `STOP_REQUESTED`.

## Co poslat zpět
- Vše, co u LIVE03.
- Navíc:
  - `V7_RUNTIME_STATUS.json`;
  - `LONG_SUPPORT_BASELINE.json` a `LONG_SUPPORT_FINAL.json`;
  - `Cxx_GENERATION/DESIGN/V7_TARGETED_GENERATION/`:
    - `V24917_FIT_SUMMARY.json`,
    - `MOBILITYZONE1_PARENT.json`,
    - případně `V24917_MOBILITY_BLOCKED.json`;
  - `Cxx_*/TRY_xx/ASSIGNMENT/`:
    - `LONG_MASK_EXECUTION_PLAN.json`,
    - `MASK_*_LONG/LONG_MASK_RESULT.json`;
  - `GENFIX2_FINAL_MOBILITY_AND_PREDICTION.json`;
  - `MEMORY/RUN_MEMORY.json` (LIVE04.1);
  - LIVE04.4: `Cxx_GENERATION/TRY_xx/STEP1_PRED_AUDIT.json`, `Cxx_GENERATION/MEASURED_ZONAL_REFIT.json`,
    `Cxx_SUPPLY_ADDVAL1/` (`SUPPLYMIX_BLOCK_RESULT.json`, `TRY_xx/SUPPLYMIX_CANDIDATE.json`, `TRY_xx/ACCEPTANCE.json`,
    `DESIGN/SUPPLY_PATH_SEQUENCE_DESIGN.json`), `ACCEPTED_ADDVAL1.csv`.

## Výsledné stavy
| `status` | Stav modelu |
|---|---|
| `NATIVE_LIVE04_ACCEPTED` | poslední přijatý stav, uložen jako nový .ver |
| `NATIVE_LIVE04_NO_ACCEPTED_CHANGE` | výchozí stav ověřen |
| `LIVE04_BLOCKED_BEFORE_ANY_WRITE` | beze změny |
| `LIVE04_STOPPED_MODEL_VERIFIED_AT_LAST_ACCEPTED_STATE` | poslední přijatý stav (rollback ověřen) |
| `LIVE04_STOPPED_MODEL_STATE_NOT_VERIFIED_REOPEN_SOURCE_OR_SAVED_VERSION` | znovu otevři zdrojovou kopii |

Typické zastavení před prvním zápisem:

- `LIVE04_BASELINE_LONG_SUPPORT_NOT_MASKED` – kopie nebyla uložená z běhu v7 (v LONG zůstaly jízdy pod 80 km);
- `MOBILITY2_BLOCKED_DATA_NOT_A_PLATEAU:<stage>` – data mobility nejsou úplná nebo jsou neplatná (např. FP_* < 0, chybí atribut);
- `V7_DONOR_FILE_CHANGED` – někdo upravil soubor v `parent/`.

## Konfigurace `CORDON_LIVE04_CONFIG.json`
- **Sekce LIVE03** (`max_cycles`, `observations`, `native_prediction`, `td_cordon`, `idp_guard` atd.) platí stejně a ověřuje je stejný validátor.
- **`v7.run_options`** jsou přesná kopie `R1_RUN_OPTIONS.json` z v7 @ 7b4c681, kromě tří schválených odchylek:
  - `long_generation_enabled = false`,
  - `long_composite_td_enabled = false`,
  - `fa_enabled = false`.
  Jiná změna se odmítne (`LIVE04_V7_RUN_OPTION_DRIFT`).
- **`v7.long_post_td_mask`**:
  - `enabled`;
  - `require_masked_baseline`, výchozí `true`, nedoporučuje se vypínat;
  - `minimum_km` = 80 (pevné podle v7).
- **`v7.coefficient_envelope`**: obálka koeficientů W/S podle role (PROD [0,5; 3,15], ATT [0,5; 5,5]). Validace vynucuje, že `run_options.mg_min_ratio`/`mg_max_ratio` = PROD a `mobility_guards.ws_attraction_coefficient_band` = ATT. Jinak by nejužší mez obálku tiše ořízla.
- **`write_policy.long_post_td_mask_matrix_writes`** musí odpovídat `v7.long_post_td_mask.enabled`.
- **`supply_mix`** (LIVE04.4): `enabled` zapíná SupplyMix; `write_policy.supply_addval1_writes` musí mít stejnou hodnotu. Volby `sp_*` (24/240/4, kroky 8/6/4/2, cykly 2, 4, …) jsou pinované run options v7.
- **`row_geh_guard`** (LIVE04.4): `enabled` zapíná SEVRELAX3 na kordonových řádcích; limity `sev_*` jsou pinované run options v7. Podrobně: `docs/live04/LIVE04_4_V7_7B4C681_CZ.md`.
- **`memory`** (LIVE04.1): paměť mezi cykly. Přenáší Jacobián TD s ověřovací sondou, korekci změny tras v TG a volí počet uzlů. Ovlivňuje jen predikci a volbu kroku, nikdy přijetí. `enabled=false` vrací přesně chování LIVE04. Podrobně: `docs/live04/LIVE04_1_MEMORY_CZ.md`.

## Hranice
Jde o technický zkušební běh (`TECHNICAL_TRIAL`, `production_ready=false`). Offline testy na syntetickém mocku nejsou nativní důkaz z PTV Visum.
