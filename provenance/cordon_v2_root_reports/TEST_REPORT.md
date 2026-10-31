# V2 test report - actual executions 2026-10-22

| Suite | Result |
|---|---|
| Original cordon V1 baseline | 86 passed |
| Resume donor complete suite | 927 passed, 4 skipped |
| Fresh donor complete suite | 993 passed, 4 skipped |
| CP01 merged cordon | 90 passed |
| CP02 IO/finalizer | 110 passed |
| CP03 semantic/targeting | 139 passed |
| CP03 source-identity hardening first attempt | 140 passed, 1 failed (legacy error-code text compatibility) |
| CP03B fixed error-code compatibility | 141 passed |
| CP04 own session/end-to-end tests | 162 passed |
| Added unchanged donor tests on merged parent | 97 passed |
| Full raw merged parent | 879 passed, 4 skipped, 1 legacy package-identity failure |
| Parent compatibility, explicit identity deselection | 879 passed, 4 skipped, 1 deselected |
| CP05 full own suite including verifier | 170 passed |
| Authority workbook re-audit | STATIC_PASS |
| Independent original V1 vs V2 demos | 40 arrays exactly equal; numerical summaries equal |
| Large synthetic same-input comparison | identical solver objective/KKT; OFFLINE_SOLVER_PASS |

The first CP05 own-suite command was interrupted by a 30-second tool-call limit
before a result; it is not counted as PASS. The complete rerun returned rc=0.
The legacy parent identity test remains unchanged; it refuses exactly the two
intentional V1 core modifications. Its failure is reported, not hidden, and the
new cordon suite tests that refusal. No historical identity manifest was forged.

170 own tests include 84 additional tests relative to V1. The 97 donor tests
are part of the 879 compatibility total, not an additional independent count.
Fault injections include locks, ENOSPC, failed publication, corrupt readback,
nonfinite data, stale snapshots, wrong domain hashes, changed code/input,
concurrent roots, symlinks, immutable C17/frozen scope and CAL/VALID isolation.
Original two opposing TG/TD infeasibility counterexamples remain in the suite.

Clean-unzip/re-run evidence and remote readback are generated AFTER final packaging
and delivered as a separate final verification receipt. No live Visum or native
Windows execution is claimed. All production APPLY gates remain closed.
