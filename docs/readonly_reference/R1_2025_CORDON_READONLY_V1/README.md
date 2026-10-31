# R1 2025 cordon preparation: read-only audit V1

This is an independent evidence-only extension, based on the source contract of
`R1_15A2_V2_4_9_15_COM_BUSY_RETRY_SAFE_FINALIZER_20261019`.
It does not modify or import that production release, launch Visum, execute a
procedure, run assignment, optimize, write OD matrices or save a `.ver` file.

## Why this separate step exists

The original `r1_15a2_core.py` supports optional ordered cordon-pair incidence.
The optimized `r1_15a2_two_mode_v238.py` intentionally rejects
`enable_kordon_pairs=True` as not implemented. We must reuse its real saved path
geometry from the immutable `TWO_MODE_PATH_STORE.sqlite` rather than re-export
millions of records or use reconstructed shortest paths.

The new auditor reads actual saved ordered link IDs (`geometry.edge_ids`), the
separate volume by DSeg (`volumes`) and the exact directional edge dictionary
(`edges`). It outputs TWO historical, mutually non-equivalent candidate methods:

- `ALL_ORDERED_UNIQUE_PAIRS`: all distinct ordered station pairs crossed by a route;
- `EXACT_TWO_HITS`: count only routes crossing exactly two station points.

Neither has been approved as the meaning of a survey OD cell. Any route with a
repeated station is excluded from both candidates and reported as ambiguous.
This does not impose an end-to-end trip interpretation on the model.

## Static preflight (works without Visum or an actual path cache)

From this directory:

```shell
python r1_cordon_2025.py \
  --mapping data/R1_2026_KORDON_STATION_LINK_MAPPING_CONFIRMED_V1.csv \
  --targets data/R1_2026_KORDON_OD_RPDI_PRIMARY_ALL_NONVIRTUAL.csv \
  --c17-budget data/C17_STATION_BY_CATEGORY_RPDI.csv \
  --output output/static
```

Expected static facts for OA: 16 stations, 32 directional edges, 240
ordered non-diagonal observations, known-pair RPDI sum 76522, and C17 one
symmetric RPDI margin 48645. All outputs explicitly say `allowed_to_calibrate=false`.

## Diagnostic route run (do NOT point at a live, changing cache)

Use a FROZEN COPY of a complete 2025 two-mode SQLite path store generated from
exactly the corresponding saved Visum assignment and network. Select every
personal DSeg whose route volumes must be included; EXOG is diagnostic only.
Example command (adjust DSeg scope to the actual accepted 2025 inventory):

```shell
python r1_cordon_2025.py \
  --mapping data/R1_2026_KORDON_STATION_LINK_MAPPING_CONFIRMED_V1.csv \
  --targets data/R1_2026_KORDON_OD_RPDI_PRIMARY_ALL_NONVIRTUAL.csv \
  --c17-budget data/C17_STATION_BY_CATEGORY_RPDI.csv \
  --route-store C:/safe-copy/TWO_MODE_PATH_STORE.sqlite \
  --dseg NATIVE_CW --dseg NATIVE_CW_noT \
  --dseg NATIVE_CS --dseg NATIVE_CS_noT \
  --dseg NATIVE_CL --dseg NATIVE_CF \
  --dseg EXOG_EE_CW --dseg EXOG_EE_CW_noT \
  --dseg EXOG_EE_CS --dseg EXOG_EE_CS_noT \
  --dseg EXOG_EE_CL --dseg EXOG_EE_CF \
  --output output/routes
```

The accepted 2025 path store may have a different DSeg inventory. The tool
fails closed if a requested segment, directed mapping edge or sequence is
absent. No automatic remapping or route search is attempted. For a limited
sample add `--max-geometry-routes 1000` and interpret it as PARTIAL only.

The SQLite store is opened with `mode=ro` and `PRAGMA query_only=ON`.

## Known hard blockers before calibration

1. 2026 survey year versus 2025 model year has no approved reconciliation.
2. The meaning of each observed matrix pair versus route station hit sequence
   is not yet approved (including orientation: matrix row=VYSTUP, column=VSTUP).
3. The two historical pair-incidence conventions produce different results.
4. C17 is shared unknown-relationship mass. It must not become an independent
   tolerance amount for each known SDP pair or be added to an already expanded
   target. D2 pre-symmetry budgets carry direction; D3 RPDI is symmetric.
5. Current 15A2 mutable demand scope has only four NATIVE WORK/SERVICE DSegs;
   COMPLETE model counts need other NATIVE/EXOG classes in read-only evidence.
   Freight and bus category mappings are not assumed in V1.
6. Same-mode shared route geometry in 15A2 is marked PROVISIONAL. It needs an
   independent identity gate before authoritative segment-specific counting.
7. There is no actual 2025 accepted route SQLite store in this package.
8. The current V24915's previous regression results do not amount to a live
   2025 Visum calibration certification.

## Test and safety status

`python -m pytest -q tests` -> 8 passed on synthetic geometry plus real static
mapping/target input files. This is an offline gate only.

`data/C17_STATION_BY_CATEGORY_RPDI.csv` is derived from D2 pre-symmetric ALL
and D3 final ALL_RPDI results. Use `data/C17_CLASS_SUMMARY_RPDI.csv` and the
separate older-output audit report for provenance and interpretation.
