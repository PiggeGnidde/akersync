# ÅkerVatten MVP v0a · STOPPUNKT C full-Skåne linkage

STOPPUNKT C scales only the linkage proven and frozen in B.

## Architecture

The full run must **not** perform one network request per field.

The pipeline acquires/caches hydrological source data first:

- SGU small-magasin raster: one cached raster package;
- SGU-HYPE areas: one full-Skåne bbox cache;
- SVAR2022 Delavrinningsområden: deterministic 20 km WFS tiles, each saved independently;
- Vattenwebb flow statistics: one cached XLS table.

The 128,636 current fields are then processed locally in deterministic chunks of 1,000.

For every chunk:

1. sample SGU small-magasin;
2. spatially join SGU-HYPE;
3. spatially join SVAR2022 Delavrinningsområden;
4. map ARO_UUID -> Vattenwebb Aroid -> Subid;
5. atomically save a Parquet checkpoint;
6. verify the checkpoint before continuing.

## Resume semantics

Checkpoints are stored under:

    work/akervatten_mvp_v0a/c_full_linkage/checkpoints/

A completed checkpoint is trusted only when its field identity exactly matches the canonical field slice.

If a run is interrupted:

- completed field chunks remain on disk;
- completed SVAR tiles remain on disk;
- a partially written `.tmp` checkpoint is ignored/removed;
- rerunning the same BAT resumes from the existing valid checkpoints.

The maximum field-work loss from an interruption is therefore less than one chunk, by default <1,000 fields.

## CMD progress

The field phase prints one line per 1,000 fields, for example:

    [FIELDS]  47000/128636 · 36.5% · chunk 47/129 · 3200.1 fields/s · ETA 00:00:26 · checkpoint saved

On restart an existing chunk prints:

    [FIELDS]  47000/128636 · 36.5% · chunk 47/129 · RESUME checkpoint already complete

SVAR acquisition likewise prints one line per cached/downloaded tile.

## Final outputs

    work/akervatten_mvp_v0a/c_full_linkage/
      field_points_3006.parquet
      checkpoints/
      akervatten_c_spatial_links_skane.parquet
      c_state.json
      c_summary.json

The summary reports:

- full-population coverage for each source/link;
- number of unique SGU-HYPE `omrade_id`;
- number of unique SVAR `ARO_UUID`;
- number of unique S-HYPE `Subid`;
- fields per hydrological unit: median, P90 and maximum;
- coverage by municipality;
- source provenance and hashes.

## C acceptance

Default minimum coverage:

- SGU small-magasin >= 95%;
- SGU-HYPE >= 99%;
- SVAR ARO_UUID >= 99%;
- S-HYPE Subid >= 99%.

These thresholds are QA gates, not product-score definitions.

No historical drought feature engineering and no ÅkerVatten component score is frozen in C.
