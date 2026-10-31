# Live VISUM acceptance — V2.4.9.15

Release `R1_15A2_V2_4_9_15_COM_BUSY_RETRY_SAFE_FINALIZER_20261019` je source-level oprava konkrétního pádu V2.4.9.14.

## Povinné live kroky

1. Načíst `ACCEPTED_A_0009_cebb9c7a9349.ver` z neúspěšného V24914 runu.
2. Spustit V24915 launcher a ověřit oba preflight JSONy jako PASS.
3. Potvrdit, že path export při dočasném COM busy zapisuje retry události se stejnými `bounded_range_first/last`.
4. Potvrdit, že export buď pokračuje, nebo po 120s transient lease skončí bez page-size fallbacku.
5. Při případném transientním selhání závěrečného snapshotu musí výsledek uvést bezpečný restart z latest accepted checkpointu a `manual_reopen_required=false`.
6. Ne-transientní chyba/nasnímaná neshoda musí zůstat fail-closed.

## Přijímací hranice

- Bez živého dokončeného VISUM běhu se nesmí tvrdit `calibration_complete=true`.
- Release je připravena pro pokračovací experiment, nikoli označena jako production-ready.
- Supply zůstává uzamčená do splnění původního kritéria dvou úplných nezměněných TG/TD cyklů.
