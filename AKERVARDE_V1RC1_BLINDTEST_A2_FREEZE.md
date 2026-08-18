# ÅkerVärde v1.0-rc1 — blindtest A2 freeze: Holmbytorp 3:21

This holdout was identified after the primary 2018–2019 blind test, while checking the previously unused period 2020-01-01 through 2020-06-30. The purchase price, tax-assessed value and K/T were not used in candidate selection or prediction.

## Candidate

- Property: Holmbytorp 3:21
- Date: 2020-04-01
- Object type: Lantbruksenhet, obebyggd
- Total area: 17 ha
- Arable area: 17 ha
- Forest: 0 ha
- Pasture: 0 ha
- Forest impediment: 0 ha
- Coordinates: 55.75790069957856, 13.423070380744376

The transaction satisfies the same pure-arable logic as the primary blind sample: market transaction, >=5 ha arable, unbuilt, no forest, no pasture, no forest impediment and no residual other land.

## Frozen model and prediction

Model: ÅkerVärde v1.0-rc1, v0j `S70_NOFOREST / BASE`, unchanged from the primary blind backtest.

Frozen point prediction:

- SEK/ha: 317,115.87
- Total: SEK 5,390,969.82

Frozen empirical uncertainty calibration from the 33 strict-anchor held-out spatial-CV predictions:

- P10 multiplier: 0.825554318
- P50 multiplier: 1.072854059
- P90 multiplier: 1.488553689

Thus the frozen candidate interval is:

- P10: SEK 261,796.38/ha; SEK 4,450,538.41 total
- calibrated P50: SEK 340,219.05/ha
- P90: SEK 472,044.00/ha; SEK 8,024,748.02 total

## Integrity

Source CSV SHA256:
`d5ea31d3d2c47272673cf0d2902a508fb4dd5fd61fe301bfd8597202d9e80544`

Price-blind candidate CSV SHA256:
`4e9228360a6af9d3f1bffe1bb3a70eb7665bee85790b9979dcea8970145835cc`

The price-blind candidate/prediction file was committed before revealing the purchase price.

This A2 result must remain reported separately from the original 12-transaction primary blind sample. It may also be shown as an explicitly labelled 13-transaction combined historical holdout after its outcome is revealed.
