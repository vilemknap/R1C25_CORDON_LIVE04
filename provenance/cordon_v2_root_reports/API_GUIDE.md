# V2 API additions

Original incidence/solve/feasibility API retained. No default solver math changed.

- cordon2025.io: atomic_output, write_json, write_csv, write_npz, copy_verified,
  safe_failure_report, telemetry_json, native_path. No global donor activate().
- cordon2025.state: snapshot_semantics, observation_roster, diagnostic_reference_hash,
  readback_manager. Declared semantic hashes do not prove a live COM read.
- cordon2025.targeting: path_targeting_report, seal_distance_context, td_component_context.
  CAL-only search evidence; no replacement of actual ordered cordon incidence.
- cordon2025.session: RunSession, verify_run. Immutable inputs and offline checkpoint
  verification; no implicit cache discovery, no solver-iteration restoration.

Future live integration must separately authorize snapshot collection, current
DSeg scope, state identity, windows COM and candidate acceptance. Retained donor
live classes are library-only and must not be blindly activated with 2022 profiles.
