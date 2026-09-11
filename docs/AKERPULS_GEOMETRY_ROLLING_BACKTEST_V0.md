# ÅkerPuls geometry rolling backtest v0

Purpose: test whether geometry history known at year `t` predicts the actual `t -> t+1` field-geometry transition.

## Why this is different from the first persistence study

The first persistence study used frozen ÅkerMinne identities expressed from the fixed 2025 reference geometry. It showed very strong field heterogeneity, but it was not a pure out-of-time forecast.

This study performs direct adjacent-year geometry matching:

- 2015 -> 2016
- 2016 -> 2017
- ...
- 2024 -> 2025

using the frozen ÅkerMinne matching thresholds (strict 0.90, relaxed 0.50, tie 0.02).

For a source field at year `t`, all predictor features are constructed only from geometry transitions at or before `t`. The outcome is the direct geometry transition from `t` to `t+1`. Future geometry is never used in the features.

## Field history features

History is propagated through the maximum-overlap predecessor. Each field gets, among other things:

- number of observed prior annual transitions;
- number/share of strict 1:1 transitions;
- current strict-1:1 streak;
- number of prior split/merge events;
- years since prior split/merge when defined;
- previous transition class.

At non-1:1 events, the maximum-overlap predecessor carries earlier history forward, while the split/merge/ambiguous/unmatched event itself is explicitly recorded. This is a deterministic primary-lineage approximation and is not claimed to resolve full many-to-many genealogy.

## Evaluation

The study reports descriptive transition persistence and a true rolling probability test. For later source years, the history-category probability model is calibrated using earlier source years only and compared with an earlier-years global-rate baseline using Brier score.

The category model uses fixed, untuned buckets for historical strict fraction, recent strict streak and whether split/merge has occurred previously. A fixed smoothing strength of 50 observations shrinks sparse categories toward the earlier-years global probability.

The same history calibration is applied to 2025 fields only as an exploratory 2026-prior preview. These probabilities are **not product-frozen**.

## Data and guardrails

Primary workspace: `C:\AkerSync-Minne`.

The runner reads the existing local ÅkerMinne configuration to locate frozen annual raw geometries and the 2025 field source. It does not download or rebuild anything.

- Sentinel Hub PU: 0
- network download: no
- frozen ÅkerMinne modification: no
- threshold tuning: no
- product prior freeze: no

Outputs are written under `C:\AkerSyncRepo\work\akerpuls_geometry_rolling_backtest_v0` and include reusable transition caches, annual transition rates, calibration tables, rolling prediction rows and an exploratory field-level 2026 prior preview.
