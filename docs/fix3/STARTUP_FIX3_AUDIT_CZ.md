# STARTUP FIX3 PRACTICAL - audit a opravy

## Rozsah

Samostatny fork R1C25_FIX2. Pracovni source je R1C25_FIX3; originalni balicek,
uzivatelska p.sqlite a NATIVE_CW.npz ani model 2022 nejsou meneny. Aktualni vstup
ve Visumu stale dela pouze preflight nebo read-only capture. APPLY ani ziva
kalibracni smycka nebyly timto ukolem implementovany.

## Reprodukce skutecne chyby

Puvodni capture NATIVE_CW selhal po nacteni 438817 parent zaznamu, pred nactenim
linkovych sekvenci. Matice ma 681 x 681 bunek. SQLite quick_check vraci ok.
Vsechny kladne mezizonalni OD maji parent zaznamy; nulovy exportovany proud
neni dukaz chybejiciho parent zaznamu. Exportovane objemy jsou kompatibilni
s mrizkou 0.001 (maximalni odchylka od mrizky 5.684341886080802e-14).

| Velicina | Hodnota |
|---|---:|
| Mezizonalni poptavka | 294958.29489583656 |
| Soucet exportovanych cest | 294954.098 |
| Export minus matice | -4.196895836581411 |
| L1 soucet absolutnich OD chyb | 92.87853685215909 |
| Maximalni OD chyba | 0.0010619048288198485 |
| Puvodne odmitnute OD bunky | 405657 |
| Odmitnute OD bunky po oprave | 0 |
| Kladne OD s nulovym exportovanym tokem | 90852 |
| Jejich mat. objem | 7.393154689935518 |
| Kladne OD bez parent zaznamu | 0 |

Replay ctoucich funkci nezapisuje do vstupu a kontroluje SHA pred i po cteni.
Castecna SQLite ma stale 438817 NULL geometrii a capture_complete neni true.
Je to dukaz OPRAVY PARITY, nikoliv dukaz dokoncene cache nebo realnych
kordonovych intenzit. Kordonovy operator tuto nedokoncenou cache nadale odmita.

## Puvodni problem a koordinovana oprava

Puvodni startup vyzadoval per-OD shodu 1e-6 a navic zakazoval nastavit vyssi
od_parity_atol/rtol. Externi ctecka hotove cache pouzivala dalsi nezavislou pevnou
1e-6 kontrolu. Pouha zmena startupu by presunula pad do nasledujiciho kroku.

Novy modul cordon2025/parity.py je spolecna autorita pro oba kroky. Porovnava
puvodni nezmenene hodnoty. Je-li export kompatibilni s explicitnim kvantem q,
pro OD s N skutecne ulozenymi cestami je lokalni mez:

    atol + rtol * abs(Q_OD) + 0.5 * q * N

Vychozi q=0.001, atol=rtol=1e-5. Zadne fiktivni cesty ani navysovani jejich
poctu. Pro OD bez parent zaznamu nema kvantizacni clen N>0; existuje pouze
vykazana drobna rezerva 0.0005 a souhrnna kontrola nevysvetleneho objemu.
Nekompatibilni export nedostane kvantizacni pridavek. NaN, zaporne hodnoty,
nespravne identity zon a objem bez radku zustavaji chybou.

### Souctove meze bez dvojiteho trestani zaokrouhleni

Pevne procento z maleho segmentu muze odmitnout i matematicky vysvetlene
zaokrouhleni. Proto se nejdrive oddeli max(0, abs(delta_OD)-0.5*q*N).
Na NEVYSVETLENY zbytek plati oddelene limity: net 1e-4, L1 1e-3, nulovy
proud 1e-4 z mezizonalni poptavky, s absolutnim minimem 0.01.
Raw odchylky, kvantizacni mez, vysvetlena cast a prekroceni raw limitu jsou
vzdy viditelne v protokolu; zadna doprava se nepripisuje do modelu.

