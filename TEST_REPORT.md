> FIX3: Tento dokument je historicky. Aktualni testy a limity jsou v docs/fix3/ a FINAL_STATUS.json. Vykonnost nove uplneho nativniho capture zatim nebyla zmerena.

# Test report - CORDON AGGRESSIVE V1, 2026-10-23

Actual completed runs in this development session:

| Suite | Passed | Failed | Skipped / excluded |
|---|---:|---:|---|
| Original cordon V2 baseline | 170 | 0 | 0 |
| Supplied aggressive PROFILE488 policy/runtime FIX1 tests | 34 | 0 | 0 |
| New cordon release, final source | 253 | 0 | 0 |
| Full unchanged parent test suite in cordon fork | 879 | 1 | 4 skipped |
| Compatibility run with explicit identity exclusion | 879 | 0 | 4 skipped, 1 deselected |

The one full-parent failure is `tests/test_v24915_release.py::test_v24915_config_runtime_bundle_and_lineage_are_hash_locked`. It requires byte-identical original
V24915 modules. Two parent files were already deliberately changed by the OLD
cordon V1/V2, and the parent identity test correctly rejects those changes.
This work did not change either parent file, any other parent source, or that test.
The original failing output is preserved in A03_parent_full.log/xml; it is NOT
reported as a passing full suite. Compatibility excludes exactly that test.

New coverage versus V2: 83 cases, including source stage/metadata sealing,
6/18/100 boundaries, illegal mutable scope, no live flags, CAL/VALID isolation,
shared C17 accounting and fair baseline, no-op detection, exact fixed volumes,
full-OD counterexamples with zero marginal residual, actuator-state binding,
backtracking under tight actuator bounds, actual parent signed-generation design,
P/A balance, zero-parameter preservation, TD seven-trial local API and native
IPF truth boundaries, CLI phases 1/7/19, run checkpoints, parent import collision.

Both infeasible synthetic OD cycle examples are rejected as full-OD actuator
infeasible even though their P/A residuals vanish. A feasible control passes.
A hard actuator limit selects scale .25 in phase 1. No actuator basis means
NOT_VERIFIED, not PASS. No live Visum or native Windows COM was tested.

A first benchmark harness attempt was rejected by OFFLINE_ONLY because the
minimal fixture config did not declare the offline contract. The harness was
fixed by explicitly combining the existing full offline config with the fixture
scope. The guard was not weakened. Both logs are retained.

Evidence: docs/aggressive/*.log, *.xml and FINAL_TEST_COUNTS.json.
Clean ZIP readback tests and checksums are recorded in the external final
verification receipt; no future result is assumed by this report.

Status: OFFLINE_TESTED; LIVE/APPLY DISABLED.
