# Zafixované vzdálenosti ze skimů Visum (2026-11-17)

Kalibrátor už nepoužívá OSRM 9697 jako vzdálenost. Používá zafixované skimy `DIS`
z uložené, plně přepočtené verze modelu.

## Matice (DATA, stejný typ jako 9697)

| číslo | CODE | obsah |
|---|---|---|
| 9720–9725 | `R1_BASE_DIS_<segment>_KM` | `DIS` segmentů NATIVE_CF, CL, CS, CS_noT, CW, CW_noT |
| 9726 | `R1_BASE_DIS_IDP_WORK_KM` | r·CW + (1−r)·CW_noT, r = 9231 (RATIO_CW) |
| 9727 | `R1_BASE_DIS_IDP_SERV_KM` | r·CS + (1−r)·CS_noT, r = 9233 (RATIO_CS) |

- Diagonála všech matic se bere z 9697, protože `DIS` nemá vnitrozonální vzdálenost
  a 9697 obsahuje schválenou vnitrozonální geometrii AMDY.
- Matice 9697 zůstává v modelu beze změny kvůli dohledatelnosti.

## Použití v kalibrátoru

- **LONG maska ≥ 80 km:** 9721 (NATIVE_CL), viz
  `v7.long_post_td_mask.distance_matrix_no`.
- **IDP guard a krok TD s IDP:** `idp_guard.distance_matrices`
  - WORK* a SCHOOL → 9726;
  - SERV* → 9727;
  - LONG_COMPOSITE → 9721.
- **Utility TD:** beze změny (TTC/TT0).
- **Kontrola při startu:** LIVE04 i RECOMPUTE ověří všechny tři matice (číslo, CODE,
  hodnoty) a výsledek zapíší do `DISTANCE_AUTHORITY.json`. Pokud některá chybí,
  běh se zastaví dřív, než cokoli zapíše.
- **Návrat k OSRM:** v configu nastav `distance_matrix_no` 9697 /
  `R1_OSRM_DIST_KM` a smaž `idp_guard.distance_matrices`.

## Postup

1. Otevři uloženou verzi s přiřazením a skimy spočtenými po poslední úpravě sítě,
   například checkpoint LIVE04 nebo `*_LIVE04_BASE_*.ver`.
2. Spusť `RUN_R1_2025_FREEZE_SKIM_DISTANCES.py`. Skript zapíše matice 9720–9727
   a uloží novou verzi `<název>_DISTFRZ_<id>.ver`.
   - Výsledek najdeš v `%LOCALAPPDATA%\R1C25_DISTANCE_FREEZE\LAST_RESULT.json`.
3. Ve stejném Visumu spusť `RUN_R1_2025_RECOMPUTE_FOR_LIVE04_BASE.py`. Ten přepočte
   model s LONG maskou na 9721 a uloží `*_LIVE04_BASE_*.ver`.
4. Na této verzi spusť kalibrátor LIVE04.

Skript nemůže sám ověřit, že `DIS` vzniklo po poslední úpravě sítě. Spouštěj ho jen
na verzi uložené po úplném přepočtu.
