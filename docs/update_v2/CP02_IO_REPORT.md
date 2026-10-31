# CP02 - 2025 I/O integration

110 focused tests PASS. Critical common.write_json/write_csv and incidence,
solution, workbook-audit NPZ publications now go through cordon2025.io.
Reused unchanged donor _native_path, _short_temp_path, _transient,
replace_with_retry, safe_sha256_file. activate() is NEVER called.

Important refinement vs donor: no default=str, no numeric NaN replacement,
no CSV extrasaction=ignore. A numerical or schema error remains a hard error.
Atomic files are read back by SHA256. Failed parsing does not publish partial
STATION_HITS. Failed status or traceback publication cannot overwrite the
original exception in the command exit path.

Fault coverage: temporary and permanent sharing errors, no retry on ENOSPC,
serialization error preserving existing destination, publication corruption,
missing copy input, long paths, Win32 local/UNC conversion, NaN/object NPZ,
telemetry fail-open versus critical fail-closed, foreign parent import collision.
Real Windows/Visum execution remains NOT_TESTED. Linux long-path I/O and simulated
Windows conversion/failure contracts are tested only as indicated.
