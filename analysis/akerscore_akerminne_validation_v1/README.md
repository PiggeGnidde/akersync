# ÅkerScore × ÅkerMinne behavioural validation v1.0

## Purpose

This package freezes the first external behavioural validation of ÅkerScore Soil
against ÅkerMinne 2015–2025.

The central question is:

> Does ÅkerScore contain information about field quality beyond the historic
> agricultural class?

The validation is deliberately not framed as direct yield validation. It tests
behavioural / revealed-preference evidence under the hypothesis that, over time,
farmers tend to allocate more production-intensive crop use to land they regard
as more productive, subject to farm-system constraints.

## Primary endpoints

1. Share of usable ÅkerMinne years used for cereal crops.
2. Share of usable ÅkerMinne years used for vall.

A secondary broad-production endpoint is also calculated. Its definition is
explicitly frozen in `crop_groups.py`.

## Frozen strict cohort

A current 2025 field is included when all conditions hold:

- dominant historic agricultural class 5–10;
- valid ÅkerScore Soil P50;
- historic class unique coverage >= 95%;
- dominant historic class share >= 95%;
- field is not marked mixed historic class;
- at least 8 of 11 years 2015–2025 have ÅkerMinne status `SINGLE_CROP`.

Crop-use shares use only the years with status `SINGLE_CROP`.

Expected strict cohort: **45,275 fields**.

## Local within-class test

Fields are grouped by:

- dominant historic agricultural class,
- SKO,
- municipality.

Only groups with at least 25 strict-cohort fields are used. Within each group,
ÅkerScore is divided into five quintiles. Ties are frozen by
`rank(method="first")` before `qcut(5)`.

Expected:

- 196 local groups;
- 44,459 fields.

The primary expected result is a monotonic increase in cereal share and decline
in vall share from Q1 to Q5.

## Block/class fixed-effects test

A stricter local analysis groups fields by current agricultural block and
historic class. Groups must have at least two fields and non-zero score
variation. Field-level outcomes and predictors are demeaned within block/class.
The regression is:

`outcome_dm = beta_score * score_dm + beta_area * log(area_ha)_dm`

No geographic between-group signal is used.

A complementary pair analysis selects, inside each block/class group with at
least a 20-point ÅkerScore range, the highest- and lowest-score field.

## Reproducibility

The input CSV.GZ files are not stored in Git. Their SHA256 hashes and row counts
are frozen in `manifests/input_manifest.json`.

Run from Windows CMD:

```cmd
cd /d C:\AkerSyncRepo
analysis\akerscore_akerminne_validation_v1\VERIFY_RESULTS.bat
```

A successful independent run ends with:

`RESULT VERIFICATION: PASS`

and:

`VERIFY_RESULTS: PASS`

Results are written to:

`C:\AkerSyncRepo\work\akerscore_akerminne_validation_v1\`

## Frozen code/data lineage

Combined ÅkerMinne + class 1–10 + SKO context:

- tag: `akerpass-akerminne-context-v1.0`
- commit: `1ad5c77656bb93664d94254af298009a6620da4f`

ÅkerScore field source:

- `akerscore_soil_v0c`

The validation does not alter or recalibrate ÅkerScore, ÅkerMinne, historic
class, SKO, ÅkerDrift or ÅkerVärde.

## Interpretation boundary

A PASS means that the exact frozen inputs reproduce the frozen analytical
results. It does not by itself establish causality or direct yield calibration.

The behavioural interpretation depends on a rational-land-use / revealed-
preference hypothesis and remains potentially confounded by livestock systems,
organic rotations, tenancy, field distance, drainage, farm strategy and other
factors.
