# Kordónový kalibrátor LIVE02 – varianta V24917 (2026-10-25)

## Zdroje
- Základ: kordónový LIVE02 (`R1_2025_CORDON_LIVE02_TG_CYCLE_FULL_20261025.zip`, SHA-256 2853d493…d254).
- Nová verze profilového kalibrátoru: `R1_15A2_V24917_COMBUSY2FIX1_ROSTEREDGE1_BNDGEN2_STEP1_PERF3_20261025_FULL.zip`
  (SHA-256 ccfd540cb07b13a6eb40965cfac988689c6fe2aab7c4670f384561f202281f4f).
- Do `parent/` převzato bajtově beze změny 9 modulů V24917: `zonal_count_fit`, `targeted_generation`,
  `step_search`, `boundary_generation`, `long_school_generation`, `combusy2`, `demand_policy_v1`, `perf_v24917`,
  `td_count_blend` (jen `cl_key`). Hashe ověřuje `live02_v24917.verify_donor_files()` při každém startu.
- Sdílené knihovny (`r1_15a2_core`, `com_compat`, `supply`, `two_mode`) zůstávají ve verzi kordónového parent stromu:
  jejich rozdíly proti V24917 jsou výhradně kordónová rozšíření (deadband, `geometry_only`, bezpečný text výjimky).

## Výchozí režim `generation_mode = V24917_TARGETED_STEP1`
| Mechanika V24917 | Kordónová varianta |
|---|---|
| Zónový fit P/A log-násobků na rezidua (`zonal_count_fit`) | stejný modul; „profily“ = 120 neuspořádaných dvojic stanic, incidence = uložené cesty aktuálního assignmentu |
| Fáze CATCH_UP (< 0,80) / REFINE, obálka [0,25; 5], TARGETED_ZONE_DIRECT | beze změny; poměr model/sčítání z kordónových vztahů hodnoticí metody |
| STEP1: vypočtený krok, přijetí na místě | `live02_step1.py` (port `generation_block`), donorové `choose_scale` beze změny; predikce obou metod, kordónová brána |
| BNDGEN: hraniční přechody X1–X31 jako páka | donorové funkce; zóny = nastavené ∩ v modelu ∩ bez páky ADD/ZAHR (kontrola modelu 2025) |
| LSGEN: LONG/SCHOOL | donorové `lsgen.design`; expozice LONG = objem NATIVE_CL uložených cest na kordónovém vztahu |
| COMBUSY2 | rozpočet 900 s (i pro kordónové čtení cest), volitelný filtr zpráv, opakování rollbacku a bloku |
| PERF3 | časy (`V24917_TIMING.json`), mazání capture odmítnutých pokusů, cache SHA v checkpointech |
| Nefatální TG brána | i ve STEP1 (viz opravy) |

Volby se berou výhradně z `CORDON_LIVE02_CONFIG.json` → `v24917.run_options` (kopie `R1_RUN_OPTIONS.json`
z V24917, připnutá v `provenance/v24917/`), validuje je donorová `demand_policy_v1.validate`.
Proměnné prostředí se nečtou (reprodukovatelnost). Změna připnuté hodnoty = `LIVE02_V24917_RUN_OPTION_DRIFT`.

Původní cesta HOTFIX2 (backtracking 1…0,0625, rollback, znovu aplikace vítěze) zůstává volitelná:
`generation_mode = HOTFIX2_BACKTRACKING`.

## Co se nepřevádí
- **FASTASSIGN1** – ve V24917 se používá jen při vypnutém STEP1; STEP1 ponechává pokus jako přijatý stav,
  proto musí pokus běžet plným postupem AMDY. Volba `fa_enabled` je v kordónu pevně `false`.
- **TDBLEND, IZPEN1, ICONG1** – patří k TD (FineCDF), který kordón zatím nemá → LIVE03.
- **ROSTER248/ROSTEREDGE1, DIAGFAST 12D/11D, SKIMFIX, D11FIX** – profilově specifické.

## Opravy proti donorovému STEP1 (nalezené při portu)
1. **Brána P/A ve STEP1 byla fatální.** V24917 STEP1 volá `apply_generation`, ve kterém `GENERATION_GATE`
   vyhodí výjimku → celý běh končí `NOT_A_PLATEAU` (TGFIX tam neplatí). Kordón bránu vyhodnotí na
   identickém náhledu před zápisem, kandidát je odmítnut a zkusí se menší vypočtený krok.
2. **Neúplný rollback po odmítnutém pokusu.** Po odmítnutí se parametry rodiče vrátí jen zápisem COM;
   pokud hledání skončí bez dalšího zápisu (např. `NO_PARAMETER_CANDIDATE`), donorový `rollback_full`
   se přeskočí a v modelu zůstane poptávka z pokusu. Kordón si pamatuje poslední zapsaný pokus a plný
   ověřený rollback (obnova + přepočet + důkaz) provede vždy.

## Simulace (681 zón, poměr model/sčítání 0,08)
| | HOTFIX2 | V24917 |
|---|---|---|
| Nativní přepočty na přijatý krok | 3 | 1 |
| Zlepšení J v 1. cyklu | 0,76 % | 2,4 % |
Simulace nepotvrzuje skutečný účinek ani časy ve Visumu.

## Provozní poznámky pro model 2025
- BNDGEN: výchozí zóny 650–680 platí pro číslování profilového modelu. Pokud v modelu 2025 neexistují,
  nebo mají páku ADD/ZAHR, BNDGEN se nezapne a `V24917_RUNTIME_STATUS.json → boundary.audit` ukáže proč.
  Jiné zóny: `v24917.run_options.bd_zones` (změna vyžaduje vědomé povolení odchylky od donoru).
- LSGEN se zapne jen tehdy, když model má ADD_PROD_L, ADD_ATT_L, ADD_PROD_SCH, ADD_ATT_SCH (V24917:
  `R1_ADD_LONG_SCHOOL_COEFFICIENTS.py`); jinak `long_school.active = false`.
