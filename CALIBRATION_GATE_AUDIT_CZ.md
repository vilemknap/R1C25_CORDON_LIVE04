# Kontrola návaznosti kalibračních pravidel (18. 11. 2026)

## Skutečné rozpory opravené v této větvi

1. TD porovnávalo kombinovaný cíl ve vnitřním hledání s aktuálním mezikrokem,
   zatímco závěrečné schválení jej porovnávalo se začátkem bloku. Pozdější
   mezikrok tak mohl projít vnitřním hledáním, ale zhoršit celkový výsledek.
   Obě fáze nyní používají začátek bloku; vnitřní hledání navíc ponechá jen
   krok lepší než dosavadní nejlepší.
2. Pokud nebyl dostupný IDP Jacobian, TD s požadovaným cílem 55 % kordón /
   45 % IDP tiše přešlo na kordónový cíl. Nyní zapíše
   `BLENDED_IDP_MODEL_UNAVAILABLE` a neprovede ostrý pokus. Výslovně nastavená
   nulová váha IDP nadále znamená kordónový režim.
3. V předchozím commitu se pro TD sjednotila kontrola EXACT_TWO_HITS ve
   vnitřním hledání i závěrečném schválení na 5 %. Hlavní kordónová mez je 1 %.

## Pravidla jednotlivých bloků

| Blok | Návrh | Rozhodnutí po Visumu | Vědomý rozdíl |
| --- | --- | --- | --- |
| Generation | fit, predikce na zachycených cestách, pre-apply kontroly | plné přiřazení, FIRST_LAST, EXACT_TWO_HITS ≤ +2 %, GEH, mobilita, LONG | změna tras může změnit účinek oproti predikci |
| TD | nativní sondy, kombinovaný cíl 55/45, IDP a obě kordónové metody | plné přiřazení, kombinovaný zisk ≥ 0,1 %, FIRST_LAST ≤ +1 %, EXACT_TWO_HITS ≤ +5 %, GEH, IDP, LONG | změna tras může změnit účinek oproti sondám |
| SupplyMix | návrh podle vybraných profilových skupin a sekvencí cest | plné přiřazení na všech pozorováních, sekundární metoda bez zhoršení, GEH, LONG | návrh nezaručuje výsledek na doplňkových pozorováních |

SupplyMix proto stále může draze zkoušet návrhy, které závěrečný gate odmítne.
Jeho nulovou toleranci sekundární metody tento audit nemění. Obdobně přeskočení
jednoho TD cyklu po cyklu bez přijatého kroku je současná plánovací politika,
nikoli důkaz, že všechny následující TD pokusy budou neúspěšné.

## Kontrola SupplyMix (19. 11. 2026)

Tvorba SQLite úložiště tras používala pevné jméno v pracovní složce. Chyba
uprostřed čtení zanechala částečný soubor, který zablokoval další pokus ve
stejné složce. Každý pokus nyní dostane vlastní jméno a neúplný soubor se po
chybě uzavře a odstraní. Průběh tvorby se zapisuje i při přechodu mezi trhy;
zápis je omezen na nejvýše jednou za 30 sekund.

Návrh SupplyMix dál hodnotí hlavní profilové skupiny podle GEH a dostupných
sekvencí cest. Závěrečná kontrola navíc zahrnuje doplňková pozorování a
EXACT_TWO_HITS s nulovou tolerancí zhoršení. Jde o rozdílný rozsah návrhu a
akceptace, takže přijetí bez plného přiřazení nelze zaručit. Měnit tuto
toleranci bez rozhodnutí o kvalitě sekundární metody by změnilo cíl kalibrace.

## Důkaz a hranice

Regresní testy ověřují společnou výchozí referenci TD, nezhoršování nejlepšího
mezikroku, 5% sekundární mez, návrat do rodičovského stavu a explicitní
nedostupnost IDP modelu. Simulace používá syntetický Visum; chování na živém
modelu lze potvrdit až novým během. Předchozí běh se řídil starším kódem.
