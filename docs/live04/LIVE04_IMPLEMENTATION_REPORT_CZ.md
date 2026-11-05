# Kordónový kalibrátor LIVE04 – port na v7 (2026-10-31)

Základ: LIVE03 (`R1C25_LIVE03`, společná kalibrace TG + TD na kordónu). LIVE04 ji přenáší na profilový kalibrátor **v7**, tedy `vilemknap/R1_15A2_V24917_v7` @ `977cef4e77ab67f159bbe392edc8d3d485dc72ee`. To je verze s P2.5/A4, která teď běží ve Visumu.

Kordónová část se nemění. Platí stejná pozorování (FIRST_LAST + C17, faktor roku 1,0), stejný cíl, nativní predikce na zmrazených cestách, blok TD_CORDON i guard IDP. Mění se všechno, co v7 dělá jinak než V24917 z LIVE03.

## 1. Co se převzalo z v7

| Oblast v7 | V LIVE04 | Kde |
|---|---|---|
| Donorové moduly v7 (20 souborů) | bajtové kopie, SHA-256 připnuté a ověřované při startu | `parent/`, `live04_v7.DONOR_FILES` |
| Run options v7 | připnutý soubor `R1_RUN_OPTIONS.json` z 977cef4, změnit lze jen tři odchylky (kap. 3) | `provenance/v24917_v7/`, `CORDON_LIVE04_CONFIG.json` → `v7` |
| Obálky podle role (TGBOUNDS v2) | P [0,75; 2,5], A [0,75; 4,0], ZAHR [0,5; 10], hranice [0,5; 2] | `tg.patch_multiblock` |
| MOBILITY2 | produkční pás + samostatný plot atrakce W/S; stejné jako obálky, od LIVE04.5 P 0,5–3,15 / A 0,5–5,5 (kap. 7) | návrh, náhled, kontrola před zápisem a po pokusu |
| MOBILITYZONE1 | pevná reference AMDY FP pro každou zónu a účel, oříznutí mezí fitu, kontrola zastaralého rodiče před zápisem | `live04_generation`, `live04_adapter` |
| BDPA1 | hraniční P/A v rebalancu a v bráně | `bdpa.install` + `bdpa.scope` |
| Zonální fit | `nonlinear_pa_repair=True`, `boundary_reference_multiplier` | `live04_generation.fit_with_boundary` |
| GENFIX2 STEP1 | viz níže | `live04_step1.py` |
| LSGEN | SCHOOL TG je pevné (AMDY), LONG TG je odloženo | kap. 3 |
| LONG post-TD maska | každý nativní přepočet včetně sond bez assignmentu | kap. 2 |
| COMBUSY2, PERF3 | jako v LIVE03 (budget floor, message filter, opakování bloku) | `live04_v7.runtime_scope` |

**GENFIX2 STEP1:**

- Pro každou škálu se predikuje *finální* kandidát. Jsou to řádky po bounds, maskách, rebalancu P/A a mzdě, plus hraniční kroky, a to pro obě kordónové metody.
- Brána před zápisem obsahuje i finální obálku MOBILITY2 a MOBILITYZONE1. Donorové `choose_scale` ji čte přes `model.final_prediction(s)`.
- Pokud brána neprojde, krok se ×0,75 zmenší ještě před zápisem.
- `GENERATION_GATE` při apply proběhne ještě před prvním zápisem zón. Parametry se pak vrátí, ověří se rodič a zkusí se menší krok.
- Plánované řádky se převezmou do vlastnictví *před* prvním zápisem COM. Částečný zápis i každý výjimečný konec (včetně stopu) tak končí ověřeným rollbackem.
- Stacionarita se potvrdí, jen když fit konvergoval, proběhl celý nakonfigurovaný reálný search, všechny pokusy byly odmítnuty a MOBILITYZONE1 je bez odkladu.

**Moduly:**

- Nové: `live04_v7.py`, `live04_guard.py`, `live04_long_mask.py`, `live04_generation.py`, `live04_adapter.py`, `live04_step1.py`, `live04_config.py`, `live04_cycle.py`.
- Vstupní body: `cordon_live04_bootstrap.py`, `RUN_R1_2025_CORDON_LIVE04_V7_TG_TD_CYCLE.py`.

## 2. LONG post-TD maska (≥ 80 km na R1_OSRM_DIST_KM 9697)

v7 po TD násobí LONG osobní matice 9111–9115 maskou podpory. Před assignmentem pak totéž udělá s vozidlovými komponentami 9291–9295 a ověří agregát 9305 typu FORMULA. Objem se ztrácí a nic se nerenormalizuje, jak uživatel schválil.

**9305 je v R1 přímo OD maticí dsegu NATIVE_CL.** Maska tedy přímo mění to, co kordón vidí na cestách NATIVE_CL. Kordónový kalibrátor proto musí počítat stejnou poptávku jako v7:

