# R1 15A2 V2.4.9.15 — COM busy retry + bezpečný finalizer

## Co se pokazilo v posledním běhu

Běh V2.4.9.14 neskončil chybou kalibrační matematiky ani neshodou continuation authority. V cyklu 6 při read-only exportu `REPRESENTATIVE_GEOMETRY` VISUM pětkrát odmítl stejný COM požadavek pro rozsah `22786049:22788096` (HRESULT `-2147418111`). Obecný retry rozpočet čekal před posledním pokusem dohromady jen 0,75 s.

Po primární chybě se finalizer pokusil okamžitě znovu číst živý snapshot. Další transientní odmítnutí COM bylo chybně převedeno na `FAILED_FINAL_VERIFICATION_MANUAL_REOPEN_REQUIRED`, přestože existoval poslední přijatý checkpoint A0009 a produkční apply nebyl aktivní.

## Oprava

- obecný COM retry zůstává beze změny: 5 pokusů, 0,05–0,8 s;
- pouze `bounded_path_export` dostává samostatný transient-only lease: max. 48 pokusů / 120 s;
- každý opakovaný pokus používá přesně stejný rozsah stránky;
- transientní RPC odmítnutí nikdy nespustí zmenšení stránky;
- `final_verification` dostává read-only lease: max. 12 pokusů / 30 s;
- pokud se transientní finální čtení vyčerpá, stav se neprohlásí za ověřený, ale běh se bezpečně klasifikuje pro restart z posledního přijatého checkpointu;
- ne-transientní chyba nebo skutečná neshoda stavu zůstává fail-closed a vyžaduje ruční kontrolu.

## Co se nezměnilo

A0009 semantic lineage, accepted count 9, pokračování od outer cycle 6, TG/TD acceptance, FineCDF reference, supply route-choice policy, produkční apply (`false`) ani přímé OD zápisy (`false`).

## Doporučené spuštění

1. V VISUMu otevřít poslední přijatý checkpoint z neúspěšného běhu:
   `R1_15A2_V24914_RUNS\RUN_20261019_095727_260953\CALIBRATION\CHECKPOINTS\ACCEPTED_A_0009_cebb9c7a9349.ver`.
2. Spustit ručně přes **Scripts → Execute script file**:
   `R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_15.py`.
3. Nespouštět launcher jako krok Procedure Sequence.
4. Po startu zkontrolovat `V24915_DEPLOYMENT_PREFLIGHT.json` a `V24915_RUNTIME_BUNDLE_PREFLIGHT.json`.

Restart acceptance je založen na semantic model state, nikoli na raw SHA `.ver`; checkpoint A0009 z neúspěšného běhu má zachovanou stejnou semantic authority.

## Ověření balíku

```text
python verify_v24915_package.py
```

Dostupné testy: 783 passed, 4 skipped, 0 failed. Živý dlouhý VISUM rerun po opravě nebyl v tomto prostředí proveden; `production_ready=false`.
