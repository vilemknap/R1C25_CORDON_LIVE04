# R1 2025 – kordónová kalibrace LIVE02: první skutečný TG cyklus

## Co LIVE02 dělá
V otevřeném Visumu na **izolované kopii** modelu R1 2025:

1. Ověří vydání a připojí se pouze k již otevřenému Visumu (žádné Dispatch, žádné přepnutí modelu).
2. Načte aktuální stav modelu stejně jako LIVE01 (681 zón, 9 TG parametrů, TD, procedury, OD vazby)
   a udělá úplný výchozí capture uložených cest (parita OD, plná geometrie).
3. Vyhodnotí celou kordónovou matici: 120 vztahů, obě metody, J = ½ Σ (w·(m−y))², GEH, RMSE, R².
4. Uloží bod obnovy (donorový snapshot: TG 9×681, TD B/C, všechny poptávkové matice, ADDVAL1, operace).
5. Spustí **původní donorové hledání TG** (DIAGFAST_V2/HOTFIX2): FISTA → projekce P/A → kandidáti
   pro kroky 1 / 0,75 / 0,5 / 0,25 / 0,125 / 0,0625. Pro každý kandidát:
   zápis ADD/ZAHR + readback → nativní přepočet TG(5)→TD(6)→…→assignment(20) → kontrola gapu
   (PrTAssQualityList op. 20, max 0,005) → kontrola, že parametry nepřepsala žádná procedura →
   `assert_freeze` → **nové čtení cest a nové kordónové vyhodnocení** → rollback (obnova parametrů +
   přepočet + důkaz shody) → další krok. Zlepšení ≥ 0,1 % ukončí hledání dříve.
6. Vítěze aplikuje znovu z identického rodiče a vyžaduje přesně stejný výsledek (reprodukovatelnost).
7. Model nechá v posledním přijatém stavu a uloží ho jako **nový** soubor .ver ve výstupní složce.
   Zdrojový .ver se nikdy nepřepisuje. LoadVersion se nepoužívá, OD matice se přímo nezapisují.

## Příprava
1. Rozbal FULL ZIP do nové samostatné složky (nemíchat s LIVE01 ani s profilovou kalibrací).
2. Ulož kopii funkčního modelu R1 2025 **s uloženými cestami** pod názvem, který obsahuje
   `LIVE02`, `KOPIE`, `COPY`, `TEST`, `TRIAL` nebo `CALIB`, např. `R1_2025_KORDON_LIVE02.ver`.
   Bez této značky se běh zastaví před prvním zápisem (`LIVE02_OPEN_MODEL_IS_NOT_MARKED_AS_ISOLATED_COPY`).
3. Otevři tuto kopii ve Visumu. V instanci nesmí běžet jiná kalibrace.

## Spuštění
Scripts → Execute script file → `RUN_R1_2025_CORDON_LIVE02_TG_CYCLE.py`

Výstupy: `%LOCALAPPDATA%\R1C25_LIVE02\LIVE02_TG_<id>\`

Bezpečné zastavení: vytvoř v této složce soubor `STOP_REQUESTED`. Probíhající rollback se vždy dokončí.

## Co poslat zpět
- `00_RESULT.json`, `CYCLE_PROGRESS.json`, `BASELINE_OBJECTIVE.json`
- `C01_GENERATION/GENERATION_BLOCK_RESULT.json` a v každém `TRY_xx/`: `TRIAL_RESULT.json`,
  `ACCEPTANCE.json`, `ROLLBACK/ROLLBACK_VERIFICATION.json`
- `ACCEPTED_TG_PARAMETERS.csv`, `WRITE_AUDIT_SUMMARY.json`, `COM_READ_RETRY.json`
- při chybě `99_TRACEBACK.txt` a `FAILURE_STATE_READBACK.json`

## Výsledné stavy
| `status` | Význam | Stav modelu |
|---|---|---|
| `NATIVE_LIVE02_TG_ACCEPTED` | přijat aspoň jeden TG stav | poslední přijatý stav, uložen jako nový .ver |
| `NATIVE_LIVE02_NO_ACCEPTED_TG_CHANGE` | žádný kandidát nezlepšil kordón | výchozí stav obnoven a ověřen |
| `LIVE02_BLOCKED_BEFORE_ANY_WRITE` | zastaveno před zápisem | beze změny |
| `LIVE02_STOPPED_MODEL_VERIFIED_AT_LAST_ACCEPTED_STATE` | chyba/STOP, rollback ověřen | poslední přijatý stav |
| `LIVE02_STOPPED_MODEL_STATE_NOT_VERIFIED_REOPEN_SOURCE_OR_SAVED_VERSION` | rollback nešel ověřit | znovu otevři zdrojovou kopii |

## Konfigurace (`CORDON_LIVE02_CONFIG.json`)
- `max_tg_cycles` (výchozí 1, max. 10): počet TG cyklů za sebou z přijatého stavu.
- `acceptance.method`: hodnoticí metoda (výchozí `ALL_ORDERED_UNIQUE_PAIRS`); druhá metoda se nesmí zhoršit.
- `evaluation.trial_full_geometry_check`: plná kontrola geometrie i u pokusů (výchozí ano; vypnutí zrychlí pokusy).
- `write_policy.save_accepted_version_new_file`: uložení přijatého stavu do nového .ver (výchozí ano).
- Hodnoty převzaté z donoru (`donor_runtime`, kroky, brána P/A, gap) se kontrolují proti donorovi;
  jejich změna je odmítnuta (`LIVE02_DONOR_RUNTIME_DRIFT`).

## Hranice
Jde o technický zkušební běh (`TECHNICAL_TRIAL`). Sémantika pozorování, časový most 2026→2025
a politika C17 nejsou schválené. TD/FineCDF a společné TG/TD cykly řeší LIVE03.

## Varianta V24917 (výchozí od 25. 10. 2026 večer)
`CORDON_LIVE02_CONFIG.json → generation_mode = V24917_TARGETED_STEP1`

- Návrh TG = zónový fit P/A přímo na rezidua 120 kordónových vztahů (V24917), fáze **CATCH_UP**
  (model/sčítání < 0,80: krok na zónu až +50 % / −20 %) a **REFINE** (+25 % / −20 %).
- **STEP1**: krok se spočítá z lineární predikce (po měření ze sečny) tak, aby predikovaný stav prošel
  kordónovou bránou s rezervou 15 %. Jeden pokus = jeden nativní přepočet + úplné čtení cest; projde-li,
  **zůstane jako přijatý stav** (bez rollbacku a bez opakovaného přiřazení). Až 3 pokusy na cyklus.
- **BNDGEN** (hraniční přechody) a **LSGEN** (LONG/SCHOOL) se zapnou jen tehdy, když to model umožňuje;
  stav je v `V24917_RUNTIME_STATUS.json`.
- **COMBUSY2**: odmítnutá volání Visumu („Volaný odmítl volání") se opakují až 900 s, rollback i celý
  blok se zopakují od nedotčeného rodiče. Během kalibrace do okna Visumu neklikat.
- Konzole: `R1 CORDON V24917 TG: phase=… ratio=… zones=… rows=… predicted_ratio=…`
  a `R1 CORDON V24917 TIMING: …`.
- Navíc posílat: `V24917_RUNTIME_STATUS.json`, `C01_GENERATION/STEP1_PLAN_*.json`,
  `C01_GENERATION/DESIGN/V24917_TARGETED_GENERATION/V24917_FIT_SUMMARY.json`, `C01_GENERATION/V24917_TIMING.json`.
- Původní chování HOTFIX2: `generation_mode = HOTFIX2_BACKTRACKING`.
