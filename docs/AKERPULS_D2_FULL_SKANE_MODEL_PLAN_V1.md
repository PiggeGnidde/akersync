# ÅkerPuls D2 full-Skåne model plan v1

## Purpose

This is a planning/freeze stage only. It is entered after D1-S3k has verified the completed direct-S3 full-Skåne raster product and field-validity coverage.

The stage makes no network calls and performs no B2 split discovery, TRUE-LOO, fusion, geometry mutation or crop classification.

## Frozen domain

- 128,636 frozen official 2025 fields
- 46 deterministic 20 km analysis cells
- six D0b sparse edge cells keep their already frozen symmetric expanded normalization windows
- minimum normalization population remains 200 intersecting 2025 fields
- exact D0b final execution contract SHA256 remains `d2c2a88d0978cffcd720dbb7a7982049fbc5c09ae41f3f7be2e959ad254aec19`
- exact resolved normalization-window SHA256 remains `0e3faedd3da470a261a7348d4d4129d52d938c10f34350ccea328b47581c6dc8`

## Frozen model

No scientific/model parameter changes are introduced.

D2 uses:

1. B2 baseline split discovery, unchanged.
2. Local robust median/MAD normalization in the exact D0b window for each owner cell.
3. TRUE leave-one-date-out only for D2A B2 split candidates; each omission recomputes the local robust scale from the three remaining snapshots.
4. Rolling history prior `prototype_p_splitmerge_2026`.
5. Frozen 3-signal empirical-midrank fusion with equal one-third weights.
6. Frozen development thresholds P90 = 0.781017 and P95 = 0.843688.
7. Frozen fusion artifact SHA256 `3ab2fcdd06284c15cbcffb20fba8da7de9f6b10ca102bd4026fc73a9ee0a7316`.

Official 2025 geometry remains the output default. No split, merge or geometry replacement is automatic.

## Two-stage execution

The full-Skåne model execution is deliberately separated.

### D2A

Run only baseline B2 split discovery and UNCERTAIN classification across all 46 cells. Each field belongs to exactly one owner cell. Scaling uses all valid field pixels in that cell's exact resolved normalization window, but only owner fields emit final D2A rows.

Fields with insufficient B2 valid pixels become `UNCERTAIN`; no relaxed threshold, rescue date or global normalization fallback is allowed.

D2A must stop after aggregation. Candidate count, uncertain count and spatial distribution are reviewed before any TRUE-LOO work is authorized.

### D2B

D2B is not authorized by this plan alone. If separately authorized after D2A review, it runs four TRUE-LOO omission refits only for D2A baseline split candidates, joins the frozen rolling history prior, applies the frozen empirical-CDF transforms and emits the three QA tiers.

This separation avoids paying the expensive TRUE-LOO cost before the full-Skåne baseline candidate census is known.

## D1-S3k coverage context

D1-S3k is a pre-model coverage QA, not a model result. The >=24 all-four-date-pixel screen is informative but does not replace exact B2 erosion/interior logic. D2A therefore decides the final `UNCERTAIN` population under the original B2 contract.

## Resumability

Execution is partitioned by analysis cell in lexicographic cell-ID order. Future D2A and D2B stages are required to write cell-level result files plus sidecars bound to the frozen D2 execution contract. Final aggregation is deterministic by `parent_field_id_2025`.

## Merge policy

D2 v1 is the frozen split-fusion QA/ranking path. It introduces no new merge automation. Merge evidence remains candidate-only under the existing formal policy and cannot change geometry automatically.
