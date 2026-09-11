# ÅkerPuls Split Fusion QA v1 — formal freeze

Freeze date: 2026-09-11

Status: **FROZEN FOR QA/RANKING — NOT AUTOMATIC GEOMETRY**

## Purpose

This freeze promotes the three-signal split fusion from an experimental validation construct to a stable **QA/ranking model** for preliminary 2026 field geometry. It does **not** authorize automatic split geometry or replacement of the official 2025 geometry.

The default geometry remains the official 2025 field geometry. Fusion v1 only prioritizes where a possible 2026 split deserves review.

## Frozen candidate population

Fusion v1 is applied only after the existing B2 baseline split discovery has produced `SPLIT_CANDIDATE` evidence.

The older precision-first locked morphology/edge gate is **not** required by this freeze. The previously tested scalar `separation_ratio >= 4` high-confidence rule is also **not** part of this freeze; that rule failed independent C5D validation.

## Frozen fusion

Development population: all baseline B2 split candidates from independent C and C5 pilots, `n=367`.

Signals:

1. `prototype_p_splitmerge_2026` — field-specific geometry-change prior from the true rolling ÅkerMinne backtest;
2. `separation_ratio` — Sentinel spectral/temporal split separation;
3. `true_loo_min_child_dice` — continuous TRUE leave-one-date-out segmentation reproducibility.

Each signal is transformed by empirical midrank CDF against the frozen 367-candidate development population. The transformed signals receive equal weight:

`fusion_score = (H_cdf + S_cdf + LOO_cdf) / 3`

Frozen source fusion artifact SHA256:

`3ab2fcdd06284c15cbcffb20fba8da7de9f6b10ca102bd4026fc73a9ee0a7316`

Frozen development tiers:

- P90: `0.781017`
- P95: `0.843688`

No C7 visual labels were used to fit the fusion, choose the weights, or choose these thresholds.

## Frozen QA interpretation

- `fusion_score >= 0.843688` → **HIGH_PRIORITY_SPLIT_CANDIDATE**
- `0.781017 <= fusion_score < 0.843688` → **SPLIT_CANDIDATE**
- `fusion_score < 0.781017` → **EVIDENCE_ONLY**; no promotion by fusion v1

These are QA/review classes, not statements that an administrative split is proven.

## Independent C7 blind validation

C7 was geographically separated from the earlier B, C and C5 pilots and selected before observing C7 outcomes. C7 contained 1000 fields. Frozen processing produced 131 baseline split candidates, 15 above the frozen development P90 threshold and 9 above the frozen development P95 threshold.

All 15 P90 cases were included in blind visual review, including all 9 P95 cases. Five just-below-P90 June-GE80 controls were added as a deliberately difficult challenge set. Human labels were frozen before the blind key was opened.

Blind key SHA256:

`d2553241211545cb8c0ffdb110e3f063680024af3b17eef818e6fb4cf9a14879`

### P95 census, n=9

- `TY`: 2/9 = 22.2%
- `TY + M/TY`: 6/9 = 66.7%
- `TY + M/TY + M`: 9/9 = 100.0%
- `TV`: 0/9
- `F`: 0/9

### P90 census, n=15

- `TY`: 4/15 = 26.7%
- `TY + M/TY`: 10/15 = 66.7%
- `TY + M/TY + M`: 13/15 = 86.7%
- `TV`: 2/15 = 13.3%
- `F`: 0/15

### Near-P90 controls, n=5

- `TY`: 1/5
- `TY + M/TY`: 3/5
- `TY + M/TY + M`: 4/5
- `F`: 1/5

The controls were intentionally the highest-scoring cases just below P90 and therefore must not be interpreted as a random negative sample or as an estimate of false-positive rate below P90.

## Scientific decision

The independent C7 holdout supports the three-signal architecture as a useful split-candidate ranking system. It does **not** support treating P90 or P95 as an automatically proven split boundary. The strict `TY` rate remains only 22.2% at P95 and 26.7% at P90; most positive cases are visually plausible rather than unequivocally proven.

Therefore:

- freeze the three-signal fusion architecture and its P90/P95 levels for QA/ranking;
- use P95 as **high-priority review**;
- use P90–P95 as **strong review candidate**;
- retain 2025 geometry by default;
- automatic split remains **NO**;
- automatic merge remains **NO**;
- merge remains candidate-only;
- do not retune downward from C7D, despite several plausible just-below-P90 controls.

All C7 P90/P95 cases happened to have June validity >=80%. This is useful validation context but is **not** promoted to a new tuned gate by this freeze.

## Rejected / diagnostic-only components

The following are deliberately not product gates in v1:

- old binary `TRUE_LOO_STABLE`; it was too permissive;
- `separation_ratio >= 4`; it failed independent C5D review;
- old locked morphology/edge candidate gate as a mandatory fusion prerequisite.

They remain available for provenance and diagnostics.

## Provenance

Primary supporting records:

- `docs/AKERPULS_PRELIM_FIELDS_2026_C7D_BLIND_REVEAL.md`
- `docs/AKERPULS_TRUE_LOO_DIAGNOSTIC_V0_RESULT.md`
- `docs/AKERPULS_GEOMETRY_PRIOR_SENTINEL_FUSION_V0_RESULT.md`
- `config/akerpuls_fusion_freeze_c7a.json`
- `config/akerpuls_split_fusion_qa_v1.json`

## Frozen policy

`AUTOMATIC_SPLIT=FALSE`

`AUTOMATIC_MERGE=FALSE`

`AUTOMATIC_GEOMETRY_REPLACEMENT=FALSE`

`PRODUCT_USE=QA_RANKING_AND_REVIEW_PRIORITY_ONLY`

Any future automatic geometry rule requires a separate explicit development and validation cycle; it must not be inferred from this QA freeze.
