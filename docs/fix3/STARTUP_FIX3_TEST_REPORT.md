# STARTUP FIX3 - test report

## Dokoncene vysledky nad finalnim kodem

| Beh | Vysledek |
|---|---|
| Puvodni FIX2 | 424 passed |
| Aktualni FIX3 uplna kordonova regrese | 493 passed, 0 failed, 0 skipped |
| Z toho nove testy | 69 |
| Nezmeneny parent kompatibilitni beh | 879 passed, 4 skipped, 1 explicitne deselected |
| Originalni parent deployment guard, spusten samostatne | 1 failed, ocekavane: ctyri historicky zmenene soubory forku |
| Realny NATIVE_CW replay | puvodni FAIL, nova parita PASS; bez zmeny vstupu |
| Synteticka agresivni demonstrace | PASS, vyber zmenseneho kroku a zamitnuti nerealizovatelnych OD |
| Syntax vsech Python souboru | viz evidence/compile.json |

## Negativni scenare

Testy nadale odmitaji: velkou chybejici dopravu, presuny mezi OD pri stejnem
celkovem souctu, NaN/Inf/zaporne hodnoty, zmenene nebo chybejici geometrie,
chybejici segmenty, zmenu source matice, zmenu path objemu pri capture,
podvrzenou politiku parity nebo evidence/cache hash, zmenu zmrazene dopravy,
nepovolene modelove zapisy a CAL/VALID leakage.

Novy test nahrazeni rodicovskeho souctoveho guardu porovnava 600 realne ulozenych
nulovych objemu: maticova hodnota 0.294 je vysvetlitelna kvantem a projde;
hodnota 0.4 uz prekroci per-OD mez a je zamitnuta. Originalni parent verdict
se neprepisuje. Test agregace chyb bez parent zaznamu dale neprojde.

Kompletni mock-COM capture kontroluje vsech 12 segmentu i nasledny nezavisly
reader. Nejde o nativni instalaci PTV. Realna p.sqlite je nekompletni; replay
nekontroluje plnou geometrii a nikdy ji neoznacuje za dokonceny snapshot.

## Dochovana neuspesna / nedokoncena evidence

- focused1: pocatecni importni chyba noveho default parametru, opravena pred dalsimi testy.
- full1: 481 passed / 8 failed. Dva testy puvodnich konfiguracnich hashu, jeden
  test noveho explicitniho COM retry nastaveni a pet spravne blokovanych vstupu
  kvuli tehdy nezapsanemu novemu replay skriptu v manifestu. Vse opraveno.
- full2: 487 passed / 2 failed. Chybne cteni mapy reviewed changes v testech.
- full3: explicitne preruseny pri oprave stejneho testovaciho kontraktu;
  nepovazuje se za PASS.
- targeted_review_fixes: preruseny casovym limitem, nepovazuje se za PASS.
- full4: 489 passed, mezibod pred posledni opravou souctoveho guardu.
- precision_aggregate: 84 passed (69 novych + navazujici incidence testy).
- full5: kompletni finalni sada 493 passed.

Puvodni deployment guard 24915 nebyl zmenen ani preznacen. Kompatibilitni beh
jej explicitne oddeluje; jeho neuspech je v parent_identity.log/xml.
Testy identity kordonoveho forku maji presne before/after SHA pouze pro
reviewovane zmeny konfigurace. Ostatni soubory nadale vyzaduji byte-shodu.

## Distribucni overeni

Po zabaleni se musi testy a demo zopakovat z ciste rozbalene dodavky.
Doklad teto posledni faze je samostatny FINAL_VERIFICATION JSON a CP_P03;
nelze jej ulozit dovnitr uz overovaneho ZIPu bez zmeny jeho hashe.

Native new FIX3 test = false; live calibration implemented = false; apply = false.
