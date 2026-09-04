# Offline pixel cases

Run `RUN_RAPSKARTAN_PIXEL_CASES.bat` from the clean feature branch. This exports
up to five cases from the existing scene archive, not a full parity rerun. No
credentials, catalog queries, downloads, model fitting or production edits occur.
The completed parity diagnostic is found automatically if exactly one run has a
manifest. Otherwise supply `--diagnostic-dir "...\run_<id>"` explicitly.

The fixed selection recipe uses three field-area ranks (smallest, median, largest)
at jointly maximum local/reference coverage, the largest absolute B08 median
discrepancy, and the largest positive coverage discrepancy. Duplicates are removed.
This is an intentionally diagnostic sample, not an unbiased accuracy benchmark.
No crop labels or model predictions enter the selection.

Only intersecting scenes on selected dates are checked and exported. Source asset
checksums are verified once per selected scene, which can take time even though
only small windows are exported. A heartbeat prints every 30 seconds during long
operations. Source files remain untouched. Re-running makes a new output directory.

Each crop is losslessly stored in GeoTIFF at its original native pixel grid,
datatype and nodata value. No reflectance scaling, clipping, interpolation or
reprojection is applied to exported pixels. The 16-native-pixel margin supports
later reprojection tests. Pixel arrays and georeferencing are read back and
verified; provenance includes original asset metadata, source window and hashes.

Limits: five cases, twenty distinct source scenes, four million pixels per band,
256 MiB total uncompressed crop pixels, and 2 GiB free output space. Missing or
corrupt sources stop the export without downloading or repairing anything.

The package includes projected field geometry, frozen reference and previous local
observations, scene lists usable by the unchanged local engine, and two diagnostic
geometry masks (current center mask and all-touched mask). Neither mask is promoted
as a production fix. Crops are replayed through the unchanged local engine and
compared to the previous local statistics. Counts and quality are checked separately;
the 1e-6 numeric tolerance concerns crop reproduction only, not production parity.
An imperfect replay is reported, not hidden; it can itself reveal grid/window effects.

Output: `data/derived/rapskartan_v1/2025_pixel_cases_v1/`. Upload the ZIP named on the
final `RETURN THIS ZIP` line. A verified manifest covers every packaged file. On
failure return the printed console log. Do not run the full map product yet.

Optional arguments: `--diagnostic-dir`, `--stop-d-dir`, `--product-dir`,
`--scene-archive`, `--output-dir`.
