# Nativni prijeti: dosud NEPROVEDENO

Pouzij oddelenou kopii R1 modelu 2025 se stejnou siti, maticemi a ulozenymi
cestami. Testy neprovadej v instanci, kde bezi kalibrace 2022, TG/TD nebo
assignment. Neotvirej jina .ver a nemen sit ani poptavku behem porovnani.

1. Rozbal FULL do nove kratke lokalni slozky. Puvodni FIX3/PERF01 nech byt.
2. `python verify_release.py` mimo Visum, nebo automaticky pres bootstrap.
3. Scripts -> Execute script file -> RUN_CORDON_2025_PARITY_AUDIT.py.
   Jedna parova uplna exekuce LEGACY/FAST256. Nejde o rychly sample test.
4. Pro uplne prijeti: LIVE_VISUM_ACCEPTANCE.py. Provede tri pary pro kazdou
   velikost 256,512,1024; poradi ve druhem opakovani obrati. To je 18
   UPLNYCH capture. Kontroly se nevynechavaji a archivace vysledku muze
   vyzadovat desitky GB. Bude potreba cas obou backendu, nikoliv jen FAST.
5. Vysledkem musi byt PARITY_PASS vsech paru, 12/12 OD a full geometry,
   presne stejna NPZ a STATION_HITS, stejna SQL data a zadne model writes.
6. Posli PARITY_REPORT.json, DIAGFAST_TIMING.json a pripadny TRACEBACK.
   Nemer rychlost pouze z poctu COM volani; pouzij median celku i proofu.

Vystupy: %LOCALAPPDATA%\R1C25\DIAGFAST_PARITY_<id>\
Jednotlive behy: captures\VISUM_CAPTURE_DIAGNOSTICS_<id>\
DIAGFAST_PARITY ma vlastni RunSession zamek a nesdili run root s jinym behem.
Pro zastaveni bez killu pridej STOP_REQUESTED do slozky aktivniho behu nebo
jeho captures rootu. Na hranici mezi pary se kontroluje take STOP_REQUESTED
v hlavni DIAGFAST_PARITY slozce. In-flight nativni COM nelze nasilne prerusit.

Je zachovan plny sitovy fingerprint klicu/TSYS a maticove/path readbacky.
Neni tim certifikovana nova assignment epoch ani uplny supply-state model.
Nove sloupce/metadata geometrickeho proofu neodemykaji metodicke gates.

FULL paired harness sam neoznacuje vydani PRODUCTION_VERIFIED: nejprve je
nutne zkontrolovat, ze skutecne slo o Windows/PTV native host a nikoli mock,
ze vstupy odpovidaji referenci a ze probehly vsechny pozadovane behy.
