# Kordonova semantika: rozhodnuti CP01

Stav: UNAPPROVED_OBSERVATION_SEMANTICS. Obe historicke varianty zustavaji pouze diagnostickymi hypotezami. Model 2025 nebyl spusten.

## Doklady
V24915 r1_15a2_core.build_actual_path_incidence tvori usporadane dvojice podle prvniho vyskytu stanice. Volitelne vylucuje opakovane stanice. Read-only V1 r1_cordon_2025.extract_pairs porovnava ALL_ORDERED_UNIQUE_PAIRS a EXACT_TWO_HITS; pri opakovani stanice obe varianty vyluci.

Prvni pravidlo zachova prujezdy pres vice stanic, ale korelovane relace mohou mit vice prispevku od jedne cesty. Druhe pravidlo je restriktivni a muze vynechat skutecne prujezdy. Bez dokladu o konstrukci prislusneho mereneho observable nelze zvolit produkcni variantu. Sekvence z rekonstrukce vypadku SDP4 NENI pouzita jako rozhodovaci pravidlo.

## Smer a agregace
Actual D1/D2 header: Riadok = Vystup (O), Stlpec = Vstup (D). Tento popis se zatim neprevadi na vstup/vystup fyzicke linky. D3 symetrizovana tabulka ma presne shodne protismery. Navrh hlavni V1 diagnostiky je BIDIRECTIONAL_SUM; jednotlive smery se vzdy zachovaji a ulozi. Smycky, navraty a vice nez dve stanice jsou explicitne oznaceny. Default EXCLUDE_FLAGGED je pouze auditovana politika, nikoli tiche odstraneni.

## Skutecna odchylka od zjednoduseneho popisu
D2 nepouziva ve vsech bunkach nezakulaceny prumer. Transit/NonTransit obsahuji IF(ISEVEN(ROW()+COLUMN()),ROUNDUP(...),ROUNDDOWN(...)); ALL se sklada z techto dvou zaokrouhlenych bloku. Proto celkova suma nemusi presne odpovidat puvodnimu souctu. D1 FINAL=D2 FINAL a D2 SYM=D3 M0 prosly po vsech 15 blocich; vzorce jsou v AUTHORITY_AUDIT.json. Data jsme neopravovali ani neprepocitavali.

## Povinne produkcni doklady
Schvalena definice merene relace a opakovanych prujezdu; smerove vazby stanic na konkretni sit; rok 2026 -> 2025; plny OA segment scope; geometricka identita a objemova parita. Bez nich pouze DIAGNOSTIC/BOUNDED_SCENARIO, nikdy production PASS.

CAL/VALID role se deli po neusporadanych dvojicich. Aktualni vyber je explicitni vyvojovy holdout; po vyrovnani matic nejde o statisticky nezavisly terenni vzorek.
