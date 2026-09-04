# Bounded reference-pixel retrieval

Run `RUN_RAPSKARTAN_REFERENCE_PIXELS.bat` on the clean feature branch. Requires
the completed pixel export, frozen STOP C/D packages and locally configured
`CDSE_CLIENT_ID` / `CDSE_CLIENT_SECRET` (not AWS keys). Never upload credentials.

Authorization: at most ten Sentinel Hub data requests for the five existing cases.
There is one separate OAuth login per invocation with uncached data; login consumes
no processing request slot. Entirely cached runs require no login or credentials.
Only the configured CDSE OAuth and Process endpoints are used. Redirects and
automatic retries are disabled. These are new observations from the service today;
they never replace the hash-locked historical reference.

For each case there are two Process API requests at the original geometry, target
grid, date, least-cloudy ordering, bilinear processing and harmonization setting:

1. SIMPLE: the frozen evalscript formulas plus SCL, input dataMask and effective
   valid mask as additional FLOAT32 TIFF bands. This is the primary pixel reference.
2. TILE: up to eight separate scene samples with the original ten optical bands,
   SCL, CLD and dataMask for every sample. Metadata lists the slot, date, cloud
   coverage, Sentinel Hub ID and source dataPath. TILE is diagnostic only; it is
   not silently substituted for SIMPLE. There are no new Statistics, STAC or S3
   requests. The package includes the old locked statistics for comparison.

All source files/manifests and geometries are checked before login. Output images
are bounded to 100000 pixels per case and 64 MiB per response. Unexpected tar
members, oversized images or changed CRS/band layout stop interpretation. Exact
grid agreement and current versus historical valid-pixel counts are reported,
not assumed. Several percentile definitions are tabulated for diagnostic analysis,
not used to tune the production algorithm or its acceptance thresholds.

The attempt ledger `cache/request_budget.json` is written BEFORE each data request.
It binds the exact request plan, survives restarts, and never resets itself.
Completed responses are checksum-verified and reused. A failed/interrupted attempt
without a complete cache blocks automatic resubmission: return the log for review.
HTTP 401, 403, 429 and other errors stop without retries. A lock prevents concurrent
runs sharing the same output. After a forced termination a stale lock may need
inspection; the runner does not remove an unknown lock automatically.

Do not delete the ledger/cache, change output directories to evade the budget, or
launch parallel copies. A changed plan requires a new authorization decision.
No tokens, secrets, authorization headers or OAuth responses are saved. Cached
metadata stores only content type, processing units and content hashes.

Output: `data/derived/rapskartan_v1/2025_pixel_reference_v1/`. Upload the ZIP named
by the final `RETURN THIS ZIP` line. On failure return the printed console log.
Success means reference retrieval completed, NOT production parity passed.
No model fitting, threshold tuning, full-map generation, deployment, tag or merge.

The runner finds the source automatically if exactly one completed pixel-export
run exists. Otherwise pass `--pixel-dir "...\run_<timestamp>"`. Other optional
arguments: `--stop-c-dir`, `--stop-d-dir`, `--output-dir` (keep this unchanged for
restarts). A full native-image cache is not needed for this step.

API sources:
- https://docs.sentinel-hub.com/api/latest/evalscript/v3/
- https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Process/Examples/S2L2A.html
- https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Data/S2L2A.html
