# ÅkerPuls D1-S3f — zero-scene frozen-date transport fix

## Observed failure

The first D1-S3f execution stopped before any C7 S3 model/fusion outcome was produced:

- `2026-04-08 / C7_FULL`: 1 STAC scene
- `2026-04-09 / C7_FULL`: 0 STAC scenes
- parent STAC helper raised `RuntimeError: No STAC scenes for 2026-04-09 / C7_FULL`
- `d1s3f_manifest.json` was therefore never created.

This was an execution/backend edge case, not a failed parity result.

## Frozen scientific quantities left unchanged

No acceptance threshold, model feature, fusion weight, C7 label, split/merge rule, geometry rule, scene-order rule, coverage rule, reflectance rule, resampling rule, or paired-date selection rule was changed.

The already frozen D1-S3f acceptance contract remains unchanged.

## Execution-policy completion

A frozen date whose exact target grid has no STAC acquisition is now represented as an empty 8-band FLOAT32 daily source:

- reflectance bands = 0
- SCL = 0
- CLD = 0
- `dataMask = 0`

The empty date remains in its original position in the paired-date list. The existing B1/C7B `choose_pair` implementation is then applied unchanged, so an empty second date cannot displace a valid first-date pixel.

This is also consistent with the full-Skåne D1 design, where a snapshot tile may be built from only the daily sources that exist for that tile/date and absent source coverage contributes no valid pixels.

The policy is pinned in `config/akerpuls_d1s3f_c7_end_to_end_parity_v1.json` as:

`ZERO_FILLED_FLOAT32_SOURCE_WITH_DATAMASK_0`

## Scope

This patch only allows the pre-existing end-to-end parity experiment to proceed past an empty frozen-date footprint. It does not authorize full-Skåne S3 acquisition. That still requires D1-S3f to satisfy the acceptance contract and return `PASS_TO_FULL_SKANE_S3_PLAN`.
