# Audit vzdáleností LIVE04 (18. 11. 2026)

## Zdroj a zafixování

Zdrojový checkpoint `C02_GENERATION_348fa1d3.ver` má SHA-256
`cddacecbd4ab507469bacad6808d9561b540d6f13f4eef604046a510e11fa034`.
Skript před zápisem ověřuje tento soubor, pořadí všech 681 zón, původní 9697,
čísla, kódy a SHA šesti nativních `DIS` matic. Čte i pasivní zóny. Nové matice
9720–9727 mají stejný zónový OD typ a datový zdroj jako 9697. Po zápisu ověří
hodnoty všech osmi matic a znovu zkontroluje zdrojové skimy a poměry.

| Úloha | Matice | Vznik |
| --- | --- | --- |
| Šest pevných segmentů | 9720–9725 | `DIS_NATIVE_CF/CL/CS/CS_NOT/CW/CW_NOT`, diagonála z 9697 |
| IDP WORK a SCHOOL | 9726 | 9724 × 9231 + 9725 × (1 − 9231) |
| IDP SERVICE | 9727 | 9722 × 9233 + 9723 × (1 − 9233) |
| IDP LONG a maska ≥ 80 km | 9721 | pevná `NATIVE_CL` |

9697 zůstává beze změny. Matice dojezdových časů pro samotný Trip Distribution
jsou oddělená část procedury; tento patch mění délky pro IDP a LONG podporu.

## Návaznost v běhu

- Přípravný přepočet i kalibrační adaptér vybírají 9721 pro LONG masku.
- Readiness a start kalibrace ověřují typ, kódy, diagonálu, SHA šesti zdrojových
  matic a výpočet obou odvozených matic. Běh uloží jejich SHA do
  `FROZEN_DISTANCE_AUTHORITY.json`.
- Po každém bloku a před závěrečným uložením se všech osm hodnot znovu ověří
  vůči výchozím hashům. IDP navíc hlídá své matice při každém vyhodnocení TD.
- IDP vyhodnocuje každou komponentu pouze na jí přiřazené vzdálenosti.
  Výpočet šesti používaných metrik byl porovnán s připnutou FineCDF v1.9
  referencí. Tím odpadá chybné vyhodnocení cizích komponent na jiné matici.
- Produkční pravidlo po TD bez přijaté změny přeskočí jeden další TD cyklus.
  Testy ověření a zamítnutí Jacobianu z paměti nastavují přeskočení na nulu,
  aby skutečně provedly dva TD cykly; provozní nastavení zůstává beze změny.

## Integrita a hranice ověření

Manifest, `SHA256SUMS.txt` a piny 22 donor modulů musí souhlasit. Offline testy
ověřují vytvoření matic, čtení všech zón, typy, výpočet blendů, chybné hodnoty,
IDP paritu, přepočet, readiness a kontrolu změny během běhu. Živý Visum zde
není dostupný; čerstvost assignmentu před uloženým checkpointem samotný export
nedokazuje. Pro další běh použijte postup v `FROZEN_VISUM_DISTANCE_RUNBOOK_CZ.md`.

Claudeova samostatná větev používá pro 9726/9727 jiné kódy matic
(`R1_BASE_DIS_IDP_WORK_KM` a `R1_BASE_DIS_IDP_SERV_KM`). Skript pro vytvoření
matic a kalibrátor proto berte vždy ze stejné větve.

## Změna 18. 11. 2026: univerzální zafixování

Zafixování už není vázané na checkpoint `C02_GENERATION_348fa1d3`. Skript
najde skimy `DIS` podle segmentu v libovolné uložené verzi 2025. Do výsledku
zapíše cestu a SHA-256 zdrojové verze a otisky všech matic. Kalibrátor nemá
napevno zapsané otisky z C02. Autoritou pro běh jsou otisky zaznamenané při
jeho startu (`FROZEN_DISTANCE_AUTHORITY.json`) a jejich kontrola po každém
bloku. Typ datového zdroje se porovnává číselně, protože Visum COM vrací
`DATASOURCETYPE` jako `1.0`.

## Audit řetězce 18. 11. 2026 odpoledne

Hodnoty z Visum COM jsme porovnali se skutečným modelem (`INVENTORY_2025.json`,
`COM_API_PREFLIGHT.json`, seznam matic, export `DIS`).

- **Typ matice:** Visum vrací `MATRIXTYPE_DEMAND`, `OBJECTTYPEREF_ZONE` a
  `DATA`/`FORMULA`. Kontrola znala jen `MATRIXTYPE_OD`, a proto start odmítl
  9697. Opraveno v kalibrátoru i ve skriptu pro zafixování. Chybová hláška teď
  vypíše skutečně přečtené hodnoty.
- **Testy:** simulovaný Visum vracel typy jako čísla (2, 3), proto testy chybu
  nezachytily. Simulace teď vrací stejné řetězce jako skutečný model.
- **Poměry 9231/9233:** jsou to vzorcové matice, které krok R1 20D přepisuje
  při každém přepočtu. Při `DT_MODE = 'LIVE'` by se řídily skimy běhu a
  kalibrace by spadla až po prvním bloku. Kontrola na začátku teď odmítne
  vzorec závislý na skimech.
- **Izolovaná kopie:** skript pro zafixování kontroluje název souboru stejně
  jako RECOMPUTE, ještě před zápisem.
- **Číslo matice:** čte se z hodnot `9720.0` i `"9720"`.
- **Ověřeno na skutečných `DIS`:** žádné buňky bez trasy ani nuly, maximum
  437 km. Zafixování i kontrola kalibrátoru projdou. IDP má na nových
  vzdálenostech pro každou složku dost relací (LONG 32 262).
- **Beze změny:** LONG maska, RECOMPUTE, readiness a IDP čtou stejnou 9721,
  respektive 9726/9727. Výpočet IDP po složkách je totožný s referencí
  FineCDF v1.9.
