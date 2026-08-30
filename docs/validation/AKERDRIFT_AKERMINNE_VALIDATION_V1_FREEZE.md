# ÅkerDrift × ÅkerMinne validation v1.0 — final freeze

Planned branch: `feature/akerdrift-akerminne-validation-v1a`

Planned tag: `akerdrift-akerminne-validation-v1.0`

## Status

**FINAL FREEZE — independent sandbox reproduction PASS and local Windows repository reproduction PASS on 2026-08-30. Ready for immutable commit/tag.**

Final local reproduction from `C:\\AkerSyncRepo` ended with:

- `RESULT VERIFICATION: PASS`
- `VERIFY_RESULTS: PASS`

and reproduced the frozen core results:

- raw cohort: **99,095**
- strict/local cohort: **47,235 / 46,431** in **198** local groups
- productive >=4-year cohort: **37,958**
- raw Spearman ÅkerDrift~area: **0.8732**
- raw Spearman ÅkerDrift~cereal: **0.5071**
- raw Spearman ÅkerDrift~broad-production: **0.5357**
- controlled broad-production-vs-vall effect per +10 ÅkerDrift: **-0.13 pp** (95% CI **-1.31 to +1.06**), **ΔR² = 0.000004**
- secondary productive-use effect per +10 ÅkerDrift: **+12.22 pp** (95% CI **+10.64 to +13.80**), **ΔR² = 0.0527**
- rotation category-count effect per +10: **+0.01213**, **p = 0.349**
- rotation entropy effect per +10: **+0.00246**, **p = 0.327**
- calendar crop-switch effect per +10: **-0.00385**, **p = 0.331**

The final Git tag may now be created after confirming that only the intended ÅkerDrift × ÅkerMinne freeze files are staged.

## Directional hypothesis and scientific status

Before inspecting this ÅkerDrift × ÅkerMinne result, the stated expectation was that raw ÅkerDrift would correlate with crop-use patterns mainly because ÅkerDrift is strongly related to field area, while the remaining shape/terrain component after area control would contribute little to crop rotation or productive crop choice.

That directional hypothesis genuinely preceded the result, but this document **must not call the study formally preregistered or blind**. The exact implementation — cohort definitions, spline control and endpoints — was frozen only after the exploratory result had been seen.

The exploratory chat summary used rounded/working implementations for a few secondary rotation statistics. This freeze is the first exact numerical contract for those details. Under the deterministic definitions below, the rotation null remains unchanged (category-count p≈0.349, entropy p≈0.327, calendar-switch p≈0.331). The central broad-production-vs-vall result reproduces at approximately -0.13 percentage points per +10 ÅkerDrift with ΔR²≈0.000004.

The auxiliary finding that ÅkerDrift remains associated with repeated productive use of a field was not hypothesized in advance and is secondary/exploratory.

## Frozen upstream data

### ÅkerDrift

Released product model:

- `akerdrift-fast-v2-hybrid-rc1`
- full Skåne: 128,636 fields
- 128,597 scored
- 39 null because of insufficient slope coverage
- source parquet SHA256: `1f451db6a7d59dfa410ab8a6924f9216a2e0e3afb12c042159d94c717deca0aa`
- selected export SHA256: `9c7d3b633b728cfdfbfe6b713371f61ad7a0a5e19565fbd088d98d4f72ff843e`

The model represents machine-oriented structural workability from size, boundary geometry, holes and slope. Hydrology/TWI is diagnostic and does not enter the score.

### ÅkerMinne / static context

- years: 2015–2025 inclusive
- 128,636 current fields
- 1,414,996 field-years
- combined context tag: `akerpass-akerminne-context-v1.0`
- combined context commit: `1ad5c77656bb93664d94254af298009a6620da4f`

## Frozen cohorts

### Raw cohort

Valid ÅkerDrift plus at least 8 of 11 years with `status == SINGLE_CROP`.

Expected n: **99,095**.

This cohort is used only to describe raw correlations.

### Strict local cohort

A field must have:

- historic agricultural class 5–10;
- valid ÅkerDrift;
- `soil_class_coverage_unique >= 0.95`;
- `dominant_soil_class_share >= 0.95`;
- `mixed_soil_class == False`;
- at least 8 `SINGLE_CROP` years.