- **Plné přepočty** (pokus, rollback, obnova) jdou přes nezměněnou donorovou `execute_sequence`. Postup:
  1. Hook na `runtime_v1.execute_procseq` se instaluje jen po dobu jednoho běhu a pak se vrátí.
  2. Fáze jsou THROUGH_TD → maska osob → REALIZATION → maska vozidel → ASSIGNMENT_SKIMS.
  3. Operace 17–19 se dočasně aktivují (ACTIVE se pak obnoví) a 20 zůstává jedinou autoritou.
  4. Patch FineCDF bridge se neinstaluje, protože kordónové TD ho nepoužívá.
- **Sondy bez assignmentu** (nativní predikce) donorová sekvence záměrně odmítá. LIVE04 má proto `execute_demand_only`:
  - stejné fáze THROUGH_TD a REALIZATION,
  - stejné donorové zápisy `apply_group` (validace celého plánu, readback, obnova při chybě, FORMULA se nikdy nezapisuje),
  - na konci `_verify_support`.
- **Baseline** musí být už maskovaná (`require_masked_baseline`). Platí to pro osoby i vozidla. Jinak by se první pokus srovnával se stavem, který v7 nikdy nevytvoří. Běh se zastaví ještě před prvním zápisem (`LIVE04_BASELINE_LONG_SUPPORT_NOT_MASKED`).
- **Brána každého pokusu** (GENERATION i TD_CORDON):
  - podpora LONG musí být čistá,
  - LONGGUARD1 (`decide`, `changed_long=False`) nesmí najít nové jízdy pod 80 km vůči poslednímu přijatému stavu.
- **Konec běhu:** audit podpory a SHA-256 matic LONG se musí přesně shodovat s posledním přijatým stavem.
- **Zápisy:** `GuardedCOM` povoluje navíc jen `SetValues(<2-D float64 numpy>, False)` na 9111–9115 a 9291–9295. 9305, 9116, všechny OD matice dsegů a ostatní matice zůstávají zakázané. Audit je počítá zvlášť (`long_mask_matrix_writes`), `direct_od_matrix_writes` zůstává 0.

## 3. Co se z v7 nepřeneslo a proč

| v7 | LIVE04 | Důvod |
|---|---|---|
| `long_generation_enabled = true` (zonální LONG TG z LONG cache) | `false` | Potřebuje profilovou LONG incidenci (`long_cache`, LONG cesty profilů). Na kordónu takový zdroj není. v7 bez ní LONG také odkládá (`defer_long`). |
| `long_composite_td_enabled = true` | `false` | LONG TD kalibruje profilový/FineCDF běh. Kordónové TD má LONG mimo rozsah (validace to vynucuje). |
| `fa_enabled = true` | `false` | STEP1 používá vždy plný assignment, v7 STEP1 také. |
| Rodičovský návrh FISTA + FlowBundle a maska FlowBundle | nepoužito | Pravidlo LIVE03: jediný návrh je zonální fit na 136 pozorováních. Maska FlowBundle je v politice v7 vypnutá (faktor 1,0); kdyby se zapnula, LIVE04 se zastaví (`LIVE04_FLOWBUNDLE_MASK_NOT_PORTED_TO_CORDON`). |
| `lsgen.design` → `guard_ls` → `defer_long` | návrh LS se nevolá | Ve v7 vychází z guardů nulové kroky SCHOOL a LONG. LIVE04 tedy rovnou nic nezapisuje. Atributy LS zůstávají ve snapshotu, rollbacku i MOBILITYZONE1. |
| LONGGUARD1 přes dynamické skimy a 512bodovou FineCDF | `measure` + `decide` na pevné 9697 | Kordón nemá epochu dynamických skimů profilového běhu. LONG se nemění, takže podle v7 stačí kontrola nových krátkých jízd. |
| `parent_equivalence.verify_parent` (12D/11D) | kordónový hash diagnostiky | Kordónová autorita je kordónová diagnostika, ne 12D/11D. |

**Změněná sémantika proti LIVE03 (záměrně):**

- Po každé nativní sondě TG se poptávka přepočte s rodičovskými parametry a dokáže se přesná rovnost snapshotu (`restore_each`). Je to o jeden přepočet poptávky na uzel navíc.
- Důvod: MOBILITYZONE1 před zápisem vyžaduje nezměněné FP_* rodiče. FP_* jsou výstupy TG, takže po sondě by jinak zůstaly ve stavu sondy.

- Po odmítnutém pokusu GENERATION se parametry rodiče vrátí přes COM, ale výstupy TG (FP_*) zůstanou ve stavu pokusu až do dalšího přepočtu. Kontrola zastaralého rodiče MOBILITYZONE1 před dalším pokusem proto v této situaci porovnává jen koeficienty (`tg_outputs_from_rejected_trial`). Jinak by každý další pokus v bloku spadl na `MOBILITYZONE1_STALE_PARENT` (oprava 2026-10-31, test `test_rejected_generation_trial_then_second_trial_runs`).

**Úpravy sdíleného kódu LIVE03** (zpětně kompatibilní, LIVE03 je nevolá):

- `live03_predictor.run_demand` použije `adapter.execute_demand_only`, pokud ho adaptér má.
- `probe_generation_nodes` přečte finální obálku mobility z náhledu a má parametr `restore_each`.
- `live03_config.validate_config` je rozdělená, aby LIVE04 mohla znovu použít `validate_sections`.

