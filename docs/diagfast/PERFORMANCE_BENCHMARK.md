# PERFORMANCE BENCHMARK - DIAGFAST EXACT V1

Status: SYNTHETIC_BENCHMARK_PASS, native performance NOT_MEASURED.

Reprodukovatelny prikaz:
```text
python tools/diagfast_benchmark.py --output NEW_FOLDER --routes 3000 --zones 681 --repetitions 3
```

Fixture: 681 zon, 12 DSeg, dva rozdilne mody, 3 000 cest na mod (6 000 celkem),
36 cteni matic na kazdy run; vsechny cesty vcetne nulovych objemu a empty cest.
Simulovany provider bez nativniho PTV/COM prenosu. Kazdy run v novem procesu,
stridave poradi, OS filesystem cache nekontrolovana. Neoznacujeme to cold-disk.
Python a platform jsou v kazdem surovem zaznamu. NumPy/BLAS threads=1.

Mereny interval zahrnuje read-only capture, vsechny proofy, originalni incidence
obou metod, legacy reporty, checkpointy a timing sidecar; nezahrnuje vyrobu
synteticke fixture, nasledne nezavisle porovnani a packaging ZIPu.

| Backend | Page | Median s | p95 s | Speedup vs legacy | Provider calls | Scratch DB |
|---|---:|---:|---:|---:|---:|---:|
| LEGACY | 256 | 11.808 | 12.325 | 1.000 | 3696 | 10 |
| FAST_EXACT | 256 | 10.293 | 10.673 | 1.147 | 3696 | 0 |
| FAST_EXACT | 512 | 10.228 | 10.979 | 1.154 | 1860 | 0 |
| FAST_EXACT | 1024 | 9.922 | 10.164 | 1.190 | 948 | 0 |

12/12 cele vysledky (vcetne opakovani legacy) PARITY_PASS: vsech osm SQL
tabulek, presne geometry blobs, OD_PARITY, STATION_HITS, oba metody, directed
diagnostiky, 120 relaci a 108/12 role. Porovnani bez nove float tolerance.

Nejlepsi median posledniho syntetickeho mereni ma 1024. Default zustava 256,
auto_tune OFF, dokud nativni benchmark neprokaze stabilni prinos vyssi stranky.
Predchozi opakovani melo nejlepsi 512. Pocet calls neni casovy speedup;
poradi vykonu se muze menit. Host nebyl dedikovany, soubezne bezely regrese.
Cil 1.5x cely capture / 2x proof NENI prokazan ani garantovan.
Pro nativni Visum plati NO_PERFORMANCE_CLAIM / LIVE_PENDING.

SQLite: legacy vytvoril deset proof databazi, soucet jejich finalnich velikosti
10 354 688 bytes (peak jednoho 1 069 056). FAST zadnou. Nejde o pocet fyzicky
zapsanych bytes; OS process_io_delta je vedlejsi samostatna metrika a muze
nezahrnovat odlozene zapisy. Native wire bytes a Windows peak RSS nejsou merene.

Instrumentace: TIMING_OVERHEAD.json porovnava raw legacy proti timed legacy
v nove, oddelene sestici pruchodu. Inclusive/exclusive stage times se nesmi
scitat naslepo. SQL execute timing nezahrnuje iteraci kurzoru; ta spada do
parseru. Zpracovani a typove prevody provideru v mocku nejsou PTV latency.

Prvni nefinalni benchmark se zastavil na CHECKPOINT_CODE_CHANGED, protoze
zdrojovy strom byl pri vyvoji soubezne upraven. Neni zapocten jako PASS.
Opakovani bezelo z nemenne zmrazene kopie; puvodni chybovy log zustava v raw/.
