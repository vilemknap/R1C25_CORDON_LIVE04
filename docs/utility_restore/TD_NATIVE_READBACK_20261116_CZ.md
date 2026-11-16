# TD: nativní zápis parametrů a přesná kontrola jejich zachování

Základ je publikovaný commit `929f9e009f708cd8d7274ca18724b1d9f7b95020`.
Opravy transakčních utility matic, COM kontextu, zotavení a identit refitu
zůstávají součástí balíku.

## Co potvrzují nové výsledky

V dodaném `CYCLE_PROGRESS.json` nejsou žádné přijaté změny ani checkpointy.
GENERATION skončila vyčerpáním hledání. TD provedla 22 nativních sond a čtyři
vnitřní vyhodnocení. Třetí vnitřní návrh prošel predikčními branami, ale plný
pokus skončil chybou `UNREQUESTED_TD_PARAMETER_CHANGE` před skutečným
vyhodnocením jeho výsledků. Předpovězené zlepšení kordonu 4,285 % a směsi
15,768 % proto není přijaté ani změřené zlepšení modelu.

`00_PROGRESS.json` ještě zachycuje čtení podpisu cest v zotavení
(`recovery_depth=1`). Dokončený důkaz rollbacku ani konečný výsledek mezi
přílohami není. Aktuálně otevřený model tím není ověřen jako přijatý stav.
Pro nový běh použít znovu otevřený zdroj:
`R1_VARIANTYBase_LIVE04_2025_2_LIVE04_BASE_48fb232a.ver`.
Jeho SHA v dodaném záznamu je
`ef0f03c0a47f69c90a84ef83731fba54164e0afc7d94c13a81ee1798a3db9836`.

## Reprodukovaný nesoulad kontrol

Donor `apply_td_candidates` a `verify_td_persistence` připouštějí absolutní
odchylku uložených b/c od požadovaných hodnot do `1e-8`. Následující
`assert_freeze` ale sestavoval očekávaný stav z požadovaných hodnot a porovnal
jej přesným hashem se skutečně uloženými čísly. Rozdíl jednoho bitu tak mohl
projít zápisem i persistence a následně zastavit celý běh.

Syntetická reprodukce vyvolává původní chybu při rozdílu
`2.220446049250313e-16`, zatímco původní persistence hlásí `OK`.
To prokazuje chybu kontraktu v kódu. Dodané živé logy neobsahují trojici
požadovaný parametr / okamžitý readback / parametr po proceduře, takže
neprokazují, že právě reprezentace čísla byla jedinou příčinou tohoto běhu.
Skutečná změna jiného parametru zůstává další možností.

## Oprava a hranice důkazu

Bezprostředně po nativním zápisu a před spuštěním procedury se znovu přečtou
b/c a status všech komponent. Změna je přípustná jen u výslovně zapisovaného
parametru, v původní toleranci `1e-8` a v přípustném znaménkovém oboru.
Ostatní komponenty a statusy se musí shodovat přesně; neúplné nebo duplicitní
záznamy se odmítají. Plánovač si zachová původní požadovaná čísla, efektivní
kandidát navíc eviduje skutečně uložené hodnoty.

Po nativním přepočtu se spouští původní donor `assert_freeze` s těmito předem
ověřenými uloženými hodnotami. Žádná nová tolerance při přepočtu nevzniká.
I další změna o jediný bit se dál odmítne a vyvolá rollback. Readback se
nesmí odvozovat až z výsledku procedury, protože by tím mohl zakrýt její
neplánovanou změnu.

Audit plného pokusu nyní obsahuje:

- `TRIAL/TD_PARAMETER_WRITE_READBACK.json`: požadovaná a okamžitě načtená
  čísla, jejich rozdíly, případné selhání a efektivní kandidát;
- `TRIAL/TD_PARAMETER_FREEZE.json`: konkrétní rozdíly vůči očekávanému stavu
  po přepočtu a výsledek původní pojistky;
- `TD_BLOCK_RESULT.json`: souhrn ověření zápisu a počet změn reprezentace.

Chyba při čtení či zápisu auditu zůstává uvnitř existujícího transakčního
bloku; model se musí obnovit před oznámením selhání. Chráněné zdroje `parent/`
se nemění. Akceptační objective, váhy, limity GEH/mobility, rozpočty a nulové
povolené zhoršení sekundární metody v GENERATION se nemění. Skript operace 15
se touto opravou nemění.

## Ověření a další spuštění

Výsledky cílených testů, reprodukce a hashe všech osmi příloh jsou v
`evidence/td_readback_20261116/`. Testy plného řídicího průchodu používají
syntetický Visum s omezením uložení b/c na 15 platných číslic. Samostatně
ověřují průchod přesnou pojistkou a odmítnutí další malé změny při proceduře
s dokončeným rollbackem. Tyto dva testy mají pro izolaci této chyby FAMILY
seskupení, jeden vnitřní krok a vypnutý IDP; nepotvrzují živou směsnou
optimalizaci ani skutečnou odezvu sítě. Související testy ověřují utility,
refit, zotavení a původní TD konfiguraci.

Nový balík rozbalit do samostatného adresáře, restartovat Visum kvůli
modulům v paměti, otevřít uvedenou zdrojovou verzi a spustit
`RUN_R1_2025_CORDON_LIVE04_V7_TG_TD_CYCLE.py`.
Živý Windows/Visum zde nebyl dostupný. Celá historická testovací sada na
tuto úpravu spuštěna nebyla.
