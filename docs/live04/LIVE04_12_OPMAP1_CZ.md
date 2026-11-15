# LIVE04.12 – OPMAP1: role posloupnosti procedur živého modelu (2026-11-15)

## Proč
Donor v7 @ 7b4c681 i vrstvy LIVE01–04 předpokládaly pevné pozice operací 09C (43 operací):
TG 5, TD 6, reset 1 / 15, dílčí přiřazení 17–19, společné přiřazení 20 (14 DSeg), GEH skript 21.
Modely R1 mají od 2026-11 kroky poptávky vnořené do dalších skupin, takže tytéž role mohou být jinde
(např. 2022: TG 6, TD 10, reset 23, přiřazení 25–28, GEH 29).

## Co se změnilo
- `parent/r1_15a2_procseq_roles_v24917.py` – modul OPMAP1 **beze změny** z kalibrátoru
  R1_15A2_V24917_v7, větev `claude-opmap1-procseq-roles-20261111` (sha256 5c4d0db…).
- `parent/r1_15a2_long_post_td_mask_v24917.py` a `parent/r1_15a2_supply_mix_v24917.py` – stejné OPMAP1 hunky
  jako v té větvi (maska LONG: role 17–20; studený řetězec SupplyMix: reset 15). Ostatní obsah donoru v7 @ 7b4c681
  zůstal (větev OPMAP1 vychází ze starší v7 – obálky 0,75–2,5, CATCH_UP – ta se **nepřebírá**). Piny v `live04_v7.DONOR_FILES` aktualizovány.
- `cordon2025/live04_opmap.py` – rozsah OPMAP1 pro jeden běh: obalí vstupní body donoru (V239/V240 audit přiřazení,
  PERF1 plán fází, supply_visum plán přiřazení a GAP readback), konfiguraci přeloží jen jednou (idempotentně),
  po běhu vše vrátí. Zapisuje `OPMAP1_ROLES.json` do složky běhu a do `V7_RUNTIME_STATUS.json` (`opmap1`).
- LIVE01 kontrola TG/TD pozice (dříve pevně 5/6), predikce na zmrazených cestách (řez před společným přiřazením)
  a READINESS (`OPERATIONS_TD_17_20`, `SUPPLYMIX_COLD_CHAIN`) používají živé pozice.

## Chování
- Model s pozicemi 17–20 = přiřazení → `LEGACY_IDENTITY`, vše jako LIVE04.11.1.
- Jinak se role hledají podle podpisu (typ, ACTIVE, přesný DSEGSET, pořadí TG < TD < reset < přiřazení);
  chybějící nebo nejednoznačná role = stop `OPMAP1_*` před prvním zápisem. Nic se nehádá, posloupnost se nemění.

## Ověření
`tests/test_live04_12_opmap.py` (7 testů, starý 43-op i nový 53-op layout). Jen syntetické mocky – první nativní běh
musí potvrdit Visum.
