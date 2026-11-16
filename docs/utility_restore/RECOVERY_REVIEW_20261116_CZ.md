# Navazující kontrola zotavení TG/TD a assignmentu

Základ: `bbdc687d5445b9c4b475f19d8ee63803e9284997` (lokálně stejný strom
`4307eab1dacab2e8de817d7ddaea874385129d28`). Navazuje na opravu COM kontextu.
Jde o chyby reprodukované offline při auditu, nikoli o další dodaný živý pád.

## Přerušený assignment nebyl označen jako neplatný

Příznak `assignment_invalidated` se pouze nastavoval na `False`. Po dřívějším
odstranění resetů z poptávkových sond nikde nezbylo jeho nastavení na `True`
při skutečném nativním assignmentu. Pokud reset smazal cesty a následný
assignment selhal, koeficienty i OD matice mohly zůstat přesně stejné.
Jejich hash tedy sám neprokazoval platné assignmentové výsledky. Větev
zotavení přitom čekala právě na tento příznak.

Adaptér nyní před spuštěním skutečného plánu s resetem nebo assignmentem
typu 9/100/101 nastaví příznak neplatnosti. Totéž platí pro obecný vstup
`assign`. Vymaže ho až úspěšné dokončení příslušného přepočtu. Chyba při
přípravě před nativním spuštěním stav původního assignmentu neznehodnotí.
Demand-only sondy stále nesmějí obsahovat reset ani assignment.

Při přerušení se shodným parametrickým a maticovým stavem se nyní může
spustit stávající opravný přepočet a důkaz ekvivalence. Po pokusu se stav
načte znovu, včetně případu, kdy zotavení selhalo.

## Chybný výsledek hlášení při selhání opravy

I když opravný přepočet vrátil `REPAIR_FAILED`, závěrečný stav mohl zůstat
`MODEL_VERIFIED`, protože vycházel jen ze shody snapshotu před opravou.
Podmínka ukládání sice kontrolovala výsledek opravy, ale samotný příznak
neplatného assignmentu v ní chyběl.

Nově se rozlišuje shoda snapshotu a ověření assignmentu. Jak neplatný
assignment, tak neúspěšná oprava znamenají `model_state_verified=false`
a zakazují uložení přijaté verze. To platí i tehdy, když cesty po přepočtu
existují, ale důkaz ekvivalence se nepodařil. Pole v
`FAILURE_STATE_READBACK.json` výslovně uvádějí obě části ověření.

## Obnovu blokovaly právě hodnoty, které měla opravit

Obnova pomocných matic používala stejnou vstupní validaci jako přijetí
nového rodiče. Nulové TTC/TT0 po přerušení nebo numericky poškozená utility
tak byly odmítnuty dřív, než se mohly obnovit známé správné hodnoty.

Pouze při obnově se nyní stávající hodnoty načtou bez požadavku na jejich
numerickou použitelnost. Identita matic, CODE, DSeg, DATA/ZONE/SKIM a rozměry
zůstávají povinné. Zápis stále smí obsahovat výhradně přesné dříve ověřené
hodnoty rodiče, chráněné hashem. Po zápisu se provede plná numerická validace
a přesná kontrola celého pomocného stavu. Běžný preflight, snapshot a přijetí
rodiče zachovávají původní přísnou validaci.

## Chybové hlášení nesmí přeskočit rollback TD ani SupplyMix

V TD následoval po výjimce nejprve převod `str(exc)` a zápis reportu, teprve
potom rollback. Nečitelná COM výjimka nebo zamčený soubor tak mohly zabránit
samotnému návratu. Rollback nyní proběhne první; výjimky se převádějí bezpečně.
Stejné pořadí je použité v chybové větvi SupplyMix po převzetí kandidáta,
včetně setteru, který nejprve změní hodnotu a potom vyvolá výjimku.

Kontrola COMBUSY2 také procházela příčiny výjimky přes nechráněný `str(exc)`.
Pro dobu běhu se nyní nasadí bezpečná varianta stejné kontroly markerů
ručního zotavení a po běhu se původní funkce obnoví. Zachová se tím i důvod
selhání TD s nečitelnou vnitřní výjimkou. Chráněné donorové soubory zůstávají
beze změny. Politika opakování transientních COM chyb se neuvolňuje.

## Ověření

Před opravou čtyři reprodukční případy selhaly: neoznačené přerušení po
resetu, obnova nulových skimů, NaN utility a záporné utility. Kontrola cizí
identity matice už před opravou správně blokovala zápis a zůstává zachována.

Další testy ověřují dokončený assignment, chybu před spuštěním a zastavení
řídicího cyklu po přijatém bloku. Rozlišují úspěšnou opravu, selhání s
chybějícími cestami i selhání důkazu po přepočtu; v neověřených případech
nesmí dojít k `SaveVersion`. Řídicí testy používají syntetický model a stuby
bloků, neověřují numerickou kvalitu jejich akceptace.

Regrese TD v nativní simulaci vyvolají chybu kvality přiřazení a vyžadují
důkaz rollbacku i při nečitelné výjimce a zamčeném reportu. Pro rychlejší
ověření chybové větve používají rodinné seskupení, jednu vnitřní iteraci
a vypnutý IDP guard; tento test neověřuje politiku IDP. Samostatné unit testy
SupplyMix používají stub návrhu a rollbacku a ověřují skutečné pořadí volání
chybové větve, nikoli numerické hledání dopravní nabídky. Samostatný existující
test STOP nad celým syntetickým cyklem ověřuje zachování cest a uložení
posledního přijatého stavu.

Logy a přesné počty jsou v `evidence/recovery_review_20261116/`. Nativní
Windows COM ani skutečný model zde testované nejsou. Skript operace 15,
výpočty utility, kalibrační meze a pravidla přijetí kandidátů se nemění.
