# Oprava identit pozorování v zónovém refitu

Základ: `0aeafc153688909911e1792692289a4792106bee`, stejný strom jako lokální
`c62120883f1e828eb3f6ee9da385839d581a6132`.

## Co potvrzují dodané výsledky

GENERATION skončila jako `CONFIGURED_GENERATION_SEARCH_EXHAUSTED`, nikoli pádem.
První plný pokus měl hlavní objective 212007.0794 → 206812.2377 (−2,4503 %),
ale EXACT_TWO_HITS 26631.0091 → 27145.0171 (+1,9301 %). Byl odmítnut z důvodu
`SECONDARY_METHOD_DEGRADED`. Další menší krok neprošel predikční branou.
Rollback uvádí shodu snapshotu a matic; řádkový důkaz při novém plném zachycení
má maximální odchylku 0 pro všechny tři metody. Podpis cest byl odlišný,
proto se použila existující kontrola shody výsledných řádků.

`MEASURED_ZONAL_REFIT.json` obsahuje `REFIT_UNAVAILABLE` a
`V24917_REFIT_PARENT_DIAGNOSTICS_MISMATCH`. Z těchto výsledků nelze určit,
jak dopadne případný nový zónový směr v příštím živém pokusu.

## Skutečná příčina: kolize číselného klíče

`pair_key(a,b)` používal `100*a+b`. To fungovalo pro původní ID stanic
a pomocných řádků menší než 100. LIVE05 ale přidal ID řádků 1000–1129 a
skupiny NDS=20, ASD=21, KMOV=22. Po obousměrném sloučení je klíč ve tvaru
`(skupina, ID řádku)`.

Například `(21,1000)` pro `ASD1_Malinovo` a `(20,1100)` pro `NDS_S51A`
daly oba číslo 3100. Ve výchozích 130 doplňkových pozorováních je 12
takových kolizí, tedy pouze 118 různých starých klíčů.

Samotný lineární fit měl samostatné řádky podle jejich pozice. Kolize ale
poškodila následné slovníkové mapování efektových operátorů do diagnostiky
a měřeného refitu. Při refitu se první řádek porovnal s modelem jiného
pozorování a původní přísná kontrola ho správně odmítla. Stejný klíč používala
tabulka profilů SupplyMix, kde mohl jeden záznam přepsat druhý.

Nejde tedy o nutnost vynechat směrové profily nebo doplňková pozorování.
Všechny zůstávají součástí svého původního cíle.

## Oprava

- Pro obě ID pod 100 se zachovává původní číslování, např. `(1,2) → 102`.
- Rozšířené dvojice používají jednoznačné Cantorovo párování v odděleném
  rozsahu od 10000. Pořadí dvojice je zachované; nejde o nové sloučení směrů.
- Konstrukce incidence, efektových operátorů a profilové tabulky SupplyMix
  kontroluje jednoznačnost a nesmí tiše přepisovat záznamy.
- Refit zachovává původní kontrolu rodičovských hodnot a navíc ověřuje
  úplnost a konečnost měřeného vektoru. Audit obsahuje `row_mapping` s metodou,
  počtem pozorování, počtem fitovaných řádků a verzí klíče.

Akceptační objective, váhy, GEH/mobilitní ochrany, kalibrační meze, rozpočet
pokusů ani `secondary_max_relative_degradation` se nemění. Povolené zhoršení
sekundární metody v GENERATION zůstává 0 %. Případný přepočítaný návrh musí
projít stejným plným nativním vyhodnocením a původními branami.

## Ověření a použití

Reprodukce v oddělené kopii původního commitu odhalila kolize, nesprávnou
predikci efektu a stejnou chybu refitu jako živý log. Po opravě se ověřuje
298 jednoznačných sémantických klíčů v aktuálním prostoru, zachování původních
ID, dvě samostatné naměřené změny v opravdovém zónovém solveru, oba efektové
operátory a všech 130 identit v tabulce SupplyMix s kladnými syntetickými cíli.
Skutečný nesoulad rodiče,
neúplný vektor i duplicitní pozorování se dál odmítají.

Test 298 klíčů pracuje s výchozím kontraktem a pevnými sémantickými klíči
směrových profilů; neprovádí živé přiřazení jejich znamének. Unit test refitu
používá malou incidenci, skutečný fit/solver a náhrady mobilitních bran.
Samostatná syntetická regrese řídicího cyklu ověřuje druhý refitovaný návrh
po odmítnutém prvním pokusu nad historickým mock schématem.

Přesné výsledky a hashe příloh jsou v `evidence/refit_identity_20261116/`.
Živý Visum zde spuštěný nebyl. Není potvrzeno, že nový směr projde skutečnou
sekundární branou ani jaké přinese zrychlení nebo zlepšení kalibrace.

Použít celý nový balík při dalším spuštění a restartovat Visum kvůli modulům
uloženým v paměti. Skript operace 15 ani připravené utility se touto opravou
nemění; do již běžícího modelu oprava sama nezasahuje.