Stejny princip se aplikuje i pred geometrii: puvodni parent collector ma
samostatny souctovy guard. Jeho vyjimku lze zachytit JEN podle presneho
nazvu a JEN po jeho ulozeni vsech radku. Nahradi ji nezavisla uplna OD kontrola.
Puvodni verdict zustava ve sloupcich inherited_aggregate_parity_passed/failure.
Jakekoliv chyby parseru, klicu, zdroju a disku se nepotlacuji. Pouziva se i pri
vytvareni docasneho proof store pro porovnani geometrii. Parent source nemenime.

Tato zmena byla dodana po prvnim uspesnem regresnim mezibodu se 489 testy,
aby malo zatizene segmenty nenarazily na dalsi nadbytecny souctovy limit.

## Audit dalsich limitu

Machine-readable prehled: LIMITS_BEFORE_AFTER.json (28 polozek) a
GUARD_INVENTORY.json (volani kontraktnich kontrol v aktivnich modulech a parentu).

Uvolneny jsou numericke tolerance souctu incidence, FISTA/KKT, C17 reseni/projekce,
full-OD realizovatelnost, minimalni zlepseni TG/TD a nepatrne srovnavaci odchylky
objective. Uvolneny jsou take kvoty matic, poctu parent/linkovych radku, COM retry
a pevna velikost SQLite. Po fazi 100 se drzi posledni omezena offline faze.
Nativni IPF, fyzicke meze parametru a agresivni kroky 20/14/8 procent nejsou
numerickou exportni presnosti a zustaly zachovane.

C17 se nema zmenit na dodatecny zdroj vozidel: rozpocty i ledger zustavaji.
Pri mene presnem ukonceni projekce se pouze nepatrny numericky presah stahne
DOVNITR pripustneho polytope, nikdy se nezvetsi limit uctu.

## Co zustava tvrde

- Konkretni sit a 32 smerovych mapovacich klicu, explicitni 12 OA segment scope.
- Zadne tiche vynechani EXOG/fixed dopravy nebo zapisy do zmrazenych matic.
- Matice a cesty se nesmeji behem capture zmenit; sha kontrola je nadale presna.
- Dokonceni cache, foreign keys, bez WAL/journal u frozen snapshotu.
- Skutecne sekvence a jejich hash/topologie; zadna nahradni Dijkstra.
- Skutecna shoda geometrie sdilenych segmentu a cela objemova evidence.
- CAL/VALID bez protismerneho uniku, source hashes a puvod roku/metodiky.
- C17 nerozdeleno jako neomezena tolerance, zadne automaticke schvaleni metodiky.
- Kryti skuteckych chyb, negativnich hodnot, nespravnych identit a korupce.
- Zadne APPLY, assignment, TG/TD ani prevzeti otevrene instance modelu 2022.

## Kontrola dopadu

807 existujicich souboru parent/ a data/ je byte-identickych s FIX2. Kod a
konfiguracni zmeny mimo parent maji explicitni before/after SHA v REVIEWED_CHANGES.
Puvodni testy identity forku byly doplneny o presny schvaleny prechod hashu
u dvou konfiguraci; stale kontroluji vsechny ostatni puvodni soubory.
Puvodni parent deployment guard V24915 se NEMENI a nadale odmita ctyri
historicky zmenene soubory tohoto forku. To je vykazano jako ocekavany neuspech,
ne jako uspesny test puvodniho vydani.

## Omezeni vysledku

Tento fix zatim neni nativne znovu spusten ve Visumu. Pouzita evidence:
realny neuspesny export NATIVE_CW, offline replay a mock-COM kompletni capture.
Nezname realny vysledek dalsich 11 segmentu ani plnych linkovych geometrii.
V1/V2 omezeni plne zive kalibrace plati dale. Navazujici krok je novy capture
z aktualniho modelu 2025, nikoliv aplikace starych castecnych vysledku.
