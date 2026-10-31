# PERF-01: skutecne testy

Vysledek cele kordonove sady: **573 passed, 0 failed**. Obsahuje 80 novych
PERF01 pripadu a 493 puvodnich pripadu. Puvodni numericky test nad nekompletnim
FIX2 NATIVE_CW byl tentokrat explicitne zapnut pres environment; neni to
akceptace dokoncenych realnych dat PERF01.

Pred zmenami: 492 passed / 1 skipped (tentyz test bez explicitniho vstupu).
Kompatibilita rodice: 879 passed / 4 skipped / 1 deselected.
Plna nezmenena sada rodice: 879 passed / 4 skipped / 1 failed.
Jediny neuspech je historicky byte-identity test V24915, ktery spravne odmita
ctyri soubory zmenene uz ve FIX3. PERF01 rodicovske moduly ani tuto kontrolu
nemenil. Nejedna se o skrytou regresi ani o tvrzeni identity puvodniho vydani.

Novy test suite zahrnuje oba enumeratory, nenulove mutable promene, prave
120 pozorovani (108/12) v mock-native fixture, C/noT oddelene, zafixovane EXOG,
per-DSeg vysledky, lazy OD audit a legacy roundtrip. Warm test odpojuje cold
builder i sqlite.connect a zakazuje COM import; hit stale projde. Uplny
snapshot a derivaty se hashuji; dalsi proces reprodukuje stejny vysledek.

Negativni testy: zmena zdroje pri stejnem case/velikosti, smeroveho mapovani,
mutability/zony/repeat policy, algoritmu, sidecaru, nedokonceneho exportu,
chybejiciho dukazu geometrie, FAIL parity, poskozenych matic/NPZ/JSON, NaN a
object dtype. Dva writers se nemohou prepsat. Simulovany pad procesu pred
publikaci nenecha falesny hit, zamek se neprebira automaticky. Testovany jsou
symlinky, reparse, traversal, Unicode/cesty s mezerou a docasne IO chyby.

## Zachovane neuspesne pokusy
Prvni focused test byl prerusen, neni PASS. Prvni velky benchmark skoncil OOM
pri 4 GiB limitu, nasledovala pametova oprava. Prvni kompletni regrese mela
pet bootstrap FAIL, protoze behem vyvoje pribyl soubor mimo tehdejsi manifest;
integrity gate pracoval spravne. Po zapeceteni aktualnich zdroju probehla
cela sada 573/573. Puvodni logy jsou v evidence, nikoliv premazane.

## Co testy nepotvrzuji
Realna referencni databaze 664272896 B se spravnym SHA a jeji kompletni
matrix_authority nejsou dostupne. E25-E28 jsou NOT_RUN / WAITING_FOR_REAL_FINAL_CACHE.
Sest nahranych vysledkovych artefaktu ma shodne hashe s realnym checkpointem,
ale nenahrazuje to replay cele databaze. Windows runtime se testoval
simulacemi; nativni spusteni PERF01 se netvrdi. Live kalibrace neni soucasti.

Testy po cistem rozbaleni a finalni release integrita jsou zaznamenany
v samostatnem FINAL_VERIFICATION JSON po vytvoreni baliku.

## Ciste rozbaleni
Z rozbaleneho RC1: 573 kordonovych testu uspesnych a 879 kompatibilitnich + 4 skip. Integrita pred/po beze zmeny. Finalni distribuce uklizi jen generovane mock vystupy a doplnuje reporty; vsech 890 porovnanych spustitelnych/datovych/config souboru je shodnych. Presne finalni bajty maji jeste samostatne readback overeni a focused regresi v FINAL_VERIFICATION.
