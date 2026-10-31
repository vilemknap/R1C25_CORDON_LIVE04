# CP04 - isolated offline execution and compatibility

Implemented short, isolated 2025 run roots, exclusive owner-token locks, no automatic stale-lock takeover, refusal to adopt arbitrary existing roots/2022 directories, critical checkpoints with input/code/authority hashes and sealed output hashes. Long run names are deterministically compacted. Windows defaults to LOCALAPPDATA/R1C25; Linux defaults to OFFLINE_RESULTS. No wallclock stop is introduced.

verify-run is a read-only verifier for an offline checkpoint. Recovery is an explicit verified restart from immutable inputs. It is NOT a resumption of Visum, path search, FISTA internal iterations or a partially completed assignment. No claim of solver continuation is made.

Validation before checkpoint:
- own suite: 162 passed;
- 97 unchanged donor regression tests passed against the merged isolated tree;
- raw parent suite: 879 passed, 4 skipped, 1 expected legacy package-identity failure (the same two intentional core modules patched in V1);
- parent compatibility: 879 passed, 4 skipped, 1 explicitly deselected byte-identity test. The original identity gate stays unchanged and is separately tested to refuse the fork;
- authority re-audit: STATIC_PASS;
- original V1 vs V2 independent-process synthetic runs: 40 arrays exactly equal and complete numerical demo summaries identical.

These are offline/mock/synthetic results, not a live Windows/Visum test. Apply remains false. The 2022 state, configuration and data were not modified.
