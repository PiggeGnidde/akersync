# ÅkerVatten MVP v0a · STOPPUNKT G geographic/agronomic sanity validation

G validates the five component scales frozen at STOPPUNKT F. It does not fit, tune or modify them.

## Purpose

The questions are:

- Do all frozen scores remain inside 0–100 with expected coverage?
- Are groundwater/surface-water scores exactly constant inside their frozen hydrological unit?
- What do top/bottom 1%, 5% and 10% look like in their raw drivers?
- Do municipality/SKO-like groups show interpretable geographic enrichment when those columns are present?
- Can we produce a compact set of representative real field cases for manual review?
- Do apparently contradictory but physically possible combinations occur, and how often?
- Is the product explanation text aligned with the actual frozen semantics?

## Fixed display bands

For product copy G uses:

- 0–20: Mycket låg
- 20–40: Låg
- 40–60: Måttlig
- 60–80: Hög
- 80–100: Mycket hög

These are display bands on the relative component scale. They are not calibrated probability classes.

## Extreme profiling

For each component G profiles top/bottom:

- 1%
- 5%
- 10%

It reports medians/means of the frozen raw drivers.

It also writes 20 highest and 20 lowest real fields per component for manual inspection.

These extremes are sanity checks only. They are not training/calibration targets.

## Hydrological invariants

G requires:

- GrundvattenTorka to be constant within each SGU-HYPE `omrade_id`;
- exactly 786 scored SGU-HYPE units;
- YtvattenTorka to be constant within each S-HYPE `Subid`;
- exactly 502 scored S-HYPE units.

## Representative cases

G selects five real fields per component nearest:

- minimum;
- P10;
- P50;
- P90;
- maximum.

This creates 25 compact case rows with all available component scores, raw drivers and identifiers.

## Contrast counts

G reports counts for intentionally informative combinations such as:

- high MarkTorka + high GrundvattenTillgång;
- high MarkTorka + low GrundvattenTillgång;
- high MarkTorka + high MarkVäta;
- high GrundvattenTorka + high YtvattenTorka.

These are not automatically treated as anomalies.

## Product text

G writes a JSON file containing short explanation text for all five components and the fixed display bands.

## Outputs

    work/akervatten_mvp_v0a/g_sanity_validation/
      g_component_distributions.csv
      g_component_bands.csv
      g_hydrological_unit_invariants.csv
      g_extreme_driver_profiles.csv
      g_extreme_cases.csv
      g_group_enrichment_top_bottom10.csv
      g_representative_25_cases.csv
      g_contrast_counts.csv
      g_product_copy.json
      g_summary.json

Expected status is `PASS_WITH_REVIEW` because the final geographic/agronomic interpretation is intentionally reviewed by a human before G freeze.
