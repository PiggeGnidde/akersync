# ÅkerVatten MVP v0a · STOPPUNKT A1 local reuse inventory

A1 follows the handoff instruction to stop after source inventory before building the full pipeline.

## Purpose

Before acquiring SGU/SMHI data, audit what ÅkerSync already contains for:

- soil texture,
- field-level TWI,
- the old exploratory drainage/irrigation heuristics,
- the old four water-regime classification,
- ÅkerPrestation static context / terrain features.

The goal is reuse, not reimplementation.

## Important architecture update

ÅkerVatten v0a starts with five interpretable physical/hydrological components:

1. MarkTorka
2. MarkVäta
3. GrundvattenTillgång
4. GrundvattenTorka
5. YtvattenTorka

A1 only addresses the first two and local reusable context.

## Existing exploratory baseline

The old exploratory code used:

    drainage_challenge = 100 * sqrt(percentile(clay_mean) * percentile(twi_mean))

and

    irrigation_sensitivity = 100 * sqrt(percentile(sand_mean) * percentile(-twi_mean))

These are useful transparent baselines, but A1 does NOT adopt them as product definitions.

## Scientific guardrails

- TWI = topographic wetness propensity, not actual soil wetness.
- TWI does not capture drainage pipes, ditches or farmer management.
- Texture is modelled DSMS2025 clay/sand/silt, not measured plant-available water capacity.
- MarkVäta must therefore be described as structural/topographic wetness or drainage-challenge propensity, not observed waterlogging.
- No SGU/SMHI data are downloaded in A1.

## Inputs

Default local roots:

    C:\AkerSyncRepo
    C:\AkerSync-Prestation

Audited artifacts:

    data\derived\soil_features_skiften.csv
    data\derived\hydrology_features_skiften.csv
    data\derived\water_prospect_features_skiften.csv
    data\derived\water_regimes_skiften.csv
    data\derived\akerprestation_phase0\skane\field_static_context.parquet

## Outputs

Written only to the ÅkerVatten worktree:

    work\akervatten_mvp_v0a\a1_local_inventory\

Files:

- a1_manifest.json
- schema_inventory.csv
- numeric_summary.csv
- key_overlap.csv
- candidate_feature_presence.csv
- A1_LOCAL_REUSE_REPORT.md

The source artifacts are read-only and are not copied or changed.

## STOPPUNKT A1 decision

After Bengt runs A1 and returns the full output, inspect:

- exact row counts and key coverage,
- whether old water_prospect features cover all fields or a robust subset,
- whether the old arithmetic reconstructs exactly,
- what terrain fields are already available in field_static_context,
- which MarkTorka/MarkVäta inputs need further work.

Only then move to official SGU/SMHI source inventory/acquisition.
