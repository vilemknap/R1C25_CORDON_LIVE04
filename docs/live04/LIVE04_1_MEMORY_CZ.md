# LIVE04.1 – paměť mezi cykly (2026-10-31)

Do LIVE04 (kordón na v7 @ 977cef4) přibyla paměť mezi cykly. Ovlivňuje **jen predikci a volbu kroku**. O přijetí dál rozhoduje výhradně plný nativní pokus s assignmentem: kordónová brána, sekundární metoda, MOBILITY2/MOBILITYZONE1, LONG, IDP a ověřený rollback. Horší paměť tak může způsobit nanejvýš zbytečný pokus, nikdy špatný přijatý stav.

- **Modul:** `cordon2025/live04_memory.py` (`RunMemory`).
- **Audit:** `MEMORY/RUN_MEMORY.json` a `RUN_MEMORY_TD_J.npz` v běhové složce, aktualizují se po každém bloku.
- **Výsledek běhu:** `00_RESULT.json → memory`.

## 1. TD_CORDON: přenos Jacobiánu
1. Na konci bloku TD se uloží **lokální Jacobián na zmrazených cestách**, tedy z sond o standardní velikosti (`probe_b`, `probe_logc`).
   - Broydenovy sečny z velkých kroků se do něj **nepřenášejí**. Popisují nelinearitu, ne lokální sklon.
   - Změřený plný pokus se do něj také nepřenáší. Obsahuje změnu tras, kterou sondy na zmrazených cestách neuvidí.
2. Další cyklus z něj naplánuje první krok trust-region a **jednou nativní sondou** ověří jeho směr ve velikosti standardní sondy.
3. Rozhodnutí podle relativní chyby předpovědi ‖skutečnost − J·krok‖ / ‖skutečnost‖:
   - pokud je ≤ `td_verify_tolerance` (0,35), Jacobián se použije (+ Broydenova oprava z ověřovací sondy) a **odpadne 6 sond**;
   - jinak se spočítá celý Jacobián jako v LIVE04 (`NATIVE_PROBES_MEMORY_REJECTED`).

Na mocku po neměnném středu: z 10 na 5 nativních vyhodnocení, chyba ověření 0,07.

Po velkém přijatém kroku TD (v mocku b 0,2 → 1,45) se skutečný Jacobián změnil o 70–100 %. Ověření ho tehdy správně odmítne a spočítá nový.

## 2. GENERATION: korekce změny tras
1. Po prvním plném pokusu bloku se uloží korekce `c = (naměřeno − predikce na zmrazených cestách) / škála` pro každý řádek kordónu a obě metody, spolu se směrem kroku (zonální log-kroky + hranice).
2. V dalším cyklu se korekce přičte k predikci jen tehdy, když:
   - je nový směr podobný, tedy kosinus ≥ `tg_min_direction_cosine` (0,5);
   - korekce je starší nanejvýš `max_age_cycles` (2) cyklů.
3. Korekce se:
   - přepočte na normu nového kroku;
   - utlumí vahou `tg_correction_weight · tg_correction_decay^(stáří−1)` (0,5 · 0,5^…).
4. Sečna z pokusu v tomtéž bloku pak opravuje už jen zbytkovou chybu.
5. **Pojistka:** když s pamětí nevyjde žádný zlepšující krok, plán se spočítá bez paměti (`memory_fallback`). Paměť tak nikdy nepotlačí pokus, který by LIVE04 udělal.
6. **Záznam:** pokus ukládá `predicted_objective` (s pamětí) i `predicted_objective_without_memory`.

Na mocku se změnou tras (`route_gamma = 0,5`) klesla chyba predikce v 2. cyklu ze 107 na 56 (váha 0,5).

## 3. GENERATION: počet nativních uzlů
1. Ze dvou uzlů (1,0 a 0,5) se změří zakřivení |n(1) − 2·n(0,5) + m0| / |n(1) − m0|.
2. Je-li ≤ `tg_single_node_curvature` (0,05), sonduje další cyklus jen uzel 1,0. Ušetří tak 2 přepočty poptávky.
3. Na mocku je zakřivení ≈ 0,2, takže se dál sondují oba uzly. Ve Visumu to ukáže první běh.

## 4. Konfigurace (`CORDON_LIVE04_CONFIG.json → memory`)
| Klíč | Výchozí | Význam |
|---|---|---|
| `enabled` | true | false = přesně chování LIVE04 (ověřeno testem) |
| `td_jacobian_reuse` | true | přenos Jacobiánu TD |
| `td_verify_tolerance` | 0,35 | max. relativní chyba ověřovací sondy |
| `tg_route_correction` | true | korekce změny tras v TG |
| `tg_correction_weight` / `tg_correction_decay` | 0,5 / 0,5 | tlumení korekce |
| `tg_min_direction_cosine` | 0,5 | min. podobnost směru kroku |
| `tg_single_node_curvature` | 0,05 | práh pro jeden uzel |
| `max_age_cycles` | 2 | stáří paměti v cyklech |
| `role` | `PREDICTION_AND_STEP_CHOICE_ONLY_NEVER_ACCEPTANCE` | pevné |

## 5. Testy (syntetický mock, nejde o nativní důkaz z PTV)
- Mock má volitelnou **změnu tras**:
  - 240 OD párů stanic má u segmentů módu C druhou cestu přes bypass, který nekříží kordón;
  - assignment dělí OD podle zatížení, sondy bez assignmentu dělení nemění.
- Nové testy:
  - pravidla paměti (stáří, podobnost směru, osy, vypnutí);
  - přenos Jacobiánu TD s ověřením;
  - odmítnutý Jacobián → plné sondy;
  - korekce tras zlepší predikci;
  - `enabled=false` dá stejný výsledek jako LIVE04.
