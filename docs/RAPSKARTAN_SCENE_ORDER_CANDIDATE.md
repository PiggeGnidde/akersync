# Scene-order candidate V3 (offline diagnostic only)

Test release: three dependency-independent tests, syntax and diff checks passed
in the authoring environment. Full raster/Parquet regression was blocked by
missing dependencies and unavailable installation permission. The user approved
publication for testing on the existing Windows installation. The batch command
therefore runs the full regression suite before allowing any candidate replay;
a test failure stops it immediately. This release is not production-approved.

## Scope

This candidate tests one general rule: sort scene cloud percentages after
truncating to two decimal places, then break ties by the original scene ID.
It does not prefer a satellite, field, date or crop label. The immutable scene
inventory keeps its original full-precision metadata. Only a temporary copy of
the cloud sorting key is supplied to the unchanged `reference_pixels_v2` engine.
All asset paths, timestamps, pixel calculations, model parameters and parity
thresholds remain unchanged. The production runner still uses its original
engine; this diagnostic never generates a full map, even if parity passes.

For the accepted 298-scene inventory, this ordering changes exactly 2025-03-21
and 2025-05-20. A guard rejects any inventory for which another date changes.
The rule is a candidate hypothesis, not a claim that the reference service's
complete internal tie-breaking policy has been established.

## Reuse safeguards

The completed V2 diagnostic is required, including its original `checkpoints`
directory, not only its report ZIP. The source report manifest and artifacts
are hash-verified. Source pixel code is compared with the unchanged current
pixel code using its recorded commit, allowing only LF/CRLF differences.
Inventory hash, locked prediction manifest, model manifest, field IDs and the
full recorded runtime fingerprint must agree. Both V2 reference replays must
have passed. The current run also requires both reference replays to pass.

Every existing scene asset is checked again, including on unchanged dates.
This can take time even though only two dates require pixel processing.
For unchanged dates, the original Parquet checkpoint must pass its identity
and checksum checks and match the manifest-backed V2 CSV within 1e-14 absolute
tolerance (CSV floating-point round-trip allowance). The exact Parquet values
are reused, not the CSV values. Missing or inconsistent checkpoints block the
run; there is no automatic full 70-date replay and no download fallback.

New checkpoints use a separate V3 identity and output directory. The identity
includes the source diagnostic manifest hash and candidate rule. Rerunning the
same command reuses completed V3 checkpoints. Do not run two copies concurrently.

## Windows command after publication and verification

```bat
cd /d C:\AkerSync-Rapskartan
git pull --ff-only
RUN_RAPSKARTAN_SCENE_ORDER_CANDIDATE.bat
```

The runner auto-selects a single source run under
`data\derived\rapskartan_v1\2025_candidate_parity_v2`. If several exist:

```bat
RUN_RAPSKARTAN_SCENE_ORDER_CANDIDATE.bat --reuse-diagnostic-dir "C:\AkerSync-Rapskartan\data\derived\rapskartan_v1\2025_candidate_parity_v2\run_d2768e101529aa21"
```

No credentials are needed. The command first runs safety tests and stops if
they fail. Output is isolated under
`data\derived\rapskartan_v1\2025_candidate_parity_v3`.

Return the `rapskartan_parity_diagnostic_<timestamp>.zip` named by the final
`RETURN THIS ZIP` line. It includes the usual full parity reports plus
`scene_order_comparison.csv` and `reuse_provenance.json`. `date_progress.csv`
distinguishes `computed`, `reused_v2_verified` and `checkpoint` rows.
The original V2 output, scene cache and frozen artifacts are not modified.

Completion is not approval: all 2,385 selected decisions are evaluated with the
unchanged gates, and failures remain visible in the report. A separate review
is required before any production adoption or map run.
