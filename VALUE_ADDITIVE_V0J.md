# ÅkerSync Value Regression v0j — anchored additive property decomposition

## Purpose

v0j returns to actual purchase price in SEK and stops using K/T as the target.
Tax-assessed value is deliberately excluded from both target and predictors.

The transaction price is represented as a sum of positive components:

`P_total = P_arable + P_house + P_econ + P_pasture + P_forest + P_impediment + P_other`

The arable component is the target of interest. Pure or near-pure arable sales anchor that component naturally because their nuisance quantities are zero. Mixed sales then contribute information while house, economic-building, pasture and forest values are estimated as nuisance components.

## Arable price model

The arable rate is positive and multiplicative:

`P_arable = arable_ha * exp(linear predictor)`

Model ladder:

1. `BASE`: year + log(arable area) + latitude + longitude.
2. `BASE_BESK`: BASE + ATL arable beskaffenhet score + mixed flag.
3. `BASE_BESK_DRAIN`: previous model + categorical drainage.
4. `BASE_BESK_DRAIN_FERRARI`: same rows as the Ferrari baseline + frozen transaction FerrariScore.

Beskaffenhet and drainage only affect the arable component. They are not allowed to explain house/forest nuisance values.

### Beskaffenhet

Uses the v0h parsing of the ATL/fastighetstaxering field. It is an administrative production/cultivation-quality factor and is not treated as laboratory soil chemistry.

### Drainage

Primary reference level is `satisfactory_other`.

Separate coefficients are fitted for:

- `unsatisfactory`
- `legacy_system_tiled`
- `missing/other/mixed`

The old and new administrative drainage wordings are not silently treated as equivalent ground truth.

## Nuisance components

All component values are constrained positive by log-rate parameterization. Components are only fitted when enough non-zero observations exist in the current sample. House value can use year and geography when support is sufficient; other minor components use deliberately simpler parameterizations to reduce identifiability problems.

The model minimizes robust log-price residuals with SciPy `least_squares(..., loss="soft_l1")`.

## Samples

- `S70_NOFOREST`: at least 70% arable area and zero recorded forest. Primary decomposition sample.
- `S50_ALL`: at least 50% arable area; mixed properties allowed.
- `ALL_ARABLE`: all v0h-eligible sales with positive arable area.

A conservative `anchor_strict` flag marks sales with no recorded house, economic building, forest, pasture or impediment and at most 0.5 ha unclassified area remainder.

## Validation

The additive model is nonlinear, so v0j uses deterministic 10-fold spatial-group cross-validation rather than pretending the OLS exact-LOO formula applies. All sales in the same existing 10 km sale cell stay in one fold.

Reported metrics:

- train R² on log(total price)
- spatial-CV R² on log(total price)
- spatial-CV median absolute percentage error
- the same held-out diagnostics restricted to strict anchors
- same-row incremental deltas for beskaffenhet, drainage and FerrariScore

The strict-anchor metrics matter: a good total-property R² can partly arise because the model explains houses and property mix rather than because it values arable land better.

## Outputs

`data/derived/value_regression_v0j_additive/`

- `report.txt`
- `v0j_features.csv`
- `v0j_model_comparison.csv`
- `v0j_model_coefficients.csv`
- `v0j_incremental_tests.csv`
- `v0j_primary_predictions.csv`
- `v0j_component_summary.csv`

## Run

```bat
cd /d C:\AkerSyncRegression
git pull
RUN_VALUE_ADDITIVE_V0J.bat
```

v0j automatically prefers the v0i feature file. If it cannot find it, it falls back to the v0h expanded feature file or opens a CSV chooser.

## Guardrails

This is a statistical component-identification experiment, not cadastral appraisal truth. Building condition, rights, local buyer competition, tenancy, development expectations and other unobserved transaction-specific factors remain potential residual drivers. Drainage information is administratively noisy. FerrariScore is based on modeled DSMS texture rather than direct soil sampling.
