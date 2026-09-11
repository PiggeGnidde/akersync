# ÅkerPuls 2026 — C6 TRUE leave-one-date-out segmentation diagnostic v0

## Status before outcomes

This document and `config/akerpuls_true_loo_diagnostic_v0.json` freeze the diagnostic contract **before any TRUE-LOO outcomes are inspected**.

The purpose is to test whether the proposed split geometry itself is reproducible when a complete Sentinel-2 snapshot is omitted and the segmentation is re-fit from scratch. This is deliberately stronger than the historical `loo_all4` flag, which only re-used the all-date segmentation and checked remaining per-date separation support.

This is a **development diagnostic**, not a product-rule freeze. C/C3 and C5/C5D have already influenced model development, so any useful TRUE-LOO rule found here must later be validated on a new independent geography before automatic geometry mutation can be justified.

## Scope

Run on every B2 `SPLIT_CANDIDATE` in the existing C and C5 1000-field pilots. No new Sentinel downloads or API calls are permitted.

The previously frozen 32 blind-review cases (20 C3 + 12 C5D) are joined after TRUE-LOO metrics are computed so the diagnostic can be compared with visual plausibility without relabelling.

## TRUE-LOO definition

For each candidate field:

1. Re-fit the deterministic B2 k=2 segmentation with all four snapshots (April, May, June, July). This is the reference segmentation.
2. Re-fit segmentation four more times, omitting one complete snapshot each time.
3. For each three-date refit, feature scaling is recomputed from the pilot pixels valid in the three retained snapshots. Only retained-date feature dimensions are used.
4. Geometry comparison is made on the reference pixels valid in all four dates. These pixels are necessarily a subset of every three-date validity intersection, so the comparison domain is common and deterministic.
5. Binary labels are aligned by the permutation that maximizes mean child Dice.

## Predeclared diagnostic stability criterion

A candidate receives the separate flag `TRUE_LOO_STABLE` only if all of the following hold:

- all four three-date re-fits return two clusters;
- the common reference comparison domain has at least 24 pixels;
- each child occupies at least 20% of the comparison domain in every omission refit;
- **each matched child Dice is at least 0.75 for every omitted date**;
- the mean matched-child Dice across all eight child comparisons is at least 0.80.

The 20% child-fraction and 24-pixel requirements reuse B2 concepts rather than inventing morphology-specific tuning. The Dice thresholds are frozen here for this diagnostic before outcomes are observed.

`TRUE_LOO_STABLE` is not a replacement for `SPLIT_CANDIDATE`, does not redefine historical `loo_all4`, and is not yet a production gate.

## Outputs to inspect

The run will report:

- number/rate of TRUE_LOO_STABLE candidates in C and C5;
- per-omitted-date Dice distributions;
- all-32 blind-case rank separation using minimum and mean TRUE-LOO Dice;
- C3 locked-pass subset diagnostics;
- C5D HIGH_CONFIDENCE_CENSUS diagnostics;
- overlap between TRUE-LOO stability, history prior, Sentinel separation, and frozen visual labels.

No fusion weight or new split threshold will be fitted in this step.

## Guardrails

- Sentinel Hub PU: 0
- Sentinel API calls: 0
- threshold tuning: FALSE
- new product split rule: FALSE
- geometry commit: FALSE
- whole-Skåne execution: FALSE
