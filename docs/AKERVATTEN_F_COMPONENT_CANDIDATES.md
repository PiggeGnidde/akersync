# ÅkerVatten MVP v0a · STOPPUNKT F transparent candidate components

STOPPUNKT F creates five separate candidate 0–100 components from the raw-feature set frozen at E.

It does **not** create a combined ÅkerVatten index.

## Percentile definition

Each primary raw feature is transformed monotonically to an empirical 0–100 percentile.

- Average ranks are used for ties.
- High-risk/high-availability direction is inherited from the E freeze.
- The lowest oriented observation maps toward 0 and the highest toward 100.
- These are relative empirical scales, not probabilities.

## Weighting population

Local field-varying inputs:

- MarkTorka
- MarkVäta
- GrundvattenTillgång

use field-level empirical percentiles.

Hydrological history inputs:

- GrundvattenTorka
- YtvattenTorka

use empirical percentiles over the **unique hydrological units first**:

- 786 SGU-HYPE units for GrundvattenTorka;
- 502 S-HYPE units for YtvattenTorka.

Those unit-defined percentiles/scores are then joined back to the 128,636 fields.

This prevents a hydrological unit containing many fields from defining more of the percentile scale than a unit containing few fields.

## Candidate aggregation

F uses a deliberately transparent equal-weight baseline:

- MarkTorka = 50% sand percentile + 50% low-TWI percentile.
- MarkVäta = 50% clay percentile + 50% high-TWI percentile.
- GrundvattenTillgång = 100% SGU small-magasin percentile.
- GrundvattenTorka = 50% low-situation persistence percentile + 50% low summer-situation percentile.
- YtvattenTorka = 50% low MLQ/MQ percentile + 50% low specific-MLQ percentile.

Equal weighting is an F candidate assumption, not yet frozen product policy.

## Missing data

F uses strict primary completeness.

If any frozen primary input for a component is missing, that component candidate score is missing. The remaining inputs are not silently reweighted.

A per-component quality flag records:

- FULL
- MISSING_PRIMARY

This keeps component semantics comparable across fields.

## Validation

F reports:

- coverage and score distributions;
- number of unique score values;
- score-vs-input Spearman correlation;
- top-10% overlap with each input;
- all cross-component Spearman correlations;
- MarkTorka + MarkVäta sum variability to prove the final components are not exact inverses;
- high/low extreme fields for each component.

## Output

    work/akervatten_mvp_v0a/f_component_candidates/
      akervatten_f_candidate_components_skane.parquet
      f_groundwater_unit_candidate_scores.parquet
      f_surfacewater_unit_candidate_scores.parquet
      f_component_distributions.csv
      f_component_input_diagnostics.csv
      f_cross_component_spearman.csv
      f_component_extremes.csv
      f_summary.json

Expected status is PASS_WITH_REVIEW. No component is frozen until the diagnostic output is reviewed.
