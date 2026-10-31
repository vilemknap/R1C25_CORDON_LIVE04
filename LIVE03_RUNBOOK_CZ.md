# R1 2025 – kordónová kalibrace LIVE03: TG + TD na pozorování ze Sprievodné správy

## Co LIVE03 dělá
Na **izolované kopii** otevřeného modelu R1 2025:

1. Ověří vydání, připojí se k otevřenému Visumu a načte stav modelu (kontrakt LIVE01). Pak udělá úplný capture uložených cest.
2. Vyhodnotí kordón podle **sémantiky průzkumu**:
   - 120 párů FIRST_LAST vůči Transit RPDI,
   - 16 stanic C17 (průchody cestami s jedním zásahem kordónu, cyklické jízdy 2×).
   Sekundární metoda EXACT_TWO_HITS se nesmí zhoršit.
   Pravidla jsou v `OBSERVATION_CONTRACT.json`.
3. Uloží bod obnovy (snapshot TG, TD b/c, matic, ADDVAL1, operací).
4. V každém cyklu provede:
   - **GENERATION.**
     1. Zonální fit V24917 (CATCH_UP / REFINE, BNDGEN, LSGEN).
     2. Nativní sondy kroku 1,0 a 0,5. Při nich se poběží jen TG→TD→maticové operace, assignment ne.
     3. Predikce na zmrazených cestách.
     4. Výběr kroku donorovým `choose_scale`.
     5. Jeden plný pokus s assignmentem a novým capture.
     6. Přijetí na místě, nebo ověřený rollback.
   - **TD_CORDON.**
     1. Nativní Jacobián pro b a c rodin WORK, SERVICE a SCHOOL.
     2. Kroky Levenberg–Marquardt, každý ověřený nativní sondou.
     3. Guard IDP FineCDF v1.9.
     4. Plný pokus TD→assignment.
     5. Přijetí na místě, nebo ověřený rollback.
5. Skončí po `max_cycles` cyklech, nebo po cyklu bez změny. Přijatý stav uloží jako **nový** .ver.
   - Zdrojový .ver se nikdy nepřepisuje.
   - LoadVersion se nevolá.
   - Do OD matic se přímo nezapisuje.

## Příprava a spuštění
1. Rozbal FULL ZIP do nové složky.
2. Ulož kopii modelu R1 2025 **s uloženými cestami**. Název musí obsahovat `LIVE03`, `KOPIE`, `COPY`, `TEST`, `TRIAL` nebo `CALIB`.
3. Otevři tuto kopii ve Visumu.
4. Spusť Scripts → Execute script file → `RUN_R1_2025_CORDON_LIVE03_TG_TD_CYCLE.py`.
5. Výstupy najdeš v `%LOCALAPPDATA%\R1C25_LIVE03\LIVE03_TGTD_<id>\`.
6. Bezpečné zastavení: v této složce vytvoř soubor `STOP_REQUESTED`. Rozpracovaná obnova se vždy dokončí.

## Co poslat zpět
- `00_RESULT.json`, `CYCLE_PROGRESS.json`, `BASELINE_OBJECTIVE.json`, `OBSERVATION_CONTRACT.json`
- `Cxx_GENERATION/`:
  - `GENERATION_BLOCK_RESULT.json`, `STEP1_PLAN_*.json`
  - `NATIVE_PREDICTION/TG_NATIVE_NODES.json`, `PREDICTOR_BASE_PARITY.json`
  - `TRY_xx/ACCEPTANCE.json`
- `Cxx_TD_CORDON/`:
  - `TD_BLOCK_RESULT.json`, `IDP_BEFORE.json`, `TD_JACOBIAN_PRIMARY.csv`
  - `TRIAL/ACCEPTANCE.json`, případně `DEMAND_RESTORE/DEMAND_RESTORE_PROOF.json`
- `ACCEPTED_TG_PARAMETERS.csv`, `ACCEPTED_TD_PARAMETERS.csv`, `WRITE_AUDIT_SUMMARY.json`, `V24917_TIMING.json`
- Při chybě také `99_TRACEBACK.txt` a `FAILURE_STATE_READBACK.json`.

## Výsledné stavy
| `status` | Stav modelu |
|---|---|
| `NATIVE_LIVE03_ACCEPTED` | poslední přijatý stav, uložen jako nový .ver |
| `NATIVE_LIVE03_NO_ACCEPTED_CHANGE` | výchozí stav ověřen |
| `LIVE03_BLOCKED_BEFORE_ANY_WRITE` | beze změny |
| `LIVE03_STOPPED_MODEL_VERIFIED_AT_LAST_ACCEPTED_STATE` | poslední přijatý stav (rollback a obnova poptávky ověřeny) |
| `LIVE03_STOPPED_MODEL_STATE_NOT_VERIFIED_REOPEN_SOURCE_OR_SAVED_VERSION` | znovu otevři zdrojovou kopii |

## Konfigurace `CORDON_LIVE03_CONFIG.json`
- **`max_cycles`** (výchozí 3), **`blocks_per_cycle`** (výchozí `["GENERATION","TD_CORDON"]`), **`stop_after_cycle_without_change`**.
- **`observations`** – sémantika a cíle:
  - `pair_matrix`: `Transit` nebo `ALL`;
  - `c17_policy`: `STATION_MARGINS` nebo `DISABLED`;
  - `c17_components`, `c17_row_weight`;
  - `year_bridge.factor` (1,0).
  - NPZ je připnuté SHA-256.
- **`native_prediction`**:
  - `enabled`; při `false` se použije lineární predikce V24917;
  - `tg_node_fractions` (výchozí `[1.0, 0.5]`).
- **`td_cordon`**:
  - skupiny komponent; LONG je zakázán;
  - kroky sond, trust radius, `max_inner_evaluations`, `min_predicted_relative_improvement`.
- **`idp_guard`**: tolerance FineCDF v1.9 (RMSE CDF +0,01, střední vzdálenost +0,02 nad max(|e|, 0,03)).
  - Guard je jen strážce: objective TD tvoří pouze kordón.
- Hodnoty převzaté z donoru a LIVE02 se kontrolují stejným validátorem jako v LIVE02. Změna se odmítne s chybou `LIVE02_DONOR_RUNTIME_DRIFT`.

## Hranice
Jde o technický zkušební běh (`TECHNICAL_TRIAL`, `production_ready=false`).

- Predikce je nativní v poptávce, trasy jsou ale zmrazené. Rozhoduje vždy plný pokus s assignmentem.
- Testy běží na syntetickém mocku. Nativní běh ve Visumu teprve potvrdí časy a skutečnou odezvu.
