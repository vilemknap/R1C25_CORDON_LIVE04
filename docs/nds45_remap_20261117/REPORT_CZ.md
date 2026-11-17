# NDS45: potvrzené přemapování na 99811855

**Příčina pádu na NDS_S45A/B je opravena.** Obě pozorování používají nový úsek,
který uživatel potvrdil v aktuální síti:

| Pozorování | Původní klíč | Nový klíč | Cíl RPDI |
|---|---|---|---:|
| NDS_S45A | 2004381:1000082:1000030 | **99811855:99800794:1000030** | 39 799 |
| NDS_S45B | 2004381:1000030:1000082 | **99811855:1000030:99800794** | 42 441 |

A vede do uzlu 1000030, B z něj. Zachovány jsou cíle, váhy, pořadí a počet
130 doplňkových řádků. V CSV se změnily pouze dvě pole `in_link`.

Podkladem je uživatelovo potvrzení a dodaný `R1C25_S45_REMAP_PATCH.zip`.
Geometrické výsledky uvedené v patchi (medián 0,2 m, překryv 1,00 a jediný
kandidát) jsou zaznamenány v provenienci jako dodané podklady. Tento merge
znovu nezpracovával původní geometrii sčítacího profilu.

## Sloučení do aktuální verze

Patch je založen na starším manifestu s 1 987 soubory; aktuální základ
`8b55068b28638d30d43506ac11f00295cc77e7da` měl 2 003 souborů a novější opravu
časné kontroly mapování. Proto se převzaly pouze tabulka pozorování a její
provenience a aktualizoval se datový SHA v obou konfiguracích. Manifesty se
vytvořily nad celým současným vydáním. Přesný rozbor změn je v
[PATCH_REVIEW.json](evidence/PATCH_REVIEW.json).

Aktivní `observations.extra_observations.file_sha256` je:

`5b9e2206e23ad07866edd8c63dbb0583bfd9a2c48b299ea60d2e6e3ae83c35cb`.

Zachována je kontrola ještě před zachycením cest, včetně konkrétních postižených
pozorování a seznamu klíčů aktuální sítě při budoucí chybě. Zůstávají také
dosavadní opravy fitu/refitu a transakčního stavu, TD **55/45** a sekundární
limit Generation **2 %**.

## Ověření

Kontrola běžícího kódu `check_links` nad dodaným `02_LINKS.csv` ze 17. 11. 2026
11:41 pro model `R1_VARIANTYBase_LIVE04_2025_4_LIVE04_BASE_d49e4158.ver` nyní
vrací **PASS**: všech 120 unikátních hran doplňkových pozorování existuje a je
povoleno pro OA. Oba nové směry mají kladnou délku, rychlost, kapacitu a pruhy.
Hlavní metoda má stále 298 řádků, sekundární 120.

Regresní testy ověřují zachování cílů, počítání správného směru a opakovaných
průchodů právě novou hranou, vynechání ostatních částí rozděleného koridoru,
hash konfigurace a úspěch na skutečném exportovaném seznamu 10 832 hran.
Zachována je i regrese, která na starém odkazu zastaví controller před baseline.
Výsledky jsou v [evidence](evidence/).

Živý Visum ani nový assignment zde nebyly spuštěny. Toto ověření odstraňuje
konkrétní zablokování vstupní kontroly; nenahrazuje nativní kontroly dalších
částí běhu. Samostatný nález s ADDVAL1 na rozdělených hranách z předchozího
auditu zůstává k ověření proti nativnímu času pro C.

## Použití

Použít celý nový ZIP z GitHubu v nové složce se všemi aktuálními soubory a
manifesty. Nad otevřenou aktuální kopií modelu spustit obvyklý
`RUN_R1_2025_CORDON_LIVE04_V7_TG_TD_CYCLE.py`. Samotné přemapování nevyžaduje
reset kalibračních koeficientů. Přímé pokračování starého checkpointu má dál
vlastní podmínku shody sady hran a referencí.
