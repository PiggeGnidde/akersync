# Offline candidate: reference_pixels_v2

Status: **experimental diagnostic only, not approved for map production**.

Run from the clean `feature/rapskartan-skane-v1a` branch:

```cmd
RUN_RAPSKARTAN_CANDIDATE_PARITY.bat
```

No credentials, new catalog calls, downloads, model fitting, threshold changes,
full-map generation, deployment, tag or merge. The Python network audit guard
blocks requests. Existing STOP C/D and scene-archive paths are unchanged.
The full scene archive is read and checksummed, so the run can take time even
without network traffic. Processing reports progress per acquisition date.

Outputs are separate in `data/derived/rapskartan_v1/2025_candidate_parity_v2`.
The profile and candidate code hash bind the diagnostic identity/checkpoints;
an original-engine checkpoint cannot satisfy a candidate request. Restart with
the same command to reuse completed dates. Run only one copy at a time.
Upload the ZIP named by `RETURN THIS ZIP`. Completion is not a parity PASS:
inspect `diagnostic_summary.json` -> `local_engine_vs_locked`.

## Implemented candidate differences

1. Polygon rasterization: 256 horizontal x 8 vertical subpixels; accumulate
   coverage; alpha `(coverage*255+512)//2048`; include nonzero alpha. Holes and
   multipolygons remain part of the geometry. The constants and quarter bias
   were independently inspected in the installed OpenJDK 17.0.20 Marlin renderer
   (`MarlinConst`, `MarlinCache.buildAlphaMap`). They were not optimized against
   crop labels. Java2D produced exactly the four supplied nonempty service masks.
   The portable rasterio implementation reproduced those same masks without
   requiring Java on the user's computer. Stripes bound the high-resolution
   uint8 mask buffer to 16 MiB; extremely wide rows stop at a resource guard.
2. Interpolate DN in double precision, truncate down to integer DN, apply
   radiometric scale/offset and nonnegative harmonization. Reconstruct double
   quantized reflectance for the original index formulas, then cast samples to
   FLOAT32. Synthetic index calculations match the actual frozen JavaScript.
3. Compute percentiles with `higher`, not linear interpolation. Existing quality
   thresholds, SCL codes and frozen statistical feature definitions are retained.

The original engine remains the default. Only the offline diagnostic runner
opts in with `--engine-profile reference_pixels_v2`. The production runner does
not select this profile, and original-engine regression tests remain in place.

## Supplied-data evidence (2026-09-04)

Reference ZIP: `rapskartan_reference_pixels_20260904T103521087986Z.zip`.
All 79 manifest entries passed checksum verification. All ten reference requests
completed; no reference request was made during these offline experiments.
Native source: verified earlier five-case pixel export, 113 manifest entries.

| Case | Original valid pixels | Candidate valid pixels | Locked reference | Candidate statistics within 1e-7 |
|---|---:|---:|---:|---:|
| 01 | 32 | 86 | 86 | 51/51 |
| 02 | 510 | 534 | 534 | 51/51 |
| 03 | 5611 | 5872 | 5872 | 41/51 |
| 04 | 7 | 16 | 16 | 51/51 |
| 05 | 168 | 181 | 0 | Not comparable: reference has no scene |

Each comparison contains 17 optical/index variables x 3 percentiles, excluding
CLD. Cases 01/02/04 differ from locked CSV values by at most 5e-11 (CSV rounding).
Case 03 maximum statistic difference is about 0.0002. All four nonempty polygon
masks match pixel-for-pixel, not merely by aggregate count. For case 04 this is
564 data pixels before SCL filtering and 16 valid pixels afterward.

## Unresolved: do not hide these differences

- Some pixel interpolation differences concentrate in source-image boundary
  columns. A trial 256-source-pixel tile-clamping rule improved some pixels but
  broke others, so it was **rejected and not implemented**. No special-casing
  of particular fields, columns or scenes is present in the candidate.
- Case 05's reference TILE response has an empty scene list. The local archive
  contains nonzero spectral/SCL data near a nodata edge. Its STAC scene cloud
  coverage is below the request's 100% cloud ceiling; a simple cloud-limit
  explanation is unsupported. The exact service eligibility/footprint rule
  cannot be recovered from the available metadata alone. The candidate does
  not discard the scene to force agreement.
- These four nonempty cases are a diagnostic development set, not independent
  proof of global engine equivalence. The next 265-field replay is an expanded
  engineering check against the same locked model, not a new blind crop test.
- Even if the expanded gate passes, this runner produces no full map and makes
  no automatic production-approval decision. All frozen decision and probability
  tolerances remain unchanged.
