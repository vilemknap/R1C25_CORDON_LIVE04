# LIVE04.13 – IDP v Generation a kumulativní ochrana proti referenci běhu

Rozhodnutí uživatele 19. 11. 2026. Ověřeno jen syntetickými testy (`tests/fake_live04.py`),
ne nativně v PTV Visum.

## Proč

- Generation dosud neměla v přijímacím rozhodnutí žádnou kontrolu rozdělení délek cest.
  Mohla zlepšovat kordónové profily tím, že nafoukne produkci a atrakci obcí u profilů
  a zkrátí cesty, aniž by to IDP/FineCDF zaznamenalo.
- Lokální IDP guard TD porovnává kandidáta jen s rodičem bloku. Malá povolená zhoršení
  se proto mohla sčítat přes desítky cyklů.

## Co platí

1. **Lokální guard i pro GENERATION** (`idp_guard.blocks = ["TD_CORDON", "GENERATION"]`):
   FineCDF se změří na začátku bloku Generation (`IDP_BEFORE.json`) a po každém nativním pokusu
   (`TRY_xx/IDP_TRIAL.json`) na stejných osobních maticích a stejnou metodikou jako v TD.
   Pravidlo je beze změny: RMSE +0,01, střední délka `max(|e_před|, 0,03) + 0,02`.
2. **Kumulativní ochrana** (`idp_guard.cumulative`) pro GENERATION i TD_CORDON, pro každou
   komponentu zvlášť a bez floor:

   - `RMSE_k(nový) <= RMSE_k(start) + 0,01`
   - `|e_k(nový)| <= |e_k(start)| + 0,02`, kde `e_k = (d_model − d_IDP) / d_IDP`

   Zlepšení jedné komponenty nekompenzuje zhoršení jiné.
3. **Kandidát se přijme jen tehdy, když splní dosavadní přijímací politiku, lokální guard
   i kumulativní ochranu.** Jinak se odmítne a proběhne ověřený rollback. Generation pak zkouší
   menší nebo upravený krok jako u každého jiného odmítnutí.
4. **Bez platných IDP údajů se nic nezapisuje.** Pokud nejde změřit stav před blokem, Generation
   skončí jako `NO_GENERATION_CANDIDATE / IDP_BASELINE_UNAVAILABLE`. Pokud nejde změřit
   pokus, je odmítnut (`IDP_EVALUATION_FAILED`).

## Reference běhu

- Je to **naměřený** FineCDF stav modelu na začátku nového běhu, ne cílová křivka IDP.
  Cílové křivky FineCDF v1.9 se nemění.
- Změří se jednou po baseline a uloží do `RUN_ANCHORS.json` (`idp_run_reference`)
  a `IDP_RUN_REFERENCE.json`. Záznam obsahuje: metriky po komponentách, SHA-256 referenčního
  skriptu FineCDF, hashe zmrazených vzdáleností 9721/9726/9727, mapu komponent → vzdálenost,
  čísla vstupních matic a SHA-256 jejich hodnot, tolerance, bloky a `record_sha256` celého záznamu.
- **Pokračování** (`continuation=True`) referenci přebírá z běhu, odkud pokračuje, a ověří ji:
  hash záznamu, FineCDF referenci, vzdálenosti, komponenty, tolerance a bloky. Když chybí nebo
  nesedí, běh se zastaví (`LIVE04_IDP_RUN_REFERENCE_MISSING_IN_CONTINUATION`,
  `..._RECORD_CHANGED`, `..._MISMATCH:<co>`). Současný stav modelu se nikdy tiše nepoužije
  jako nová reference.
- Pokračování z běhu staršího než LIVE04.13 (bez reference v `RUN_ANCHORS.json`) proto není
  možné. Je potřeba spustit nový běh. To odpovídá plánu začít znovu od koeficientů 1.

## Beze změny

- Komponentová TD (11 komponent, 22 souřadnic) a její cíl 55 % kordón / 45 % FineCDF.
- Lokální TD guard včetně `mean_error_floor = 0,03`.
- Referenční křivky FineCDF v1.9, zmrazené vzdálenosti 9726/9727 (a 9721 pro LONG).
- Nativní kontroly, checkpointy a rollback ostatních bloků. SupplyMix kumulativní IDP nemá.

## Kde to je

- `cordon2025/live04_idp_run.py` – reference, ověření, kumulativní rozhodnutí.
- `cordon2025/live04_step1.py` – IDP v přijímacím rozhodnutí Generation.
- `cordon2025/live03_td.py` – kumulativní kontrola spolu s lokálním guardem TD.
- `cordon2025/live04_cycle.py` – zachycení či převzetí reference na začátku běhu.
- `tests/test_live04_13_idp_run.py` – pravidlo, kumulace, neměnnost, pokračování,
  odmítnutí s rollbackem, chybějící IDP.

## Revize 19. 11. 2026 – přípustnost středu IDP kroku TD, balík, SupplyMix

- **Záporné RHS se už neořezává.** `IdpStepModel.constraints()` ověří, že střed trust-regionu
  splňuje lokální IDP guard. Jen šum zaokrouhlení (|rezerva| ≤ 1e-12, střed přesně na hranici)
  se bere jako 0. Střed mimo guard skončí chybou `LIVE04_TD_IDP_CENTER_OUTSIDE_GUARD`.
  `constrained_least_squares()` odmítne záporné d (`LIVE04_TD_IDP_ZERO_STEP_INFEASIBLE`)
  i box bez nulového kroku, protože závěrečné promítání k nule předpokládá přípustnou nulu.
  Řešič pro obnovu přípustnosti záměrně není: TD blok pak skončí bez kandidáta
  (`stop_reason = IDP_CENTER_OUTSIDE_GUARD`, `idp_center_invariant = VIOLATED`).
- **Invariant TD smyčky:** střed se posune jen na nativně přijatý vnitřní krok, který prošel
  `guard_decision()` a má platné IDP. Test ověřuje, že se ve standardním běhu (4 přijaté
  vnitřní kroky) nepřípustný střed neobjeví.
- **Balík:** `tools/build_release_package.py` zabalí přesně soubory ze `SOURCE_MANIFEST.json`
  (bez filtru přípon a složek). Zip pak rozbalí do čisté složky a v izolovaném interpretu spustí
  `verify_release`, `load_config()` a kontrolu v7 pinů (včetně
  `R1_RUN_OPTIONS_V24917_V7_7b4c681.json`). Výsledek zapíše do `*.PACKAGE_CHECK.json`.
- **SupplyMix:** `row_semantics()` vyžaduje stejnou délku `pairs`, `model` a `observed`
  (`LIVE04_SUPPLY_ROW_SEQUENCE_LENGTH_MISMATCH`), aby `zip()` nic tiše nezahodil.
