# LIVE02 – implementační report (2026-10-25)

## Rozsah
První skutečný TG cyklus kordónové kalibrace R1 2025 ve Visumu: bod obnovy, zápis TG kandidáta,
nativní přepočet TG→TD→assignment, kontrola gapu, nové čtení uložených cest, vyhodnocení celé
kordónové matice (120 vztahů), ACCEPT/ROLLBACK, znovu aplikace vítěze s kontrolou reprodukovatelnosti.

## Převzato z DIAGFAST_V2 / HOTFIX2 beze změny kódu
Funkce běží ze svých původních code objectů (test `DONOR_TRANSACTION_IDENTITY.json` to ověřuje),
v privátní kopii jmenného prostoru modulu, kde jsou nahrazena pouze profilová jména `ledger`
a `diagnostic_hash`:

- `_generation_update_once` / `_impl` (coupled force100): plánování kroků, náhledy, first-sufficient,
  výběr nejlepšího, adopce, záznam bloku;
- `_evaluate_candidate`, `_adopt_candidate`, `_apply_candidate`, `_assign_candidate`, `_rollback_candidate`;
- `rollback_and_verify`, `restore_generation_parameters` (obnova parametrů + přepočet, bez LoadVersion);
- `assert_freeze` (TD beze změny, žádný nevyžádaný TG parametr, 9116/EXOG_EE/LNV/NV beze změny,
  změna aspoň jedné matice bloku GENERATION);
- TGFIX `wrap_evaluate` (`r1_15a2_generation_gate_nonfatal_v1.py`, SHA-256 2ca13966…): brána P/A
  odmítne kandidáta, běh pokračuje dalším krokem;
- `VisumAdapter.snapshot/apply_generation/generation_preview/parameter_persistence/gap` (supply_visum,
  v rozsahu COMBUSY hotfixu) a PERF1 `_execute_perf1_plan` + `phase_recompute_plan` (fázový ProcSeq,
  přesné obnovení ACTIVE).

## Nové kordónové části
| Modul | Účel |
|---|---|
| `live02_config.py` | samostatný kontrakt zápisu; LIVE01 pohled zůstává read-only; donorové hodnoty se porovnávají s pinem (drift = chyba) |
| `live02_namespace.py` | spuštění donorové transakce s kordónovým hodnocením (bez patchování globálů) |
| `live02_adapter.py` | donorový adaptér na skutečné ose 681 Zone.NO; kordónové `diagnostics`, `block_gate`, `generation_design`, důkaz rollbacku |
| `live02_evaluation.py` | nový preflight + LEGACY capture + incidence + 120 vztahů × 2 metody; J, GEH, RMSE, R²; podpis cest |
| `live02_guard.py` | vynucená politika zápisu mezi donorem a Visumem + `WRITE_AUDIT.jsonl` |
| `live02_cycle.py` | orchestrace, STOP s odložením během obnovy, ověření stavu po chybě, export parametrů, SaveVersion do nového souboru |

## Optimalizace (bez změny kritérií)
- **Důkaz rollbacku bez dalšího capture:** po obnově se porovná donorový snapshot (všechny poptávkové
  matice, TG, TD, ADDVAL1, operace) a klíče + objemy cest všech 12 segmentů. Při shodě se převezme
  výchozí vyhodnocení, jinak úplný capture. Ušetří jeden úplný capture na pokus.
- **Zkratka brány P/A:** kandidát, který neprojde bránou, se rozhodne na identickém náhledu před
  zápisem; nedochází k obnově ani přepočtu (ověřen nezměněný snapshot). Bez zkratky platí donorová cesta.
- **Úklid pokusů:** p.sqlite a matrix_authority neúspěšných pokusů se mažou (výchozí; přijatý stav zůstává).
- **Rychlá cesta strážce:** číselné matice procházejí bez obalování prvků.

## Nalezené a opravené problémy
1. **LIVE01 FIX1 – `ReadOnlyObject` a pywin32 CDispatch.** `callable()` je u objektů COM vrácených
   pywin32 pravdivé (`__call__` = DISPID_VALUE), LIVE01 by proto ve skutečném Visumu pravděpodobně
   odmítl `Visum.Net` jako neautorizovanou metodu. Opraveno pravidlem donorového `member_value`
   (objekt s `_oleobj_` je objekt, metoda jen skutečná Python funkce/metoda). Regresní test simuluje CDispatch.
2. **Konvergence FISTA.** Vnitřní donorový FISTA končí podle relativní změny cíle (1e-9), kordónová
   obálka vyžaduje KKT < 1e-5; na simulaci zůstalo KKT 4,9e-3 a donor správně odmítl zápis.
   Přidán žebříček vnitřních tolerancí (1e-11, 1e-13, 1e-15, 1e-30 = pevný počet iterací);
   kritérium KKT se nemění. Na simulaci KKT 1,1e-6 po 440 iteracích.

## Hranice důkazu
Testováno pouze na syntetickém hostiteli 681 zón (`tests/fake_live02.py`). Nativní běh ve Visumu
neproběhl (`NOT_RUN`). Simulace nahrazuje TG/TD/assignment jednoduchou gravitační odezvou
a nepotvrzuje skutečný účinek kandidátů ani časovou náročnost úplného capture ve Visumu.
Sémantika pozorování, časový most a C17 zůstávají neschválené (TECHNICAL_TRIAL).
