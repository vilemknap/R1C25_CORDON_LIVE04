# C17: ucet nejistoty V1

## Dukazy a hypoteza
D2 pred symetrizaci uchovava odlisne smerove radky/sloupce. D3 obsahuje dve
symetricke marginove kopie po expanzi. Uchovavame oba zdroje s adresami
bunek a hashi; zadny smer ani koeficient 2026->2025 nedomyslime.
Specialni navratova kategorie vjazd-vyjazd je z C17 vyjmuta. Klasifikacne
nerozpoznanych 1218 zaznamu ma samostatny audit a nepricita se znovu.

Vychozi politika UNAPPROVED (numericky stejne jako DISABLED) dava u=0.
Znama matice se nemeni. C17 se vykazuje v samostatnem prehledu rozpoctu.
Fyzicke prirazeni nezname dopravy ke konkretnim parum je PRODUCTION_DISABLED.

## BOUNDED_SCENARIO: pouze konzervativni kreditni relaxace
Tato explicitne zapinana citlivostni varianta NENI odhadem chybejici OD matice,
produkcni alokaci ani statistickym intervalem spolehlivosti.

Pro kazde stanovište s existuje jediny ucet B_s pro konkretni kategorii a
casovou bazi, prevzaty JEDNOU z jednoho symetrickeho marginálu D3. Radek a
sloupec nejsou dva nezavisle baliky. Predsymetricke smery zustavaji v auditu.

Nezaporna relaxace paru u_(a,b) rezervuje u kreditu na uctu a a u kreditu na
uctu b. Plati:

  R_s = sum_(paru obsahujicich s) u_par <= B_s
  sum_s R_s = 2 * sum_par u_par <= G
  0 <= G <= sum_s B_s

Protismery pouzivaji TYTEZ sdilene ucty. Globalni rozpočet neni dalsim
nezavislym zdrojem dopravy. Je to kontrola týchz kreditu. Jednotkou vystupu
je POOLED_STATION_RPDI_TOLERANCE_CREDITS_NOT_IMPUTED_VEHICLES.

Pravidlo rezervuje kredity konzervativne u obou koncu, ale NETVRDI, ze
nezname detekce opravdu identifikuji oba tyto konce. Zadna vozidla se jim
fyzicky neprideluji. Nelze z neho odvodit pocet dosud nezjistenych jedinecnych
jizd. Bez event-level evidence ani neumoznuje takovy pocet dokazat.

Rozpocty se nemuseji vycerpat. Kazdy navrh se posuzuje proti STEJNYM vychozim
limitum; zkouseni kandidatu postupne nespotrebovava trvale zasobu. VALIDATION
neovlivnuje alokaci. Spolecne zpracovane D3 ma korelovane chyby; tento mechanismus
nenahrazuje jejich statisticky model.

## Numericka implementace
Dykstrova projekce na nezapornost, stanovisni poloprostory a globalni kreditni
mez. Konvergence hlida primal i korekcni vektory a nasledne primalni
pripustnost. Pouhe sekvencni orezani bez Dykstrovych korekci se nepouziva.
Resic ma kladnou kvadratickou penalizaci cerpani; nema smysl vse schovat do u.
Pripustnost a shoda s nezavislym SLSQP oracle jsou testovany.

`eligible_fraction` je explicitni scenarovy parametr, ne odhadnuta mira
nesparovani. Produkcni prirazeni zustava vypnute i po uspesnem numerickem testu.

## Proc nejde o neomezene +/-C17
u>=0 muze zmírnit pouze prebytek modeloveho proudu nad znamou relaci.
Nedostatek modelovych vozidel vuci znamemu cilu C17 nevysvetluje. Samostatne
symetricke epsilon se smi zkoušet, ale default je 0 a bez chyboveho modelu
neni statistickym intervalem. Vyber realnych intervalu neni soucasti V1.
