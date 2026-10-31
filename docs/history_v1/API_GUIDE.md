# Integracni API offline V1

`cordon2025.authority.audit_workbooks(source_dir, output_dir)`
Cte originaly D1/D2/D3 pomoci openpyxl read-only, kontroluje labels, cisla,
zdrojove hashe a lineage. Nevypocitava Excel formule a neopravuje workbooky.

`build_from_snapshot(path, station_map, cfg, evidence, hits_output=None)`
Vraci dict dvou `Incidence` objektu. Presna hodnota geometrie v cache je
pouzita pouze jednou. Zdroj je SQLite mode=ro, query_only. Neni zde route
search ani propojeni na Visum. Binarnim hypotezam odpovidaji rozlisene vystupy.
V `r1_15a2_two_mode_v238.TwoModeRouteCollector` je novy opt-in hook
`cordon_incidence_offline`, delegujici stejnemu modulu. Puvodni `incidence`
a jeho blokace `TWO_MODE_CORDON_INCIDENCE_NOT_IMPLEMENTED` zustaly zachovane.

`Incidence.operator`: T[r,k]=p[r|k]*Q[k], zmena RELATIVNIHO x -> vozidla.
`Incidence.share_operator`: H[r,k]=T[r,k]/Q[k], zmena delta_Q -> vozidla.
`model`: fixed+mutable; `fixed` nikdy neni actuated. `projection_base_variables`
obsahuje uplne mutable-family P/A zakladny, ne jen prave vybrane sloupce.
`all_od_totals` uchovava i collateral/fixed scope pro naslednou kontrolu.

`aggregate_observations(inc, targets, bidirectional=True, roles=None)`
Pouze algebraicke sdruzeni smeru. Missing neni nula. Role protismeru nesmeji
uniknout do jine skupiny. D3 sumou neziskava puvodni merenu smerovou informaci.

`SharedBudget.project(vector)`
Dykstrova projekce na nezaporny, spolecne omezeny kreditni polytope. Kontroluje
zmenu primalu I korekci, nejen zdani stacionarity. `ledger` kontroluje cerpani.
Kreditni pravidlo je popsano v C17_ACCOUNTING_SPEC.md; neni odhadem OD vozidel.

`solve(inc,cfg,budget=None,allow_unapproved_scenario=False)`
Sestavi puvodni `GuidanceProblem`/`SparseOperator`; x-blok resi skutečny
`r1_15a2_core.solve_guidance`. Volitelny deadband je novy posledni parametr
GuidanceProblem s defaultem None. Původni quadratic/l1/l2/bounds cesta je tim
zachovana. Resic neposila pokyny do Visumu, pouze tvori shadow guidance.
CALIBRATION se optimalizuje, VALIDATION jen reportuje; budgets validaci necerpa.
Konvergence se kontroluje proximalnim gradientovym mapovanim x i u.

`parent_projection(inc,solution,cfg,zone_rows=None)`
Vola originalni `project_guidance_to_add`. Pokud je dodana actual audited
zonalni authority, muze zavolat i stavajici generation design. Bez ni vraci
ZONE_PARAMETER_AUTHORITY_NOT_SUPPLIED. Vysledek neni certifikat full-OD realizace.

`evaluate_realizability(inc,solution,basis=None)`
Bez basis -> TG_TD_REALIZATION_NOT_VERIFIED. S explicitni full-OD basis
(klice, meze, povolene TG/TD parametry, provenance) resi druhou ulohu stejnym
parent resicem. Zahrnuje collateral scope a kontrolu zakazanych/fixed radku.
EXACT_SYNTHETIC_LINEAR umoznuje dukaz INFEASIBLE_TG_TD pro uvedeny synteticky
model. AUDITED_LOCAL_JACOBIAN dovoluje pouze lokalni linearizovany zaver.

`finecdf_availability()`
Jen hash-locked import puvodniho FineCDF reference modulu. Neni to nativni TD run.

Puvodni CSD-only `prepare_guidance_problem` se pro kordon nepouziva: jeho
vyber profilu, pozitivni target filtry a GEH vahy nejsou survey authority 2025.
Neprebirame produkcni CSD config 2022. Prime OD write ani libovolne Vol(AP)
nasobeni v modelu nebylo pridano.
