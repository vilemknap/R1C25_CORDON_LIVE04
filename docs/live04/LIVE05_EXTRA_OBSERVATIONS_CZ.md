# LIVE05 – doplňková pozorování (NDS profily, ASD1–7, křižovatky K1/K2)

Rozhodnutí uživatele 2026-11-15: kalibrace se neřídí jen kordonem, ale i
profily NDS, stanicemi ASD a křižovatkovými průzkumy K1/K2.
Váhy: **kordon 70 % / NDS 15 % / ASD 10 % / K 5 %**. Duplicity jsou vyřazené.

## Co se kalibruje

| skupina | řádků | typ | cíl |
|---|---|---|---|
| NDS | 94 | LINK – objem na směrové hraně | RPDI 2025 vozidla |
| ASD | 12 | LINK – ASD1–7 po směrech (bez ASD4) | RPDI z ASD |
| KMOV | 24 | PAIR – odbočení vjezd → výjezd (K1 + K2 okružní) | 12h průzkum přepočtený na RPDI |

Vyřazené řádky jsou v souboru `data/audited/EXTRA_OBSERVATIONS_LIVE05_PROVENANCE.json` (pole `dropped`):
- ASD4 je totožná s kordonovou stanicí SDP10.
- 2 NDS řádky leží na hraně kordonové stanice.
- 4 NDS řádky leží na hraně ASD nebo K.
- 34 NDS řádků nemá jednoznačné umístění na síti (vzdálenost, víc kandidátů nebo nenalezeno).

K1 vstupuje jen podílem odbočení. Pro každé rameno je celkový příjezd přepočten na RPDI:
- rameno 2: SDP10, koeficient 0,7573;
- rameno 3: SDP14, koeficient 1,4577;
- rameno 4: ASD2, koeficient 0,7073;
- rameno 1: průměr, koeficient 0,9741.

## Jak se to počítá

Řádky jsou přidány k FIRST_LAST pozorováním: `row_id` ≥ 1000, skupiny NDS = 20, ASD = 21, KMOV = 22.

Prediktor (zmrazené cesty) počítá příspěvky takto:
- LINK přičte každý průchod cesty hranou.
- PAIR přičte 1, když cesta projde vjezdovou hranou a později výjezdovou hranou.

Váha řádku skupiny g je `sqrt(podíl_g / 0,70 · W_kordon / n_g)`. Součet čtverců vah skupiny je tedy přesně její podíl na cíli: NDS 0,62, ASD 1,41, K 0,71 na řádek.

GEH stráž (SEVRELAX3) a SupplyMix (výběr pák) zůstávají jen na kordonových řádcích. Doplňková pozorování hýbou jen cílovou funkcí, tedy přijetím a odmítnutím kroků TG/TD.

## Kontroly při běhu

- Na začátku cyklu se ověří, že všech 120 hran doplňkových pozorování v síti existuje a je pro dopravu otevřených. Výsledek se zapíše do `EXTRA_OBSERVATION_LINKS.json`. Když hrana chybí, běh se zastaví před prvním zápisem.
- Soubor pozorování je zamčený přes sha256 v konfiguraci (`observations.extra_observations`).
- `enabled: false` vrátí kalibraci čistě na kordon.

## Postup spuštění

Postup se nemění: READINESS → CYCLE (viz `00_START_HERE_LIVE04_CZ.txt`). Z výsledků prosím pošli:
- `00_RESULT.json` (blok `extra_observations`);
- `EXTRA_OBSERVATION_LINKS.json`.
