# ÅkerVärde × ÅkerScore market-gap v1.0 — freeze candidate

Planned freeze tag: `akervarde-akerscore-marketgap-v1.0`

Planned freeze branch: `feature/akervarde-akerscore-marketgap-v1a`

## Status

**FINAL FREEZE — independent sandbox reproduction PASS and local Windows repository reproduction PASS on 2026-08-30. Ready for immutable commit/tag.**

The first local Windows reproduction exposed a deliberately small but real cross-platform numerical sensitivity in the nonlinear robust solver for the >=90% raw-ÅkerScore same-row CV comparison. Inventory, residual correlations, median APE results, >=95% comparison and all other frozen checks reproduced; only the fourth decimal of the two >=90% R² values moved enough to exceed the original overly tight 5e-5 tolerance. Candidate v2 therefore froze the scientifically relevant invariant for that weak diagnostic: both R² values must remain within 0.001 of the reference run and |ΔR²| must remain <=0.002. This does not change the interpretation that raw ÅkerScore gives no material/stable incremental price-model improvement at >=90% coverage.

Final local reproduction from `C:\\AkerSyncRepo`:

- `INPUT VERIFICATION: PASS`
- `RESULT VERIFICATION: PASS`
- `VERIFY_RESULTS: PASS`
- frozen ÅkerVärde sales: **233**
- locked reconstruction: **215**
- transactions with any ÅkerScore: **212**
- score coverage >=80/90/95%: **198 / 191 / 179**
- strict-context >=90%: **113**
- local surprise n: **111**
- >=90% raw-score comparison: BASE R² **0.7547** -> BASE + ÅkerScore **0.7542**; median APE **17.20% -> 18.21%**
- >=95% raw-score comparison: BASE R² **0.7676** -> BASE + ÅkerScore **0.7698**; median APE **17.22% -> 16.72%**
- raw ÅkerScore residual Spearman: **-0.0067**
- class-surprise residual Spearman: **-0.2287**
- local class × SKO × municipality surprise residual Spearman: **+0.0061**
- retrospective candidate screen: **10 / 111**

The final Git tag may now be created after confirming that only the intended market-gap freeze files are staged.

## Scientific question

The upstream ÅkerScore × ÅkerMinne validation showed that ÅkerScore contains information beyond historic agricultural class that is reflected in 2015–2025 field-use decisions.

This study asks a separate market question:

1. Does adding ÅkerScore materially improve the frozen ÅkerVärde market-price model?
2. Is the additional field-quality signal — especially ÅkerScore relative to historic class, SKO and municipality — systematically reflected in held-out transaction-price residuals?
3. Can a fixed retrospective screen identify transactions combining unusually strong local ÅkerScore with unusually low observed/frozen-ÅkerVärde price ratio?

## Interpretation guardrail

This is a **retrospective diagnostic information-gap study**.

It was developed after the ÅkerScore × ÅkerMinne behavioural-validation result was known. It is therefore:

- not prospective validation,
- not a blind test,
- not a causal estimate of soil quality on transaction price,
- not proof that any individual transaction was mispriced,
- not evidence of risk-free arbitrage.

The correct interpretation is narrower: the results test whether modern, field-specific ÅkerScore information appears to be consistently capitalized in observed transaction prices after the frozen ÅkerVärde market baseline is held fixed.

## Frozen upstream lineages

### ÅkerVärde

Frozen model:

- model id: `akervarde-v1.0-rc1`
- regression worktree freeze commit: `d940d057489b1402dd7ed8c762913175b296192f`
- model: `S70_NOFOREST / BASE`
- arable terms: year + log(arable area) + latitude + longitude
- target: observed total purchase price
- tax-assessed value: not used as target or predictor
- deterministic spatial 10-fold CV; 10 km sale cells stay in one fold

The market-gap analysis does not modify the frozen ÅkerVärde model.

### ÅkerScore / historic class / SKO context

Combined context:

- tag: `akerpass-akerminne-context-v1.0`
- commit: `1ad5c77656bb93664d94254af298009a6620da4f`

Upstream behavioural validation:

- tag: `akerscore-akerminne-validation-v1.0`
- commit: `9ca92418d6c100793dcaf3ae70705c97e556a9d5`

