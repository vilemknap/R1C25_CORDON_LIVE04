# Synthetic bridge benchmark (not native Visum)

201 zones, 12 DSeg, 10,000 parents per DSeg, 120,000 volume records,
20,000 stored two-mode geometries and 480,000 geometry list rows checked
across every DSeg. Full proof enabled, no provisional sharing.

Preflight: 0.409 s.
Capture plus full same-mode proof: 6.597 s.
Two incidence variants plus independent matrix parity: 1.181 s.
Calls: 2868 bounded; 0 unbounded; 0 model writes.
Store: 6,418,432 bytes; peak process RSS 173.4 MiB.

The process includes the mock provider. This is not a prediction for the
millions of routes in R1 or a native COM speed claim. The first complete
geometry proof deliberately reads more than just the two representatives;
no cross-run geometry reuse is authorized by this result.
