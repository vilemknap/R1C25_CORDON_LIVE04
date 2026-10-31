# V2 synthetic performance comparison

Same exact generated SQLite, 100,000 geometries, 600,000 segment-volume rows,
4,899,808 ordered link occurrences and 200,000 mutable OD variables. Independent
measurement processes, one run per version, same environment Python 3.13.5.

| Measurement | Original V1 | Updated V2 |
|---|---:|---:|
| Incidence seconds | 29.594258 | 26.211824 |
| Solver seconds | 8.057359 | 7.281043 |
| Peak RSS MiB | 1005.473 | 1005.434 |
| Solver iterations | 410 | 410 |

Objectives and KKT values are exactly equal. Input hash: 840dad1975864905eb7ab78ba748af6a753a9b8eb5d7ffff3d45739cf7b77c86.
Geometry decoded once, both historical incidence hypotheses produced.
C17 relaxation is disabled in this large-scale test; its separate synthetic
joint-solver tests still run. Results do not estimate live Visum time. Single-run
timing differences are not a statistical speedup claim. The earlier V1 figures
from another runtime are historical, not the baseline for this comparison.
