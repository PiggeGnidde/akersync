# ÅkerVärde × ÅkerScore market-gap v1.0

This folder contains the reproducible retrospective information-gap analysis that asks whether field-quality information in ÅkerScore is consistently reflected in transaction prices after the frozen ÅkerVärde v1.0-rc1 baseline is held fixed.

## Important scientific status

This is a retrospective diagnostic study developed after the upstream ÅkerScore × ÅkerMinne behavioural validation was known.

It is not:

- a new blind test,
- prospective validation,
- causal proof of mispricing,
- proof of arbitrage.

The analysis does not alter or recalibrate the frozen ÅkerVärde v1.0-rc1 model.

## Cross-platform numerical guardrail

The nonlinear robust additive fit uses SciPy `least_squares`. The >=90% raw-ÅkerScore comparison is so close to zero incremental R² that Linux and Windows solver stacks can move the fourth decimal and even flip the sign of the tiny ΔR². Candidate v2 therefore verifies a bounded scientific invariant (`|ΔR²| <= 0.002`) rather than pretending a 5e-5 R² tolerance is portable. All row counts, residual correlations and substantive error metrics remain tightly frozen.

## Required local input packages

The verifier expects the two already-created ZIPs:

`C:\AkerSyncRegression\work\akervarde_residual_inputs.zip`

`C:\AkerSyncRepo\work\akerscore_validation_csv_upload.zip`

All core files inside those packages are SHA256-locked in `manifests/input_manifest.json`.

## Run

From `C:\AkerSyncRepo`:

```cmd
analysis\akervarde_akerscore_marketgap_v1\VERIFY_RESULTS.bat
```

Expected end state:

```text
INPUT VERIFICATION: PASS
RESULT VERIFICATION: PASS
VERIFY_RESULTS: PASS
```

Generated outputs are written under:

`C:\AkerSyncRepo\work\akervarde_akerscore_marketgap_v1\`

They are local analysis artifacts and should not be committed.

## Frozen core tests

The verifier reproduces:

1. frozen ÅkerVärde S70_NOFOREST / BASE metrics;
2. transaction-to-block linkage inventory;
3. raw ÅkerScore incremental spatial-CV tests at >=90% and >=95% score coverage;
4. historic-class score surprise;
5. class × SKO × municipality local score surprise;
6. correlations with frozen held-out ÅkerVärde price residuals;
7. a fixed retrospective high-local-surprise / low-price-ratio candidate screen.

See `docs/validation/AKERVARDE_AKERSCORE_MARKETGAP_V1_FREEZE.md` for definitions and interpretation guardrails.
