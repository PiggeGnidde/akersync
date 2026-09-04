# Offline parity diagnostic

Run from the clean `feature/rapskartan-skane-v1a` Windows checkout:

```cmd
RUN_RAPSKARTAN_PARITY_DIAGNOSTIC.bat
```

Requires the existing STOP C/D directories and complete downloaded scene archive.
No AWS credentials, STAC queries, new downloads, model fitting, threshold tuning,
crop-ground-truth analysis, full map output, or changes to the production pipeline.
The runner preserves the existing engine, including its current radiometric behavior.

It selects the same bounded parity panel as the full runner (265 fields for the
accepted inputs; contract maximum 400), uses hash-locked sample geometries in
EPSG:3006, and compares three paths against the locked satellite predictions:

1. Replay saved reference temporal features in the current Python environment.
2. Rebuild temporal features from saved reference satellite statistics and replay.
3. Recompute statistics from local scenes, save temporal features and predict.

Comparisons include raw scores, calibrated probabilities, unchanged parity gates,
per-variable signed/absolute differences, missingness, per-day pixel counts,
coverage, quality classifications, and per-cutoff decision differences.
No hypothesis is selected by its agreement score and no production fix is applied.

Each date's source files are size/checksum-verified before use. No remote asset is
opened: all paths resolve below the selected local archive. Missing/corrupt files
stop the diagnostic without downloading, deleting, or repairing anything.
Python network operations are blocked by an audit hook; rasterio only receives
validated local filesystem paths. The only subprocess operations are local Git
inspection. Output must be separate from input directories.

Progress prints at every acquisition date and a heartbeat every 30 seconds during
long steps. Atomic Parquet date checkpoints preserve float precision. Restarting
the same command verifies source files and checkpoint hashes, then reuses complete
dates. Changed code, models, scene inventory, selected fields or runtime versions
produce a different checkpoint identity. No 250-GiB first-download guard is used;
only 2 GiB of diagnostic output headroom is required.

Outputs are under `data/derived/rapskartan_v1/2025_parity_diagnostic_v1/run_<id>/`.
The final `RETURN THIS ZIP` line identifies the timestamped archive to upload.
It includes all comparison tables, full-precision local/reference statistics and
features, model scores, runtime metadata, logs and an artifact hash manifest. It
excludes satellite imagery and date checkpoints. On operational failure return the
console log printed by the runner; existing checkpoints remain available.

**Exit 0 means diagnostics completed, not that parity passed.** Inspect
`diagnostic_summary.json` for the separate replay/parity results. This command
never proceeds to municipal full-map calculations, even if parity happens to pass.

Optional named arguments (passed through by the BAT): `--stop-c-dir`,
`--stop-d-dir`, `--product-dir`, `--scene-archive`, `--output-dir`.
