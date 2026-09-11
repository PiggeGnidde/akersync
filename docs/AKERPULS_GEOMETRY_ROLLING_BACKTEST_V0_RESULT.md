# ÅkerPuls Geometry Rolling Backtest v0 — result

Run date: 2026-09-11

Status: **PASS**

This study is a true adjacent-year rolling geometry backtest. For every transition 2015→2016 through 2024→2025, annual field geometries are matched directly with the frozen ÅkerMinne geometry matcher. Historical features for a source-year field use only predecessor transitions available up to that year. No future geometry is used in the features.

## Annual forward transition rates

| Transition | N source fields | strict same | practical same | split/merge |
|---|---:|---:|---:|---:|
| 2015→2016 | 114,675 | 0.7940 | 0.8219 | 0.0895 |
| 2016→2017 | 120,073 | 0.7830 | 0.8146 | 0.0874 |
| 2017→2018 | 118,844 | 0.7638 | 0.8058 | 0.0967 |
| 2018→2019 | 118,288 | 0.7911 | 0.8181 | 0.0923 |
| 2019→2020 | 118,109 | 0.8504 | 0.8719 | 0.0750 |
| 2020→2021 | 122,291 | 0.8302 | 0.8572 | 0.0773 |
| 2021→2022 | 121,146 | 0.8603 | 0.8750 | 0.0679 |
| 2022→2023 | 121,687 | 0.8300 | 0.8547 | 0.0855 |
| 2023→2024 | 120,872 | 0.8607 | 0.8778 | 0.0749 |
| 2024→2025 | 121,795 | 0.8491 | 0.8778 | 0.0914 |

Weighted across all ten forward transitions (1,197,780 source-field transitions): strict same ≈0.8216, practical same ≈0.8478, split/merge ≈0.0837.

Important denominator/direction note: the earlier 2025-reference persistence study reported 2024→2025 as strict 0.8039 and practical 0.8312 because it asked, for each of the 128,636 **2025 fields**, what its 2024 predecessor relationship was. The true rolling result above asks, for each of the 121,795 **2024 source fields**, what happens forward into 2025. Split/merge, unmatched/new fields, and changing field counts make those directional rates legitimately different. For the 2026 forecasting problem, the forward formulation is the relevant one.

## Persistence signal

- `P(next strict | previous strict) = 0.8767`, N=880,639.
- `P(next strict | previous non-strict) = 0.5972`, N=202,466.
- Odds ratio = **4.796**.
- With at least five prior transitions and all of them strict: `P(next strict)=0.9396`, N=235,103.
- With at least five prior transitions and historical strict fraction ≤0.60: `P(next strict)=0.6258`, N=82,234.

This confirms that field-specific geometry persistence is strongly predictive out of time. A common one-year unchanged prior is materially inferior to a field-specific history prior.

## Split/merge persistence

- `P(next split/merge | previous split/merge) = 0.3499`, N=90,414.
- `P(next split/merge | previous not split/merge) = 0.0588`, N=992,691.
- Odds ratio = **8.608**.
- With at least five prior transitions and any prior split/merge: `P(next split/merge)=0.2009`, N=160,565.
- With at least five prior transitions and no prior split/merge: `P(next split/merge)=0.0285`, N=369,070.

Thus historical structural volatility is especially informative for the 2026 split/merge prior.

## Rolling probability quality

History-category predictions were fitted only on earlier source years and evaluated on the next source year.

- Strict-same Brier: baseline `0.131682`, history `0.115375`, relative improvement **12.38%**.
- Split/merge Brier: baseline `0.072599`, history `0.064305`, relative improvement **11.42%**.

This is genuine rolling out-of-time improvement, not merely a same-sample association.

## Prototype 2026 field-specific prior

Not product-frozen. The empirical rolling calibration gives the following distribution across the 128,636 2025 fields:

- `P(strict same 2026)` P10/P50/P90 = **0.5267 / 0.8489 / 0.9395**.
- `P(split/merge 2026)` P10/P50/P90 = **0.0193 / 0.0776 / 0.3238**.

The spread is large enough that a single global Sentinel threshold is poorly motivated. The intended architecture should be history prior + independent satellite likelihood/evidence, with geometry change remaining conservative.

## Guardrails and interpretation

- `FEATURES_USE_FUTURE_GEOMETRY=FALSE`
- `SOURCE_TRANSITIONS_ARE_TRUE_ADJACENT_YEAR_GEOMETRY=TRUE`
- `PRODUCT_PRIOR_FROZEN=FALSE`
- `SENTINEL_HUB_PU_USED=0`
- 330 transition caches were built (10 transitions × 33 municipalities); future reruns can reuse them.

The current empirical prior is a prototype and should not yet be frozen as the production rule. A useful next zero-PU test is to join the frozen 2026 prior to the already blind-labelled C3/C5D Sentinel split candidates without changing any threshold, to test whether history separates visually plausible from false candidate splits. A separate true leave-one-date-out Sentinel stability test remains outstanding before any automatic split product decision.
