# CP01 - exact contract

Historical startup, bootstrap, collectors and PERF01 remain byte-identical.
New module diagfast_runtime installs scoped wrappers inside isolated_imports;
all functions/classes restore in finally, including failure paths.
LEGACY uses original capture. FAST uses original parent and representative
parsers; only ten same-mode proof stores are replaced. Parent data read once
per segment and final path/matrix/network readback stay unchanged.

Pages: reuse original bounded_rows, signature verifier, BoundedReadTarget and
retry owner. Explicit 256/512/1024; default 256. No autotune. Fallback only for
original recognized capacity errors, same first row. No geometry/data error
can become fallback PASS. Backend fallback is manual LEGACY in a NEW run;
automatic whole-backend fallback is intentionally disabled.

Streaming proof: dictionary by (orig,dest,path_index), seen set, one route's
uint32 bytes; reference blobs read from existing SQL per route. Full key
coverage; exact bytes/count/kind/hash; no scratch writes. Legal group reordering
is accepted. Parent parser guards are copied with pinned source hash and
independent differential tests. No sample-only proof. Input routes with zero
volume and zero link count remain included.

Telemetry accumulates counts/timing in RAM, no per-page event file. Exclusive
wall/CPU excludes instrumented nested spans; uninstrumented work remains in
the enclosing phase. Unknown native wire bytes reported NOT_MEASURED.
36 GetValues are preserved: preflight/capture/final are distinct epochs.
No reuse of old values after TG/TD/assignment/rollback.
