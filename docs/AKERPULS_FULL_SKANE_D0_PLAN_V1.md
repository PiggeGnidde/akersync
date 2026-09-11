# ÅkerPuls split-fusion QA v1 — STOPPUNKT D0 full Skåne

Status: **PRE-EXECUTION PLAN; ZERO PU**

## Purpose

D0 is the final zero-PU planning step before spending Sentinel Hub Process API units on a full-Skåne application of the formally frozen split-fusion QA v1.

D0 does **not** alter geometry and does **not** re-open model development. The product remains a QA/ranking layer on top of official 2025 geometry.

Formal split-fusion freeze:

- tag: `akerpuls-split-fusion-qa-v1.0`
- commit: `bd8ef176ffdb1c29c2db42bcdbf83fb4bdca8899`
- frozen fusion artifact SHA256: `3ab2fcdd06284c15cbcffb20fba8da7de9f6b10ca102bd4026fc73a9ee0a7316`
- DEV-P90: `0.781017`
- DEV-P95: `0.843688`
- automatic split: **FALSE**
- automatic merge: **FALSE**
- automatic geometry replacement: **FALSE**

## What D0 verifies

D0 reads the frozen 2025 field geometry and requires:

- 128,636 fields;
- geometry SHA256 `63f256c012a8f8aab75f22699bc729e60036913429caeb070306f57c19b31706`;
- unique stable field IDs;
- no null/empty/invalid geometry rows silently removed.

It then re-queries only the **public CDSE STAC catalogue** for the frozen dates and reconstructs the full raster request plan. No OAuth token and no Sentinel Hub Process API call is made in D0.

The expected continuity values from A0 are:

- raster tiles: 142;
- planned daily Process requests: 593;
- estimated PU upper: 5534.67.

Any difference becomes `REVIEW` before the expensive D1 run.

## Frozen raster execution topology

D1 will use the same preprocessing semantics as B1/C1/C5B/C7B:

- Sentinel-2 L2A;
- EPSG:32633;
- 10 m resolution;
- 1024 × 1024 aligned raster tiles;
- source bands `B02,B03,B04,B08,B11,SCL,CLD,dataMask`;
- NEAREST up/downsampling for the full input set;
- SCL clear codes 2, 4, 5;
- paired dates are mosaicked only: clear pixel first, otherwise lower CLD; paired dates are never averaged;
- snapshot bands `B02,B03,B04,B08,B11,SCL,CLD,VALID,NDVI,LSWI,SOURCE_DATE_INDEX`.

Daily source tiles are retained through Stage-D freeze for audit/cache reproducibility. Four tiled snapshot stores are then assembled, one for April, May, June and July.

A VRT is built for each snapshot. Later field processing reads only a field-sized window from the VRT; **no whole-Skåne 11-band raster is loaded into RAM**. This also handles fields that cross raster-tile boundaries without truncating them.

## Important normalization contract

The development/validation runs C, C5 and C7 did not use one Skåne-wide feature standardization. Each geographically compact pilot used its own robust median/MAD scaling. Applying a new global Skåne-wide scaling would therefore be a scientifically new preprocessing regime.

D0 freezes a deterministic local extension instead:

- 20 × 20 km analysis grid, origin `(0,0)` in EPSG:32633;
- every 2025 field has one unique owner cell from its representative point;
- the normalization population for an owner cell is **all 2025 fields intersecting that 20 km cell**;
- median/MAD scaling is computed from all valid field pixels in that local population;
- TRUE-LOO recomputes the same local scaling after each omitted snapshot;
- a cell with fewer than 200 normalization fields is not silently pooled with a neighbor; D0 returns `REVIEW` instead.

This is deliberately conservative. It preserves the local-normalization character under which the frozen fusion was independently validated while making the full-Skåne run deterministic and non-overlapping at the field-result level.

## Frozen model application after D1

For each field:

1. official 2025 geometry remains the parent/default geometry;
2. B2 baseline candidate discovery is applied without the obsolete locked morphology gate;
3. the rejected `separation_ratio >= 4` rule is not used;
4. baseline candidates receive TRUE-LOO continuous minimum child Dice;
5. the true rolling ÅkerMinne `prototype_p_splitmerge_2026` prior is joined;
6. the exact frozen three-signal empirical-CDF fusion is applied with equal weights;
7. QA tier is assigned:
   - `HIGH_PRIORITY_SPLIT_CANDIDATE`: fusion ≥ 0.843688;
   - `SPLIT_CANDIDATE`: 0.781017 ≤ fusion < 0.843688;
   - `EVIDENCE_ONLY`: fusion < 0.781017.

No tier changes the geometry automatically.

## D0 artifacts

The run writes to:

`C:\AkerSyncRepo\work\akerpuls_full_skane_d0_plan_v1`

Key artifacts:

- `d0_raster_tiles.csv/.gpkg`
- `d0_scene_inventory.csv`
- `d0_snapshot_coverage.csv`
- `d0_process_request_plan.csv`
- `d0_snapshot_tile_plan.csv`
- `d0_field_partition.csv`
- `d0_analysis_cells.csv/.gpkg`
- `D1_EXECUTION_CONTRACT.json`
- `d0_manifest.json`
- `d0_qa.md`

`D1_EXECUTION_CONTRACT.json` receives a deterministic SHA256. The later D1 downloader must pin this exact contract and request-plan hash before it is allowed to spend PU.

## STOPPUNKT D0 decision

Proceed to D1 only if all of the following are true:

- `D0_STATUS=PASS`
- `A0_REFERENCE_MATCH=PASS`
- `RESOURCE_GUARD=PASS`
- `SPARSE_NORMALIZATION_CELLS=0`
- fusion freeze hash remains unchanged
- automatic geometry mutation remains false.

If any of these fail, stop before D1 and review the plan. D0 itself uses zero Sentinel Hub PU.
