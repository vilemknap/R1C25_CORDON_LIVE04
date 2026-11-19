# LIVE04.14 – Prostorová regularizace Generation, paměť účinnosti a IDP-aware krok

Rozhodnutí uživatele 19. 11. 2026 („implementuj je, pak je budeme ladit a testovat za běhu").
Ověřeno jen syntetickými testy, ne nativně v PTV Visum. Všechny váhy jsou **výchozí hodnoty
pro ladění** v `CORDON_LIVE04_CONFIG.json`.

## Proč

Zonální fit Generation penalizoval jen krok jednoho cyklu (`ridge` na x). Kroky se sčítaly
v zónách, jejichž OD vztahy procházejí profily, až narazily na stropy 3,5 / 7,0 (např. Veľké
Úľany P_W 3,26, A_W 5,29 při sousedech na 0,33). Fit neznal rozdíl mezi produkcí a atrakcí
a neučil se z naměřených pokusů.

## Co se mění (jen návrh kroku; nativní přijetí je beze změny)

V log prostoru koeficientů platí y = l + x, kde l = log(současný / cíl) a x je krok. Cíl je
`anchor_target`: `UNIT` = koeficient 1, nebo `RUN_START`.

| Část | Penalizace | Parametr |
|---|---|---|
| Kotva produkce | (R_z − 1)², R_z = Σ_f w_zf · c_zf / t_zf = skutečný poměr produkce k referenci (w = podíl FP WORK/SERVICE na začátku běhu), linearizovaný v současném stavu | `production_anchor_relative` |
| Slabá kotva po rodinách | y_zf² | `production_family_anchor_relative` |
| Okolí produkce | (y_zf − Σ_u K_zu · y_uf)², kde K = obyvatelé × exp(−d/decay) do `neighbour_radius_km` na zmrazené matici 9697, max. `neighbour_max` sousedů, × podobnost cílových podílů z referenční OD (`neighbour_destination_similarity_weight`) | `neighbour_relative` |
| Atrakce podle centrality | váha_z · y_z², váha = min + (max − min) · (1 − c_z)^p | `attraction_anchor_min/max_relative`, `attraction_centrality_power` |

**Centralita c_z** = 0,5 × percentil referenčního potenciálu + 0,5 × percentil efektivního počtu
zdrojových zón. Referenční potenciál je u WORK `NUM_PM`, u SERVICE `FA_2_SERVICE` vydělené
koeficientem atrakce na startu. Efektivní počet zdrojových zón je exp(entropie příjezdů)
v osobních OD 9101–9110 na startu běhu.

- Centrum s mnoha zdrojovými zónami (Bratislava, Galanta, Senec) má atrakci volnou.
- Malá obec ji má pevně u cíle.
- Žádné pevné přiřazení satelitu k jednomu centru.

Všechny váhy jsou relativní k mediánu datové křivosti fitu (jako dárcovský `ridge_relative`).
Box, P = A nadroviny, MOBILITYZONE1, mobilita, IDP a nativní přijetí zůstávají.

**Okolí s pevnou zónou:** člen okolí zóny z vznikne vždy, když je proměnnou aspoň jedna zóna s nenulovým koeficientem (střed nebo soused). Neoptimalizovatelné zóny vstupují jako konstanty (např. pevná zóna s koeficientem 1 táhne proměnného souseda k sobě), z výpočtu se nevypouštějí.

**Zóny bez obyvatel (průmyslové)** nemají kotvu ani okolí produkce (podíl FP 0, bez sousedů).
Jejich pracovní atrakce je řízená centralitou (NUM_PM), takže zůstává kalibrovatelná.

## Paměť účinnosti (`efficiency_memory`)

- Faktory η_g pro skupiny g = rodina × role (4 čísla, nikdy ne zóna) násobí sloupce lineárního
  efektového operátoru ve fitu i v predikci pokusu.
- Po **každém platně změřeném** pokusu Generation (přijatém i odmítnutém) se aktualizují
  regularizovanou sekantou: min ‖W(Δ_naměřené − Σ_g η_g c_g)‖² + μ‖η − η_předchozí‖²,
  ořez na [`eta_min`, `eta_max`], vyhlazení `smoothing`.
- Z naměřené změny se nejdřív odečte část, kterou už předpověděla paměť tras (route-choice
  memory), aby obě paměti nemodelovaly stejné reziduum dvakrát.
- Aktualizace je transakční: když se nový stav nepodaří uložit, faktory v paměti se vrátí.
- Neplatný záznam pokusu (`valid = false`) se nikdy neučí, ani do η, ani do IDP modelu.
- Stav paměti (η i IDP model) se ukládá ke stavu modelu: `GENERATION_MEMORY_SNAPSHOTS.json`
  mapuje `state_hash` → paměti v okamžiku, kdy se stav stal přijatým (první zápis platí).
  Pokračování načte paměti přesně otevřeného stavu (checkpoint C01 nikdy nedostane paměť z C03).
  Načtené η se ověří (4 skupiny, konečné hodnoty, stejná reference) a ořízne na aktuální meze.
- Paměť nikdy nerozhoduje o přijetí. Chyba její aktualizace se jen zapíše.

## Etapa B – IDP-aware krok (`idp_guard.generation_prediction`)

- IDP metriky (RMSE_k, e_k) jako lineární funkce průměrného log kroku ve 4 skupinách,
  Broydenova aktualizace z každého změřeného pokusu.
- Před pokusem se z modelu spočítá největší měřítko kroku, při kterém předpovězené IDP spotřebuje
  nejvýš `slack_use` (0,7) zbývající lokální i kumulativní rezervy. Tím se omezí horní mez měřítka.
- Bez naučeného modelu, bez předpovězeného zhoršení nebo s limitem pod `min_scale` se nic
  neomezuje. O přijetí vždy rozhoduje naměřené IDP.

## Reference běhu

`capture()` na začátku nového běhu přečte (jen čtení COM):

- POP_ZP;
- ADD_PROD/ATT_W/S;
- FP_1_WORK_* a FP_2_SERVICE_*;
- potenciály;
- osobní OD 9101–9110;
- matici 9697.

Uloží se odvozené veličiny: podíly, centralita, seznamy sousedů s vahami, cílové koeficienty,
parametry a `record_sha256`. Záznam jde do `RUN_ANCHORS.json` (`generation_structure_reference`),
pokračování ho převezme a ověří (hash, parametry). Chybějící nebo změněný záznam zastaví běh.

## Soubory

- `cordon2025/live04_generation_structure.py` – reference, penalizace, řešič, paměť účinnosti.
- `cordon2025/live04_generation.py` – zapojení do fitu, měřeného refitu a predikce.
- `cordon2025/live04_step1.py` – učení paměti po pokusu, omezení měřítka podle IDP.
- `cordon2025/live04_idp_run.py` – `GenerationIdpModel` (etapa B).
- `tests/test_live04_14_genstruct.py`, `tests/test_live04_13_idp_run.py`.

## Ladění za běhu

Pro každý cyklus sledujte:

- `C0x_GENERATION/DESIGN/V7_TARGETED_GENERATION/V24917_FIT_SUMMARY.json` → `fit_summary.genstruct1`
  (penalizace, η, konvergence);
- `GENSTRUCT1_EFFICIENCY.json`;
- `STEP1_PLAN_xx.json` → `idp_scale_cap`;
- `TRY_xx/IDP_TRIAL.json` a rozhodnutí `idp_guard` v `ACCEPTANCE.json`.

Každou část lze vypnout nulovou vahou nebo `enabled: false`. Váhy penalizace lze mezi
pokračováními měnit. Parametry, ze kterých se reference počítá (cíl kotvy, matice a okruh
okolí, počet sousedů, podobnost cílů, atributy potenciálu), změnit nelze, protože pokračování
by se zastavilo. Pro jiné hodnoty je potřeba nový běh.

V auditu řešiče (`genstruct1.objective_parts_*`) je penalizace uvedena včetně konstantního
členu, takže je to úplná, nezáporná hodnota srovnatelná mezi cykly.

## Pokračování a reference (revize 19. 11. 2026)

- **Přesný stav:** pokračování vyžaduje úplnou shodu `state_hash` otevřeného modelu s přijatým
  stavem. Při rozdílu se běh zastaví a chyba vyjmenuje rozdílné části (pokud je checkpoint zná).
- **Plán bloků:** `td_skip_until` a nezměněné bloky se ukládají do `CYCLE_PROGRESS.json`
  i do checkpointu a obnoví se. Index dalšího bloku se ověří podle jeho názvu.
- **RUN_ANCHORS.json** má obsahový otisk `anchors_sha256` (bez rostoucího `chain`).
  Změněné nebo nezapečetěné kotvy pokračování odmítne.
- **Paměti vázané na stav** (`GENERATION_MEMORY_SNAPSHOTS.json`) obsahují η, IDP model
  i RunMemory z LIVE04.1 (TD Jacobian s IDP rysy, korekci tras, křivost). Záznam nese svůj
  `state_hash` uvnitř kontrolního součtu.
  - Chybějící záznam znamená čerstvé paměti a zapíše se to.
  - Poškozený soubor, změněný, přesunutý nebo odmítnutý záznam běh **zastaví**.
  - Pro čerstvé paměti je potřeba soubor vědomě smazat.
- **Start z koeficientů 1** (`reference_start_policy = REQUIRE_UNIT_WS_ON_ACTUATABLE_DOMESTIC_ZONES`):
  referenci (centralitu, vazby OD, podíly produkce) lze zachytit jen z modelu, kde ADD_PROD_W/S
  a ADD_ATT_W/S jsou na všech aktuátorových domácích zónách přesně 1. Jinak se běh zastaví
  s počtem a příklady zón. `ACCEPT_CURRENT_MODEL` to výslovně povolí a stav zapíše.
- **Čtení zón:** indexovaným čtením (Zone.NO, omezené opakování COM). Prázdné hodnoty
  i NaN jsou chyba. Na další atribut potenciálu se přejde jen při „attribute not found“.
- **Centralita:** rozmanitost zdrojů je násobena spolehlivostí objemu příjezdů
  1 − exp(−V/V50), takže zóna s nepatrnými rozptýlenými příjezdy není centrum.
- **Etapa B:**
  - Učí se z rysů skutečně aplikovaného kroku (implementované efekty preview), ne z projekce.
  - Zapisuje chybu předpovědi mimo vzorek. Model, jehož poslední předpověď byla horší než
    „beze změny“, krok neomezuje.
  - Uložení je transakční.
