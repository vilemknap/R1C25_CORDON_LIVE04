# DIAGFAST CP00 - authoritative source audit

PERF01 archive and independent FIX3 oracle exactly match the requested SHA256.
Original source, parent, bootstrap, solver and PERF01 files are preserved.

RUN_CORDON_2025_CAPTURE.py -> cordon_visum_bootstrap.launch -> isolated_imports
-> verify_release -> visum_startup.run -> parent_hotfix_scope -> _run_scoped
-> RunSession -> preflight -> capture -> empirical_run -> final checkpoint.

Preflight: 12 matrix reads, 24 bounded list probes; four bulk network columns.
Capture: 12 parent scans, two representative full geometry scans, ten proof
stores populated from existing parent volumes plus full geometry COM scans.
Each legacy proof store creates edge_postings, profiles, markets and indexes
even though the final equality uses five fields. It is then deleted.
Final verification: 12 matrix reads, 12 independent path-parent/volume scans,
network/dseg/source-version check. No stage will be removed.

Proposal: separate FAST runtime with scoped wrappers; keep original functions
byte-identical. Original bounded_rows continues to own cursor, typeinfo,
retry, downshift and page-repeat safeguards. New streaming parser checks
all routes, including zero-flow and zero-link records, against representative
SQL bytes. Matching is by keys, not incidental provider order.

The native full capture timings are NOT_MEASURED. The old local p.sqlite
is incomplete (~30 MB), not the sealed 664272896-byte reference. Native
Windows/Visum is unavailable in this Linux environment. Live acceptance
will be supplied as an injected-instance-only read-only harness.
