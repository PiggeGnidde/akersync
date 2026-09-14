# ÅkerPuls D1-S3i — full-Skåne direct-S3 plan

## Prerequisite

D1-S3h passed the prospectively frozen C5 backend-confirmation contract with exact equality through the complete B2 -> TRUE-LOO -> rolling-history-prior -> frozen fusion pipeline. Historical D1-S3f on C7 remains `REVIEW`; it is not rewritten.

D1-S3i therefore advances only to a **full-Skåne acquisition plan**. It does not acquire imagery and does not run the model.

## Frozen domain

The plan consumes the existing D0/D0b contract unchanged:

- 128,636 frozen 2025 fields
- 142 raster tiles, 1024 x 1024 pixels at 10 m
- 593 frozen daily tile-date source rows
- 568 snapshot tiles
- dates: 2026-04-08, 04-09, 05-25, 06-26, 06-27, 07-09
- final D0b execution-contract SHA256: `d2c2a88d0978cffcd720dbb7a7982049fbc5c09ae41f3f7be2e959ad254aec19`

The other 142 x 6 - 593 = 259 tile-date combinations remain zero by the frozen D0 request domain. Current STAC results are not allowed to expand that domain.

## Direct-S3 backend

The already validated semantics remain unchanged:

- all acquisitions intersecting the exact frozen D0 daily tile
- `PARENT` / most-recent scene ordering
- `SCL_NONZERO` coverage
- STAC `SCALE_OFFSET` reflectance harmonization
- `NEAREST` resampling for reflectance and quality layers
- clear SCL classes 2, 4, 5
- paired-date mosaic: clear pixel first, otherwise lower CLD, never average
- missing frozen source: zero-filled FLOAT32 daily input with `dataMask=0`

## What D1-S3i does

D1-S3i makes only public STAC metadata requests. It queries the full D0 tile envelope once for each of the six frozen dates, then intersects exact STAC item geometries with the exact 593 frozen daily tiles.

It freezes:

- exact scene IDs and parent ordering
- exact STAC asset URIs, byte sizes, checksums, scales and offsets
- exact daily tile -> scene mapping
- existing verified source-asset cache hits
- missing source-asset count and projected bytes
- storage upper bounds

The generated `FULL_SKANE_S3_EXECUTION_CONTRACT.json` binds the later acquisition stage to those exact artifacts. A later run may not silently re-query and add newer scene IDs.

## Cache and Process isolation

The validated original-scene cache under `C:\AkerSyncRaw\akerpuls_d1s3_parity_v1` may be reused. This is source-data reuse, not backend mixing.

The old 180 cached Sentinel Hub Process tiles are never read as full-Skåne source imagery. They remain validation evidence only. Every one of the 593 eventual daily source tiles must be rebuilt from the frozen direct-S3 scene assets.

## Stop rule

`PASS_TO_FULL_SKANE_S3_ACQUISITION` authorizes only a separate guarded acquisition stage. It does not authorize model execution, split/merge mutation, or replacement of official 2025 geometry.
