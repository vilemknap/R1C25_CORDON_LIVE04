# Oprava předávání vstupů do nativního Run scriptu Visumu

Základ: `fc388950f412593261ca9b8adb962a661101d3bc` z větve
`codex/cordon-utility-restore-fix-20261115`. Nová větev:
`codex/cordon-utility-com-fix-20261116`.

## Dvě odlišná selhání z dodaných běhů

1. `TD_UTILITY_NATIVE_SCRIPT_MUST_USE_PARENT_INPUTS_ONCE`: vložený skript
   Visumu neviděl `ContextVar` vnějšího kalibrátoru. Oprava `fc38895` již
   předává vstupy přes jeden procesní kontext; tuto opravu zachováváme.
2. COM chyba při `a == b` v `transaction_inputs`: porovnání dvou COM proxy
   se pokusilo použít rozhraní z jiného COM apartmánu. Záložní porovnání názvu
   verze se k vykonání vůbec nedostalo. Ani čtení `raw.IO` z vnějšího COM
   objektu by uvnitř callbacku nebylo vhodnou náhradou.

Obě příčiny jsou reprodukovatelné na syntetické náhradě. V dodaném
`00_RESULT.json` pro první chybu je `model_state_verified=true`, nulový počet
přijatých stavů a stav `LIVE04_STOPPED_MODEL_VERIFIED_AT_LAST_ACCEPTED_STATE`.
Pro COM chybu dodaný `FAILURE_STATE_READBACK.json` také potvrzuje shodu hashe
s posledním přijatým stavem. Tím se tyto běhy liší od staršího neověřeného
návratu TG. Baseline, maska LONG a čtení cest v těchto bězích již prošly.

## Výsledná oprava

Před synchronním `Procedures.Execute` se v původním kontextu připraví balík
čistých dat: přijaté časové skimy, OD váhy, hashe, pořadí zón, vazby matic
a aktuální název otevřené `.ver`. Balík neobsahuje adaptér ani COM proxy.

Vložený skript může běžet ve vlastním Python kontextu nebo vlákně. Ze svého
vlastního, Visumem vloženého COM objektu přečte název verze; předávané zóny
a vazby skimů musejí také souhlasit. Vnější COM objekt neporovnává ani nečte.
Kontrola je vázaná na aktivní synchronní volání procedury, jeho rodičovský
stav a tyto datové identity; není to porovnání identity COM instance ani
trvalá cache podle názvu souboru.

Název verze se zachytí znovu pro každé volání. **Checkpoint s novým názvem
`.ver` mezi voláními je povolený.** Změna názvu během jednoho předání je
odmítnuta. Normalizují se Windows oddělovače a velikost písmen.

Procesní kontext se otevírá a zavírá pod krátkým zámkem. Zámek se nedrží
během COM volání. Vnořený či souběžný pokus nesmí kontext přepsat; opožděné
čtení po uzavření nesmí převzít data. Úklid proběhne i po chybě. Zůstává
požadavek přesně dvou čtení skriptem: vstupní načtení a závěrečná kontrola.
Váhové a časové mapy jsou pouze ke čtení, NumPy pole jsou nezapisovatelná
a diagnostické slovníky se vracejí jako samostatné kopie.

Zachovány jsou všechny změny od `41ee523` po `fc38895`: segmenty bez OD
matice, načítání vloženého kódu přes `ExecuteScriptParameters`, diagnostika
skutečně přečteného skriptu, podrobná kontrola release a procesní kontext.
Zachovány jsou i ASD3, OPMAP, geometrická pipeline, LONG maska a pravidla
přijetí a rollbacku. Žádný nový přímý zápis OD matic se nepovoluje.

Navíc jsou opravené dvě chyby ve stejném ověřování vstupů:

- Deklarovaný prázdný vložený skript nebo prázdná deklarovaná cesta se nesmí
  ověřit podle jiné, staré reference `SCRIPTFILE`. Takový stav se nyní odmítne
  před změnou koeficientů.
- Výjimka při čtení OD vazby, kterou nelze převést na text, nesmí být
  nahrazena novou chybou ze `str(exc)`. Původní výjimka se zachová.

Dřívější zastavení na chybějících cestách má samostatný návod
[MISSING_PATHS_20261116_CZ.md](MISSING_PATHS_20261116_CZ.md). Čtecí preflight
nyní zaznamená všechny chybějící segmenty; automatický assignment nepřidává.

## Instalace

Rozbalit celý nový balík do čisté složky. Přenést případné vlastní nastavení
`CORDON_LIVE04_CONFIG.json`. Restartovat Visum, aby se odstranily staré moduly
z paměti, otevřít ověřenou připravenou výchozí verzi a spustit obvyklý
`RUN_R1_2025_CORDON_LIVE04_V7_TG_TD_CYCLE.py`.

**Tato oprava nemění `RUN_R1_TD_UTILITY_TRANSACTIONAL.py`.** Pokud vložený
skript operace 15 již prošel kontrolou v dodaném běhu, není potřeba jej
znovu instalovat ani kvůli této opravě přepočítávat výchozí model. Nemění se
`LAMBDA=0.5`, poměr TTC/TT0 ani 16 utility matic.

## Ověření

Testy zahrnují COM proxy, jejichž porovnání úmyslně vyvolá obdobu chyby
apartmánu, a to na stejném i odlišném vlákně. Dále ověřují obnovu rodiče,
nezávislost sond TD na pořadí, vložený kód, checkpoint, cizí model, změněné
osy a vazby, nezapisovatelnost vstupů, vnořené/souběžné kontexty a opožděný
callback. Přesné počty, logy a hashe vstupů jsou v
`evidence/com_context_20261116/`.

ZIP dodaný v chatu přesahoval přenosový limit 32 MiB. Podle uživatelova
potvrzení byl novější základ ověřen přímo na GitHubu; doplňující tracebacky
byly přečteny samostatně. Nativní Windows COM ani skutečný model zde spustit
nelze. Offline simulace tedy neprokazuje bezchybný celý živý kalibrační běh.
