# ÅkerNorm V1 – model candidate at STOPPUNKT B

This phase-B implementation freezes the model candidate authorized by `GO MODELLFREEZE`.
It does not authorize or implement a full Skåne field run, web integration, deployment, or
Sentinel-2 work.

## Formula

For field `i`, crop `z`, and dominant SKO `k`:

```text
field_akernorm_t_ha = official_sko_norm_t_ha
                      + beta_t_ha_per_score
                      * (akerscore_value - sko_crop_reference_score)
```

The crop/SKO reference score is recomputed from the hash-locked ÅkerMinne 2015–2025
`SINGLE_CROP` field-year population. Each qualified field-year is weighted by
`current_area_m2`; repeated years for the same field remain repeated. A field-adjusted value
requires `dominant_sko_share >= 0.95`, a valid ÅkerScore, a published official 2026 norm, and
an approved crop/SKO reference.

The global analysis regression intercept is never used as a local base. The area-year
weighted adjustment is verified to be zero per crop/SKO.

## Frozen candidate coefficients

| Crop | Code | Mode | beta t/ha/score | +10 score |
|---|---:|---|---:|---:|
| Winter wheat | 4 | field adjusted | 0.025 | 0.25 t/ha |
| Spring barley | 2 | field adjusted | 0.040 | 0.40 t/ha |
| Oats | 3 | field adjusted, higher uncertainty | 0.024 | 0.24 t/ha |
| Winter rape | 20 | field adjusted, weak effect | 0.0050 | 0.05 t/ha |
| Table potato | 45 | official SKO only | none | none |
| Starch potato | 46 | official SKO only | none | none |

Climate coefficients are excluded. Potato is never score-adjusted. Score values are not
silently clamped; P05/P95 and observed min/max support statuses are retained for QA.

## Derived artifacts

The runners write ignored derived artifacts under `data/derived/akernorm_v1` by default:

- exact STOPPUNKT-A PxWeb query/raw/normalized source snapshot and source manifest;
- crop/SKO reference table, model contract, reproduction comparison, and conservation QA;
- bounded pilot field/crop rows, status coverage, formula examples, QA, and manifests;
- full logs and an independent STOPPUNKT-B verification report.

The normalized source remains in `t/ha` while raw `kg/ha`, raw values, missing/suppressed
statuses, query files, raw response hashes, and normalized hashes remain preserved.

## Commands

All runners require explicit input paths and therefore do not hardcode a developer machine:

```bat
FREEZE_AKERNORM_V1_MODEL.bat "STOPPUNKT_A_DIR" "FROZEN_INPUT_DIR"
RUN_AKERNORM_V1_PILOT.bat "FROZEN_INPUT_DIR" "AKERMINNE_SKANE_ROOT"
VERIFY_AKERNORM_V1_PILOT.bat
```

The pilot selects a deterministic bounded test set. It must include grain premium/discount,
Kristianstad potatoes, oats, winter rape, low SKO share, a mixed/component-only history case,
and a crop without a published norm. A missing-ÅkerScore case is included when one exists in
the frozen input; absence is reported rather than fabricated.

## STOPPUNKT B

After the independent verifier passes, return the artifacts listed by
`VERIFY_AKERNORM_V1_PILOT.bat`. Do not continue to full Skåne or web without a new explicit
GO from Bengt.
