# LIVE05.6 – zrychlení běhu (2026-11-15)

Kde se v běhu ztrácí čas (nativní běhy 4.–5. 11.): přepočet modelu trvá asi 1 min, ale čtení uložených
cest z Visumu desítky minut až hodiny. Od té doby už je zapnuté zrychlení 10.2, 10.3, 10.4 a 10.7.
LIVE05.6 přidává další tři kroky.

## 1. Souběžné čtení a zpracování geometrie (`evaluation.pipelined_geometry = true`)

Seznam cest a hran reprezentativního segmentu (~26 mil. řádků na mód) se dosud četl a zpracovával za sebou:
~6–7 min čtení přes COM + ~4 min zpracování v Pythonu. Nově čtení zůstává ve vlákně COM a hotové stránky
zpracovává druhé vlákno stejným kódem a ve stejném pořadí. Úložiště je bit po bitu stejné (testy porovnávají
celé úložiště i chybová hlášení). Odhad: −3 až 4 min na každé zachycení. `false` = původní sériové čtení.

## 2. Čtení jen cest přes pozorované hrany – nejdřív měření

Cesty, které nejdou přes žádnou stanici, profil NDS/ASD ani rameno K1/K2, do cílové funkce nic nedávají.
Visum umí vypsat jen cesty svazku (flow bundle). Zda svazek přes ~150 hran vrátí cesty přes KTEROUKOLI
z nich (NEBO), nebo jen přes všechny (A), a jaký je opravdu zisk, se bez Visumu ověřit nedá. Proto:

`RUN_R1_2025_FLOWBUNDLE_PROBE.py` (5–15 min, síť ani poptávku nemění; nastaví a na konci vyprázdní jen svazek):
změří počet cest a řádků filtrovaného seznamu, dobu čtení proti stejnému počtu řádků celého seznamu
a hlavně důkaz, který by kalibrátor vyžadoval: na každé pozorované hraně se intenzita NATIVE_CW z vybraných
cest musí rovnat `VOLVEH_DSEG`. Výsledek: `%LOCALAPPDATA%\R1C25_BOOT\FLOWBUNDLE_PROBE_<čas>\PROBE.json`.
Teprve podle něj se filtrované čtení zapojí do zachycení (s tímtéž důkazem a návratem k plnému čtení).

## 3. TD se po neúspěchu jeden cyklus přeskočí (`td_cordon.skip_cycles_after_unchanged = 1`)

V obou živých bězích skončil TD_CORDON bez kandidáta (`NO_TD_CANDIDATE`). Stál ~8 min sond a ~14 min opravy
přiřazení. Když TD v cyklu nic nezmění, v dalším cyklu se vynechá (`CYCLE_PROGRESS.json → skipped_blocks`)
a v tom dalším běží znovu. Pravidlo zastavení na TD dál čeká. `0` = TD v každém cyklu jako dřív.
