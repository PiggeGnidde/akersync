# ÅkerPuls D1-S3j — full-Skåne direct-S3 acquisition

## Prerequisite

D1-S3i passed and froze the exact full-Skåne direct-S3 execution contract:

`9764672a66938f7526c8cca9ab2140ec205d4ad993f798239b627c17c559bbc8`

The plan contains 29 Sentinel-2 scene items / 203 source assets, 593 frozen D0 daily tile-date rows, 259 frozen zero tile-date rows, 142 raster tiles and 568 snapshot tiles. At D1-S3i plan time 119 assets (5.845 GiB) were already verified in the local S3 source cache and 84 assets (3.304 GiB) remained to download.

## Scope

D1-S3j is acquisition/derivation only. It:

1. verifies the exact D1-S3i execution-contract hash and hashes of the frozen scene catalog, tile-scene map, daily plan and D0 tile plans;
2. audits the local source-asset cache and downloads only missing objects from the exact frozen S3 URIs;
3. derives all 593 daily 8-band FLOAT32 tiles from the original Sentinel-2 L2A assets;
4. derives all 568 four-snapshot tiles under the frozen pair rule;
5. builds one VRT per snapshot;
6. writes SHA256-bound sidecars and output indexes so interrupted runs can resume safely.

It never performs a STAC query, never calls Sentinel Hub Process API, never reads the old Process tiles as source input, and never runs the split/fusion model.

## Frozen backend

- scene order: `PARENT`
- coverage: `SCL_NONZERO`
- reflectance: `SCALE_OFFSET`
- resampling: `NEAREST`
- clear SCL: 2, 4, 5
- pair rule: clear pixel first, otherwise lower CLD; never average paired dates
- unplanned D0 tile-date: zero by frozen D0 domain

Daily bands:

`B02 B03 B04 B08 B11 SCL CLD dataMask`

Snapshot bands:

`B02 B03 B04 B08 B11 SCL CLD VALID NDVI LSWI SOURCE_DATE_INDEX`

## Storage

Source scene cache remains:

`C:\AkerSyncRaw\akerpuls_d1s3_parity_v1`

Full-Skåne derived rasters are written separately to:

`C:\AkerSyncRaw\akerpuls_full_skane_s3_v1`

The previous 180 Process-API tiles are validation evidence only and are never mixed into these sources.

## Resumability

Each daily and snapshot TIFF has a JSON sidecar bound to:

- the frozen execution-contract SHA256;
- tile/date or tile/snapshot identity;
- exact parent-ordered scene IDs or exact daily-source hashes;
- backend semantics;
- final TIFF SHA256.

On rerun, a tile is reused only when its sidecar key, file hash, raster dimensions, CRS and transform all match. Otherwise that dedicated derived output is regenerated atomically.

## PASS meaning

`PASS_TO_FULL_SKANE_D1_RASTER_QA` means source assets, 593 daily rasters, 568 snapshot rasters and four VRTs were created and structurally verified under the frozen contract.

It does **not** authorize D2 model/fusion execution yet. The next stage is a zero-network full-Skåne D1 QA pass over the raster outputs and field-level snapshot validity. Automatic split, merge and geometry replacement remain false.
