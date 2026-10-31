# R1 2025 cordon calibration - audit of earlier outputs (2026-10-19)

## Scope and verdict

Audited supplied historical packages, saved PrT export logs, 15A2 source code,
CP86 V24916 design, approved 16-station directed mapping and D1/D2/D3 survey
matrices. Source and result SHAs are in `SOURCE_AND_CHECKS.json`.

Verdict: REUSE THE 15A2 V24915 TWO-MODE PATH STORE; DO NOT REUSE THE OLD 15N
EXPORT LOOP OR REPLACE THE MODERN CONTROLLER. This package records evidence;
read-only prototype V1 is a separate deliverable. No 2025 production calibration
is claimed or attempted.

## Audit of older tools

| Component | Verified earlier output/code | Consequence |
|---|---|---|
| 15L v1.1 | FlowBundle two-link pair constraints and separate Dijkstra order diagnostics | The FlowBundle condition alone does NOT certify SDP_i before SDP_j on a saved route. Own shortest path is not an assignment route. No production incidence. |
| 15M v1 | Read-only COM investigation into actual PrT path lists | Useful interface discovery; no calibration evidence or exact volume/sequence baseline. |
| 15N v1 | 5,244,852 path parent rows from 14 DSegs; path link export succeeded only for LNV/NV (786,186 total raw lines) | PASS in old JSON is PARTIAL for the personal cordon task. Unbounded SaveToArray failed for all 12 personal path-link lists. |
| 17A v1 | Reads actual link order, but counts only routes with exactly two SDP crossings | Reliable restricted diagnostic, not a general cordon observation definition. No route scaling. |
| 16P | 16 station mapping to 32 directional keys | SDP1-14 had no directional RPDI at the time. SDP15/16 had duplicated opposite-direction totals with unproven direction status. |
| Early 15A2 core | Optional ordered pair operator from actual link sequences (`build_actual_path_incidence`) | Counts ALL unique ordered pairs on a multi-hit route and can exclude repeated SDP. This is a DIFFERENT diagnostic convention from 17A and has no C17 shared tolerance model. |
| 15A2 v24915 | Validated two-mode SQLite structure with ordered `geometry.edge_ids`, `edges`, `volumes`, `profile_hits` | Structural and performance foundation for 2025 SDP, without regenerating routes. `enable_kordon_pairs` explicitly unsupported in optimized `incidence()`. |
| CP86 V24916 | Design-only FlowBundle/skim targeting rebase | Useful parallel optimization plan for 2022; NOT a completed 2025 cordon calibration branch. |

The supplied V24915 CP79 log reports 783 passed, 4 skipped and 0 failures.
Its release evidence explicitly records `real_visum_tested=false` and
`production_ready=false`. An independent full test rerun in the present Linux
container was attempted, but timed out at approximately 36% without a
conclusive result. Do not represent that rerun as PASS or FAIL. The new V1
cordon read-only tests passed separately: 8 passed.

## Shared C17 uncertainty budget

Final D3 ALL_RPDI amounts from the 18 x 18 symmetric matrices:

| Class | Known physical 16x16 SDP volume | One C17 row/column margin | Special vjazd-vyjazd one margin |
|---|---:|---:|---:|
| OA | 76,522 | 48,645 | 1,807 |
| LNA | 9,530 | 4,486 | 205 |
| STNA | 1,298 | 737 | 20 |
| TNA | 9,492 | 2,698 | 150 |
| BUS | 470 | 238 | 17 |
| ALL | 97,312 | 56,804 | 2,199 |

The table shows ONE of two symmetric C17 margins. The opposite matrix margin
represents the other axis of the SAME expanded OD table. They must not be
interpreted as independent per-pair free-flow tolerances.

Earlier D1 -> D2 checks reported exact final empirical matrix parity, and
D2 SYM -> D3 M0 exact parity. D1 allocates 1,218 category-unknown detections,
including 848 into the physical 16x16 relations. C17 is a distinct and much
larger category of unknown second endpoints and does not consist exclusively
of those 1,218 category-unknown events. It is not a geographic 17th station.

D2 before symmetry retains different C17 row and column sums; for OA the
observed empirical counts were 39,323 station->C17 and 41,953 C17->station.
D3 is symmetric RPDI (OA margin 48,645). Directional physical route matching
must not silently treat this post-processed symmetry as directly observed.

## Scope mismatch in current 15A2

Current `R1_15A2_CONFIG_V2_4_9_15.json` exports only NATIVE_CW, CW_noT, CS,
CS_noT and has `include_exog_ee_paths=false`, `enable_kordon_pairs=false`.
Those settings are correct for the current 2022 CSD calibration but are NOT a
complete census of the 2025 personal OA model flow between SDP locations.
Read-only 2025 evidence must include all contributing personal NATIVE and
EXOG_EE segments. Optimization authority over frozen EXOG / LONG / FOREIGN
components must be a separate explicit decision, never accidental.

D3 physically observed OA, LNA, STNA, TNA, BUS. No assumed direct mapping of
STNA/TNA/BUS to model LNV/NV is permitted until demand-class definitions are
audited. Starting with OA evidence is a deliberate bounded first stage.

## Main unresolved observation-semantic question

Original 15A2 core: each route with hit sequence (s1,s2,s3) can contribute to
(s1,s2), (s1,s3) and (s2,s3) without automatically making those separate trips.
Older 17A: only exactly-two-hit routes contribute to preliminary pair counts.
Neither convention has yet been verified against the source ECV survey OD cell
construction. This has nothing to do with the separate SDP4 outage recovery
methodology. No production pair operator may be selected merely because it
improves a model-to-observation fit.

## Blockers before first 2025 calibration candidate

1. Freeze the actual 2025 `.ver`, network hash, OD demand identities and an
   accepted same-run path SQLite store; never import the older 2022 cache.
2. Approve 2026-to-2025 time-base/year interpretation for survey RPDI values.
3. Establish matrix row/column physical direction semantics versus Visum
   directed SDP link mapping.
4. Establish pair counting convention against the survey source observation
   definition, including multi-station and repeated crossing routes.
5. Build a shared, station-by-class budget for C17 uncertainty, with unused
   mass retained and without independent per-pair duplication.
6. Collect route evidence for all OA assignment segments and prove geometry
   sharing for the relevant segments; identify immutable components.
7. Compare modelled pair counts to the source RPDI matrix WITHOUT updating
   OD or network; report both historical candidate conventions separately.
8. Only then integrate an explicitly bounded cordon residual objective and
   accepted-parent TG/TD/supply cycle with rollback, CAL/VALID separation,
   profile and turn holdouts.

## Outcome

`R1_2025_CORDON_READONLY_V1` implements the safe static-gate and exact saved
ordered-route read-only diagnostics from 15A2 SQLite, with both historical
pair conventions and honest unapproved state. It does NOT implement a C17
optimizer or mutate any Visum objects. The actual 2025 route store has not
been supplied, so there is no live 2025 modelled-pair count evidence yet.
