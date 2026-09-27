# ÅkerVatten MVP v0a · STOPPUNKT E candidate feature validation

STOPPUNKT E does not create a product score. It tests whether the raw candidate variables frozen through D are suitable, redundant, stable and physically interpretable before any component percentile is frozen.

## Candidate families

### MarkTorka

Required:

- sand_mean, directional high = more drought-prone;
- twi_mean, directional low = more drought-prone.

Optional if available:

- mean slope, directional high = more drought-prone.

No formula or weights are frozen.

### MarkVäta

Required:

- clay_mean, directional high = more wetness-prone;
- twi_mean, directional high = more wetness-prone.

Optional if available:

- mean slope, directional low = more wetness-prone.

MarkVäta is deliberately not defined as 100 - MarkTorka.

### GrundvattenTillgång

- SGU small-magasin screening value, directional high = more modelled groundwater availability.

This remains screening information, not individual well yield.

### GrundvattenTorka

Primary historical candidates:

- maximum run with small-magasin grundvattensituation <=10;
- small-magasin summer P10 of grundvattensituation;
- small-magasin summer P10 of fyllnadsgrad.

Additional diagnostics include <=20 run duration and low-fill run duration.

### YtvattenTorka

Primary historical candidates:

- total MLQ/MQ ratio;
- total specific MLQ in l/s/km².

Natural-flow counterparts are retained as diagnostics.

## Weighting distinction

For groundwater and surface-water historical variables E reports both:

- **unit-weighted** distributions: every hydrological unit gets one vote;
- **field-weighted** distributions: every field gets one vote.

The difference is explicit because C showed strong reuse: many fields can share the same hydrological unit.

Local soil/TWI variables are inherently field-level and therefore only field-weighted.

## Redundancy diagnostics

Within each family E computes:

- direction-oriented Spearman correlation;
- overlap among the directional top 10%.

A pair is flagged for review when either:

- absolute Spearman >= 0.90; or
- directional top-10% overlap >= 0.80.

These are review flags, not automatic feature deletion rules.

## Cross-family diagnostics

All candidate variables available on the 128,636-field table are compared with direction-oriented Spearman correlations.

This is used to spot likely double-counting, for example if a groundwater drought descriptor and a surface-water drought descriptor are effectively carrying the same geographic signal.

## Extremes

For every available candidate E writes the 10 highest and 10 lowest directional observations to:

    e_directional_extremes.csv

These are intended for map/manual sanity checks before any score is frozen.

## Outputs

    work/akervatten_mvp_v0a/e_feature_validation/
      e_candidate_inventory.csv
      e_candidate_distributions.csv
      e_history_field_vs_unit_quantile_shift.csv
      e_within_family_pair_diagnostics.csv
      e_cross_family_spearman.csv
      e_directional_extremes.csv
      e_summary.json

Expected E status is `PASS_WITH_REVIEW`: data/QA passed, but the human feature-choice review is intentionally still open.

No component percentile and no combined ÅkerVatten score is frozen in E.
