# Offline scene-choice diagnostic

This is a source-attribution diagnostic, not a new production scene-order rule.
The completed `reference_pixels_v2` diagnostic still fails the unchanged exact
decision-parity gate. No map product is authorized by these reports.

## Fixed scope

- Dates: 2025-03-21 and 2025-05-20 only.
- One to six existing decision-mismatch fields, plus up to six controls selected
  by a stable hash of field identity (not by crop labels or error magnitude).
- At most sixteen scenes, from the already frozen scene inventory.
- Existing local scene assets only; an audit hook blocks network connections.
- No models are loaded, and no production engine, threshold or gate is changed.

Each scene is processed separately with the unchanged `reference_pixels_v2`
pixel engine. The result is compared with the saved reference statistics for
the selected field and date. A complete match requires all 51 spectral/index
percentile statistics to be finite and within absolute tolerance 1e-7, plus
matching valid-pixel count and observation-quality status. Missing observations
or missing statistics cannot be reported as complete matches.

The metadata report lists four hypothetical scene orderings: full-precision
cloud percentage, or cloud percentage truncated to two decimals with ties
ordered by identity, newest acquisition, or oldest acquisition. These orderings
are **not applied** to the engine. A global rank does not imply that a scene
covers a particular field. Single-scene matches can also be ambiguous or absent
when the reference used a mosaic. Lowest error alone does not prove the
reference service's tie-breaking rule.

## Run in Windows cmd.exe

```bat
cd /d C:\AkerSync-Rapskartan
git pull --ff-only
RUN_RAPSKARTAN_SCENE_CHOICES.bat
```

No credentials are needed. The runner requires the clean feature branch
`feature/rapskartan-skane-v1a`. It automatically selects a single completed
candidate run under `data\derived\rapskartan_v1\2025_candidate_parity_v2`.
If several run folders exist, pass the intended folder explicitly:

```bat
RUN_RAPSKARTAN_SCENE_CHOICES.bat --diagnostic-dir "C:\AkerSync-Rapskartan\data\derived\rapskartan_v1\2025_candidate_parity_v2\run_d2768e101529aa21"
```

The input manifest, STOPPUNKT D, source inventory and candidate pixel-code
identity are checked before processing. Every scene asset is hash-checked,
including on restart. Progress messages and periodic heartbeats are printed;
checking large existing assets can still take time. Two GiB of free output
space is required; no scenes are downloaded or copied into the output.

Each completed scene has a checksummed checkpoint. Rerunning the same command
reuses valid checkpoints when code, inputs and recorded runtime identity match.
Keep the original scene archive and candidate diagnostic intact.

## Return package

Output is under `data\derived\rapskartan_v1\2025_scene_choice_v1`.
The final `RETURN THIS ZIP` line names `rapskartan_scene_choices_<timestamp>.zip`.
Return that ZIP, which contains only reports and a checksum manifest, not
scene imagery or checkpoint copies. Key reports:

- `scene_choice_summary.json`: bounded scope and diagnostic status.
- `scene_comparison.csv`: per-scene, per-field comparisons.
- `best_single_scene.csv`: all complete matching scene identities, plus the
  lowest-error scene where all statistics are available.
- `single_scene_timeseries.csv`: individual-scene statistics.
- `reference_timeseries.csv` and `baseline_timeseries.csv`: saved comparison data.
- `scene_order_hypotheses.csv`: unapplied metadata orderings.
- `verified_scene_assets.csv`, `scene_progress.csv`, and the console log.

`SCENE_COMPARISON_COMPLETE` means the diagnostic ran, not that parity passed.
On failure the runner preserves checkpoints and prints the log to return.
