# Aktuální síť 17. 11. 2026 11:41: NDS45 a časná kontrola

**Vyřešeno následným potvrzením uživatele:** NDS_S45A/B jsou přemapovány na
99811855 se zachováním směrů. Aktuální stav a úspěšnou kontrolu popisuje
[sloučená oprava](../nds45_remap_20261117/REPORT_CZ.md).
Následující text a přiložené záznamy zachycují stav před tímto přemapováním.

**Nativní pád je reprodukován i na nově dodaném exportu. Chybí oba směry
hrany 2004381 pro NDS_S45A/B. Technická oprava přesouvá kontrolu před drahé
zachycení cest, ale nenahrazuje rozhodnutí, kde leží skutečné sčítací místo.**

Aktuální podklad: `R1_VARIANTYBase_LIVE04_2025_4_LIVE04_BASE_d49e4158.ver`,
export `R1_FREIGHT_ODME_EXPORT_V2`, čas `2026-11-17T11:41:04`.
Uživatel potvrdil, že síť po předchozích `nodes.csv` a `links.csv` ještě upravil.
Výsledky předchozího auditu proto popisují starší stav, ne tento model.

## Potvrzená příčina pádu

Původní hrana `2004381:1000030:1000082` a její opačný směr již neexistují.
Po původním úseku nyní vede řetězec:

`1000030 —99811855→ 99800794 —99811856→ 99800795 —99811857→ 99800792 —99811844→ 99800791 —99811842→ 1000082`.

Součet délek je 1 548,555 m, původní export uváděl 1 548,554 m.
Přibyly však také místní napojovací hrany a exportované intenzity jednotlivých
částí se liší. Výběr libovolné části nebo části s nejlepším fitem by mohl změnit
význam pozorování. Polohu NDS45 nový export neobsahuje; očekává se číslo
odpovídající nové hrany, souřadnice nebo kilometráž sčítacího místa.

Cíle NDS_S45A = 39 799 a NDS_S45B = 42 441, jejich váhy a řádky zatím zůstávají
zachované. Žádné pozorování není vypnuto a neexistuje automatický fallback.
Podklady: [kandidáti](evidence/NDS45_CANDIDATE_LINKS.csv),
[reprodukce vstupní kontroly](evidence/EXTRA_OBSERVATION_LINKS.json).

## Opravený nedostatek startu

Dosavadní `live04_cycle.run` nejprve zachytil všechny cesty a až poté ověřil
hrany doplňkových pozorování. Nyní kontrola probíhá po identifikaci modelu,
ještě před vytvořením baseline evaluatoru, zachycením cest a kalibračními zápisy.

`EXTRA_OBSERVATION_LINKS.json` nově obsahuje identitu otevřené verze, počet a
otisk skutečně přečtených klíčů a systémů, konkrétní postižená pozorování a
existující hrany stejného čísla nebo okolí původních uzlů. Kandidáti jsou pouze
diagnostika. Při selhání se ze stejných čtyř COM čtení uloží také úplný seznam
klíčů `EXTRA_OBSERVATION_NETWORK_KEYS.csv`. Režimy C_noT a C_NOT se sjednocují.
Neshodné pokrytí sloupců a duplicitní klíče nejsou přijaty.

Regrese zahrnuje dříve platný export, rozdělený úsek s přesně těmito dvěma
pozorováními, zachování blokace uzavřených hran, pořadí COM sloupců, názvy
režimů a skutečný vstup controlleru, v němž se baseline vůbec nesmí zahájit.
Spolu s původními testy doplňkových řádků prošlo 13 testů. Živý Visum zde
nebyl spuštěn. Jde o technickou opravu startu, nikoli o hotové přemapování NDS45.

## Další ověřené vstupy

- 3 873 uzlů, 10 832 směrovaných hran, 1 424 konektorů, 17 014 odbočení a 681 zón.
- Proti předchozímu exportu je 258 nových a 40 zaniklých směrovaných klíčů.
- Na společných hranách se nezměnily typy, kapacity, rychlosti, pruhy, systémy
  ani délky nad toleranci zaokrouhlení exportu.
- Všech 32 kordónových směrů existuje a souhlasí typ, kapacita a délka.
- Konektory odkazují na existující objekty; každá zóna má konektor pro OA
  v obou směrech. Odbočení mají existující vstupní i výstupní uzlové dvojice.
- Matice C/LNV/NV mají platné zóny, konečné nezáporné hodnoty, bez duplicit;
  součty odpovídají metadatům v přesnosti exportu.

Tyto kontroly nepotvrzují úplnost implicitních odbočení, aktuální uložené cesty,
utility, skimy, jednotlivé LONG matice a jejich masku ani odezvu modelu na nový
kalibrační krok. Podrobnosti a SHA vstupů: [CURRENT_NETWORK_AUDIT.json](evidence/CURRENT_NETWORK_AUDIT.json).

## Samostatný nález: ADDVAL1 na rozdělených hranách

Ve směru 1000082 → 1000030 má všech pět částí ADDVAL1 = −2. Při dosavadním
přepočtu 10 s na jednotku jde v součtu o −100 s. Pokud se při rozdělení měla
zachovat jediná původní úprava −20 s, její účinek se tím znásobil.

U 36,093 m dlouhé části 99811844 vychází z obecné V0PRT = 90 km/h volný čas
1,44372 s a odhad `t0 + 10 × ADDVAL1 = −18,55628 s`. Ze stejných exportovaných
veličin vychází nekladný minimální náklad v 15 směrech, z toho čtyři patří do
nově rozděleného koridoru NDS45. Pro přesné nativní rozhodnutí je nutné načíst
`T0_PRTSYS(C)` a ověřit aktuální impedanční funkci; odhad z obecné rychlosti
není vydáván za jejich přímé měření. Audit hodnoty ADDVAL1 nemění.

Tento nález nezpůsobil doložený traceback. Doložený běh skončil na chybějícím
mapování před kalibračními zápisy. Nastavení cílů a pojistek, včetně TD 55/45,
se technickou opravou nemění.
