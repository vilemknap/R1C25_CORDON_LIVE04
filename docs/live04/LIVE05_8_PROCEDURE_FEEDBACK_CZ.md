# LIVE05.8 – zpětná vazba procedury (TD utility step, dálniční kupóny)

Běh 2026-11-15 22:44 skončil v prvním bloku GENERATION chybou
`LIVE03_DEMAND_RESTORE_SNAPSHOT_DIFFERS`. Příčinou byla operace 15, skript
„R1 TD utility step“ (`R1_TD_UTILITY_PROCSEQ_COLD_START_20261110`). Ten při každém
spuštění upraví utility matice 9700–9715 metodou MSA:

    U_nové = 0,5 · U_staré + 0,5 · M9002 · poměr(TTC/TT0, toky 9301–9304)

Krok si tedy pamatuje stav (je neidempotentní). Probe ho spustil, obnova ho spustila
podruhé, a poptávka proto vyšla jinak než v rodičovském stavu.

Rozhodnutí uživatele: zpětná vazba poběží dál, protože díky ní se počítá vliv
kongescí. Přijetí a rollback nemusí mít přesné shody.

## Jak to kalibrátor dělá

| Spuštění procedury | výchozí stav zpětné vazby | operace 15 |
|---|---|---|
| probe (TG uzly, TD Jacobián) | přijatý | **běží** – predikce trialu včetně kroku |
| trial (kandidát) | přijatý | **běží** – jedna iterace modelu s kongescemi |
| obnova po probe, rollback zamítnutého trialu, oprava přiřazení | přijatý | **vynechá se** |

* **Stav zpětné vazby** = utility matice 9700–9715 + skimy TTC/TT0 segmentů
  NATIVE_CW, NATIVE_CW_NOT, NATIVE_CS, NATIVE_CS_NOT a NATIVE_CL (tj. vstupy kroku).
  Kalibrátor ho načte na začátku (BASELINE) a po každém bloku, který přijal změnu.
* Před každým spuštěním procedury se tyto matice vrátí na přijatý stav, pokud je
  předchozí spuštění změnilo. Zápis probíhá přes SetValues s kontrolou zpětného
  čtení a je zaznamenán ve WRITE_AUDIT.jsonl jako `FEEDBACK_STATE_MATRIX_WRITE`.
* Trial = parametry kandidáta + jeden krok MSA z přijatého stavu. Přijatý stav
  tak obsahuje i posun utilit od kongescí. Po přijetí se z něj stává nový
  přijatý stav zpětné vazby.
* Obnova, rollback a oprava přepočítají přijatý stav bez kroku a se stejnými
  utilitami. Platí: stejné parametry + stejné utility → stejná poptávka → stejné
  přiřazení. Přesné důkazy (snapshot, path signature) proto dál platí a
  tolerance tu nejsou potřeba. Kdyby se stav i přesto nevrátil, běh se zastaví
  jako dosud.
* „Neshoda“, kterou uživatel povolil, je v přijetí: měřený trial obsahuje navíc
  krok MSA, takže výsledek dvou běhů z různých výchozích verzí není
  reprodukovatelný bit po bitu. Predikce probe krok obsahuje, takže se s trialem
  shoduje (u TD probe přibližně, protože toky 9301–9304 jsou z předchozí probe).

Kalibrátor operaci kroku najde sám: je to právě jeden aktivní Run-script mezi
aktivní nativní TG a TD (`expected_feedback_operations: 1`). Jiný počet běh
zastaví před prvním zápisem.

## Dálniční kupóny (20D)

`R1_20D_VIGNETTE_SPLIT.py` s `DT_MODE='FROZEN'` čte dT z datových matic 9235/9236
(vytvoří je `R1_20D_FREEZE_DT.py`). Je deterministický a nic dalšího nevyžaduje.

Režim `DT_MODE='LIVE'` reprodukovat nejde ani na výchozí verzi. Uložená poptávka
byla rozdělena se skimy běhu, který předcházel uloženému běhu, a ty už ve verzi
nejsou. Kalibrátor proto zkontroluje vzorce 9231–9234 a povolí v nich jen odkazy
na 9235/9236. Jinak se zastaví s chybou
`LIVE05_VIGNETTE_SPLIT_NOT_FROZEN_NOT_REPRODUCIBLE`. To se stane v readiness
(kontrola `PROCEDURE_FEEDBACK`) nebo na začátku běhu před baseline capture.
Řešení: v `R1_20D_VIGNETTE_SPLIT.py` nastavit `DT_MODE = 'FROZEN'`, spustit
`R1_20D_FREEZE_DT.py`, přepočítat a uložit kopii.

## Konfigurace

`CORDON_LIVE04_CONFIG.json`:

* `procedure_feedback` (enabled, utility_matrix_nos, time_skim_codes,
  time_skim_dsegs, formula_matrix_nos, formula_allowed_reference_nos,
  expected_feedback_operations);
* `write_policy.procedure_feedback_state_matrix_writes: true`.

Obě hodnoty musí souhlasit, jinak konfigurace neprojde. Zapisovat je dovoleno
jen do vyhodnocených matic stavu. Do OD matic segmentů poptávky a komponent
9101–9117 se zapisovat nesmí a jejich překryv se stavem běh zastaví.

## Výstupy

* `00_PROCEDURE_FEEDBACK/PROCEDURE_FEEDBACK.json` – pozice operace, matice stavu,
  vzorce kupónů;
* `FEEDBACK_STATE_<blok>.json` – hashe přijatého stavu;
* `00_RESULT.json` → `procedure_feedback` (počty obnov a zapsaných matic, počet
  spuštění s krokem a bez něj).

## Testy

`tests/test_live05_feedback.py` obsahuje syntetický model se stavovým krokem MSA,
TD, realizací, přiřazením a skimem. Testuje:

* původní chybu (bez úpravy se obnova liší);
* přesnou obnovu po dvou probe;
* přesný rollback trialu;
* opakovaný trial ze stejného rodiče, který dá stejný výsledek;
* nový přijatý stav po přijetí;
* zastavení u kupónů v režimu LIVE ještě před zápisem;
* guard zápisů a release konfiguraci.

Jde o mock, ne o důkaz z Visumu.