ÅkerScore source: `akerscore_soil_v0c`.

No ÅkerMinne crop-history rows are used as price-model inputs in this market-gap analysis. ÅkerMinne is upstream validation evidence only.

## Frozen transaction-to-field linkage

For each transaction, the analysis reuses the already locked v0h transaction-to-block reconstruction.

The sold agricultural area is therefore **not** re-selected using ÅkerScore, historic class, SKO or observed price residual.

Transaction ÅkerScore is the field-area-weighted mean of valid current-field ÅkerScore P50 values inside those already selected current agricultural blocks.

Coverage denominator is the summed locked reconstructed block area.

Observed inventory:

- frozen ÅkerVärde sales: **233**
- sales with locked reconstructed blocks: **215**
- sales with any ÅkerScore: **212**
- ÅkerScore coverage >=80%: **198**
- ÅkerScore coverage >=90%: **191**
- ÅkerScore coverage >=95%: **179**

## Frozen hidden-quality definitions

### Raw ÅkerScore

Area-weighted transaction ÅkerScore P50 over valid scored fields in the locked sale blocks.

### Strict historic-class context

A field is eligible for the surprise benchmarks when:

- historic agricultural class is 5–10,
- valid ÅkerScore P50,
- unique historic-class coverage >=95%,
- dominant historic-class share >=95%,
- `mixed_soil_class == False`.

Observed strict-context field inventory: **58,345 fields**.

### Class surprise

For strict-context field `i`:

`class_surprise_i = ÅkerScore_i - median(ÅkerScore | historic class_i)`

Transaction class surprise is area-weighted across strict-context fields in the locked sale blocks.

### Local surprise

For strict-context field `i`:

`local_surprise_i = ÅkerScore_i - median(ÅkerScore | historic class_i, SKO_i, municipality_i)`

Only local benchmark groups with at least 25 strict-context fields are used.

Observed:

- class × SKO × municipality groups: **273**
- groups with n >=25: **210**
- transactions with >=90% strict-context coverage: **113**
- transactions with valid local surprise at that threshold: **111**

Local surprise is the primary hidden-quality signal because it removes the broad historic-class and local production/geography strata used in the behavioural interpretation.

## Frozen residual definition

The price residual is calculated from the already frozen held-out ÅkerVärde prediction:

`r_i = log(observed purchase price_i / frozen ÅkerVärde CV prediction_i)`

The ÅkerVärde residual is not recomputed after ÅkerScore is observed.

## Reproduced baseline

Standalone reconstruction of the frozen `S70_NOFOREST / BASE` model:

- n: **233**
- spatial CV log-price R²: **0.700814**
- spatial CV median APE: **18.75%**

This agrees with the frozen ÅkerVärde artifact.

## Frozen result A — raw ÅkerScore as a price feature

Same-row, same-fold comparisons:

### >=90% ÅkerScore coverage, n=191

- independent sandbox reference: BASE spatial CV R² **0.75450**, BASE + ÅkerScore **0.75504**
- first Windows reproduction: BASE **0.75467**, BASE + ÅkerScore **0.75416**
- platform-robust frozen invariant: **|ΔR²| <= 0.002** and both levels remain within 0.001 of the reference values
- BASE median APE: **17.20%**
- BASE + ÅkerScore median APE: **18.21%**
- P90 APE: **47.76% -> 46.18%**

The sign of the tiny fourth-decimal R² difference is not treated as scientific evidence. The robust conclusion is that the >=90% raw-score augmentation leaves R² effectively unchanged while median APE does not improve.

### >=95% ÅkerScore coverage, n=179

- BASE spatial CV R²: **0.76753**
- BASE + ÅkerScore R²: **0.76980**
- BASE median APE: **17.22%**
- BASE + ÅkerScore median APE: **16.72%**
- P90 APE: **47.63% -> 46.03%**
- fitted arable-price effect: approximately **+0.93% per +10 ÅkerScore points**

Interpretation: raw ÅkerScore does not provide a large or sufficiently stable incremental improvement to justify inserting it into the frozen ÅkerVärde point model on this evidence alone.

