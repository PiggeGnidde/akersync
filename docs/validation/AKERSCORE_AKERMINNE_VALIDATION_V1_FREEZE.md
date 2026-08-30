# ÅkerScore × ÅkerMinne validation v1.0 — freeze

Freeze tag: `akerscore-akerminne-validation-v1.0`

## Status

**PASS — locally reproduced and verified 2026-08-30.**

The frozen validation implementation reproduced the expected results from the
exact hash-locked input export.

Observed verification inventory:

- Context rows: **128,636**
- ÅkerMinne field-years: **1,414,996**
- ÅkerScore rows: **128,636**
- Strict validation cohort: **45,275 fields**
- Local class × SKO × municipality quintile cohort: **44,459 fields**
- Local comparison groups: **196**
- Q5 − Q1 cereal-share difference: **+15.83 percentage points**
- Cluster-bootstrap 95% interval: **+13.98 to +17.88 percentage points**
- Block × historic-class comparison groups: **5,770**
- Fields in block fixed-effects analysis: **14,466**
- Block/class high-vs-low pairs with ÅkerScore difference >=20: **891**
- Input verification: **PASS**
- Result verification: **PASS**

## Scientific question

Does ÅkerScore provide field-quality information beyond the historic general
agricultural class?

## External signal

ÅkerMinne records actual crop use on the land constituting each present-day
2025 field for 2015–2025. Crop allocation is treated as an indirect
revealed-preference signal under the hypothesis that rational farmers, subject
to farm-system constraints, tend to allocate higher-value/intensive crop use
toward land they perceive as more productive.

## Interpretation guardrail

This is **external behavioural validation**, not direct yield validation and
not a causal estimate.

The behavioural interpretation may still be affected by livestock systems,
organic rotations, tenancy, distance, drainage, field geometry, farm strategy
and other management constraints.

## Frozen primary analysis

Implementation:

`analysis/akerscore_akerminne_validation_v1/run_validation.py`

Crop endpoint definitions:

`analysis/akerscore_akerminne_validation_v1/crop_groups.py`

Expected reproducibility targets:

`analysis/akerscore_akerminne_validation_v1/expected_results.json`

Exact input hashes:

`analysis/akerscore_akerminne_validation_v1/manifests/input_manifest.json`

One-command verifier:

`analysis/akerscore_akerminne_validation_v1/VERIFY_RESULTS.bat`

## Frozen design

Primary strict cohort:

- historic agricultural class 5–10;
- valid ÅkerScore Soil P50;
- historic class unique coverage >=95%;
- dominant historic class share >=95%;
- no mixed historic class;
- at least 8 of 11 ÅkerMinne years with status `SINGLE_CROP`.

Local quintiles are formed within:

- dominant historic agricultural class;
- SKO;
- municipality.

Only groups with at least 25 strict-cohort fields enter the local-quintile
analysis.

A separate block fixed-effects analysis compares fields within the same
current agricultural block and historic class, controlling for log field area.

## Data lineage

Combined ÅkerMinne + historic class 1–10 + SKO context:

- tag: `akerpass-akerminne-context-v1.0`
- commit: `1ad5c77656bb93664d94254af298009a6620da4f`

ÅkerMinne baseline:

- tag: `akerminne-v1.0`

ÅkerScore field source:

- `akerscore_soil_v0c`

The validation does not alter or recalibrate ÅkerScore, ÅkerMinne,
historic agricultural class, SKO, ÅkerDrift or ÅkerVärde.

## Reproduction contract

The input CSV.GZ files are not committed to Git. Their SHA256 digests and row
counts are frozen in `input_manifest.json`.

From a compatible local checkout with the hash-matching validation input
package present, run:

```cmd
analysis\akerscore_akerminne_validation_v1\VERIFY_RESULTS.bat
```

A valid reproduction must end with both:

`RESULT VERIFICATION: PASS`

and:

`VERIFY_RESULTS: PASS`

Any input hash mismatch or core result mismatch is a failure of the frozen
reproduction contract.

## Freeze policy

The tag `akerscore-akerminne-validation-v1.0` is immutable.

Any change to the analysis cohort, crop endpoint definitions, grouping rules,
quintile construction, bootstrap, block fixed-effects specification, expected
results, input hashes or interpretation contract requires a new validation
version/tag.

The external Word report must cite this immutable validation tag/commit rather
than an unfrozen chat analysis.
