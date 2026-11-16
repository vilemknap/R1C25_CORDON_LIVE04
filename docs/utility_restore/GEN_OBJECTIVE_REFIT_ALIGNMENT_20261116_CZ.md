# Sjednocení cíle Generation, měřený refit a návaznost bran

Základ: `9fe9cb8e3ffb5bbc8870b154f4330387777023ac`.
Zůstávají opravy utility transakce, COM kontextu, zotavení, identit pozorování,
přesné TD pojistky a uživatelem zvolené GENERATION +2 % / TD 50:50.

## Dodané podklady

Přílohy odpovídají běhu `LIVE04_TGTD_98c4c9cb1092` ze stejné zdrojové kopie
`R1_VARIANTYBase_LIVE04_2025_2_LIVE04_BASE_48fb232a.ver`.
`CYCLE_PROGRESS.json` má 0 přijatých stavů a vyčerpané hledání GENERATION.
Poslední `00_PROGRESS.json` je čtení podpisu cest při zotavení TD
(`recovery_depth=1`); dokončený důkaz tohoto zotavení mezi přílohami není.

Vložený výpis původní GENERATION má jako jediný důvod odmítnutí
`SECONDARY_METHOD_DEGRADED`: FIRST_LAST se zlepšil o 2,4503 %, EXACT_TWO_HITS
se zhoršil o 1,9301 %. V aktuálním balíku je pro GENERATION už zvolen limit
2 %. Změna plánovacího minima popsaná níže nebyla příčinou tohoto konkrétního
historického odmítnutí; odstraňuje další, samostatnou překážku hledání.

Starší vložený kód refitu používal `100*a+b`. Jeho kolize pro rozšířené
řádky už byla opravena v základním commitu. Nadále se používají jednoznačné
ID, skutečný rodič se musí shodovat a chybějící či duplicitní pozorování se
odmítají. Hashy všech nových 17 příloh jsou v přiloženém auditu.

## Opravené nesoulady

1. **Jedna datová část cíle pro návrh a přijetí.** Zónový fit přebírá přesně
   `w`, `y` a nulový deadband z `_terms` platné zachycené diagnostiky. Používá
   tedy stejné skupinové koeficienty i normalizaci intenzitou jako
   `objective_from_model`: `Q = 0,5 Σ [w_i (M_i − O_i)]²`.
   Původní GEH váhy donoru se po sestavení efektového operátoru nahradí
   těmito autoritativními váhami; ve fitu odpadá dodatečné násobení rezidua
   chráněných profilů 3×. Samostatné GEH a severity pojistky zůstávají aktivní.

2. **Nulová pozorování se neztrácejí.** Donor při konstrukci G přijme pro
   nulový cíl pouze technickou kladnou hodnotu; před řešením i souhrnem se
   obnoví přesný původní cíl 0 a jeho skutečné reziduum. Modelové hodnoty
   pocházejí z kanonického zachyceného vektoru. Žádná změna pozorování ani
   zápis OD matice tím nevzniká. Přímé testy ověřují všech 298 identit.

3. **Stejné minimum zlepšení.** Plánovač už nepoužívá 0,1 % převzaté z
   nastavení first-sufficient jako další podmínku přijatelnosti. Bere přímo
   `acceptance.min_relative_improvement = 0,001 %` (`1e-5`), stejně jako
   finální brána. Ostatní relativní a absolutní podmínky kontroluje táž
   akceptační funkce při predikci i po přiřazení.

4. **Měřený refit zachová datový cíl a ověří totožnost řádků.** Kontrolují se
   modelové vektory, skutečný rodič, pořadí dvojic a autorita vah/cílů.
   Broydenova oprava dál musí reprodukovat naměřený účinek realizované změny.
   Refit nekopíruje sekantový účinek na jiný směr bez nového modelu. Původní
   matice G, cíle, váhy a metadata problému se při refitu nemění.

5. **Stejná použitelnost návrhu před refitem a po něm.** Numericky
   nedokonvergovaný výsledek se smí stát návrhem pro skutečný pokus, pokud
   má konečný a zlepšený cíl, stejně jako při prvním návrhu. Musí dál projít
   mobilitou, preview i plným nativním hodnocením. Jeho flag
   `solver_converged=false` se propíše do bloku a nemůže založit certifikát
   stacionarity. Nezlepšený nedokonvergovaný refit se dál nepoužije.

6. **Vysvětlení zmenšení robustností.** Donor výběru škály zůstává beze změny,
   včetně rezervy 15 %. Když bod sám projde a jeho zvětšená sonda neprojde,
   STEP1 plán nově zapíše `robust_probe_scale` a `robust_probe_reasons`.
   Tato kontrola zůstává úmyslnou rezervou nad finálními podmínkami.

## Zachované podmínky

- Skupinové koeficienty 70 % kordón / 15 % NDS / 10 % ASD / 5 % pohyby.
- Finální GENERATION: hlavní cíl se musí zlepšit, EXACT_TWO_HITS nejvýše +2 %
  vůči rodiči. SupplyMix má původní sekundární limit 0 %.
- TD: 50 % normalizované Q / 50 % FineCDF IDP, `F ≤ 0,999`, současně nejvýše
  +1 % hlavního i sekundárního kordónového cíle a původní komponentní IDP guard.
- Profilové GEH/severity, mobilita, role koeficientů, P/A balance, LONG maska,
  přiřazovací gap, přesný readback, potvrzení akceptace a ověřený rollback.
- Původní počet pokusů, nejmenší škála, důvěrové pásmo refitu a pravidlo
  zastavení po průchodu všech bloků bez přijaté změny.

Regularizace a P/A omezení nad datovou částí fitu zůstávají součástí návrhu.
Jde o lokální lineární odhad; nativní přiřazení může změnit trasy a vést k
odmítnutí návrhu. Nové kolo proto nemá zaručené přijetí ani velikost kroku.
Aktuální vydaná konfigurace má nulový deadband. Nový fit odmítne neověřené
váhy, jiné cíle či nenulový deadband před řešením, místo tichého nesouladu.

## Ověření a použití

Výsledky jsou v `evidence/gen_alignment_20261116/`. Pokrývají přesnou shodu
datové ztráty pro náhodné směry, nulové cíle, všech 298 identit, ochranné
brány, refit po skutečně simulovaném odmítnutí a následný plný pokus.
Testy numerického refitu používají skutečný zónový solver a náhrady mobilitních
bran; integrační test používá celý syntetický řídicí průchod.

Použít celý nový balík pro další běh po restartu Visumu. Spouštěcí soubor je
`RUN_R1_2025_CORDON_LIVE04_V7_TG_TD_CYCLE.py`.
Živý Windows/Visum zde nebyl dostupný; celá historická sada spuštěna nebyla.
