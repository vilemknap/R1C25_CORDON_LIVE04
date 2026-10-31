# Kordónový kalibrátor LIVE03 – společná kalibrace TG + TD (2026-10-26)

Základ: LIVE02 varianta V24917 (`R1C25_LIVE02V`). LIVE03 do ní přidává tři části, které LIVE02 neměl:

1. kalibraci **tvaru distribuce TD** (gravitační b/c),
2. **schválené vstupy**: sémantiku sčítání, převod roku a C17,
3. **nativní predikci kroku** místo lineární.

LIVE02 zůstává beze změny (vlastní konfigurace, běh i testy). Chráněný zdroj LIVE01 `cordon2025/incidence.py` je bajtově stejný a rozšíření je v novém modulu `live03_incidence.py`.

## 1. Vstupy – rozhodnutí podle Sprievodné správy

| Otázka | Rozhodnutí LIVE03 | Doklad |
|---|---|---|
| Sémantika páru | **FIRST_LAST**: jízda = (první, poslední stanovište) | Správa kap. 6, krok 2–3: pro každou jízdu se uloží první a poslední detekce |
| Cíl pro páry | **Transit RPDI** OA (`OA_Transit_D3_RPDI`, 71 914 jízd) | NonTransit = zastavení v území = v modelu dvě cesty; „pre ďalší prepočet je rozhodujúca tranzitná matica“ |
| C17 | **16 nových pozorování**: průchody stanicí cestami s jedním zásahem kordónu | Správa: okraj matice (izolované + vjazd–výjazd) = 17. zóna, jen v Transit |
| Rok 2026 → 2025 | faktor **1,0** (bez přepočtu) | rozhodnutí uživatele 2026-10-25 |

Model stanice C17 (jednotka: průchod stanicí):

- cesta s jedním průchodem v `s` → 1×,
- cesta, která vjede a vyjede týmž stanovištěm (první = poslední) → 2×.

Cíl stanice C17:

> isolated (riadok C17 + stĺpec C17) + 2 × cyklické (vjazd–výjazd, oba okraje) + konce NonTransit jízd (řádkový a sloupcový součet N)

Celkem jde o 113 734 průchodů. Pro stanici 1 to je 29 638, pro stanici 9 jen 1 132.

**Metody:**

- `FIRST_LAST` je primární: 120 párů + 16 řádků C17 = 136 řádků.
- `EXACT_TWO_HITS` je sekundární a nesmí se zhoršit: 120 párů vůči Transit.
- `ALL_ORDERED_UNIQUE_PAIRS` slouží jen k diagnostice.

**Kde je co:**

- Smlouva vstupů: `live03_observations.Contract`; v každém běhu se zapíše `OBSERVATION_CONTRACT.json`.
- NPZ je připnuté SHA-256 hashem.

**Přepínače v konfiguraci** (`observations`):

- `pair_matrix` = `ALL` – vyžaduje vypnuté `nontransit_endpoints`, jinak by se NonTransit počítaly dvakrát.
- `c17_policy` = `DISABLED`.
- `c17_row_weight` – váha řádků C17.
- `cyclic_crossings_per_trip` = 1 nebo 2.
- `year_bridge.factor`.

## 2. Nativní predikce na zmrazených cestách (místo lineární)

`live03_predictor.FrozenPathPredictor`:

- **Share operátor.** Z capture přijatého stavu se pro všech 12 OA dsegů a všechny OD postaví operátor `share_k = objem cest OD na řádku / q_OD`. Tvoří ho `live03_incidence`, a to pro každou metodu.
- **Kontrola parity.** Před prvním zápisem musí predikce z aktuálních matic přesně reprodukovat capture (`PREDICTOR_BASE_PARITY.json`, tolerance 1e-6). Jinak se běh zastaví.
- **Sonda:**
  1. Zapíšou se parametry kandidáta.
  2. Spustí se jen poptávková část plánu PERF1, tedy operace před prvním schváleným assignmentem. Žádný assignment se nespustí.
  3. Načtou se matice 12 dsegů.
  4. Spočte se `Σ share × Q_new`.
  5. Parametry se vrátí přes COM.

  TG a TD a maticové operace jsou tedy nativní (včetně nelinearit gravity a vyrovnání). Zbývající aproximací je jen volba tras.
- **Neznámá podpora.** OD s novou kladnou poptávkou bez uložené cesty se hlásí jako `unsupported_share`.
- **Obnova poptávky po sondách bez pokusu.** Parametry se obnoví, spustí se tatáž poptávková část a ověří se rovnost snapshotu (`DEMAND_RESTORE_PROOF.json`).

**STEP1 (TG):**

- Uzly se počítají nativně na škálách `tg_node_fractions × ts_max_scale` (výchozí 1,0 a 0,5).
- `CordonStepModel` mezi body (0, m0) a uzly interpoluje po částech lineárně. Za posledním uzlem extrapoluje lineárně.
- Po skutečném pokusu se přičte měřená korekce na volbu tras, škálovaná délkou kroku.
- Donorové `choose_scale` (robustní okraj 0,15, mřížka) se používá beze změny.
- Když nativní predikce nenajde zlepšující krok, plný pokus se nespouští (`NATIVE_PREDICTION_NO_ROBUST_IMPROVING_SCALE`).
- Při `native_prediction.enabled=false` zůstává původní lineární model V24917.

## 3. Blok TD_CORDON (b/c), objective = jen kordón

`live03_td.td_block`:

