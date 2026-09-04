# Full historical Skane map: adopted local engine V3

## Accepted baseline

The returned diagnostic `19ac4e565e80e59828fe6ef8b87ecc192b7838249b024c9b63af1b1a874c72c5`
passed all unchanged parity gates: 265 fields, nine cutoffs, 2,385 identical
frozen-P95 decisions and matching cutoff-level data-quality statuses.
Its 26 report artifacts were hash-verified. Acceptance is bound to the original
diagnostic manifest by `analysis/rapskartan_v1/accepted_local_engine_v3.json`.

This does not mean every probability or observation-quality flag is identical:
seven observation-level quality differences remain; the largest calibrated
probability difference is about 0.089, without changing a tested P95 decision.
The accepted engine is the unchanged reference-pixel V2 implementation plus
the V3 cloud-percentage sorting adapter (truncate to two decimals, then scene ID).
No model, threshold, parity requirement or post-blind memory rule is changed.

## Run

```bat
cd /d C:\AkerSync-Rapskartan
git pull --ff-only
RUN_RAPSKARTAN_2025_MAP_PRODUCT.bat
```

The command runs three gated stages: full regression tests, map generation,
then the independent STOPPUNKT E verifier. It stops immediately on failure.
There is no web, Sentinel-1, deployment, tag or merge step.

The new runner is entirely offline. It needs no AWS or CDSE credentials and
does not query the scene catalog or download missing images. It requires:

- The accepted STOPPUNKT C and D folders at their existing default locations.
- The original scene inventory under `2025\source\scene_inventory.json`.
- The existing scene archive under `C:\AkerSyncRaw`.
- The accepted V3 diagnostic **including its original Parquet checkpoints**
  under `2025_candidate_parity_v3\run_19ac4e565e80e598`.
- The same recorded Python, package, GDAL and PROJ runtime as the accepted run.
- At least 20 GiB of free output-disk space.

A single V3 run folder is detected automatically. If there are several, invoke
the Python runner with `--accepted-parity-dir` set to the accepted folder; do not
delete any diagnostic data to make autodetection succeed.

## Isolation and restart

New output is under `data\derived\rapskartan_v1\2025_map_product_v3`, separate
from the original `2025` output and the diagnostic folders. The new run identity
binds repository tree, accepted engine receipt, frozen model and contract,
complete scene metadata, runtime and memory rule. A different identity cannot
silently reuse or overwrite this output; choose another output directory.

All existing scene assets are hash-checked before processing. The mandatory
parity gate is evaluated again by replaying the accepted, hash-verified Parquet
observations through the unchanged frozen models. The accepted report CSV is
also checked against these checkpoints; exact Parquet values are used for
predictions. Reusing the approved pixel computation avoids a redundant 70-date
pixel run but does not bypass the classification-parity gate.

Full-population pixels are then computed with that same adopted engine.
Checkpoints are saved per municipality **and per observation date within a
municipality**. A date with no scene coverage is an explicit empty checkpoint,
not a reason to invent observations or skip the rest of the period.
Completed municipalities bind their historical-prior provenance by checksum;
the referenced historical input files are checked when those results are reused.

To resume after interruption, run the same command with the same inputs and
runtime. The in-progress date may need repeating; completed dates survive.
Do not run concurrent copies or update code/packages while a run is active.
Do not remove the scene archive or diagnostic checkpoints after this stage.

Full-population processing is substantially larger than the parity sample.
There is no reliable full-run time estimate yet. Progress is printed per scene,
date and municipality, with 30-second heartbeats during long pixel operations.

## Return and independent verification

The verifier checks artifact hashes, accepted V3 receipt and code/runtime,
parity rows against locked predictions, full field/date coverage, crop-label
exclusion, frozen threshold decisions, exact monotonic memory behavior,
historical-prior source hashes and every cached scene asset.

After PASS it creates `rapskartan_full_map_<timestamp>.zip` and prints
`RETURN THIS ZIP`. The ZIP includes manifest-listed products, QA, accepted
diagnostic reports and logs. It excludes raw imagery and working checkpoints.
Return this ZIP for review at STOPPUNKT E. A completed map does not authorize
web publication or deployment.

If only final verification must be repeated:

```bat
VERIFY_RAPSKARTAN_2025_MAP_PRODUCT.bat
```

On failure, return the displayed error and the logs in the new output folder.
Source files and completed checkpoints remain available for diagnosis/restart.
