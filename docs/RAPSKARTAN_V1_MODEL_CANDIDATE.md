# Rapskartan Skåne V1 – pre-blind model candidate

This phase is deliberately limited to model development on crop years 2018–2024.
It does not read row-level 2025 crop labels and does not create 2025 predictions.

## Development experiment

- 1,680 deterministic field-years: 60 observations per year in each of four strata.
- Strata: winter rapeseed, winter-crop controls, spring-crop controls and other-crop controls.
- Sampling is municipality-balanced and population weights restore year/group prevalence.
- Sentinel-2 L2A uses the STOPPUNKT B SCL mask, original field geometry and nine frozen cutoffs.
- ÅkerMinne-style prior features are reconstructed by spatial overlap with only the preceding four crop years.

## Model arms

1. `PRIOR_ONLY`
2. `SATELLITE_ONLY`
3. `PRIOR_PLUS_SATELLITE`

Candidates include the prior-frequency baseline, logistic regression and random forest.
Base models use whole target years as held-out folds. Platt and isotonic calibration are
cross-fitted across the same development years. Thresholds for 90% and 95% empirical
precision are selected exclusively from pre-2025 out-of-fold predictions.

## STOPPUNKT C

The independent verifier must pass before the package may be described as ready for the
2025 blind test. Even after PASS, no 2025 feature build, prediction or label join is allowed
without Bengt's explicit `GO 2025 BLIND TEST`.
