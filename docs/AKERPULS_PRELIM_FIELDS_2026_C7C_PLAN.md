# ÅkerPuls preliminary 2026 geometry — C7C frozen fusion validation plan

## Purpose
C7C evaluates the already frozen three-signal fusion score on the fourth geographically independent C7 holdout. No C7 visual labels are available or used in this step.

## Frozen upstream inputs
- C7A pilot: 1,000 fields, geographically separated from B, C and C5.
- C7B rasters: identical preprocessing contract to B1/C1/C5B.
- Fusion freeze SHA256: `3ab2fcdd06284c15cbcffb20fba8da7de9f6b10ca102bd4026fc73a9ee0a7316`.
- Development fusion P90: `0.781017`.
- Development fusion P95: `0.843688`.
- Fusion uses equal-weight empirical-CDF transforms of:
  1. `prototype_p_splitmerge_2026`,
  2. `separation_ratio`,
  3. `true_loo_min_child_dice`.

The fusion reference distributions and weights are not refit on C7.

## C7B June availability
June has lower valid coverage in C7B (pilot-pixel valid fraction 0.6648; 625/1000 fields >=80% valid, 666/1000 >=50%). The frozen June snapshot is retained. C7C does not substitute another date or change the discovery/TRUE-LOO logic. Results are reported by June validity stratum (`GE80`, `50_80`, `LT50`) so availability can be separated from algorithmic behavior.

## C7C computation
1. Apply B2 split discovery exactly as before using the all-four-valid analysis domain.
2. Report the historical locked candidate gate unchanged from C2/C5; this is diagnostic only and is not the frozen fusion rule.
3. Refit TRUE leave-one-date-out segmentation for every C7 baseline `SPLIT_CANDIDATE` using the frozen C6 implementation.
4. Join the already-computed 2026 ÅkerMinne prototype prior.
5. Apply the frozen empirical-CDF reference distributions and equal weights from `FUSION_SCORE_FREEZE_BEFORE_C7.json`.
6. Report counts above the predeclared development P90/P95 fusion levels, overall and by June-validity stratum.

## Guards
- Sentinel Hub Process API calls: **0**.
- Threshold tuning on C7: **forbidden**.
- Fusion refit on C7: **forbidden**.
- C7 visual labels: **not used**.
- Automatic geometry changes: **off**.
- Product split rule freeze: **not yet**.

## Decision after C7C
C7C does not judge visual correctness. If the run is technically clean and produces a useful number of P90/P95 candidates, C7D will render a deterministic blind visual review set from the predeclared fusion tiers plus controls. The review design must be fixed before labels are seen. Only after reveal can the frozen fusion be judged as a possible automatic split ranking/gate.
