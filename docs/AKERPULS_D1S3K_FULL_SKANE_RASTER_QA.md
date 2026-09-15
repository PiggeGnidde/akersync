# ÅkerPuls D1-S3k — full-Skåne zero-network raster / field-validity QA

D1-S3j completed the frozen direct-S3 acquisition domain: 593 daily tile-date sources, 568 snapshot tiles and four VRT mosaics, with no model execution or geometry mutation.

D1-S3k is the mandatory local QA before any full-Skåne D2 split/fusion run. It performs no network call of any kind.

## Frozen inputs

- 128,636 official 2025 fields, geometry SHA256 `63f256c012a8f8aab75f22699bc729e60036913429caeb070306f57c19b31706`
- 142 D0 raster tiles
- 568 D1-S3j snapshot tiles
- D1-S3j snapshot-output index SHA256 `a3a26d1f454a8c0d65e326a913b0d10d91c54d4ba9886315ec5d5dd1e35cafff`
- D1-S3j VRT-output index SHA256 `0210f78b9780f6b586be0c89109e5a696202167b5283d5bae6b20a24d23c8979`

## QA method

All frozen fields are rasterized tile-by-tile onto the exact 10 m D0 grid. For each field the stage accumulates:

- rasterized field pixels;
- VALID pixels for April, May, June and July;
- pixels VALID in all four snapshots;
- a pre-B2 coverage flag requiring at least 24 all-four VALID pixels.

The last quantity is only a coverage screen. D2 still applies the exact B2 one-pixel interior erosion/fallback and can classify fields as `UNCERTAIN`.

The raster scan also verifies that:

- VALID is binary;
- every VALID pixel has SCL in `{2,4,5}`;
- NDVI and LSWI are finite on VALID pixels;
- SOURCE_DATE_INDEX is inside the allowed range for each one- or two-day snapshot;
- snapshot tile grids, CRS and band descriptions remain frozen.

## Acceptance frozen before full-Skåne field-validity outcomes

The structural checks must all pass. Catastrophic-coverage guards are deliberately broad and are not model thresholds:

- at least 99.9% of fields rasterize to at least one 10 m pixel;
- field-pixel VALID fraction is at least 0.60 in each snapshot;
- field-pixel all-four VALID fraction is at least 0.45;
- at least 70% of fields have at least 24 all-four VALID pixels.

These guards decide whether the raster product is fit to proceed to a separate D2 execution plan. They do not change candidate thresholds, fusion, split/merge logic or geometry.
