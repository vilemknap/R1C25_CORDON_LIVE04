# Jednorázové zafixování vzdáleností pro další běh LIVE04

Zdroj: uložený checkpoint `C02_GENERATION_348fa1d3` s SHA-256
`cddacecbd4ab507469bacad6808d9561b540d6f13f4eef604046a510e11fa034`.
Tato větev nemění již běžící kalibraci.

1. Otevřete uložený checkpoint ve složce
   `C:\Users\vilem_knap\Documents\VISUM\v45\2025\`. Můžete pracovat i s jeho
   byte-identickou kopií; upravená nebo znovu uložená zdrojová verze vstupní
   kontrolou neprojde.
2. Spusťte `RUN_R1_2025_FREEZE_VISUM_DISTANCES.py`. Skript zkontroluje verzi,
   pořadí zón, matici 9697 a šest zdrojových matic `DIS`. V otevřeném modelu
   vytvoří osm datových matic 9720–9727 a ověří jejich zpětné čtení. Nemění 9697
   a neukládá `.ver`. Stav zapíše do
   `%LOCALAPPDATA%\R1C25_DISTANCE_PREP\FROZEN_DISTANCE_RESULT.json`.
3. Ve **stejném otevřeném Visumu** spusťte
   `RUN_R1_2025_RECOMPUTE_FOR_LIVE04_BASE.py`. Znovu spočítá poptávku a přiřazení,
   aplikuje LONG masku podle pevné matice 9721 a uloží nový `*_LIVE04_BASE_*.ver`
   vedle otevřeného checkpointu. Zkontrolujte `RECOMPUTE_*/00_RESULT.json`.
4. Otevřete nový uložený `.ver`, spusťte `RUN_R1_2025_LIVE04_READINESS.py`
   a po `READY_FOR_LIVE04` spusťte nový kalibrační cyklus.

Matice 9720–9725 ukládají šest nativních délek podle segmentu. Pracovní a školní
IDP používá 9726, váženou délku CW/CW_NOT podle matice 9231. Služební IDP
používá 9727, váženou délku CS/CS_NOT podle matice 9233. LONG IDP i maska
používají 9721 `NATIVE_CL`. Diagonála všech osmi matic přebírá intrazonální
vzdálenosti z 9697, protože nativní `DIS` má na diagonále nuly.

Při chybě po vytvoření matic zavřete změněný model **bez uložení** a znovu
otevřete původní kopii checkpointu. Živý průchod ve Visumu tato větev ještě
nemá; offline testy ověřují vazby, výpočty a integritu balíku.
