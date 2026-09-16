# ÅkerPuls D2C – full-Skåne QA ranking freeze + review product

D2C is authorized only after the completed D2B review stop (`GO D2C`). It does not rerun D2B or change the scientific model. Its purpose is to freeze the exact full-Skåne QA ranking and make it practical to inspect spatially before any future split-line/geometric stage.

## Frozen parent result

D2C requires D2B status `PASS_TO_D2B_REVIEW_STOP` and verifies the D2B manifest hashes against the actual files before doing anything else. The expected census is fixed from the reviewed D2B run:

- 12,676 baseline split candidates
- 10,250 TRUE-LOO stable
- 1,136 at or above frozen development P90 = 0.781017
- 618 at or above frozen development P95 = 0.843688
- QA tiers: 618 `HIGH_PRIORITY_SPLIT_CANDIDATE`, 518 additional `SPLIT_CANDIDATE`, 11,540 `EVIDENCE_ONLY`

The formal fusion artifact remains SHA256 `3ab2fcdd06284c15cbcffb20fba8da7de9f6b10ca102bd4026fc73a9ee0a7316`. D2C neither tunes thresholds nor refits the fusion.

## Geometry policy

All review polygons are unchanged official 2025 field geometry with the already-frozen source SHA256 `63f256c012a8f8aab75f22699bc729e60036913429caeb070306f57c19b31706`.

D2C does **not** generate a proposed split line, does not split or merge a polygon, and does not authorize replacement of official geometry. It merely attaches the frozen ranking attributes to the existing polygons.

## Review outputs

The output directory is `C:\AkerSyncRepo\work\akerpuls_d2c_full_skane_freeze_review_v1`.

The stage writes a GeoPackage for all 12,676 ranked candidates, separate P90+ and P95 GeoPackages/GeoJSON/CSVs, a convenient P90+ HTML map, and a deterministic 100-field visual-audit sample. The sample has 50 P95 fields and 50 P90-only fields. Selection first seeks geographic coverage across analysis cells and then uses a frozen SHA256 ordering. It is a deliberately broad review/challenge sample, not a random population accuracy estimate.

The HTML file contains the P90+ GeoJSON. Generating it is zero-network; opening it in a browser loads Leaflet and OpenStreetMap tiles from the internet.

`D2C_FULL_SKANE_QA_RANKING_FREEZE_V1.json` records the exact D2B parent hashes, formal model freeze, geometry policy, review output hashes, and audit-selection contract. `d2c_manifest.json` binds that freeze file to the Git/script version used to create it.

## Run

From the isolated ÅkerPuls worktree:

```cmd
cd /d C:\AkerSync-Prelim2026
git pull --ff-only
RUN_AKERPULS_D2C_FULL_SKANE_FREEZE_REVIEW_V1.bat
```

No S3/CDSE credentials are required. D2C has no STAC/S3/Process execution path and spends no Sentinel Hub PU.

## Mandatory stopping point

A successful run ends at `FROZEN_FULL_SKANE_QA_RANKING_V1`. The next action is human review of the 100-field sample and P90+/P95 map. Any algorithm that proposes an actual internal split boundary or persists a new 2026 geometry is a separate future stage and requires separate authorization.
