# CP00 - baseline audit

Source FIX3 verified unchanged (1,422 manifest entries). Local p.sqlite is a 30,425,088-byte incomplete FIX2 export, not the required 664,272,896-byte completed native snapshot. The final geometry and parity evidence files exist, but cannot substitute for missing SQLite and 12 matrix authorities. Exact Drive searches returned no final snapshot. Full-real gate remains WAITING_FOR_REAL_FINAL_CACHE.

Existing hooks: incidence.build_from_snapshot (cold oracle), aggregate_observations (cheap downstream), __main__.empirical_run, state.validate_runtime_options, RunSession, IOFIX atomic_output. The default cross-run cache prohibition stays intact; a separate explicit PERF01 policy will be validated. No parent solver changes.

Plan: CP01 contracts; CP02 implementation; CP03 negative and original regressions; CP04 benchmark and native handoff; CP05 clean-package verification.
