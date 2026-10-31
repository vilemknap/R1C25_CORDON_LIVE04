> FIX3: Tento dokument je historicky. Aktualni testy a limity jsou v docs/fix3/ a FINAL_STATUS.json. Vykonnost nove uplneho nativniho capture zatim nebyla zmerena.

# Aggressive synthetic benchmark

Measured in a fresh process, Python 3.13.5, Linux, single
BLAS thread. Fixture creation and measured processing ran in separate processes.
One measurement per policy; not a statistical speed guarantee.

- 10,000 synthetic geometries; 60,000 per-segment volume records.
- 489,808 link occurrences; 20,000 mutable OD variables; 120 aggregated rows.
- C17 disabled in this scaling benchmark; no actuator basis supplied.
- Same path incidence, targets and regularization for standard and aggressive.
- Truth target deliberately requires a +25% step; this favors a larger trust region
  and is a functionality demonstration, not independent traffic validation.

| Measurement | Value |
|---|---:|
| Incidence (both historical hypotheses) | 1.4707 s |
| Standard solve | 0.1822 s |
| Aggressive solve + six trial scores/projections | 1.2614 s |
| Process peak RSS | 199.70 MiB |
| Standard objective | 231.35596599 |
| Aggressive objective | 95.39080729 |
| Max OD step (standard / aggressive) | 15% / 20% |

Both guidance solvers converged. The aggressive route is slower because it does
more work; no claim of improved runtime is made. Native TG/TD, assignment, COM,
real R1 convergence and real-model speed are not measured.

Reproduction outside Visum (new empty benchmark folder):

    python tools/benchmark.py --phase create --count 10000 --work-dir BENCH_NEW
    python tools/benchmark_aggressive.py --work-dir BENCH_NEW

Machine results: docs/aggressive/AGGRESSIVE_BENCHMARK_10000.json.
