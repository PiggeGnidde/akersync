# ÅkerSync Value Regression v0c — multi-block

v0c replaces the single-block geometry assumption with a conservative nearby-block reconstruction.

## Principle

The transaction may contain several Jordbruksverket blocks. The ATL map point is treated as an anchor, not as proof that the containing block is the whole sale.

Block selection uses only:

1. ATL point location,
2. spatial proximity/connectivity between blocks,
3. sold arable hectares.

**No geometry score participates in block selection.** Rectangularity etc. are calculated only after the block set is locked.

## Reconstruction

Default parameters:

- search radius: 3000 m from ATL point
- maximum link gap between growing cluster and next block: 750 m
- maximum blocks: 15
- mandatory anchor: 2025 block containing ATL point

The algorithm grows from the anchor by the smallest polygon-to-cluster gap. It stops after reaching/exceeding sold hectares, at the gap cap, or at the block cap. Only prefixes of this proximity ordering are considered; arbitrary subset-sum combinations are deliberately forbidden to reduce accidental hectare-fitting against neighbouring farms.

Main geometry models use reconstructions within ±20% of sold arable area. ±10/20/30% sensitivity is exported.

This is a **proxy reconstruction**, not cadastral identification.

## Transaction geometry

Selected blocks remain separate. They are not unioned into one field for geometry scoring.

For block i with area A_i and rectangularity R_i:

### Area-weighted mean rectangularity

`R_mean = sum(A_i R_i) / sum(A_i)`

### BAD20 rectangularity

Sort blocks from lowest to highest rectangularity and compute area-weighted rectangularity over the worst 20% of reconstructed hectares. If the 20% boundary falls inside a block, only the required fraction of that block area is used.

Interpretation: a 1 ha amoeba next to a 46 ha good rectangle hurts only slightly, while a large bad field dominates the lower tail.

### Bad-area share

Share of reconstructed hectares in blocks with rectangularity < 0.60.

### Effective block count

With area shares `s_i=A_i/sum(A_i)`:

`N_eff = 1 / sum(s_i^2)`

A tiny extra field barely changes N_eff; several similarly sized fields increase it strongly.

### Boundary burden

`sum(perimeter_i) / sum(area_i)` in metres per hectare.

### Largest-block share

Largest selected block as percent of reconstructed area.

## Regression evaluation

Baseline remains locked:

`log(kr / sold arable ha) ~ year + log(area) + latitude + longitude`

Each geometry metric is tested one at a time. Primary decision metric is change in exact leave-one-out R² against the baseline on the same complete-case rows.

## Outputs

`data/derived/value_regression_v0c/`

- `report.txt`
- `model_comparison.csv`
- `point_features.csv`
- `multiblock_reconstruction.csv`
- `multiblock_members.csv`
- `multiblock_geometry_sensitivity.csv`
- baseline coefficient / LOO files
