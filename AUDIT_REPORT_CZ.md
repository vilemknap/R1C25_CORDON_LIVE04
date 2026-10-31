# Audit agresivni kordonove varianty

Zaklad: uz hotovy R1_2025_CORDON_V2_BUGFIX_PORT_20261022.zip.
Zdroj politiky: R1_15A2_PROFILE488_AGGRESSIVE_TGTD_V1_FIX1_IOFIX4_BASE_20261022(1).zip.
Presne hashe zdroju jsou v docs/aggressive/INPUT_MANIFEST.json.

## Strategie portu

Zachovan cely parent kordonu; z profiloveho baliku se neprenasi launcher ani
zmena runtime matice. 153 sdilenych top-level knihoven jsou identicke, 4 se lisi.
Rozdily jsou evidovane, neprepisuji se slepe. Zdrojove JSON politiky jsou ulozeny
beze zmen, ale jejich prenesena nastaveni jsou explicitne na whitelistu.
Vsech 807 chranenych parent/data/config souboru souhlasi s V2.

## Preneseno do skutecnych konzumentu

Fazove OD bounds -> puvodni FISTA GuidanceProblem.
ADD/salary/family log bounds -> puvodni project_guidance_to_add a signed design.
6 meritkovych pokusu -> nova OFFLINE orchestrace s CAL objektivem a realizovatelnosti.
7 TD meritek + komponentni prahy -> lokalni parametricky API kontrakt, ne Visum.
Sealed konfigurace, zdrojovy hash, scenario hash a oddelene behy -> stavajici session.

## Zamerne neprevzato

488/CSD observation autorita, vsechny profily CAL, GEH20/30 severity vyjimky,
FRESH100 automaticka produkcni smycka, COM write/reload, globalni aktivace runtime
patchu. Zadny uvolneny C17, fixed scope, epsilon, L1/ridge nebo native IPF.

## Nova ochrana pri vetsi agresivite

Stejny C17 podproblem se pocita i pro nulovou zmenu modelu; srovnani proto
neodmeni pouhe prealokovani nejistoty. Kazda alternativa ma vlastni ledger
nad stejnym nezvetsenym budgetem. Hodnoty holdoutu nevybiraji vitezny krok.
Chybejici realna TG/TD response zustava NOT_VERIFIED. P/A projekce nestaci jako
dukaz realizace cele OD matice. Stage je explicitni offline selector, ne realny
pocet acceptance cyklu. I plne schvaleni metodickych vstupu v teto V1 neodemkne APPLY.

## Soubory a dukazy

SOURCE_CHANGE_MAP.json: konkretni zdrojove zmeny oproti V2.
PRESERVED_V2_FILES.json: puvodni chranene byty.
TEST_REPORT.md: 253 nove+puvodni kordonove testy, 879 parent kompatibilitnich,
a explicitne zachovany nezdar originalni V24915 identity v plne sade.
SYNTHETIC_EVIDENCE: demonstrace vetsi korekce i nerealizovatelnosti.

Historicke root reporty V2 jsou v provenance/cordon_v2_root_reports.
Zive testovani: NE. Model 2022 ani otevrena instance Visumu nebyly pouzity.
