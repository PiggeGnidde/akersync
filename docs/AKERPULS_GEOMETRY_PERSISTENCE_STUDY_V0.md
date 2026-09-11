# ÅkerPuls geometry persistence study v0

Purpose: test whether geometry stability is concentrated in the same fields over time, and whether frozen ÅkerMinne history can provide a field-specific prior for preliminary 2026 geometry.

## Source contract

- Frozen ÅkerMinne v1, 2025 reference geometry.
- 128,636 current Skåne fields.
- Historical years 2015-2024.
- Strict same geometry = `direct_id` or `one_to_one_strict`, i.e. the frozen >=90% mutual geometry criterion.
- Practical same geometry additionally includes `one_to_one_relaxed`.
- Split/merge history is kept separate from ambiguous/unmatched history.
- No frozen ÅkerMinne file is modified.
- Zero Sentinel API calls and zero PU.

## Questions

1. What fraction of 2025 fields are strict/practical 1:1 with 2024?
2. Is stability concentrated in the same fields, rather than independent across years?
3. Does a field that was strict 1:1 in many of 2015-2023 have a higher probability of also being strict in 2024 relative to 2025?
4. Does earlier split/merge history increase the probability of a 2024-to-2025 split/merge relation?

## Independence benchmark

The study does **not** assume a common annual survival probability. It takes the observed strict-same marginal rate separately for each year 2015-2024 and forms the corresponding Poisson-binomial distribution under independent years. The observed distribution of each field's 0-10 strict years is compared against this benchmark.

Useful diagnostics include:

- observed versus independent-expected share with all 10 years strict;
- observed versus independent-expected share with 9-10 years strict;
- observed versus independent-expected share with <=5 years strict;
- variance overdispersion of the per-field strict-year count;
- pairwise phi/Jaccard association of strict identity across years.

If stable and volatile fields are persistent latent types, the actual distribution should have more mass at the extremes and positive across-year association relative to the independent benchmark.

## Latest-year descriptive calibration

2024 is used as the most relevant one-year geometry event relative to the 2025 reference. The study reports `P(strict 2024 | strict-count 2015-2023)` and the analogous relationship with the recent strict streak. It also reports split/merge 2024 rates by prior split/merge count.

This is a **descriptive calibration**, not a causal out-of-time validation, because all historical identity labels are defined against the frozen 2025 reference geometry. It is appropriate for deciding whether a field-specific history prior is promising; it is not yet a frozen 2026 probability model.

## Outputs

Written under `C:\AkerSyncRepo\work\akerpuls_geometry_persistence_study_v0`:

- `annual_identity_summary.csv`
- `field_geometry_persistence.parquet` and `.csv`
- `strict_count_observed_vs_independent.csv`
- `latest_year_calibration_by_prior_strict_count.csv`
- `latest_year_calibration_by_prior_recent_streak.csv`
- `latest_year_calibration_by_prior_splitmerge_count.csv`
- `strict_same_year_pair_association.csv`
- `adjacent_year_strict_persistence.csv`
- `municipality_2024_2025_geometry_baseline.csv`
- `summary.json`

No prior is frozen by this study. If the concentration/calibration signal is strong, a later version can define and independently validate an empirical field-level prior before combining it with Sentinel likelihood evidence.
