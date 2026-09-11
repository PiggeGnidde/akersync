# ÅkerPuls Geometry Prior + Sentinel Fusion v0 — pre-run plan

## Purpose

Test whether the independently derived 2026 geometry-history prior adds useful discrimination among already frozen C3 and C5D Sentinel split-review cases.

This is a zero-PU diagnostic. It does not alter Sentinel thresholds, define a new automatic split rule, freeze the geometry prior, or mutate any 2026 geometry.

## Inputs fixed before this analysis

1. Rolling adjacent-year geometry prior from `AKERPULS_GEOMETRY_ROLLING_BACKTEST_V0`.
   - 128,636 current 2025 fields.
   - `prototype_p_strict_same_2026`.
   - `prototype_p_splitmerge_2026`.
   - Prior was derived independently from 2015–2025 annual geometry transitions and not from C3/C5D visual labels.
2. C3 frozen blind labels, 20 cases, committed before reveal.
3. C5D frozen blind labels, 12 cases, committed before reveal.
4. Existing Sentinel `separation_ratio` from the blind keys.

## Predefined visual views

- Strict visual positive: `TYDLIG` only.
- Liberal visual positive: `TYDLIG + MÖJLIG`.
- Ordinal visual scale: `FALSK=0`, `TVEKSAM=1`, `MÖJLIG=2`, `TYDLIG=3`.

No relabelling is permitted after the prior is joined.

## Predefined analysis sets

- `ALL_32`: all C3 + C5D cases.
- `C3_ALL`: all 20 C3 cases.
- `C3_LOCKED_PASS`: the 10 C3 locked-pass representative cases.
- `C5D_ALL`: all 12 C5D cases.
- `C5D_HIGH_CONFIDENCE_CENSUS`: all six C5D high-confidence cases.

The within-rule subsets are especially important because they ask whether history distinguishes visually plausible from implausible candidates after the Sentinel selection rule has already acted.

## Scores compared

Primary history score:

`prototype_p_splitmerge_2026`

Secondary history score:

`1 - prototype_p_strict_same_2026`

Existing Sentinel score:

`separation_ratio`

No fitted combination weight is allowed in v0. In particular, this study will not fit a logistic regression, optimize a cutoff, or choose a posterior threshold from these 32 cases.

## Metrics

For each predefined analysis set and binary visual view:

- rank AUC (Mann–Whitney interpretation),
- positive and negative medians,
- median gap,
- two-sided Mann–Whitney p-value as a descriptive small-sample statistic.

Additionally, Spearman correlation is reported between each score and the four-level frozen visual ordinal label.

The p-values are diagnostic only; the challenge sets are selected and are not population-random samples.

## Interpretation guardrails

- Do not call the 32-case results population precision, recall, specificity, or accuracy.
- Do not tune a split/merge threshold from these cases.
- Do not product-freeze the prior from this analysis.
- A useful outcome is evidence that history has independent rank separation, especially inside `C3_LOCKED_PASS` and `C5D_HIGH_CONFIDENCE_CENSUS` where Sentinel selection is held approximately fixed.
- If history shows no useful separation, retain it as a population-level geometry-risk prior only and do not force it into the candidate classifier.
- True leave-one-date-out Sentinel re-segmentation remains a separate outstanding validation task before automatic geometry mutation.

## Technical guards

- Sentinel API calls: **FALSE**.
- Sentinel Hub PU: **0**.
- Threshold tuning: **FALSE**.
- New split rule: **FALSE**.
- Automatic geometry change: **FALSE**.
- Product prior freeze: **FALSE**.
