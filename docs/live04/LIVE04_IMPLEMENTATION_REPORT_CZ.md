# Kordónový kalibrátor LIVE04 – port na v7 (2026-10-31)

Základ: LIVE03 (`R1C25_LIVE03`, společná kalibrace TG + TD na kordónu). LIVE04 ji přenáší na profilový kalibrátor **v7**, tedy `vilemknap/R1_15A2_V24917_v7` @ `977cef4e77ab67f159bbe392edc8d3d485dc72ee`. To je verze s P2.5/A4, která teď běží ve Visumu.

Kordónová část se nemění. Platí stejná pozorování (FIRST_LAST + C17, faktor roku 1,0), stejný cíl, nativní predikce na zmrazených cestách, blok TD_CORDON i guard IDP. Mění se všechno, co v7 dělá jinak než V24917 z LIVE03.

## 1. Co se převzalo z v7

| Oblast v7 | V LIVE04 | Kde |
|---|---|---|
| Donorové moduly v7 (20 souborů) | bajtové kopie, SHA-256 připnuté a ověřované při startu | `parent/`, `live04_v7.DONOR_FILES` |
| Run options v7 | připnutý soubor `R1_RUN_OPTIONS.json` z 977cef4, změnit lze jen tři odchylky (kap. 3) | `provenance/v24917_v7/`, `CORDON_LIVE04_CONFIG.json` → `v7` |
| Obálky podle role (TGBOUNDS v2) | P [0,75; 2,5], A [0,75; 4,0], ZAHR [0,5; 10], hranice [0,5; 2] | `tg.patch_multiblock` |
| MOBILITY2 | produkční pás 0,75–2,5 (`mg_max_ratio` 2,5) + samostatný plot atrakce W/S 0,75–4,0 | návrh, náhled, kontrola před zápisem a po pokusu |
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

- piny a politiku v7 (P2,5/A4, odchylky, drift, zdroj);
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
