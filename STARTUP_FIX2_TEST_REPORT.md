# R1 CORDON STARTUP FIX2 COMBUSY - testovaci protokol

## Aktualni vysledek

- Obnoveny STARTUP_FIX1: 270 + 68 = **338 passed**, vsechny puvodni testy, dve navazujici sady.
- Dodany profilovy COMBUSY HOTFIX1, cela sada: **967 passed / 4 skipped / 0 failed**.
- Nove kordony STARTUP_FIX2, cela sada v jednom procesu: **424 passed / 0 failed / 0 skipped**.
- Z toho pridano **86** automatickych testu v tomto pokracovani.
- Rodicovska kompatibilita: **879 passed / 4 skipped / 1 explicitly deselected**.
- Vyrazeny historicky test byl spusten samostatne a **FAILNUL**: puvodni V24915 byte-identity seal odmita ctyri soubory jiz zmenene v obnovenem STARTUP_FIX1: r1_15a2_com_compat.py, r1_15a2_core.py, r1_15a2_supply.py, r1_15a2_two_mode_v238.py. Neni to PASS puvodni identity. Ani jeden z techto souboru nebyl v tomto portu zmenen.
- Synteticka numericka parita oproti obnovenemu STARTUP_FIX1: **84/84 poli v 19 NPZ archivech presne shodnych**; obe demonstrace SYNTHETIC_AGGRESSIVE_DEMO_PASS.
- Chranene puvodni soubory: **808** (parent, data a oba konfiguracni soubory) beze zmeny.
- Dalsi existujici moduly cordon2025 mimo startup/verzi: **17** beze zmeny.

## Red/green dukazy a nehotove behy

1. Sest nezakrytych vlastnosti/TypeInfo v obnovenem zdroji bylo reprodukovano jako BusyError: ROOT_NET, NET_ZONES, NET_LINKS, NET_DSEGS, GET_MULTI_MEMBER, TYPEINFO. Pred/po JSON zustavaji v evidence.
2. Prvni novy STOP test zjistil druhe Invoke po STOP vytvorenym behem message pump. Opravena kontrola pred kazdym dalsim nativnim Invoke, bez druhe retry smycky.
3. Prvni rozsirena hostitelska sada mela dve chyby testoveho setupu: cizi modul byl vlozen pred vyrobenim simulovaneho modelu, a tim opravnena izolacni kontrola zablokovala uz konstrukci fixture. Poradi setupu bylo opraveno; produkcni guard nebyl uvolnen. Puvodni log je zachovan.
4. Prvni uplny pokus o obnovene testy a prvni spolecny pokus FIX2 nemely konecny JUnit/summary po preruseni nastrojem. **Nejsou pocitany jako PASS**. Diagnosticka 185-testova skupina dokoncila vsechny testy. Nasledujici uplny beh FIX2 ma JUnit 424/424 a returncode=0.
5. Vsechny Visum/COM testy jsou **oznacene simulace**. V prostredi nebyl nativni Windows/PTV Visum ani skutecny R1 2025 model.

## Pokryte chyby

RPC_E_CALL_REJECTED, RPC_E_SERVERCALL_RETRYLATER, unsigned HRESULT, chyby s rozbitym str/repr; busy pri ziskavani vlastnosti i bound metody, TypeInfo a SaveToArray; nepremenene rozsahy davek a zadne duplicity; jeden retry rozpocet bez nasobeni vnorenych pokusu; vypnute retry; vycerpani pokusu a casoveho rozpoctu; porucha telemetrie; STOP behem backoff/message pump; chybne/menici se matice, geometrie a Vol(AP); zachovani cizich modulu 2022 a sys.path po uspechu i chybe; zadne profilove launchery ani ROT/Dispatch.

## Reprodukce

```text
python verify_release.py
python -m pytest -q tests -p no:cacheprovider
python tools/parent_compatibility.py
python RUN_CORDON_AGGRESSIVE_OFFLINE.py demo
```

Surove logy, JUnit XML, prikazy a navratove kody jsou v docs/startup_fix2/evidence. Cisty rozbaleny release ma samostatny externi finalni overovaci protokol. Uplynuly cas testu neni vykonovy benchmark realneho modelu.