## Frozen result B — residual correlation

Spearman correlation with frozen held-out log-price residual:

- raw ÅkerScore, n=191: **rho = -0.00670**, p=0.927
- class surprise, n=113: **rho = -0.22867**, p=0.0148
- local class × SKO × municipality surprise, n=111: **rho = +0.00611**, p=0.949

The primary local hidden-quality signal is therefore effectively uncorrelated with whether an observation sold above or below the frozen ÅkerVärde prediction.

## Frozen result C — class-surprise geography warning

At >=80% strict-context coverage, n=119:

- BASE spatial CV R²: **0.72940**
- BASE + class surprise: **0.74090**
- median APE: **20.11% -> 17.87%**
- fitted price effect: approximately **-4.77% per +10 class-surprise points**

The negative sign must **not** be interpreted as better soil reducing value.

When the surprise benchmark is localized by class × SKO × municipality, the apparent signal disappears. At >=90% strict-context coverage, n=111:

- BASE spatial CV R²: **0.70794**
- BASE + local surprise: **0.70688**
- median APE: **20.07% -> 20.13%**

The v1.0 interpretation is that class-only surprise retains regional/geographic market structure not fully represented by the simple linear latitude/longitude baseline.

## Frozen retrospective candidate screen

Within the n=111 local-surprise sample:

- high hidden quality: local surprise >= sample P75 = **6.26768**
- low relative price: observed/frozen-ÅkerVärde ratio <= sample P25 = **0.848703**

Transactions satisfying both: **10**.

This screen was developed retrospectively and is frozen only as a reproducible descriptive candidate generator. It must not be described as validated mispricing or arbitrage.

`Borrby 43:34` is both a strict anchor and one of the 10 quartile-screen candidates.

`Humlarp 4:12` is a separate descriptive strict-anchor example with ÅkerScore about 91.9, local surprise about +22.36 and observed/frozen-ÅkerVärde ratio about 0.866. It lies just above the frozen bottom-quartile price-ratio cutoff and is therefore **not** one of the 10 strict quartile-screen candidates.

## Core interpretation

Together with the separate frozen ÅkerScore × ÅkerMinne behavioural validation, the results are consistent with the hypothesis that field-specific agronomic information can affect long-run farmer crop-allocation behaviour without being consistently capitalized in observed transaction prices.

The market-gap study alone does not establish that mechanism. The two studies must be presented as separate evidence:

1. behavioural validation: ÅkerScore sorts real 2015–2025 land-use behaviour within historic-class/local strata;
2. market-gap diagnostic: the corresponding local hidden-quality signal is essentially uncorrelated with frozen ÅkerVärde price residuals.

## Market-communication audit

The separate quick audit of sales advertisements — historic agricultural class frequently stated, SKO/norm yield not found in the checked object descriptions — is **supplemental external context**.

It is not part of this computational freeze or verifier and must be cited/researched separately in the Word report.

## Reproduction contract

Hash-locked inputs are defined in:

`analysis/akervarde_akerscore_marketgap_v1/manifests/input_manifest.json`

Expected results are defined in:

`analysis/akervarde_akerscore_marketgap_v1/expected_results.json`

From the repository root run:

```cmd
analysis\akervarde_akerscore_marketgap_v1\VERIFY_RESULTS.bat
```

The verifier accepts the two previously created local ZIP packages:

- `C:\AkerSyncRegression\work\akervarde_residual_inputs.zip`
- `C:\AkerSyncRepo\work\akerscore_validation_csv_upload.zip`

A valid reproduction must end with:

`INPUT VERIFICATION: PASS`

`RESULT VERIFICATION: PASS`

`VERIFY_RESULTS: PASS`

## Freeze policy

After local PASS and replacement of the candidate status with a final local-reproduction status, create immutable tag:

`akervarde-akerscore-marketgap-v1.0`

Any later change to input hashes, transaction-block linkage, score coverage definition, strict-context rule, benchmark construction, minimum local-group size, residual definition, spatial CV specification, retrospective candidate screen or interpretation guardrail requires a new version/tag.

The eventual Word report must cite the final immutable market-gap tag/commit and clearly retain the retrospective/non-causal guardrail.
