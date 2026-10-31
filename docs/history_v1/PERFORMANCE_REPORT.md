# Performance report - SYNTHETIC ONLY

Mereni na explicitne konstruovanych cestach ve formatu V24915 SQLite. Nejde
o vytvareni alternativnich cest pro realny model. Prumerna delka je ~49 hran;
16 station IDs, dva mody a 12 demand segmentu s nezavislymi Vol(AP).
Tvorba fixture a mereni probehly v oddelenych procesech. Peak RSS z mereni
proto nezahrnuje predchozi vyrobu fixture. Jeden BLAS/OMP thread.

| Geometrie | Objemove radky DSeg | Vyskyt hran | Incidence s | Solver s | Peak RSS MiB |
|---:|---:|---:|---:|---:|---:|
| 20,000 | 120,000 | 979,616 | 2.694 | 0.757 | 288.4 |
| 100,000 | 600,000 | 4,899,808 | 14.835 | 4.363 | 1000.2 |

Velka uloha ma 200 000 mutable OD promennych a 666 624 nenulovych clenu
all-pairs operatoru. Dekodovano presne 100 000 geometrii, nikoli 12x tolik
ani 240x tolik. Soucasne vznikaji OBE hypotezy. Per-DSeg a per-OD parita PASS.
Solver je puvodni FISTA nad nove sestavenou kordonovou ulohou a konvergoval
podle ulozeneho KKT/gradient mapping kriterium. Nejde o Visum assignment.

C17 polytope je v tomto velkem sparse benchmarku DISABLED. Jeho joint
konvergence/projekce je overena samostatnymi malymi testy a demo. Neni zde
mereni vykonu C17 na plne realne uloze ani tvrzeni o zrychleni realneho R1.

Prvni kombinovany pokus pro 100k skoncil tool timeoutem bez mericiho reportu.
Fixture se dokoncilo. Nasledujici SAMOSTATNE mereni ze stejneho snapshotu
probehl s rc=0; jeho log/JSON jsou autorita techto cisel. Root cause prvniho
preruseni nebyla prokazana a nebyl oznacen jako PASS.

Reprodukce do noveho izolovaneho adresare (ne do existujici cache):

```text
python tools/benchmark.py --count 20000 --work-dir OFFLINE_RESULTS/BENCH_NOVY_20K --report OFFLINE_RESULTS/BENCH_NOVY_20K.json
python tools/benchmark.py --count 100000 --work-dir OFFLINE_RESULTS/BENCH_NOVY_100K --report OFFLINE_RESULTS/BENCH_NOVY_100K.json
```

Velke fixture databaze nejsou nutne pro spusteni baliku; jsou reprodukovatelne
generatorem. Do release patri merene logy/JSON a male end-to-end SQLite demo.
