# R1 2025 – kordónová kalibrace LIVE04: LIVE03 na profilovém kalibrátoru v7 (P2.5/A4)

## Co LIVE04 dělá
Postup je stejný jako v LIVE03: TG + TD na pozorováních ze Sprievodné správy (FIRST_LAST + C17), nativní predikce na zmrazených cestách a TD_CORDON s guardem IDP. Pravidla Generation a LONG jsou ale převzatá **z v7 @ 977cef4**, tedy z verze, která teď běží ve Visumu:

1. **TG:**
   - obálky podle role: P 0,75–2,5 a A 0,75–4,0 (ZAHR 0,5–10, hranice 0,5–2);
   - MOBILITY2 (produkční pás 0,75–2,5 a plot atrakce W/S 0,75–4,0);
   - MOBILITYZONE1 (pevná reference AMDY FP pro každou zónu);
   - BDPA1 a STEP1 podle GENFIX2 (predikce finálního kandidáta, brána s mobilitou, zmenšení ×0,75 před zápisem, vlastnictví obnovy).
2. **SCHOOL TG** zůstává pevné (AMDY). **LONG TG** je odložené, stejně jako ve v7 bez LONG cache.
3. **LONG post-TD maska ≥ 80 km** (OSRM 9697) se použije při každém nativním přepočtu: v pokusu, rollbacku, obnově i v nativních sondách bez assignmentu. 9305 = OD matice NATIVE_CL, takže maska je vidět i na kordónu.
4. Zápisy:
   - TG atributy zón;
   - TD b/c;
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
  - `MEMORY/RUN_MEMORY.json` (LIVE04.1).

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
- **`v7.run_options`** jsou přesná kopie `R1_RUN_OPTIONS.json` z v7 @ 977cef4, kromě tří schválených odchylek:
  - `long_generation_enabled = false`,
  - `long_composite_td_enabled = false`,
  - `fa_enabled = false`.
  Jiná změna se odmítne (`LIVE04_V7_RUN_OPTION_DRIFT`).
- **`v7.long_post_td_mask`**:
  - `enabled`;
  - `require_masked_baseline`, výchozí `true`, nedoporučuje se vypínat;
  - `minimum_km` = 80 (pevné podle v7).
- **`write_policy.long_post_td_mask_matrix_writes`** musí odpovídat `v7.long_post_td_mask.enabled`.
- **`memory`** (LIVE04.1): paměť mezi cykly. Přenáší Jacobián TD s ověřovací sondou, korekci změny tras v TG a volí počet uzlů. Ovlivňuje jen predikci a volbu kroku, nikdy přijetí. `enabled=false` vrací přesně chování LIVE04. Podrobně: `docs/live04/LIVE04_1_MEMORY_CZ.md`.

## Hranice
Jde o technický zkušební běh (`TECHNICAL_TRIAL`, `production_ready=false`). Offline testy na syntetickém mocku nejsou nativní důkaz z PTV Visum.