## 4. Stav LIVE02-V24917 a LIVE03 v tomto stromu

`parent/` teď obsahuje donory v7. Vstupní body LIVE02 (režim V24917) a LIVE03 kontrolují své staré piny donorů, a proto se **zastaví před prvním zápisem** (`V24917_DONOR_FILE_CHANGED`). Je to záměr, ne chyba.

- Pro LIVE03 použij jeho vlastní release ZIP.
- Odpovídající cyklové testy jsou v tomto stromu označené `SUPERSEDED_IN_LIVE04_TREE`.
- Jednotkové testy kontraktu, incidence a modelu kroku běží dál.

## 5. Testy (synteticky, nejde o nativní důkaz z PTV)

Mock `tests/fake_live04.py` rozšiřuje LIVE03:

- **9697** je kód `R1_OSRM_DIST_KM`. Cesty kordónu jsou střídavě 120 a 30 km.
- **TD** dává nemaskovaný LONG.
- **20B** vytváří vozidlové komponenty a k nim malý „opravený reverzní“ únik na krátkých buňkách.
- **9305** je FORMULA = Σ 9291–9295 a zároveň OD matice NATIVE_CL.
- **TG** realizuje FP_* jako pevné jednotky × ADD_PROD.

`tests/test_live04.py` pokrývá:

- piny a politiku v7 (odchylky včetně obálek P 0,5–3,15 / A 0,5–5,5, drift, zdroj);
- guard zápisů (jen matice masky, numpy float64, Add=False);
- obnovu všech globálů po běhu;
- rozhodnutí LONGGUARD1;
- celý cyklus:
  - plán masky v pokusu i v sondách, nic pod 80 km,
  - přijatá GENERATION, kde predikce = měření,
  - MOBILITY2 a MOBILITYZONE1 live,
  - přijaté TD s branou LONG;
- odmítnutí pokusu TD branou LONG s ověřeným rollbackem;
- nemaskovanou baseline (stop před zápisem);
- chybu dat mobility (stop před zápisem);
- chybu zápisu masky (donorová obnova, obnova poptávky, ověřený stop);
- druhý pokus GENERATION po odmítnutém prvním (nativní i lineární/sečnová predikce);
- opakování bloku COMBUSY2 po odmítnutém volání COM uvnitř maskovaného pokusu;
- dva cykly za sebou (kotva MOBILITYZONE1, audit LONG);
- lineární predikci GENFIX2;
- LONG/SCHOOL pevné nebo odložené;
- společný fit s hranicí (BNDGEN + BDPA1);
- launcher a obnovu importů.

Výsledky regrese jsou v `LIVE04_TEST_RESULTS.txt`.

## 6. Co ověřit v nativním Visumu (před prvním ostrým během)

1. **Baseline:** kopie verze uložené během v7 musí mít LONG maskovaný. `LONG_SUPPORT_BASELINE.json` musí mít `support_clean = true`. Pokud ne, běh se zastaví sám a bez zápisu.
2. **Operace 17–19:** musí existovat s DSEGSET podle v7. Kontroluje to donorová sekvence (`LONGMASK_PARTIAL_ASSIGNMENT_DEFINITION_MISMATCH`).
3. **Typy matic:** 9291–9295 musí být DATA a 9305 FORMULA. Donor to čte z `DATASOURCETYPE` a na FORMULA se zastaví.
4. **Délka:** sonda TG teď stojí dva přepočty poptávky na uzel, tedy čtyři na blok.
5. **Oddělený Visum:** LIVE04 a běžící profilová kalibrace v7 nesmí běžet ve stejné instanci. Bootstrap hlídá kolizi modulů `r1_15a2_*` z jiné složky.

## 7. LIVE04.3 – širší obálky domácích koeficientů W/S (rozhodnutí 2026-11-01)
| | v7 (profilová kalibrace) | LIVE04.3 (kordón) |
|---|---|---|
| ADD_PROD_W/S | 0,75–2,5 | **0,5–3,0** |
| ADD_ATT_W/S | 0,75–4,0 | **0,5–5,0** |

Změna se musí projevit na čtyřech místech najednou. Jinak by nejužší z nich obálku tiše ořízlo:
1. **Obálky politiky TG** (`domestic_hard_by_role`, `refine_domestic_soft_by_role`) v `live04_v7.targeted_policy` ze `v7.coefficient_envelope`.
2. **Produkční pás MOBILITY2/MOBILITYZONE1** pro W/S: `run_options.mg_min_ratio = 0,5`, `mg_max_ratio = 3,0`. Obě hodnoty jsou deklarované odchylky od pinu v7. Pás SCHOOL je min(3,0; 2,0) = 0,5–2,0 a LONG zůstává 0,5–1,5.
3. **Plot atrakce W/S** `ws_attraction_coefficient_band = [0,5; 5,0]`.
4. **Konstanta donoru `ATTRACTION_BAND`.** Donor ji porovnává s plotem, a proto se na dobu jednoho běhu nastaví na stejnou hodnotu a po běhu se vrátí.