- **Parametry** (prostor FineCDF v1.9, po rodinách WORK / SERVICE / SCHOOL):
  - `b' = b + db_g`, `c' = c·exp(dl_g)`;
  - meze podle v1.9: `b ∈ [0, max(4, b)]`, `|c| ∈ [min(0,001, |c|), max(8, |c|)]`;
  - trust radius podle v1.9 (0,25 pro b, ln 1,25 pro c).
  - LONG se v kordónovém TD nekalibruje (LONG_COMPOSITE, LSGEN), validace to vynucuje.
- **Jacobián:** jedna nativní sonda na parametr. Parametry bez odezvy na kordónu, např. SCHOOL mimo OA dsegy, zůstanou pevné.
- **Vnitřní krok:** box Levenberg–Marquardt na vážených reziduích cíle J v proměnných škálovaných trust radiusem.
  - Každý krok se ověří nativní sondou a Jacobián se pak opraví Broydenem.
  - Přijme se, jen když se predikovaný kordón zlepší, projde kordónová brána (sekundární metoda se nezhorší) a projde guard IDP.
  - Jinak se trust radius zmenší na polovinu.
- **Guard IDP** (`live03_idp`):
  - Používá nezměněné donorové `Metrics` FineCDF v1.9 (512 uzlů, `reference_v19`, připnutý SHA-256) a jeho měkké tolerance (RMSE CDF +0,01, střední vzdálenost max(|e|, 0,03) + 0,02).
  - Kontroluje se každá komponenta.
  - IDP není objective, jen zabraňuje zhoršení.
  - Když referenci nelze spočítat, TD se nezapíše (`IDP_BASELINE_UNAVAILABLE`).
- **Plný pokus:**
  1. Donor `_apply_candidate` (readback).
  2. PERF1 `TD_TO_ASSIGNMENT`.
  3. Nový plný capture.
  4. Kordónová brána, sdílený ledger a IDP na skutečném výstupu TD.
  5. Kandidát se buď **ponechá na místě**, nebo proběhne donorový `rollback_and_verify` (obnova b/c + přepočet + důkaz diagnostiky).
- Freeze kontrolu (`assert_freeze`) zajišťuje `matrix_scope_by_block.TD_CORDON`.

**Cyklus:** `blocks_per_cycle = [GENERATION, TD_CORDON]`, `max_cycles` = 3. Běh skončí po cyklu bez přijaté změny.

## 4. Bezpečnost zápisů (beze změny principu LIVE02)

- `GuardedCOM` nově povoluje jen `TripDistributionParameters…SetAttValue(<b|c>, číslo)`, a to pouze pokud má `write_policy.td_parameter_writes = true`. `PARA_A`, nečíselné hodnoty a NaN se odmítnou.
- Nikdy se nevolá LoadVersion, nikdy se přímo nezapisuje do OD matic a zdrojový .ver se nepřepisuje.
- Přijatý stav se uloží jako nový `…_LIVE03_ACCEPTED_<id>.ver`.

## 5. Testy (synteticky, nejde o nativní důkaz z PTV)

Mock `tests/fake_live03.py`:

- přidává cesty s jedním průchodem a cyklické cesty,
- přidává odezvu TD (D^Δb · exp(Δc·D), produkčně vázaná),
- obsahuje matici vzdáleností 9697 a matice IDP.

`tests/test_live03.py` (29 testů) pokrývá:

- **Smlouvu vstupů:** součty 71 914 / 113 734, chybné varianty, pin NPZ.
- **Incidenci:** FIRST_LAST a C17 (izolovaná, cyklická, opakovaná stanice), paritu `live03_incidence` s LIVE01 bez nových metod, predikci zmrazeným share operátorem.
- **Model kroku:** interpolaci, extrapolaci a měřenou korekci.
- **Guard zápisů:** povolené b/c, zakázané `PARA_A` a NaN.
- **Validaci konfigurace.**
- **Celý běh:**
  - TG přijato s nativní predikcí (predikce = měření; mock má pevné trasy);
  - TD odmítnuto guardem IDP a poptávka obnovena;
  - TD přijato na místě s uvolněným guardem;
  - TD pokus odmítnut a vrácen;
  - chyba sondy → obnova poptávky → stop s ověřeným stavem;
  - fallback na lineární predikci;
  - TG bez predikovaného zisku → žádný slepý pokus;
  - IDP nedostupné → bez zápisu TD;
  - launcher.

## 6. Omezení a co ověřit v nativním Visumu

- **Volba tras:** predikce je přesná v poptávce, ne v trasách. Rozhoduje vždy plný pokus. V mocku je predikce = měření, ve Visumu ne.
- **Více assignmentů v poptávkové části:** pokud procedura obsahuje před schváleným assignmentem další assignment (typ 100/101), sonda ho přeskočí a hlásí `exact_demand_of_full_trial=false`.
- **Cena bloků:**
  - TD blok: 6 sond + ≤ 4 vnitřní sondy + 1 plný pokus (nebo 1 obnova poptávky);
  - TG blok: 2 sondy + pokusy STEP1.
- **Jednotky C17:** model a cíl se počítají v průchodech. Ověřit, zda okrajové efekty měřicího okna (jízdy na začátku a konci měření) nejsou v modelu systematicky jinak.
- **Rozsah TD:** TD v kordónu mění jen OA WORK/SERVICE (dsegy NATIVE_CW/CS). SCHOOL je bez odezvy na kordónu a zůstane pevný.
