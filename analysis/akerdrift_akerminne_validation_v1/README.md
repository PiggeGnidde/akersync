# ÅkerDrift × ÅkerMinne validation v1.0

This folder contains the reproducible field-use analysis of the released ÅkerDrift Hybrid RC1 score against ÅkerMinne 2015–2025.

## Scientific question

The directional hypothesis was stated before the result was inspected: raw ÅkerDrift may correlate with crop-use patterns, but most of that association is expected to be explained by field area. After flexible control for `log(area_ha)` and local historic-class × SKO × municipality context, the remaining ÅkerDrift association with crop choice and rotation should be small.

This is **not a formal preregistration or blind study**. The conversational directional hypothesis preceded the result, but the exact statistical implementation was frozen only after the exploratory result was observed.

## Required local input packages

The verifier expects:

`C:\AkerSyncRepo\work\akerdrift_akerminne_validation_inputs\akerdrift_akerminne_validation_inputs.zip`

`C:\AkerSyncRepo\work\akerscore_validation_csv_upload.zip`

Only the ÅkerDrift, field-context and ÅkerMinne members are used. Their SHA256 hashes are frozen in `manifests/input_manifest.json`.

## Run

From `C:\AkerSyncRepo`:

```cmd
analysis\akerdrift_akerminne_validation_v1\VERIFY_RESULTS.bat
```

Expected end state:

```text
INPUT VERIFICATION: PASS
RESULT VERIFICATION: PASS
VERIFY_RESULTS: PASS
```

Generated local outputs are written under:

`C:\AkerSyncRepo\work\akerdrift_akerminne_validation_v1\`

They are derived analysis artifacts and should not be committed.

## Frozen design

- released model: `akerdrift-fast-v2-hybrid-rc1`;
- ÅkerMinne years 2015–2025;
- raw screening cohort: valid ÅkerDrift and at least 8 `SINGLE_CROP` years;
- strict local cohort: historic class 5–10, >=95% unique class coverage, >=95% dominant-class share, non-mixed class, >=8 `SINGLE_CROP` years;
- local groups: historic class × SKO × municipality, minimum n=25;
- productive-use cohort for crop-choice/rotation endpoints: at least 4 years classified as broad-production or vall;
- area control: cubic B-spline of `log(area_ha)`, 8 columns, Patsy-compatible quantile knots;
- local fixed effects removed by within-group demeaning;
- uncertainty: cluster-robust covariance by historic class × SKO × municipality group;
- ÅkerDrift enters linearly after the flexible area control.

Primary interpretation: distinguish **which productive crop strategy is chosen** from **whether the field is repeatedly used for broad-production/vall at all**.