Validace konfigurace vynucuje PROD = pás mobility a ATT = plot atrakce. Krok na cyklus se nemění (CATCH_UP +50 %/−20 %, REFINE +25 %/−20 %).

Test `test_wider_domestic_envelope_reaches_the_model` ověří na mocku, že přijatý stav přesáhne 3,0 a 5,0 a nepřekročí 3,15 a 5,5.

### LIVE04.5 – horní meze W/S 3,15 / 5,5 (rozhodnutí 2026-11-03)
| | v7 @ 7b4c681 | LIVE04.3–04.4 | LIVE04.5 (kordón) |
|---|---|---|---|
| ADD_PROD_W/S | 0,5–3,0 | 0,5–3,0 | **0,5–3,15** |
| ADD_ATT_W/S | 0,5–5,0 | 0,5–5,0 | **0,5–5,5** |

Stejná čtyři místa jako výše. `mg_max_ratio = 3,15` je znovu deklarovaná odchylka kordonu od pinu v7 (`CORDON_DEVIATIONS`, `cordon_deviations`); `mg_min_ratio` zůstává 0,5 podle v7. SCHOOL (0,5–2,0), LONG (0,5–1,5) a ZAHR (0,5–10) se nemění. Ve vstupní zónové tabulce 2026-11-03 bylo na staré mezi 3,0 u ADD_PROD_W 261 zón a u ADD_PROD_S 236 zón; ADD_ATT_S mělo 181 zón ≥ 4,95, ADD_ATT_W max 4,71.

**Pozor:** profilová kalibrace v7 má dál 0,75–2,5 / 0,75–4,0. Pokud by se na kordónem kalibrovaný stav pustila v7, koeficienty mimo její obálku smí jen vracet dovnitř.

## 8. LIVE04.4 – přechod na v7 @ 7b4c681 (rozhodnutí 2026-11-01)
Uživatel chtěl do kordonového kalibrátoru převést z profilového kalibrátoru změny SupplyMix, trip generation, GEH limitů a severity. Upřesnil, že:
- SupplyMix se přidá jako nový blok řízený kordonovými řádky;
- limity SEVRELAX3 platí na kordonové řádky.

Co se změnilo:
- Donory v `parent/` jsou zkopírované z 7b4c681 (8 změněných a nový `r1_15a2_supply_mix_v24917.py`) a nově pinované.
- Run options jsou pinované z 7b4c681. Odchylky `mg_min_ratio` a `mg_max_ratio` odpadly, protože v7 má stejné pásmo P 0,5–3 / A 0,5–5.
- TG: bez CATCH_UP, ±5 %, měřený zónový refit a `STEP1_PRED_AUDIT.json`.
- Nový blok SupplyMix (`cordon2025/live04_supply.py`).
- SEVRELAX3 na kordonových řádcích (`cordon2025/live04_severity.py`, `cordon2025/live04_evaluation.py`).
- Nové oprávnění guardu: `Link.SetAttValue('ADDVAL1', …)`.

Podrobně: `docs/live04/LIVE04_4_V7_7B4C681_CZ.md`.


## LIVE04.5.1 – predikce na zmrazených cestách ukotvená na zachycených řádcích (2026-11-03)
První živý běh LIVE04.5 se zastavil před prvním zápisem: `LIVE03_PREDICTOR_BASE_PARITY_FAIL` (FIRST_LAST max 0,59 %, EXACT_TWO_HITS 0,36 %). Model zůstal ověřeně ve výchozím stavu.

Příčina: Visum ukládá objemy cest na mřížce 0,001, matice OD mají plnou přesnost. Podíl × matice rodiče proto není bitově shodný se zachycenými řádky; tolerance 1e-6 (s podlahou 1 vozidlo) platila jen pro mock, kde jsou objemy cest přesné.

Oprava (`cordon2025/live03_predictor.py`): predikce = zachycené řádky + F(Q_kandidát) − F(Q_rodič). Rodič se reprodukuje přesně (tolerance 1e-6 zůstává), kandidát nese jen změnu nativní poptávky. Surová odchylka F(Q_rodič) − zachycené řádky se zapisuje do `PREDICTOR_BASE_PARITY.json` a je omezená pojistkou (řádek ≤ 5 % s podlahou 10 vozidel, součet metody ≤ 0,25 %); větší odchylka znamená, že cesty nepatří k maticím, a běh se zastaví (`LIVE03_PREDICTOR_RAW_SHARE_DEVIATION_TOO_LARGE`). Platí pro TG uzly STEP1 i pro TD_CORDON. Přijetí kroku se nemění: rozhoduje vždy změřený plný pokus. Testy `tests/test_live04_5.py`.

## LIVE04.5.2 – audit numerických tolerancí a přesných hash kontrol (2026-11-03)
Prošel jsem všechny kontroly na živé cestě LIVE04 (cycle, step1, TD, SupplyMix, adaptéry, capture, predikce, LONG maska, transfer). Rozdělení:

**Ponecháno přesné – na živém Visumu ověřeno nebo jde jen o čtení:**
- snapshot po obnově parametrů a přepočtu poptávky (parametry + všechny matice bitově): živý běh 2026-11-03 po chybě obnovil poptávku a `FAILURE_STATE_READBACK` se shodoval; demand je deterministický, tolerance by jen skryla chybu;
- `assert_freeze` (zapsané hodnoty zón/TD/ADDVAL1 = readback), zápis masky LONG (`array_equal` readback prošel živě), shoda matic mezi preflightem a capture, topologie sítě, observace, integrita souborů a balíčku;
- `ADOPTION_NOT_REPRODUCIBLE` se v LIVE04 nepoužívá (přijetí „in place", bez opakovaného nasazení).

**Upraveno:**
1. *Predikce na zmrazených cestách* (LIVE04.5.1): ukotvení na zachycených řádcích, viz výše.
2. *Ověření rollbacku.* Po rollbacku musí snapshot (parametry + matice) sedět přesně. Pokud se liší jen podpis uložených cest (přidělení není bitově opakovatelné nebo mřížka 0,001), udělá se jedno plné zachycení a kordonové řádky se porovnají s tolerancí: |Δ| ≤ 1 vozidlo + 0,1 % na řádek a cíl ≤ 0,1 %. Při shodě se pokračuje s rodičovskou diagnostikou, prokázaný podpis se pamatuje pro daný stav (další rollback do téhož stavu už nezachytává znovu). Mimo toleranci se běh zastaví jako dosud (`INPLACE_ROLLBACK_DIAGNOSTICS_DIFFER`) a zachycení se nepořizuje dvakrát. Rozdíl ve snapshotu tolerancí nikdy neprojde. Soubor `ROLLBACK_DIAGNOSTIC_REUSE_PROOF.json`.
3. *Gap přidělení nad limitem v pokusu* (`ASSIGNMENT_NOT_TIGHT`, limit 0,005): u Generation je to zamítnutý pokus (ověřený rollback, pak poloviční krok), u TD zamítnutý pokus bloku. Dřív to zastavilo celý běh. Pokud není těsný přepočet rodiče při rollbacku, běh se zastaví (to je skutečná chyba).
4. *Nedostupná predikce* (`LIVE03_PREDICTOR_*`, vzniká před jakýmkoli zápisem): Generation pokračuje s predikcí GENFIX2 (o přijetí rozhoduje měřený pokus), TD blok se v daném cyklu přeskočí (`NO_TD_CANDIDATE / PREDICTOR_UNAVAILABLE`). Dřív stop běhu.
5. *Uložení postupu při zastavení:* když se běh zastaví (STOP_REQUESTED, chyba bloku) a model je ověřeně v posledním přijatém stavu a byl přijat aspoň jeden krok, uloží se nová verze `…_LIVE04_ACCEPTED_….ver` do složky běhu (`saved_version_at_stop` v `00_RESULT.json`). Zdrojová verze se nemění.

Testy: `tests/test_live04_5.py` (mock, ne nativní Visum).

## LIVE04.5.3 – tichý běh bez dialogů (2026-11-03)
Spouštěče `RUN_R1_2025_CORDON_LIVE04_V7_TG_TD_CYCLE.py` i `RUN_R1_2025_*` TRANSFER2025 (RECOMPUTE/READINESS/…) běží v `cordon_visum_silent.py`:
- varování procedur Visumu: uživatelská předvolba `SuppressWarningsDuringProcExec` = 1 a `SaveWarningsToErrorFile` = 1 (zápis ověřený readbackem), soubor zpráv Visumu přesměrován do boot složky (`VISUM_MESSAGES.txt`); po běhu (i po chybě) se vše vrátí přesně na původní hodnoty – stejný mechanismus jako dřívější tiché TD skripty (`parent/reference_v19`);
- výstup Pythonu (`print`, stderr, `warnings`) jde do `PYTHON_CONSOLE.log` v boot složce, spouštěč nic netiskne; výsledek je v `00_LIVE04_BOOT_RESULT.json` / `00_TRANSFER_BOOT_RESULT.json` a v `00_RESULT.json` běhu;
- stav je v `SILENT_MODE.json` (boot složka `%LOCALAPPDATA%\R1C25_BOOT\<id>\`). Pokud předvolba v dané verzi Visumu přes COM dostupná není (`NOT_ACCESSIBLE`), běh pokračuje a je třeba ji zapnout ručně: Úpravy > Uživatelská nastavení > Uživatelské rozhraní > Varování > Potlačit výstup varování během provádění procedur.
Kritické chybové dialogy Visumu tato předvolba nepotlačí a nic se automaticky neodklikává (žádné SendKeys).

## LIVE04.6 – rychlejší zachycení pokusů (2026-11-04)
Živý běh 2026-11-04: jedno zachycení kordonové diagnostiky trvalo ~66 min (`V24917_TIMING`: 2 volání, 7981 s), přepočet přidělení 43 s. Zachycení tedy tvoří ~98 % času pokusu. Nejdražší část je čtení hierarchie cest a hran (`CreatePrTPathLinkList`, ~31 mil. řádků na DSeg): pro každý mód se čte reprezentativní DSeg a s `full_geometry_check` ještě každý další DSeg téhož módu kvůli důkazu shodné geometrie – 12 čtení geometrie na zachycení.

Změna (`cordon2025/live04_capture.py`, overlay; chráněný `visum_startup.py` LIVE01 zůstává bajtově beze změny):
1. **Důkaz geometrie v pokusech přes hrany stanic.** Pro STEP1_TRIAL / AFTER / ROLLBACK (`evaluation.trial_geometry_proof = STATION_LINK_VOLUME_CROSSCHECK`) se geometrie čte jen pro reprezentativní DSeg každého módu (2 čtení místo 12). Ostatní DSegy téhož módu mají už teď vynucenou přesně shodnou množinu klíčů cest (`FULL_PARENT_KEYS_DIFFER`); navíc se pro každý z 12 DSegů porovná objem Visumu `VOLVEH_DSEG(<kód>,AP)` na všech 32 hranách stanic s objemem odvozeným z reprezentativní geometrie a objemů cest daného DSegu (tolerance 1 vozidlo + 0,1 %). Kontroluje se i reprezentativní DSeg (ověří jednotky). Při jakékoli neshodě nebo nečitelném atributu proběhne ve stejném zachycení původní plný důkaz (selže-li, běh selže jako dřív). Výsledek `GEOMETRY_CROSSCHECK.json`, `SNAPSHOT_EVIDENCE.json` → `geometry_identity_basis`.
2. **BASELINE na začátku každého běhu dokazuje geometrii vždy plně** (vynuceno v `CordonEvaluator.evaluate`).
3. **Podpis objemů cest bez třetího čtení.** `FINAL_PATH_READBACK` uvnitř zachycení počítá přesně týž digest (pořadí řádků COM, součet) jako `path_volume_signature`; evaluátor ho převezme a nečte 12 seznamů cest potřetí. Rollback dál čte podpis živě a porovnává ho se stejným protokolem.
4. **Měření:** `CAPTURE_TIMING.json` v každé složce zachycení (rodiče+matice, geometrie reprezentanta, křížová kontrola, plný důkaz, závěrečné čtení).

Odhad: 12 → 2 čtení geometrie a 36 → 24 čtení seznamů cest na pokus; skutečné zrychlení ukáže `CAPTURE_TIMING.json` z prvního živého běhu (testy jsou jen na mocku). Testy `tests/test_live04_6.py`.

## LIVE04.7 – epocha geometrie cest pro pokusy (2026-11-04)
Kordonová obdoba epoch cest profilového kalibrátoru v7 (V2.4.7), `cordon2025/live04_epoch.py`, konfigurace `evaluation.geometry_epoch` (`enabled: true`, `max_reuse: 3`).

Každé zachycení, které čte geometrii z Visumu, uloží sekvence hran cest do `GEOMETRY_EPOCH/epoch.sqlite` ve složce běhu. Další zachycení pokusu (STEP1_TRIAL/AFTER/ROLLBACK) geometrii pro mód z Visumu nečte, ale přehraje ji z epochy, jen pokud platí všechno:
- stejný hash sítě a slovník hran;
- přesně stejná množina klíčů cest (orig, dest, PathIndex) módu jako v epoše;
- pro **každý** DSeg módu (i reprezentativní) a **každou hranu sítě** sedí objem Visumu `VOLVEH_DSEG(<kód>,AP)` s objemem spočteným ze sekvencí epochy a **aktuálních** objemů cest (tolerance 1 voz. + 0,0005 na kladnou cestu na hraně – mřížka 0,001 – + 0,1 %);
- epocha nebyla pro mód použita 3× za sebou (pak se geometrie znovu čte z Visumu).

Jinak se geometrie čte z Visumu jako v LIVE04.6. Přehrané řádky procházejí nezměněným donorovým parserem (souvislost, existence hran v síti, pokrytí všech cest). BASELINE nikdy nepřehrává. O přijetí kandidáta dál rozhoduje čerstvé nativní přidělení a čerstvě přečtené objemy cest; z epochy se bere jen to, kudy cesty vedou.

Zbývající riziko: shoda objemů na všech hranách nedokazuje matematicky stejné pořadí hran u každé jednotlivé cesty (prakticky by šlo jen o výměnu tras mezi cestami se stejnými objemy na každé hraně). Proto omezení `max_reuse` a plné čtení na začátku každého běhu. Výsledky: `GEOMETRY_EPOCH_CHECK.json` v každé složce zachycení, `GEOMETRY_EPOCH/EPOCH.json`, `SNAPSHOT_EVIDENCE.json` → `geometry_epoch`, časy v `CAPTURE_TIMING.json`.

TD (v7 td-perf): rychlejší FineCDF v7 se týká jejího vlastního TD jádra (FineCDF gapfix, skimy, souřadnicové hledání). Kordonový TD používá referenční FineCDF v1.9, který už má předpočítanou mřížku a vektorizovaný výpočet; čas TD tvoří hlavně přepočet poptávky ve Visumu a čtení matic. Port proto nepřinese měřitelné zrychlení a neprovádí se.

## LIVE04.7.1 – přijetí kandidáta jen na plném zachycení (2026-11-04)
Připomínka uživatele: shoda intenzit `VOLVEH_DSEG` (na 32 hranách stanic, ale ani na všech hranách sítě) nedokazuje shodu tras ani matice FIRST_LAST. Protipříklad: cesty 1→2 a 3→4 dávají při sdílené střední hraně stejné intenzity na všech hranách jako 1→4 a 3→2, ale jinou kordonovou matici. Intenzity na hranách obecně neurčují rozklad do cest.

Pravidlo: **zrychlené zachycení (LIVE04.6 křížová kontrola, LIVE04.7 epocha) smí kandidáta jen zamítnout nebo řídit hledání, nikdy přijmout.** Když blok (Generation, TD_CORDON, SupplyMix) na zrychleném zachycení rozhodne „přijmout", proběhne nad stejným stavem přidělení nezávislé plné zachycení (`ACCEPTANCE_CONFIRM`): celá hierarchie cest a hran všech 12 DSegů přečtená z Visumu, bez epochy, s plným důkazem shody v módu. Rozhodnutí o přijetí se pak vyhodnotí **znovu celé na plném zachycení** (brána, sdílený cíl, IDP pojistka u TD). Zrychlené řádky se jen porovnají a zapíšou (`ACCEPTANCE_CONFIRM.json`: shoda řádků, rozhodnutí fast/full, `decision_basis: FULL_CAPTURE`). Přijatý stav i jeho úložiště cest (pro SupplyMix, epochu a další cyklus) pochází vždy z plného zachycení. ROLLBACK a AFTER zachycení jsou vždy plná. BASELINE je vždy plný.

Důkaz v regresi (`tests/test_live04_7.py`, mock):
- protipříklad A/B postavený přesně podle připomínky (stanice 2,4,7,9 se sdílenou hranou): křížová kontrola LIVE04.6 i epocha LIVE04.7 na něm **projdou** (slabina potvrzena), FIRST_LAST z přehrané geometrie (2→4, 7→9) se liší od skutečné (2→9, 7→4); plný důkaz neshodu odhalí;
- `confirm_before_accept`: matice ze zrychleného zachycení, která by byla přijata, je na plném zachycení zamítnuta (`REJECTED_ON_FULL_CAPTURE`); správná je potvrzena a stav se převezme z plného zachycení;
- celý mock cyklus: brána nastavená tak, že na každém zrychleném zachycení říká ANO a na plném NE → nepřijme se nic; v běžném cyklu má každé přijaté rozhodnutí `decision_basis = FULL_CAPTURE`;
- statická kontrola, že všechna tři místa přijetí vedou přes `confirm_before_accept`.

Cena: přijatý pokus stojí jedno rychlé + jedno plné zachycení; zamítnuté pokusy (většina) zůstávají rychlé.

## LIVE04.8 – checkpointy .ver a navázání na předchozí běh (2026-11-04)

Dosud se `.ver` ukládala jen na konci běhu nebo při ověřeném zastavení; pád Visumu znamenal ztrátu
všech přijatých stavů a nebylo možné rozumně navázat (nový běh by ukotvil meze v už upraveném stavu).

- **Checkpoint.** Po každém bloku, který přijal změnu, se nový snapshot porovná s přijatým stavem a model
  se uloží jako NOVÝ soubor `<běh>/CHECKPOINTS/<základ>_LIVE04_CKPT_C<cyklus>_<blok>_<hash8>.ver` se
  sidecarem `<…>.CHECKPOINT.json` (sha256 souboru, hash stavu i jeho složek, pozice dalšího bloku).
  Drží se posledních `checkpoint.keep_last` (výchozí 2); mažou se jen vlastní checkpointy běhu.
  Zdrojová `.ver` se nikdy nezapisuje (kontrola sha256 před/po). SaveVersion přesune ve Visumu ukazatel
  aktuální verze na checkpoint; evaluátor tento ukazatel povolí jen pro checkpointy uložené tímto během.
- **Navázání** (`RUN_R1_2025_CORDON_LIVE04_CONTINUE.py`): otevřená `.ver` musí být checkpoint nebo
  `SAVED_ACCEPTED_VERSION` běhu LIVE04 a musí mít stejný sha256 jako při uložení. U checkpointu se navíc
  vyžaduje přesná shoda hashů ADDVAL1, koeficientů TG a parametrů TD. Převezmou se kotvy PŮVODNÍHO běhu
  (`RUN_ANCHORS.json`, u starších běhů z `RESTORE_POINT.json`): reference koeficientů pro znaménkové
  zpřesnění / obálky ZAHR a startovní ADDVAL1 pro kumulativní meze SupplyMix. Číslování cyklů a parita
  SupplyMix pokračují; běh začne přerušeným blokem (z `CYCLE_PROGRESS.json` nebo ze sidecaru).
  Nový běh má vlastní BASELINE zachycení; rozhodování je stejné jako v novém běhu. Paměť běhu (TD Jacobián)
  a stav krokového hledání začínají znovu.
- Testy: `tests/test_live04_8.py` (10) – checkpoint, navázání dalším cyklem s kotvami původního běhu,
  navázání z checkpointu i z uložení při zastavení uprostřed cyklu, odmítnutí změněného / cizího souboru,
  vypnutí checkpointu, pozice skutečného běhu 852bbf8fbea2 (C02 → SUPPLY_ADDVAL1). Jen syntetický mock.

## LIVE04.8.1 – přidělení po sondách predictoru, navázání podle přijatého stavu (2026-11-04)

- **Chyba (živý běh 852bbf8fbea2):** poptávková část posloupnosti procedur, kterou pouští predictor na
  zmrazených cestách (sondy TG/TD a jejich obnova), obsahuje operace 1 a 15 „reset PrT assignment results“,
  ale ne přidělení. Každá sonda tak ve Visumu smaže uložené cesty. Když blok skončil jen sondami
  (TD `NO_TD_CANDIDATE`) nebo se zastavil v návrhu, zůstal model bez cest; další start skončil
  `NO_SAVED_PRT_PATHS_FOR_POSITIVE_DEMAND` a uložená `.ver` by neměla cesty.
- **Oprava:** adaptér si po poptávkovém běhu nastaví `assignment_invalidated`; plný přepočet ho zruší.
  Na konci každého bloku (před checkpointem) a při zastavení (před uložením, se zastavením odloženým)
  se při nezměněných přijatých parametrech spustí plný nativní přepočet a ověří se snapshot a podpis
  cest (`ASSIGNMENT_REPAIR.json`, při neshodě plné zachycení s tolerancí řádků). Bez ověřeného přidělení
  se `.ver` při zastavení neuloží (`assignment_repair_at_stop` v `00_RESULT.json`).
- **Navázání podle stavu:** otevřená `.ver`, kterou neuložil LIVE04 (ruční uložení + RECOMPUTE), se
  přiřadí k předchozímu běhu ve stejné výstupní složce, jehož `CYCLE_PROGRESS.accepted_state_hash` je
  přesně hash otevřeného modelu (a má aspoň 1 přijatý stav).
- **Tichý start:** spouštěcí skripty LIVE04/TRANSFER zachytí veškerý výstup do
  `%LOCALAPPDATA%\R1C25_BOOT\LAST_LAUNCHER_OUTPUT.txt` (žádná okna „Information“).
- Mock: reset maže cesty bez přidělení (testy `test_live04_8.py`).


## LIVE04.8.2 – upravitelná konfigurace (2026-11-04)

- `CORDON_LIVE04_CONFIG.json` a `TRANSFER_2025_CONFIG.json` nejsou v `SOURCE_MANIFEST.json`: jejich úprava
  (např. `max_cycles`, `parameter_file`) už nezpůsobí `RELEASE_INTEGRITY_FAIL … HASH_OR_SIZE_MISMATCH`.
  Obsah dál přísně ověřuje zavaděč konfigurace (schéma, pole, rozsahy, zakázané zápisy). Výchozí hodnoty
  vydání jsou hashované v `provenance/live04_user_config/*.RELEASE_DEFAULT.json`; změna kódu se dál odhalí.
- `max_cycles` pro LIVE04 1–200 (dříve 10 převzaté z LIVE03; LIVE03 si limit 10 ponechává).
- Testy `tests/test_live04_8_2.py`.

## LIVE04.9 – profily kordonových stanovišť (2026-11-04)

Rozhodnutí uživatele 2026-11-04: kordonová stanoviště jsou zároveň sčítací profily; kalibruje se na OD vazby
i na celkový počet průjezdů stanovištěm. Data sčítačů (ASD 1–14) se **nepoužívají**; cíl profilu je pro všech
16 stanovišť řádkový + sloupcový součet matice D3 `OA_ALL_RPDI` (`data/audited/AUDITED_MATRICES.npz`, stejná
autorita jako OD vazby, sha256 beze změny), tj. vazby, C17 (bez páru) i vjazd‑výjazd.

- Řádky FIRST_LAST: 120 vazeb + 16 C17 + **16 profilů** = 152 (`KORDON_STATION_PROFILE`, klíč `(s, 18)`).
- Model profilu = intenzita na hranách stanice: každý průjezd každé uložené cesty (i průběžná stanoviště,
  cyklická cesta 2×) – `first_last_contributions(..., profile_rows=True)`.
- Profilové řádky jdou do cílové funkce s vahou `observations.station_profiles.row_weight` (výchozí 1,0),
  do pojistky GEH po řádcích, do prediktoru TG/TD (zmrazené podíly cest) a do SupplyMix (řídicí profily).
- Sekundární metoda EXACT_TWO_HITS zůstává jen na vazbách – krok, který by kvůli profilům zhoršil vazby,
  se dál odmítne (`SECONDARY_METHOD_DEGRADED`).
- Vypnutí: `station_profiles.enabled = false` → původních 136 řádků.
- Navázání (CONTINUE) funguje i z běhu se 136 řádky: kontrolují se jen hashe stavu modelu; cílová funkce se
  v navazujícím běhu spočte znovu nad 152 řádky.
- Testy `tests/test_live04_9.py` (profil v mocku = nezávisle spočtená intenzita na hranách stanic). Starší mock
  testy běží na 136 řádcích přes `conftest.py` v kořeni (`tests/conftest.py` je chráněný zdroj LIVE01).
