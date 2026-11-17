# Síť z 17. 11. 2026 12:44: kontrola průchodnosti vstupů

**V dodaných vstupech nebyla zjištěna nová překážka startu současného
kalibrátoru. Mapování včetně NDS45 je platné; kód ani mapování nevyžadují
další změnu. Plný nativní běh tímto exportem ověřený není.**

Kontrolovaný kalibrátor: `3a6dd167a93ac493043236c11dcea9a4065eda77`, tedy celý
balík s potvrzeným S45 remapem, časnou vstupní kontrolou a TD 55/45.
Zdroj: export `R1_FREIGHT_ODME_EXPORT_V2`, čas `2026-11-17T12:44:43`, model
`R1_VARIANTYBase_LIVE04_2025_4_LIVE04_BASE_d49e4158.ver`.

## Ověřené kontroly

| Oblast | Výsledek |
|---|---|
| Uzly / směrované hrany | 3 908 / 10 938; unikátní klíče, existující konce, bez smyček hrany na jediném uzlu |
| Kordónové stanice | Všech 32 směrů existuje a je použitelných pro OA; typy, kapacity i délky souhlasí s referencí |
| NDS / ASD / K1–K2 | Aktuální funkce `check_links` nad CSV adaptérem: **PASS**, 120 hran, 0 chybějících, 0 uzavřených |
| NDS45 | A = 99811855:99800794:1000030; B = opačný směr; původní cíle zachované |
| Dálniční režimy SDP1/3/15/16 | Původní kontrola `validate_motorways` prochází pro všech osm směrů |
| Směry +/− stanic | Explicitní mapované klíče stále existují |
| Segmenty | V metadatech je všech 12 očekávaných osobních segmentů, se správnými módy C/C_noT |
| Konektory | 1 430; všechny odkazují na existující zóny a uzly; 681 zón má oba směry pro C, C_noT, LNV i NV |
| Odbočení | 17 042; unikátní uzlové trojice a existující příjezdové/odjezdové dvojice; TURNS_ALL a 04_TURNS jsou shodné |
| Zóny | Stejných 681 NO ve stejném pořadí jako v exportu 11:41 |
| Koeficienty | Všech devět společných W/S/ZAHR pák, LONG a SCHOOL jsou konečné, nezáporné a oproti 11:41 beze změny |
| Matice C / LNV / NV | Platné zóny, konečné nezáporné hodnoty, bez duplicit, součty odpovídají metadatům v přesnosti exportu |
| Silniční dosažitelnost | Ve čtyřech módech není nedosažitelná dvojice zón ani kladná relace dodaných matic; tato kontrola ignoruje odbočovací omezení |

Pro síťovou kontrolu se skutečně použily funkce aktuálního kalibrátoru se
sloupci načtenými z exportu. Nejde o volání COM do živého Visumu.

## Co se změnilo proti exportu 11:41

- Přibylo 36 uzlů a jeden zanikl; čistá změna je +35 uzlů.
- Zanikl uzel 1000389. Souřadnice společných uzlů se nezměnily nad 1 mm;
  společné hrany mají také shodné exportované geometrie WKT.
- Přibylo 132 směrovaných klíčů, zaniklo 26; čistá změna je +106 hran.
- Přibylo šest konektorů. V zónách 83, 105 a 133 se NUMCONNECTORS změnilo
  z 1 na 2. Všechna ostatní exportovaná zónová pole jsou stejná.
- Na společných hranách jsou shodné typy, délky v přesnosti exportu, pruhy,
  kapacity, rychlosti, systémy, ADDVAL1/2/3, exportované nákladní penalizace
  a mýtné sazby.
- LNV a NV jsou byte po bytu shodné. Součet C je 2 241 055,074 oproti
  2 239 377,069 ve starším exportu. Matice C je datově platná a její součet
  souhlasí s novými metadaty; příčina změny součtu není z exportu prokázaná.

Podrobné výsledky, změněné klíče a SHA-256 všech vstupů:
[AUDIT.json](AUDIT.json). Přímý výsledek kontroly pozorování:
[EXTRA_OBSERVATION_LINKS.json](EXTRA_OBSERVATION_LINKS.json).

## Přetrvávající odhad nákladu ADDVAL1

Stále jde o stejnou sadu 15 směrů, kde z obecné rychlosti V0PRT vychází
`3600 × LENGTH_KM / V0PRT + 10 × ADDVAL1 < 0,001 s`. Nová změna sítě
nepřidala žádný takový směr a žádný z původních neodstranila.

Není to přímé měření nativního C nákladu ani důkaz, že kvůli tomu spadne start.
Export opět neobsahuje přesný T0_PRTSYS(C), TCUR_PRTSYS(C) a aktuální
impedanční funkci C/C_noT. Tento dosavadní nález zůstává k nativnímu ověření.

## Co zbývá ověřit ve Visumu

CSV neobsahují definice procedur a skriptů, TG/TD formule a b/c, skutečné
číselné vazby a typy všech matic, OSRM 9697 a jednotlivé LONG matice, utility
9700–9715 ani TTC/TT0, uložené cesty a jejich aktuální epochu. Přítomnost
kódu segmentu neprokazuje správné číslo jeho OD matice. Silniční dosažitelnost
bez odbočení neprokazuje dosažitelnost přes všechna nativní odbočení.

Pro živé ověření otevřeného modelu slouží stávající read-only skript
`RUN_R1_2025_LIVE04_READINESS.py`; aktuální konfigurace má
`readiness_baseline_capture = false`, takže znovu nepořizuje celé zachycení cest.
Následuje standardní nový běh `RUN_R1_2025_CORDON_LIVE04_V7_TG_TD_CYCLE.py`
nad aktuální uloženou a přepočtenou kopií, se zachovanými kalibrovanými parametry.

Přímé CONTINUE ze starého checkpointu není pro tuto sadu hran ekvivalentní:
reference 10 832 hran z předchozího běhu se liší od nynějších 10 938 klíčů.
Nový běh musí získat aktuální výchozí stav a incidenci.
