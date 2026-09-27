# ÅkerVatten MVP v0a · STOPPUNKT F FREEZE

**Status: PASS**

STOPPUNKT F is frozen after the transparent component-candidate run and the focused F2-F5 MarkVäta reviews.

F freezes five separate empirical 0-100 component scales. It does **not** create or freeze a combined ÅkerVatten index.

## Frozen component definitions

### MarkTorka

Primary raw features:

- `sand_mean` — higher = more drought-prone;
- `twi_mean` — lower = more drought-prone.

Transform:

- each input is converted to a field-weighted empirical percentile;
- MarkTorka = 50% sand percentile + 50% low-TWI percentile.

Strict primary completeness is required.

Full-population result:

- coverage: 124,380 / 128,636 = 96.691%;
- P10: 20.94;
- P50: 51.22;
- P90: 78.27.

### MarkVäta

MarkVäta uses two alternative physical evidence branches.

#### Mineral/topographic branch

- clay percentile — higher clay = more wetness-prone;
- TWI percentile — higher TWI = more wetness-prone.

The branch is joint evidence:

```
mineral_wetness = min(clay_percentile, twi_percentile)
```

High mineral wetness therefore requires both high clay and high TWI.

#### Organic-soil branch

Raw feature:

- `organic_ge20_share_pct`.

Because this raw feature is strongly zero-inflated, the frozen transform is a hurdle transform:

- missing -> missing;
- raw value 0 -> score 0;
- raw value >0 -> empirical percentile among positive observations only.

#### Final MarkVäta

```
MarkVäta = max(mineral_wetness, organic_hurdle_percentile)
```

Strict completeness is required for the frozen score: both the mineral branch and the organic branch must be known.

Full-population result:

- FULL: 124,380;
- MISSING_ORGANIC_BRANCH only: 0;
- MISSING_MINERAL_BRANCH only: 1,557;
- MISSING_BOTH: 2,699;
- strict coverage: 96.691%;
- P10: 6.02;
- P50: 34.96;
- P90: 74.10;
- unique score values: 67,155.

The organic branch adds no extra coverage loss among fields with a valid mineral branch.

MarkVäta is not defined as the inverse of MarkTorka.

Distinctness diagnostics:

- Spearman MarkTorka vs MarkVäta: -0.798;
- directional top-10 high overlap: 0.002;
- fraction with both scores >=80: 0.006%;
- std of MarkTorka + MarkVäta: 14.903;
- range of MarkTorka + MarkVäta: 150.168.

These diagnostics confirm that the frozen components are related but not mirror images.

### GrundvattenTillgång

Primary raw feature:

- `sgu_smallmag_value`.

Transform:

- field-weighted empirical percentile;
- higher raw value -> higher modelled groundwater availability.

Full-population result:

- coverage: 128,632 / 128,636 = 99.997%;
- P10: 9.99;
- P50: 49.99;
- P90: 89.99.

This is hydrological screening context, not individual-well yield.

### GrundvattenTorka

Primary raw features:

- `gw_small_situation_le10_max_run_days` — higher = more drought-prone;
- `gw_small_situation_summer_p10` — lower = more drought-prone.

Transform:

1. empirical percentiles are defined over the 786 unique SGU-HYPE units;
2. the two directional percentiles are averaged 50/50;
3. the resulting unit score is joined back to fields.

Full-population result:

- unit coverage: 786 / 786 = 100%;
- field coverage: 128,636 / 128,636 = 100%;
- field-weighted P10: 27.29;
- P50: 48.73;
- P90: 80.73.

The percentile scale is unit-weighted, not field-weighted.

### YtvattenTorka

Primary raw features:

- `sw_MLQ_MQ_ratio_total` — lower = more low-flow-prone;
- `sw_MLQ_total_lps_km2_upstream` — lower = more low-flow-prone.

Transform:

1. empirical percentiles are defined over the 502 unique S-HYPE units;
2. the two directional percentiles are averaged 50/50;
3. the resulting unit score is joined back to fields.

Full-population result:

- unit coverage: 502 / 502 = 100%;
- field coverage: 128,636 / 128,636 = 100%;
- field-weighted P10: 12.48;
- P50: 58.18;
- P90: 90.42.

The percentile scale is unit-weighted, not field-weighted.

## Cross-component diagnostics

Using the frozen F definitions:

- MarkTorka vs MarkVäta: -0.798
- MarkTorka vs GrundvattenTillgång: +0.285
- MarkVäta vs YtvattenTorka: +0.260
- MarkTorka vs YtvattenTorka: -0.259
- GrundvattenTillgång vs YtvattenTorka: -0.241
- MarkVäta vs GrundvattenTillgång: -0.233
- GrundvattenTillgång vs GrundvattenTorka: -0.187
- MarkVäta vs GrundvattenTorka: +0.089
- MarkTorka vs GrundvattenTorka: -0.066
- GrundvattenTorka vs YtvattenTorka: +0.058

No pair other than the deliberately related MarkTorka/MarkVäta pair shows strong rank dependence.

## Frozen missing-data policy

No component silently renormalizes weights when a required primary input is missing.

- MarkTorka: missing if sand or TWI is missing.
- MarkVäta: missing unless both mineral and organic branches are known.
- GrundvattenTillgång: missing if SGU small-magasin value is missing.
- GrundvattenTorka: missing if either frozen groundwater-history input is missing.
- YtvattenTorka: missing if either frozen surface-water-history input is missing.

Quality flags/lower-bound diagnostics may be retained separately, but they are not substitutes for the frozen strict score.

## Statistical semantics

All five scales are empirical relative 0-100 scales.

They are not:

- probabilities;
- physical volumes;
- legal withdrawal limits;
- individual-well yields;
- deterministic predictions of future drought or wetness.

Hydrological and physical screening is not legal water-withdrawal right.

## What F does not freeze

F does not define any combined ÅkerVatten index.

Any future combination of these five components requires a separate checkpoint and explicit product semantics.
