# Zastavení před kalibrací: EXOG_EE_CF nemá dostupné uložené cesty

Dodané logy z 16. 11. končí chybou
`NO_SAVED_PRT_PATHS_FOR_POSITIVE_DEMAND:EXOG_EE_CF`.
Jde o jiný problém než dřívější neekvivalentní návrat po sondě TG.

V tomto pokusu preflight načetl kladnou mezizónovou poptávku segmentu
`EXOG_EE_CF`, ale omezené čtení jeho seznamu uložených cest vrátilo prázdný
výsledek. Selhání nastalo před vytvořením kalibračního adaptéru, před skriptem
utility a před změnami koeficientů či matic. Režim potlačení hlášení Visumu
byl podle `SILENT_MODE.json` obnoven bez chyby.

Z těchto příloh nelze rozlišit, zda segment nebyl přidělen, nebylo zapnuté
ukládání cest, výsledky smazal reset, nebo jde o jiný důvod prázdného seznamu.
Nevíme ani, zda chybějí cesty dalším segmentům: původní kontrola skončila
na prvním nevyhovujícím segmentu v abecedním pořadí.

## Postup ve Visumu

1. Otevřít ověřenou izolovanou kopii modelu 2025 se správnými koeficienty.
2. V operaci 15 ponechat nový `RUN_R1_TD_UTILITY_TRANSACTIONAL.py`.
3. Ověřit, že společný OA assignment zahrnuje všech 12 segmentů včetně
   `EXOG_EE_CF` a ukládá jejich cesty. Samotné zatížení WORK/SERVICE/LONG
   nestačí. Pokud je ukládání cest vypnuté, je nutné je nastavit v parametrech
   assignmentu; přípravný skript toto nastavení sám nepřepíná.
4. Přes **Scripts → Run script file** spustit z celého balíku
   `RUN_R1_2025_RECOMPUTE_FOR_LIVE04_BASE.py`. Tento existující postup
   nepřenáší ani nenastavuje koeficienty; provede nativní řetězec s LONG maskou,
   assignmentem a aktivními skimy. Uloží novou `<kopie>_LIVE04_BASE_<id>.ver`.
   Před spuštěním ověřit, že procedura obsahuje aktivní výpočet TTC/TT0 pro
   NATIVE_CW, NATIVE_CW_noT, NATIVE_CS, NATIVE_CS_noT a NATIVE_CL po assignmentu.
5. V `%LOCALAPPDATA%\R1C25_TRANSFER2025\RECOMPUTE_<id>\00_RESULT.json`
   vyžadovat `status = RECOMPUTED_SAVED` a `readiness = READY_FOR_LIVE04`.
6. Z nově uložené připravené verze spustit
   `RUN_R1_2025_CORDON_LIVE04_V7_TG_TD_CYCLE.py`. Mezitím nespouštět reset
   výsledků přiřazení.

Samotné opakování launcheru ani samostatné spuštění utility skriptu chybějící
cesty nevytvoří. Nový kalibrátor neprovádí automatický assignment uvnitř
čtecího preflightu.

## Doplněná diagnostika

`00_BASELINE/PATH_AVAILABILITY_PREFLIGHT.json` nyní obsahuje výsledky omezené
kontroly všech 12 segmentů, čísla a mezizónové objemy jejich matic a oba druhy
seznamů, které vrátily prázdný výsledek. Prázdné seznamy při kladné mezizónové
poptávce dál blokují spuštění. Pro nulovou mezizónovou poptávku se původní
výjimka nemění. Poškozené schéma nebo neověřené COM rozhraní zůstává chybou.

Kontrola prvních osmi řádků není důkazem úplné OD parity; tu stále ověřuje
následující plné zachycení. Boot výsledek při tomto konkrétním zastavení uvádí
konkrétní přípravný skript a cestu k diagnostice.

Testy ověřují chybějící cesty všech segmentů, chybějící geometrii jediného
segmentu při existujících rodičovských řádcích, výjimku pro čistě intrazonální
poptávku, správný startovací návod a nulový počet zápisů či neomezených exportů.
Přesné výsledky jsou v `evidence/path_preflight_20261116/CHECKS.json`.
Živý model ani Windows COM zde testovaný není; kód diagnostiky sám dostupnost
cest v uživatelově modelu nemění.
