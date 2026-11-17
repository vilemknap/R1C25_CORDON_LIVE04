# Kontrola sítě po úpravách, 17. 11. 2026

**Mapování kalibrace zůstává použitelné. Nulový dopad na intenzity ale z exportů
potvrdit nelze: změnila se topologie a před dalším během je nutný nový assignment
a skimy na upravené síti.** Kód ani nastavení kalibrátoru nebyly tímto auditem
změněny; TD zůstává 55 % kordón / 45 % IDP.

Porovnání vychází z dodaných `nodes.csv`, `links.csv`, úplného seznamu klíčů hran
v předchozím `RUN_ANCHORS.json`, počtů a typů uzlů z `NODE_VDF_BASELINE.json`
a aktuálních autorit mapování vydání `d69f2a1`. SHA-256 všech použitých vstupů
jsou v [AUDIT.json](AUDIT.json).

| Kontrola | Výsledek |
|---|---|
| Uzly | 3 791 → 3 803, tedy +12 |
| Směrované hrany | 10 576 → 10 614; 50 přidáno, 12 odstraněno |
| Kordónová mapování | Všech 32 směrů existuje a má kladné provozní parametry pro OA |
| Typ a kapacita hran kordónových stanic | Shodné s referenční tabulkou ve všech 32 směrech |
| Délky hran kordónových stanic | Maximální rozdíl 0,000289 m, pouze přesnost exportu |
| Srovnatelné historické volné rychlosti stanic | 24 směrů, bez rozdílu; ostatních 8 nemá historické t0 |
| Dálniční režim SDP1/3/15/16 | C povoleno, C_noT nepovoleno; vyhovuje |
| Směry +/− u stanic | Všechna explicitní mapování zůstávají platná |
| NDS/ASD/K1/K2 | Všech 120 unikátních hran pro 130 pozorovacích řádků existuje a je použitelných pro OA |
| Klíče a koncové uzly | Bez duplicit, chybějících uzlů a smyček na jediném uzlu |
| Nové hrany | Všech 50 má kladnou délku, kapacitu, rychlost a počet pruhů a povoluje OA i nákladní dopravu |
| Nové uzly | 99800765–99800776, všechny typ 0 a T0PRT = 0 |

Směrované křižovatkové pozorování je dvojice hran potkaných v daném pořadí na
jedné cestě; hrany nemusí být přímo sousední. Jejich vzájemná nesousednost
proto není označena jako chyba. V exportu je také 961 směrů s nulovými
kapacitami, rychlostmi a pruhy: všechny mají nulový exportovaný tok a použitelný
opačný směr; žádný z těchto klíčů nebyl nově přidán. Nejsou zde vydávány za novou závadu sítě.

## Co se může projevit ve výsledcích

Nové uzly leží nejblíže stanicím SDP11–13, nejbližší asi 628 m od SDP12.
Platné mapování tedy samo o sobě nezaručuje stejné dopravní proudy.

U pěti odstraněných obousměrných úseků existuje spojení přes dvě nově přidané
hrany v každém směru. Šestý úsek **9800534, 9900277 ↔ 9900281**, přímou náhradu
mezi novými hranami nemá. Současná síť mezi těmito uzly obsahuje spojení přes
9800525–2001669–9800529–9800533, dlouhé asi 812,8 m. To je skutečná změna
nabídky tras; její intenzitní dopad nebyl měřen. Kontrola spojení respektuje
použitelnost hran pro OA, ale nezná omezení odbočení.

Přesné klíče jsou v [ADDED_LINKS.csv](ADDED_LINKS.csv),
[REMOVED_LINKS.csv](REMOVED_LINKS.csv) a [NEW_NODES.csv](NEW_NODES.csv).
Podrobnosti pro stanice jsou v [STATION_CHECKS.csv](STATION_CHECKS.csv).

## Použití pro kalibraci

1. Zachovat dosavadní kalibrované koeficienty a parametry v upravené kopii.
2. Přepočítat assignment, uložené cesty a skimy na nové síti včetně dosavadní LONG masky.
3. Spustit standardní nový běh kalibrátoru, aby získal aktuální výchozí stav a incidenci.

Původní `CONTINUE` není přímým pokračováním pro tuto změněnou síť: staré
ADDVAL1 reference mají 10 576 klíčů, nyní jich je 10 614 a 12 původních chybí.
Kontrola `LIVE04_CONTINUE_ADDVAL_LINK_SET_CHANGED` takovou kombinaci nepovoluje.
Nový běh zachytí incidenci a výchozí reference odpovídající upravenému modelu.
Pozorovací mapování a cílové hodnoty nevyžadují na základě těchto exportů změnu.

## Rozsah důkazu

Nemáme starý úplný export atributů hran. Nelze proto potvrdit všechny změny
rychlostí, kapacit, délek či povolených systémů na 10 564 společných hranách.
Exporty neobsahují ADDVAL1, linkový TMODELSPECIAL, kapacity uzlů, odbočení,
konektory, zónové koeficienty ani matice a jejich epochy. Bez živého přepočtu
není prokázána shoda výsledných intenzit ani stavu uložených cest.
