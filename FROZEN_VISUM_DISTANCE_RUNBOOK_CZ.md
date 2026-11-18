# Zafixování vzdáleností pro další běh LIVE04

Od 18. 11. 2026 postup funguje na libovolné uložené verzi 2025. Na konkrétní
checkpoint není vázaný.

1. Otevřete uloženou verzi `.ver`, ve které jsou přiřazení a skimy `DIS`
   spočtené po poslední úpravě sítě. Skript neumí ověřit, že `DIS` jsou
   aktuální, proto vybírejte verzi uloženou po úplném přepočtu.
2. Spusťte `RUN_R1_2025_FREEZE_VISUM_DISTANCES.py`.
   - Najde šest skimů `DIS` podle segmentu (CODE `DIS` + DSEGCODE), ne podle čísla.
   - Zkontroluje 681 zón, matici 9697, poměry 9231/9233 a to, že žádná buňka
     `DIS` mimo diagonálu nemá hodnotu „bez trasy“.
   - Stejně jako RECOMPUTE ověří, že otevřený soubor je izolovaná kopie (název
     obsahuje LIVE04/KOPIE/COPY/TEST/TRIAL/CALIB, ne 2022). Udělá to ještě před
     zápisem.
   - Odmítne poměry 9231/9233, jejichž vzorec závisí na skimech (krok R1 20D
     s `DT_MODE = 'LIVE'`). Takové poměry by se během kalibrace měnily a
     9726/9727 by k nim přestaly sedět. Musí být `DT_MODE = 'FROZEN'`.
   - Do otevřeného modelu zapíše osm datových matic 9720–9727 a ověří jejich
     zpětné čtení. Matici 9697 nemění a `.ver` neukládá.
   - Pokud matice 9720–9727 už v modelu jsou se stejnými kódy, přepíše je.
     Pokud je číslo obsazené jinou maticí, skončí ještě před zápisem.
   - Výsledek včetně cesty a SHA-256 zdrojové verze a otisků všech matic je v
     `%LOCALAPPDATA%\R1C25_DISTANCE_PREP\FROZEN_DISTANCE_RESULT.json`.
3. Ve **stejném otevřeném Visumu** spusťte
   `RUN_R1_2025_RECOMPUTE_FOR_LIVE04_BASE.py`. Ten přepočte poptávku a
   přiřazení s LONG maskou podle 9721 a uloží nový `*_LIVE04_BASE_*.ver`.
4. Otevřete nový `.ver`, spusťte `RUN_R1_2025_LIVE04_READINESS.py` a po
   výsledku `READY_FOR_LIVE04` spusťte kalibraci.

| Matice | Obsah |
| --- | --- |
| 9720–9725 | `DIS` NATIVE_CF, CL, CS, CS_noT, CW, CW_noT; diagonála z 9697 |
| 9726 | 9724 × RATIO_CW (9231) + 9725 × (1 − RATIO_CW): IDP WORK a SCHOOL |
| 9727 | 9722 × RATIO_CS (9233) + 9723 × (1 − RATIO_CS): IDP SERVICE |
| 9721 | LONG IDP a LONG maska ≥ 80 km |

Kalibrátor při startu ověří existenci, kódy a typ všech osmi matic, platné
hodnoty, diagonálu z 9697, výpočet 9726/9727 z aktuálních poměrů a to, že
vzorce poměrů nezávisí na skimech. Otisky
všech osmi matic, 9697 a pořadí zón uloží do `FROZEN_DISTANCE_AUTHORITY.json`.
Po každém kalibračním bloku a před uložením výsledku ověří, že se nic z toho
nezměnilo. Pokud se změnilo, běh zastaví.

Pokud skript skončí chybou po zápisu (stav `MODEL_MAY_BE_CHANGED_CLOSE_WITHOUT_SAVING`),
zavřete model **bez uložení**.
