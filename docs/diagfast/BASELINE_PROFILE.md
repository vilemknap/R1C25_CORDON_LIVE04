# Baseline

Kodove potvrzena cesta: viz BASELINE_CALL_GRAPH.md a COM_READ_PLAN_AUDIT.csv.
Native R1 soubory dokladaji dokonceny FIX3 capture, ale neobsahuji synchronni
rozpad doby COM/SQLite/CPU. Tyto casy jsou NOT_MEASURED.
Pocet ~296 mil. linkovych vyskytu je extrapolace z 8x C + 4x C_NOT;
neni namereny cas ani pocet volani nove vetve.
Nova merena synteticka legacy baseline: PERFORMANCE_BENCHMARK.json.
Pro DIAGFAST native zatim zadny speedup claim.