Expected strict n: **47,235**.

Local comparisons require historic class × SKO × municipality groups with at least 25 strict fields.

Expected local n: **46,431** in **198** groups.

Crop-choice and rotation endpoints additionally require at least four productive years, where productive means broad-production or vall.

Expected n: **37,958**.

## Frozen crop-use definitions

The cereal, vall and broad-production definitions are inherited from the frozen ÅkerScore × ÅkerMinne validation v1.0.

Productive years are years classified as either broad-production or vall.

Within productive years, secondary crop-specific endpoints are:

- cereal;
- raps;
- sugar beet;
- potato;
- maize.

Rotation categories are cereal, vall, raps, sugar beet, potato, maize and other broad-production. Category-count, Shannon entropy and calendar-consecutive crop-switch rate are reported. The exploratory entropy calculation used a fixed `ln(8)` normalization constant; this is retained verbatim to reproduce the original calculation and affects scale only, not the substantive inference.

## Frozen area/local control

The controlled tests remove local historic class × SKO × municipality fixed effects by within-group demeaning.

Field size is controlled flexibly using a cubic B-spline of natural-log area with eight retained basis columns. The basis is mathematically equivalent to:

`bs(log(area_ha), df=8, degree=3, include_intercept=False)`

with five interior quantile knots at 1/6, 2/6, ..., 5/6 of the analysis-sample `log(area_ha)` distribution.

ÅkerDrift then enters as one linear term. Effects are reported per +10 ÅkerDrift points. Cluster-robust covariance uses the local historic class × SKO × municipality groups.

## Frozen primary interpretation

The key result is a separation between raw association and incremental information after area/local controls.

Expected raw relationships:

- ÅkerDrift vs area Spearman: about **0.873**;
- ÅkerDrift vs cereal share: about **+0.507**;
- ÅkerDrift vs broad-production share: about **+0.536**.

Yet among fields with >=4 productive years, after flexible area and local controls:

- broad-production vs vall: approximately **-0.13 percentage points per +10 ÅkerDrift**;
- incremental within-group R²: approximately **0.000004**.

The pre-result directional hypothesis is therefore supported for the central crop-choice endpoint: once area and local production context are held fixed, the released ÅkerDrift score contributes essentially no additional information about broad-production versus vall choice.

## Rotation robustness

Raw field size strongly sorts rotation behavior. Local largest-vs-smallest area quintiles are expected to differ by approximately:

- **+0.73** rotation categories;
- **+0.143** normalized entropy;
- **+25.8 percentage points** calendar-consecutive crop switching.

After area and local controls, +10 ÅkerDrift is expected to have only very small effects on category count, entropy and switch rate, with all three cluster-robust p-values comfortably above conventional significance thresholds.

This supports the narrow statement that the official ÅkerDrift score adds little information about *which productive rotation strategy is selected* after area is known.

## Important secondary finding: repeated productive use

A separate endpoint asks whether `SINGLE_CROP` years are classified as broad-production or vall at all.

After the same local fixed effects and flexible area control, +10 ÅkerDrift is expected to be associated with approximately **+12.2 percentage points** higher productive-use share, with an incremental within-group R² of approximately **0.053**.

This result was not part of the directional hypothesis. It is secondary and must not be used to retroactively redefine the primary question.

A useful product interpretation is therefore:

- **area** strongly structures crop/rotation choices;
- **ÅkerDrift** adds little to productive crop choice once area is known;
- **ÅkerDrift may still contain material information about whether a field is repeatedly used as productive arable/vall land at all.**

## Guardrails

This study does not show:

- causal effects of field geometry on crop choice;
- that area alone determines crop choice;
- that individual ÅkerDrift components are irrelevant;
- that the +12.2 pp productive-use association is causal;
- that subgroup/component findings discovered after this freeze are confirmatory.

No component or crop-subgroup result found after this freeze should be presented as part of the ex-ante directional hypothesis. Such analyses are exploratory unless separately frozen in a later version.

## Reproduction contract

The verifier SHA-locks the core input members, rebuilds all frozen cohorts and endpoints, writes local CSV/JSON outputs, and checks both numerical tolerances and substantive invariants.

The final Git tag may only be created after a local PASS and after this status section is replaced with the final reproduction record.
