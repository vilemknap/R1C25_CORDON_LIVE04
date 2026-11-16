# Porovnání a spojení diagnostiky Claudeova refit patche

Základ výsledného balíku je `57d91d865a3482ffc2beef8a5b1b92e01b63d01b`.
Přiložený patch `R1C25_REFITFIX_PATCH_5696339.zip` má SHA-256
`5bb3df5f56a6e1a0b8793ee216c51db7eb93372f68fa24c4d61a3cb3e819ba95`.

## Co obsahuje příloha

ZIP obsahuje čtyři soubory: `cordon2025/live04_generation.py`, tři krátké testy
pomocné kontroly rodiče a oba manifesty. Manifest je označen
`R1C25_LIVE05_8_UTILITY_STATE_RESTORE_20261115` a popisuje 1899 souborů;
současný základ popisuje 1971. Hashy obou Python souborů souhlasí s jeho
vlastním manifestem. To potvrzuje jejich vnitřní shodu, nikoli možnost
přepsat tím manifest a kód novějšího balíku.

Přepis současného `live04_generation.py` přílohou by odstranil sjednocení
datového cíle fitu/refitu, zahrnutí nulových cílů, některé kontroly totožnosti
pozorování a objektivu a zpracování použitelného nedokonvergovaného refitu.
Starší manifest navíc nezná sedm současných Python souborů. Příloha proto
byla porovnána samostatně a do aktuálního stromu se nepřepisovala celá.

## Převzatá diagnostika a zachovaná kontrola

Claudeův patch přidává užitečný přehled po řádcích, největší rozdíl,
nejhorší klíč a seznam chybějících klíčů. Tato diagnostika je zapojena do
současné verze a pokrývá dvě různé kontroly:

- zachycený vektor incidence proti rodičovské diagnostice;
- řádky vytvořeného fitu proti stejné rodičovské diagnostice.

Při selhání vznikne `MEASURED_ZONAL_REFIT_PARENT_MISMATCH.json` s metodou,
typem porovnání, dotčenými řádky, absolutními i povolenými rozdíly,
chybějícími a duplicitními klíči. Nepřípustné číselné hodnoty se zaznamenají
bez NaN/Infinity, aby audit zůstal platný JSON. Úspěšný refit zapisuje souhrn
této kontroly do `MEASURED_ZONAL_REFIT.json`.

Kontrola zachovává dosavadní toleranci stejného zachyceného rodiče:
`atol = 1e-9`, `rtol = 1e-12` (relativní část vůči hodnotě fitu jako v původním
`np.isclose(parent, fit)`). Claudeova navržená tolerance
`1 vozidlo + 0,001 × max(|fit|, |parent|)` se nepřebírá.

Tyto dvě kontroly porovnávají odvozené údaje stejného zachycení. Rollback
naopak může potřebovat porovnat dva nezávislé nativní přepočty. Jeho širší
tolerance zůstává ve své původní roli. U řádku kolem 1000 by tolerance
navržená v patchi připustila i skutečný rozdíl 1,5 vozidla. Syntetický test
ověřuje, že jej kontrola stejného rodiče dál odmítne.

Dřívější chyba kolizí `100*a+b` byla v našem základu reprodukována a
opravena jednoznačnými klíči. Dodaný výpis neuvádí skutečnou velikost
původního rozdílu a neprokazuje vysvětlení numerickým šumem. Nový audit
zaznamená konkrétní hodnoty, pokud se další nesoulad vyskytne.

## Nastavení a závěr o mobilitě

Zůstává uživatelem zvolený limit GENERATION EXACT_TWO_HITS +2 % vůči rodiči
a TD váhy 50 % normalizovaný kordónový cíl / 50 % FineCDF IDP. Poslední
živý běh dodaný před patchem už obsahuje přijatý krok s EXACT_TWO_HITS
+1,9301 %. Staré doporučení vrátit nulovou toleranci se nepoužilo.

Součet 1,03 milionu modelových hodnot proti 1,80 milionu pozorovaných je
součet přes 298 částečně se překrývajících pozorování; jedna cesta může
přispět do více řádků. Tento poměr sám neurčuje počet chybějících vozidel
ani příčinu chyby. Mobilitní brána v přijatém kroku prošla, rodinné poměry
WORK 1,84998 a SERVICE 2,04611 jsou pod horní mezí 3,5. U platných zónových
poměrů těchto rodin bylo maximum přibližně 3,1497. Tyto údaje neprokazují,
že mobilita způsobuje celkový rozdíl; k rozlišení zdrojů chyby je třeba
řádkové členění a příspěvky DSeg.

## Ověření a použití

Testy a audit porovnání jsou v `evidence/claude_refit_review_20261116/`.
Kontrolují přesnou shodu, malý numerický rozdíl, odmítnutí širšího rozdílu,
chybějící či duplicitní ID, neplatné hodnoty, oba typy skutečného selhání
refitu a zachování jeho úspěšného průchodu. Živý Windows/Visum zde není.

Pro další spuštění použít celý spojený balík po restartu Visumu.
Do právě běžící instalace se žádné soubory nepřepisovaly.
