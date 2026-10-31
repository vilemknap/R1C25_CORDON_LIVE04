# PERF-01: namereny benchmark

Fixture: 100 000 geometrii, 600 000 segmentovych objemovych radku, 12 DSeg / 2 mody / 16 SDP. Nenulovy mutable operator se 200 000 promennymi. Synteticky stresovy vstup, nikoliv native R1.

| Vypocet | Wall s | Peak RSS MiB | Vystupni bajty |
|---|---:|---:|---:|
| 0 reference | 89.133 | 3087.0 | 605157595 |
| 1 build | 77.226 | 3088.7 | 26830531 |
| 2 warm | 23.494 | 2248.0 | 26830397 |
| 3 warm | 23.450 | 2248.1 | 26830393 |
| 4 warm | 23.188 | 2248.1 | 26830397 |
| 5 warm | 23.811 | 2248.1 | 26830405 |

Median warm: 23.47199 s. Zrychleni proti cold reference: **3.797x**.
Jednorazova derived cache: 18940571 B. Kazdy warm vytvori pouze vlastni maly report a numericke vystupy, cache se pri hitu nerozrusta.

V kazdem warm: **0 COM call, 0 geometry redecode, 0 geometry SQL scan**. Shoda obou metod zahrnuje vsechny numericke vektory/sparse pole a per-DSeg smerove radky, ne pouze total sum. Zdrojove a odvozene SHA byly zapnute. Kazdy warm je samostatny novy proces.

## Metodika a limity
Cold reference je zachovana vypocetni funkce FIX3 a stary plny JSON vystup; nejedna se o cold disk. OS file cache se nevyprazdnovala. PERF01 pouziva stejny algoritmus cold a na warm nove kompaktni tabulky/odkazy. Zisk zahrnuje i odstraneni ctyr redundantnich OD JSON auditu, coz je soucast zadani.
Benchmark probehl po dokonceni testu bez soubezneho velkeho testovaciho jobu. CPU/wall, /proc/self/io, hash bytes, fazove casy, velikosti a podpisy jsou v JSON. Peak RAM je procesni maximum a merit lze jen v podporovanem OS; zde Linux.
Prvni velke mereni skoncilo OOM pri limitu 4 GiB. Oprava nahradila U64 nazvy segmentu slovnikovymi indexy, odstranila zdvojenou parse evidence a uvolnila cold struktury pred readback. Neuspesny pokus je v evidence/benchmark_initial_failure.json, nezapocitava se do zrychleni.

Tento vysledek NEGARANTUJE 3.8x rychlejsi Visum capture ani stejny vykon nad skutecnym 868022-geometrickym R1 exportem. Full-real replay vyzaduje chybejici finalni cache; hot path neoslabuje proverovani obsahu.
