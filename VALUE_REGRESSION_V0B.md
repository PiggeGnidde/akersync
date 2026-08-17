# ÅkerSync Value Regression v0b

## Purpose

v0b is a QA-focused iteration of the first ATL land-value regression. It does not add a large set of new predictors. The main change is to make geometry defensible before interpreting rectangularity.

## Current sample convention

Default date window: **2020-07-01 and later**.

For `ATL_AkerSync_2026-08-17_436_poster_v03.csv`, the expected baseline-only sanity check is:

- raw ATL rows: 436
- unique transactions after deduplication: 425
- clean cases before date-window filter: 57
- clean v0b cases: 56
- baseline train R2: about 0.553182
- baseline adjusted R2: about 0.518138
- baseline LOO R2: about 0.449810
- baseline LOO median absolute percentage error: about 20.45%

The one otherwise-clean pre-window observation is from 2019 and is kept in `selection_audit.csv` but excluded from the v0b model sample.

## Geometry QA

v0a used the 2025 skifte containing the ATL point. That is not sufficient for interpreting field-shape effects because the sold arable area can contain several skiften or blocks.

v0b instead:

1. finds the 2025 Jordbruksverket block containing the ATL point;
2. compares that block's area with ATL sold `akermark_ha`;
3. records 10%, 20% and 30% area-match flags;
4. uses **block geometry** for the main regression only when block area is within **±20%** of sold arable area;
5. saves skifte-area matching separately as QA only.

A block-area match is evidence for a plausible single-block sale. It is **not** cadastral identification.

Outputs of special interest:

- `geometry_area_match.csv`
- `geometry_area_match_sensitivity.csv`
- `model_comparison.csv`
- `report.txt`

Primary decision metric remains delta LOO R2 relative to the baseline on the same rows.
