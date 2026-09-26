# ÅkerVatten MVP v0a · STOPPUNKT A1b coverage/schema audit

A1b is a small diagnostic checkpoint after A1.

## Questions

1. Can the old 70,399-field exploratory subset be reconstructed exactly from the full 128,636-field soil/hydrology inputs?
2. How many fields truly lack the core clay/sand/TWI inputs?
3. How many fields merely failed the old conservative robustness filter?
4. Which terrain/hydrology columns actually exist in ÅkerPrestation field_static_context?

## Diagnostic statuses

A1b reports:

- DATA_MISSING
- AVAILABLE_BUT_NOT_OLD_ROBUST
- OLD_ROBUST

These are diagnostic labels only.

They are not a new ÅkerVatten product-quality contract.

## Old exploratory filter

Reconstructed from the old code:

- area >= 1 ha
- clay coverage >= 90%
- sand coverage >= 90%
- clay pixels >= 10
- sand pixels >= 10
- TWI cells >= 25
- clay_mean, sand_mean and twi_mean finite

If this reconstructs exactly the keys in water_prospect_features_skiften.csv, the 70,399 subset is explained by filtering rather than missing source layers.

## Static context

A1b searches all columns dynamically for:

- slope
- relief
- elevation
- TPI
- local low
- TWI
- hydrology / flow
- wet/dry
- terrain/topography

This avoids assuming old column names.

## Outputs

    work\akervatten_mvp_v0a\a1b_coverage_schema\

including:

- data_status_counts.csv
- old_robust_exclusion_reasons.csv
- raw_core_coverage.csv
- static_context_pattern_matches.csv
- static_context_all_columns.csv
- a1b_field_data_status.parquet
- a1b_summary.json

No SGU/SMHI download and no MarkTorka/MarkVäta score is produced.
