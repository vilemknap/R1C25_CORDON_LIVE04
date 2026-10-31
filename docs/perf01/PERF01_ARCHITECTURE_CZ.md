# PERF-01: odvozena cache pro nemenny snapshot

## Kontrakt CP01
Jeden immutable bundle obsahuje OBE smerove incidence, station hits a JEDNOU sdilene OD/variable tabulky. Vychozi FIX3 cold oracle zustava beze zmeny vypoctu. Nezavadime druhy exporter ani zivy epoch detector.

Dve logicke identity, jedna fyzicka publikace: geometry key (zdrojovy seal, algoritmus, presne smerove mapovani, inventory); incidence key (geometry key, repeat policy, selected/mutable DSeg, relation policy, actuatable zones, tolerance souctu, semantic expectations). Zmena mutable scope vytvori novy bundle a konzervativne rebuild; samostatny partial geometry-hit rebuild neni soucasti V1. Solverove vahy, C17, cile a CAL/VALID nepatri do geometry key. Pozorovani a role se po kazdem nacteni levne agreguji znovu puvodni funkci.

## Explicitni API a CLI
`--reuse-cache-dir PATH --reuse-policy build-offline|require-verified-hit`, pouze prikazy inspect-cache a propose. Vychozi politika disabled. Volba `--reuse-context after-new-assignment` vzdy skonci CACHE_EPOCH_NOT_PROVEN_RECAPTURE_REQUIRED. Puvodni persistent_path_cache_enabled zustava zakazan; jde o odlisnou read-only derived cache.

## Overeni zdroje
Kazdy beh streamuje plne SHA SQLite, evidence a prislusnych dukazu/matic. Na cold probehne puvodni SQL/schema/integrity a per-OD overeni. Na warm se nepouziva SQLite pruchod: platnost cold overeni je vazana na stejny obsah souboru a hash implementace. Vychozi evidence s NOT_CERTIFIED necertifikuje novy assignment. Po operaci se overi nemennost zdroju. Native zdroj vyzaduje full geometry proof a externi per-OD paritu/matice; synthetic fixture je samostatne oznacena.

## Publikace a recovery
Vlastni explicitni koren s markerem CORDON_PERF01_ROOT, pripoutany k jednomu snapshotu. Existujici neznamy neprazdny adresar se neadoptuje. Writer ma exkluzivni O_EXCL lock, zadne automaticke prebirani opusteneho locku. Data vznikaji ve vlastnim staging adresari. Readback SHA a fsync pred atomickym rename hotoveho adresare. Reader cte jen complete bundle; zadne partial hits. Poskozeny bundle se nikdy tise neprepocita. Stare bundle jsou immutable; nove klice tvori nove adresare. Bezpecnost zahrnuje symlink/reparse/path traversal a vstupni/vystupni kolize.

## Vystupy
PERF01_CACHE_STATUS.json: action, hit/miss, identity, actual geometry decode/SQL/COM counters, source and derived bytes, cas a RAM. INCIDENCE_METADATA ve verzi 4 odkazuje na overeny sdileny audit/table bundle; ctecka rekonstruuje stejny obsah. Explicitni legacy export zachova puvodni JSON schema a hodnoty. Auditni all_od_totals je bezeztratova typed tabulka, ne zahozena statistika.

## Gate
apply=false, assignment_executed=false, live_calibration_verified=false vzdy. Zadna nova metodicka schvaleni. Real-final acceptance bude NOT_RUN, pokud chybi konecna 664272896-byte databaze a matrix_authority; lokalni nedokonceny FIX2 je pouze negativni test.

## Finalni implementacni upresneni
Numericka cold funkce build_from_snapshot je beze zmeny; save() ma jen explicitni
kompatibilni prevod lazy auditu pro legacy export. Defaultni warm vystup pouziva
jednu ALL_OD_TOTALS.npz s typovanymi ciselniky segmentu, jednu VARIABLE_TABLES.npz
a sdileny SHARED_AUDIT.json. Dva smerove operatory se serializuji bez pickle.
Dictionary indexy se validuji vcetne mezniho rozsahu, numericka pole vcetne
konecnosti, nezapornosti, delky a consistency q/share/fixed. Zdrojova presnost
FIX3 ani kalibracni regularizace se nemeni.

Geometry key obsahuje presnou usporadanou tabulku (LinkNo,FromNodeNo,ToNodeNo,SDP)
uvnitr SHA-256 kanonicke identity, nikoliv nahodnou pozici radku v CSV. Puvodni
mapping CSV je navic byteove chranen manifestem release. Jmena/formatovani
nepouzita ve vypoctu sama o sobe nemeni geometrii. Oba mody jsou odlisene
source SHA a kompletnim mode/DSeg inventarem cold validace.

Pro warm se obsahove overeni zdroje provede pred a po nacteni. Source-seal
synchronizace se NEROVNA autentizaci libovolneho noveho Visum stavu. Autority
musi byt explicitne predane a duveryhodne; SHA manifesty nejsou digitalni podpis.
Nesmime je rucne prepisovat za ucelem obejiti kontroly. Vystupni checkpoint
navic pripina hash konkretniho odvozeneho manifestu i vazby na vstupni soubory.

Cache je immutable po publikaci. Na POSIX je fsync take adresare; na Windows
jsou fsyncovany soubory a pouziva se atomicky rename. Nativni Windows durability
pri vypadku napajeni nebyla overena. Zadny automaticky steal locku nebo adopce
neznameho adresare neni implementovan. Docasne I/O chyby pouzivaji existujici
IOFIX retry; chyby obsahu nejsou opravovany tichym rebuildem.

Monoliticky bundle je zamerne minimalni V1: zmena mutable scope nebo mapovani
vyvola novy cold derivat. Pouze geometry key muze zustat logicky stejny; V1
nepredstira samostatnou partial geometry refresh optimalizaci. Solverovy krok,
pozorovane cile, C17 nebo CAL/VALID nevyvolaji dekodovani; agregace/role a
nasledna kalibracni logika se pocitaji znovu puvodnim kodem.
