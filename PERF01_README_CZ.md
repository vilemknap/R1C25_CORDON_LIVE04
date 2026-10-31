# R1 2025 CORDON PERF-01

**Explicitni overena cache pro opakovany offline vypocet stejneho snapshotu.**
Nevytvari nova data ve Visumu a nezapina kalibraci. Puvodni FIX3 exportery,
metodika, numericke tolerance a 15A2 solver zustavaji zachovane.

Zacnete souborem `docs/perf01/PERF01_RUNBOOK_CZ.txt`. Pouzivaji se prikazy
`python -m cordon2025 inspect-cache` nebo `propose` s explicitnimi volbami
`--reuse-cache-dir` a `--reuse-policy`. Vychozi `disabled` zachovava FIX3.
Nespoustejte tyto offline prikazy jako Visum Script.

Prvni build jednou vytvori immutable bundle. Dalsi `require-verified-hit`
hashuje zdroje a derivaty, ale znovu nedekoduje geometrie ani nestavi sparse
operatory. Vysledky obou metod zustavaji shodne s puvodnim cold oraclem.

Velky audit all_od_totals je ulozen jednou v typovane tabulce s bezeztratovym
slovnikovym kodovanim nazvu segmentu. Male run manifesty na nej odkazuji.
Pro stary samostatny format je dostupna explicitni volba `--legacy-incidence-output`.

Po novem assignmentu tato cache neni automaticky platna. Je urcena JEN pro
puvodni nemenny zapeceteny snapshot. Neumime z jeho OD souctu dokazat novy
routing; takovy pozadavek skonci blokaci.

Testy, schema, benchmark, omezeni a nezkracene logy jsou v `docs/perf01`.
Test na uplnem realnem exportu R1 zustava `WAITING_FOR_REAL_FINAL_CACHE`;
prilozeny `tools/perf01_real_acceptance.py` jej lze spustit lokalne bez Visumu.

Puvodni README_CZ.md zustava historickym navodem FIX3. Toto je nadstavba,
nikoliv nova aplikace puvodnich profilovych konfiguraci 2022.
