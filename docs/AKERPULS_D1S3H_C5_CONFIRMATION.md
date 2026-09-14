# ÅkerPuls D1-S3h — C5 geographic backend confirmation

## Why this stage exists

D1-S3f on the independent C7 1000-field holdout passed 12 of 13 frozen checks. The only failed check was the global maximum fusion-score difference:

- frozen maximum: 0.030000000
- observed maximum: 0.030881017

D1-S3g showed that the maximum occurred on one field below both P90 and P95 in both backends. The entire difference came from TRUE-LOO empirical-CDF rank quantization:

- history prior CDF difference: 0
- separation CDF difference: 0
- TRUE-LOO CDF difference: 34/367
- equal-weight fusion difference: 34 / (3*367) = 0.030881017...

C7 P90 and P95 sets were exactly identical between Process and direct S3. The frozen D1-S3f result nevertheless remains REVIEW; its 0.03 global-max criterion is not waived or changed retroactively.

## New confirmation contract

D1-S3h uses the previously created C5 1000-field geography. C5 is geographically separate from C7, but it was part of the frozen fusion development/reference population. Therefore D1-S3h is a backend-equivalence confirmation, not a new test of model generalization.

The D1-S3h acceptance contract is committed before any C5 direct-S3 end-to-end result is observed.

It keeps the previous structural checks:

- field-discovery exact agreement >= 0.995
- uncertain-flag agreement >= 0.995
- baseline candidate Jaccard >= 0.97
- locked candidate symmetric difference <= 2
- separation-ratio abs-diff P95 <= 0.02 and max <= 0.10
- TRUE-LOO min-Dice abs-diff P95 <= 0.02 and max <= 0.10
- fusion-score abs-diff P95 <= 0.01
- P90 symmetric difference <= 2
- P95 symmetric difference <= 1
- no reference P95 candidate may fall below S3 P90

The post-C7 refinement is prospective and outcome-relevant:

- the global fusion-score maximum across low-tier candidates is diagnostic only;
- the maximum fusion-score difference on the union of P90-or-higher candidates must be <= 0.03;
- every P90-or-higher candidate must be present in both backend baseline-candidate sets.

This preserves sensitivity where the QA/ranking product actually changes while preventing a single low-tier empirical-rank jump from dominating the backend decision.

## Reference integrity

D1-S3h never modifies the original C5B Process rasters. It stages links/copies into a compatibility directory and runs the already frozen C7C B2 -> TRUE-LOO -> history-prior -> empirical-CDF fusion implementation unchanged.

Before S3 comparison, the staged Process run must reproduce the legacy C5C discovery exactly:

- 1000 fields
- 141 baseline split candidates
- 21 locked candidates
- 4 uncertain
- exact field-by-field discovery and locked-rule agreement with the original C5C output

If this adapter check fails, D1-S3h stops.

## Direct-S3 semantics

The S3 side remains the D1-S3e-validated backend:

- all STAC acquisitions for the frozen date/grid
- PARENT scene order
- SCL_NONZERO coverage
- SCALE_OFFSET reflectance
- NEAREST resampling
- frozen pair rule: clear first, then lower CLD
- a frozen date with zero intersecting STAC scenes becomes an all-zero FLOAT32 daily source with dataMask=0

No Sentinel Hub Process API calls are made.

## Interpretation

A D1-S3h PASS authorizes only a separately guarded full-Skåne direct-S3 acquisition plan. It does not rewrite the historical D1-S3f C7 result, does not refit fusion, does not change split/merge rules, and does not automatically replace 2025 geometry.
