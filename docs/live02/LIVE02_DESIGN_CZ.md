# LIVE02 – první skutečný TG cyklus kordónové kalibrace R1 2025 (návrh, CP00)

## Zdroje
- Základ: R1_2025_CORDON_LIVE01_FOUNDATION_BASELINE_FULL_20261024.zip
  (SHA-256 acb590a9b59785cfab0bcfb3eebadb7938bb1d1e4e3d2a84389174ab8e48e9d6), všech 1 699 souborů beze změny.
- Donor TG/TD mechaniky: R1_15A2_DIAGFAST_V2_BULK_NUMPY_TGFIX_20261025_FULL.zip
  (SHA-256 a89d00c6a924cfa72f997831e6867d6da2890b3efee7a2f2be56d661f3ab4359).
  Je to HOTFIX2 (c3f5a2d7…) + DIAGFAST profilová diagnostika + TGFIX. Všech 82 donorových
  souborů indexovaných v LIVE01 je v DIAGFAST_V2 bajtově shodných.
- Z DIAGFAST_V2 přibývá do parent/ jen `r1_15a2_generation_gate_nonfatal_v1.py` (TGFIX, beze změny).
  DIAGFAST 12D/11D je profilová diagnostika (498/488 profilů) a v kordónu se nepoužívá;
  nahrazuje ji kordónové vyhodnocení celé matice.

## Princip: donorová transakce beze změny, vyměněné jen kordónové hodnocení
Používají se přímo původní funkce (stejný bytecode), pouze s jiným jmenným prostorem pro
profilově specifická jména:

| Donorová funkce | Modul | Co se mění |
|---|---|---|
| `_generation_update_once` / `_impl` | overnight_controller_coupled_v24915p2_force100 | `ledger`, `diagnostic_hash`, `_evaluate_candidate`, `_adopt_candidate` z kordónového jmenného prostoru |
| `_evaluate_candidate`, `_adopt_candidate`, `_apply_candidate`, `_assign_candidate`, `_rollback_candidate` | overnight_controller_v24915p2 | `ledger`, `diagnostic_hash` |
| `wrap_evaluate` (TGFIX) | generation_gate_nonfatal_v1 | nic – obaluje kordónově navázaný `_evaluate_candidate` |
| `rollback_and_verify`, `restore_generation_parameters` | inplace_transaction_v24915p2 | nic |
| `assert_freeze` | controller_v22 | nic (snapshot má donorové schéma) |
| `VisumAdapter.snapshot/apply_generation/generation_preview/parameter_persistence/gap/apply_td` | supply_visum | jen `__init__`: skutečná osa 681 Zone.NO místo 1..681 |
| `phase_recompute_plan`, `activate_operation_plan` | acceleration_v24915p1 | nic |

Kordónová vrstva dodává adaptéru: `diagnostics` (nový preflight + úplný LEGACY capture uložených
cest + incidence + 120 vztahů pro obě metody), `block_gate` (kordónové přijetí),
`generation_design` (FISTA → projekce P/A, totéž co LIVE01), `rollback_diagnostic_equivalence`
(důkaz: stejný snapshot + stejné klíče a objemy cest všech 12 segmentů → převzetí výchozího
vyhodnocení; jinak úplný capture).

## Průběh jednoho běhu (RUN_R1_2025_CORDON_LIVE02_TG_CYCLE.py)
1. Integrita vydání, kontrola, že otevřený .ver není 2022 a má v názvu značku izolované kopie.
2. Výchozí stav: LIVE01 preflight + čtení donorového stavu + úplný capture (stejně jako LIVE01).
3. Donorový snapshot (ADDVAL1, matice 12+2 DSeg, 9101–9117, TG 9 atributů × 681 zón, TD B/C,
   operace) = bod obnovy; žádný SaveVersion/LoadVersion, žádný zápis do OD matic.
4. TG cyklus (donorový `_generation_update_once`):
   FISTA na celé matici → projekce → kandidáti pro kroky 1, .75, .5, .25, .125, .0625 →
   pro každý: zápis ADD/ZAHR s readbackem → fázový přepočet TG(5)→TD(6)→…→assignment(20)
   + kontrola gapu z PrTAssQualityList op. 20 → persistence parametrů → `assert_freeze`
   (TD beze změny, žádný jiný TG parametr, fixní matice 9116/EXOG/LNV/NV beze změny,
   aspoň jedna matice bloku GENERATION změněna) → kordónové vyhodnocení → rollback
   (obnova parametrů + přepočet + důkaz rovnosti) → další krok.
   Brána P/A (TGFIX): kandidát je odmítnut, běh pokračuje dalším krokem.
   First-sufficient: zlepšení ≥ 0,1 % ukončí hledání dříve.
5. Vítěz: nová aplikace z identického rodiče, assignment, vyhodnocení, kontrola
   reprodukovatelnosti (shodný hash vyhodnocení) → ACCEPTED, jinak rollback.
6. Volitelně další TG cykly (výchozí 1) z přijatého stavu.
7. Na konci: nezávislý readback, ACCEPTED_TG_PARAMETERS.csv, volitelně SaveVersion do NOVÉHO
   souboru ve výstupní složce (výchozí zapnuto, zdrojový .ver se nikdy nepřepisuje).

## Kordónové kritérium přijetí
J = ½ Σ_i (w_i · deadzone(m_i − y_i, ε_i))², w_i = 1/√max(1, y_i), 120 vztahů, BIDIRECTIONAL_SUM,
C17 bez alokace (UNAPPROVED). Je to přesně datová složka cílové funkce FISTA.
Přijetí: J_sel klesne alespoň o min_relative_improvement (1e-5) a o > 1e-8 absolutně
(donorový shared_objective), druhá metoda se nezhorší nad toleranci (výchozí 0 %).
Hodnotí se skutečné zátěže z nového assignmentu, ne linearizace ani stará incidence.

## Výběr metody (technické rozhodnutí, ne schválení sémantiky)
Výchozí `acceptance_method = ALL_ORDERED_UNIQUE_PAIRS`, druhá metoda EXACT_TWO_HITS je
pojistka „nezhoršit“. Lze přepnout v konfiguraci. Sémantika pozorování zůstává UNAPPROVED,
režim TECHNICAL_TRIAL, výsledek není produkční PASS.

## Mimo rozsah LIVE02 (LIVE03)
TD návrh FineCDF a společné TG/TD cykly. Primitiva TD zápisu/obnovy (`apply_td`,
`restore_td_parameters`) jsou z donoru dostupná a otestovaná, ale TD kandidáti se v LIVE02
negenerují.
