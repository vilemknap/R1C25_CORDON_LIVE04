# Export aktuálních vzdáleností z Visumu

Spusťte `RUN_R1_EXPORT_CURRENT_VISUM_DISTANCES.py` přes **Scripts → Execute script file**
na uložené kopii modelu po dokončeném přiřazení a výpočtu skimů. Během běžící
kalibrace skript nespouštějte.

Skript pouze čte: pevnou matici 9697 a skimy `DIS` pro NATIVE_CF, NATIVE_CL,
NATIVE_CS, NATIVE_CS_noT, NATIVE_CW a NATIVE_CW_noT. Nový adresář
`R1_DISTANCE_EXPORT_YYYYMMDD_HHMMSS` vznikne vedle otevřené `.ver`. Obsahuje:

- `CURRENT_VISUM_DISTANCES.npz`: plné matice a `zone_no` v pořadí os;
- `RESULT.json`: čísla matic, hashe, základní statistiku rozdílů;
- `LARGEST_DISTANCE_DIFFERENCES.csv`: nejvýše 100 největších rozdílů od 9697
  pro každý segment, pokud je absolutní rozdíl alespoň 5 km.

`DIS` v dodaném postupu znamená průměrnou délku **přiřazených tras váženou
objemem**, včetně konektorů. `DID` je přímá vzdálenost a neexportuje se. Samotné
čtení matice nedokáže prokázat, že skimy byly po poslední změně konektorů znovu
vypočteny; tuto podmínku musí splnit předchozí přiřazení a výpočet skimů.

Export nemění 9697, LONG masku ani model. Rozhodnutí, zda a jak nahradit 9697,
vyžaduje následně prohlédnout výsledné hodnoty a rozdíly mezi segmenty.
