# LIVE01 - skutecne provedene testy po obnove

Stav: READY_FOR_NATIVE_READONLY_BASELINE; native PTV/Windows NOT_RUN.

| Sada | PASS | FAIL | SKIP |
|---|---:|---:|---:|
| Kompletní kordónová sada | 830 | 0 | 1 |
| Z toho nové LIVE01 případy | 116 | 0 | 0 |
| Donor HOTFIX2 znovu | 977 | 0 | 4 |
| Parent plná původní sada | 879 | 1 | 4 |
| Parent compatibility (1 identity test deselected) | 879 | 0 | 4 |

Původní identity test vyžaduje byte-identický V24915. Odmítá čtyři soubory
upravené již ve starším kordónovém forku; LIVE01 žádný z nich nemění.
Test ani jeho manifest nebyl změněn, selhání je uchováno.

Čtyři nově napsané poruchové testy nejprve selhaly proti CP03. Po opravě
prošlo všech 13 recovery testů. Úplná nová sada zahrnuje i původní 715
kordónových testů v jediném procesu. Nedokončený historický full log
a námi přerušený běh obnoveného CP03 nejsou započteny jako PASS.

MOCK 681 zón / 12 OA / 14 assignment DSeg / 120 vztahů: 960 OD proměnných
a 744 nenulových prvků operátoru v každé metodě, 64 návrhů TG změn pro
každou metodu. Žádné model write ani unbounded path calls. Nejde o reálný
výsledek R1. Efekt kandidátů a plná OD realizovatelnost nejsou ověřené.

24 NPZ polí po opraveném readbacku je přesně shodných s CP03; TG návrhy
jsou také shodné. 1606 původních souborů zůstalo beze změny.

Úplné příkazy, exit codes, časy, test cases, prvotní chyby a skip důvody
jsou v LIVE01_TEST_REPORT.json a docs/live01/test_evidence.
Čistě rozbalená finální dodávka má vlastní externí ověřovací protokol;
její výsledky se nepřičítají jako nové unikátní testy.

Preskoceny puvodni kordonovy test: tests/test_practical_limits_fix3.py:226,
real user failure fixture is supplied externally and is not embedded.
Tato stara realna chybova databaze nebyla v tomto prostredi dostupna.

Vedlejsi paralelni nezavisly testovaci pokus byl zamerne prerusen pri
priblizeni ke sdilenemu 4 GiB limitu pameti. Nebyl zapocten jako PASS;
primarni kompletni sada dobehla bez chyby. Finalni unzip se overuje
samostatne, bez soubezneho velkeho testovaciho procesu.
