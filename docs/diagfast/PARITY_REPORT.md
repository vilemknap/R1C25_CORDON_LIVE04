# Parita LEGACY / FAST

12 benchmark runu PARITY_PASS, testy take pro 256/512/1024.
Comparator: cordon2025/diagfast_parity.py; numpy allow_pickle=False, dtype,
shape a vsechny hodnoty; SQL presna rovnost a kanonicke digests. Dlouhe JSON
se porovnavaji streaming line-by-line; nikoli dva 617MB objekty v pameti.
Pouze cache/evidence SHA se normalizuji, az po nezavisle semanticke kontrole
obsahu. Proof schema se lisi o oznacena nova evidencni pole, nikoli scope.

Negativni testy umi zamitnout mimo jine jednu zmenenou hodnotu, redistribute
OD se stejnym souctem, chybnou geometrii a zmenu aktualniho stavu behem capture.
Neovereny native stav ani kalibracni ACCEPT/ROLLBACK tim nejsou schvaleny.
