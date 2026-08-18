# ÅkerVärde v1.0-rc1 — 2018/2019 blind-backtest freeze

Frozen before inspection/use of the purchase prices for the selected candidates.

## Primary blind sample

Selection is deterministic and price-blind, applied only to source rows 437 onward in
`ATL_AkerSync_2026-08-18_556_poster_v03.csv`.

Rules:
- sale year 2018 or 2019
- `valid_market_sale = 1`
- arable area >= 5 ha
- object type contains `obebyggd`
- forest = 0 ha
- pasture = 0 ha
- forest impediment = 0 ha
- small-house area = 0
- economic-building area = 0
- unexplained other land <= 0.5 ha
- usable latitude/longitude

Result: **12 primary blind-test transactions** (9 from 2019, 3 from 2018).

## Frozen model

ÅkerVärde v1.0-rc1 uses v0j `S70_NOFOREST / BASE`.

Arable SEK/ha rate:

`exp(13.098846306972883
 + 0.007982890108546714*(year-2024)
 + 0.005538958814058302*ln(arable_ha/20)
 - 1.020031932935096*(lat-55.5)
 - 0.3212824756343288*(lon-13.0))`

For these pure-arable blind candidates, predicted total value is simply arable hectares
multiplied by this rate.

## Frozen uncertainty calibration

Computed from the 33 strict-anchor held-out spatial-CV predictions of the frozen BASE model:

- observed/predicted P10 = 0.825554318
- observed/predicted P50 = 1.072854059
- observed/predicted P90 = 1.488553689

The candidate CSV contains the point prediction and these frozen P10/P50/P90-calibrated
SEK/ha values, but **does not contain actual purchase price, tax value or K/T**.

## Validation metrics to reveal after freeze

Primary:
- median absolute percentage error
- median observed/predicted ratio (bias)
- log-price R²
- fraction of observed prices inside frozen P10-P90 band

Small-n interpretation is descriptive; 12 transactions are an initial historical external
backtest, not a final validation sample.

## Integrity

Source CSV SHA256:
`d5ea31d3d2c47272673cf0d2902a508fb4dd5fd61fe301bfd8597202d9e80544`

Frozen candidate/prediction CSV SHA256:
`057445759efff9c41080eaab5527c31c0318dc49e56eb19864cfe24aaca4dca1`

The source file itself is intentionally not committed here.
