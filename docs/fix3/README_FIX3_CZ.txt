R1 2025 CORDON AGGRESSIVE - STARTUP FIX3 PRACTICAL
Datum vydani: 2026-10-23

UCEL
Oprava falesneho zastaveni PER_OD_PATH_MATRIX_PARITY_FAIL:NATIVE_CW a auditovane
uvolneni numerickych a technickych limitu. Nejde o vypnuti kontroly dat a nejde
o implementaci zive automaticke kalibracni smycky.

SPUSTENI VE VISUMU
1. Rozbalit CELY ZIP do NOVE kratke lokalni slozky R1C25_FIX3.
   Neprepisovat FIX2, slozku modelu 2022 ani bezici vypocet.
2. Ve spravne instanci Visumu otevrit model R1 2025 se spravnou siti
   a hotovym assignmentem s ulozenymi cestami.
3. Scripts -> Execute script file -> RUN_CORDON_2025_CAPTURE.py.
   Capture zopakuje preflight; samostatny RUN_CORDON_2025_VISUM.py je volitelny.
4. Behem capture nemenit model, matice ani assignment. Vse je read-only.
   Script sam nevyhledava jinou instanci Visumu, nepripojuje 2022 a neprovadi
   TG/TD, assignment, SaveVersion, LoadVersion ani APPLY.
5. Vystupy: %LOCALAPPDATA%\R1C25\VISUM_CAPTURE_DIAGNOSTICS_...
   Pri chybe pred startem: %LOCALAPPDATA%\R1C25_BOOT\...

PREDCHOZI NEDOKONCENY p.sqlite SE NESMI POUZIT JAKO HOTOVA CACHE.
Obsahuje pouze parent zaznamy NATIVE_CW, nikoliv nactene geometrie.
FIX3 nevydava tuto castecnost za PASS, neobnovuje export z neovereneho mista
ani nedoplnuje fiktivni cesty. Spust novy capture; puvodni dukazy zustanou zachovane.
Kvuli dolozenemu zaokrouhleni neni nutne menit poptavku nebo znovu pocitat
assignment. Pokud se mezitim model zmenil, pouzij konzistentni aktualni stav.

PARITA CEST A MATIC
- Hodnoty matic a cest se NIKDY nezaokrouhluji, neprenasobuji ani nedoplnuji.
- Vol(AP) ve tvem exportu odpovida mrizce 0.001 vozidla. Pri kompatibilite
  skutecnych hodnot s touto mrizkou je mez pro OD:
  1e-5 + 1e-5*abs(Q_OD) + 0.0005 * pocet SKUTECNE ulozenych cest tohoto OD.
- Nulovy objem s existujicim parent zaznamem neni tototez jako chybejici cesta.
- Pro OD bez parent zaznamu lze tolerovat pouze vykazane drobne hodnoty
  do 0.0005 plus zakladni numericka presnost; kontroluje se i jejich celkovy objem.
- Mimo dokazatelnou mrizku se kvantizacni pridavek NEPOUZIJE.
- Dalsi nezavisle limity se vztahuji na ZBYTKOVOU odchylku nad prokazanou
  mezi zaokrouhleni: net 0.01 %, soucet absolutnich OD chyb 0.1 %,
  nevysvetlena poptavka OD s nulovym ulozenym tokem 0.01 %; absolutni minimum 0.01.
  Cele puvodni odchylky se take vykazuji. Vysvetlitelne zaokrouhleni se nesmi
  podruhe zablokovat procentnim limitem u malo zatizeneho segmentu.
  Puvodni souctovy guard 15A2 lze prekrocit pouze po teto nezavisle kontrole
  vsech bunek; puvodni nepriznivy verdict zustava v auditnim zaznamu.
- Zmeny se nekompenzuji jen celkovym souctem. Presun vozidel mezi OD bez zmeny
  souctu stale muze a musi selhat. Stejne pravidlo pouziva capture i cteni cache.
- Numericka pravidla jsou ulozena a hashovana spolu s cache a evidenci.
  Starsi zapechatene cache bez nove politiky se nepreinterpretuji potichu.

DALSI ZMENY (viz docs/fix3/LIMITS_BEFORE_AFTER.json)
- FISTA stop tolerance 1e-12 -> 1e-9; kontrola optimality 1e-6 -> 1e-5.
- C17 vnitrni reseni 1e-9 -> 1e-7, projekce 1e-11 -> 1e-8.
  Dostupne rozpocty C17 se NEMENI; maly presah projekce se stahne dovnitr.
- TG minimum relativniho zlepseni 1e-5 -> 1e-6.
- TD minimum relativniho zlepseni 5e-4 -> 5e-5.
- Realizovatelnost celeho OD: 1e-5 -> 0.001 + 1e-6*abs(pozadovane zmeny).
  Jde o numericky pribliznou realizovatelnost, ne dukaz ziveho assignmentu.
- Po cislovani offline faze 100 se drzi posledni DISTRIBUTION_FOCUS faze;
  stale se jedna o jeden offline navrh, ne automatickou smycku Visumu.
- COM busy: 128 pokusu / 180 s na jedno odmitane cteni misto 64 / 75 s.
  Neni to limit celeho behu. Nelze prerusit uz probihajici nativni COM volani.
- SQLite nema pevny 12 GiB limit; kontrola skutecneho volneho disku zustava.
- Vyssi limity velikosti matic a poctu radku, nikoliv vetsi COM davka.

NEUVOLNENO
Smerove klice, site/roky/segmenty, nekonecne a zaporne hodnoty, skutecne chybejici
geometrie, shoda geometrii pri sdileni, stabilita snapshotu, hash integrity,
zmrazene matice, CAL/VALID, fyzicke C17 rozpocty, kladne zlepseni kandidata,
bezpecnostni zakaz ziveho APPLY. Mereni a jejich metodicky vyznam se nemeni.
Neprovadi se zasah do tolerance nativniho IPF ani libovolne zvetseni agresivnich
kroku 20/14/8 procent - ty nejsou numerickou chybou exportu.

OFFLINE OVERENI
python verify_release.py
python -m pytest tests -q
python RUN_CORDON_AGGRESSIVE_OFFLINE.py demo
Volitelny forenzni replay puvodni chyby (NEPROVADI CAPTURE):
python REPLAY_OD_PARITY.py --cache p.sqlite --matrix NATIVE_CW.npz --output replay.json
Test skutecneho exportu pouziva promenne R1_REAL_PARITY_SQLITE a
R1_REAL_PARITY_NPZ; nejsou-li k dispozici, pouze tento test se explicitne preskoci.

HRANICE OVERENI
FIX3 je offline a mock-COM otestovana oprava. Skutecna data NATIVE_CW prochazeji
nezavislym readonly replayem. FIX3 zatim nebyl znovu spusten v nativnim Visumu.
Ostatnich 11 segmentu a plne geometrie realneho modelu musi teprve projit capture.
Plna ziva TG/TD -> assignment -> ACCEPT/ROLLBACK kalibrace neni implementovana.
Vysledne protokoly a puvodni neuspesne testovaci pokusy jsou v docs/fix3/.
