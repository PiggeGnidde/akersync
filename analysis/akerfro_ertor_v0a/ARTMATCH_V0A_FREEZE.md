# ÅkerFrö – ÄrtMatch v0a freeze contract

**Status:** freeze contract defined; formal local freeze is created by `FREEZE_AKERFRO_ARTMATCH_V0A.bat`.

## Frozen product definition

```text
ÄrtMatch v0a =
    0.65 * slope_component
  + 0.25 * ÅkerScore_component
  + 0.10 * residual_texture_component
```

Each component is scaled 0–100 relative to the current Skåne field population.

- **Slope component:** inverse empirical percentile of slope P90. Flatter is better.
- **ÅkerScore component:** empirical percentile of ÅkerScore P50. Higher is better.
- **Residual texture component:** empirical percentile of the texture-only contribution from the C5b quadratic orthonormal ILR model.

The 65/25/10 weights are transparent product-policy weights reflecting the evidence ordering from C2–C5b. They are **not** optimized agronomic coefficients.

## Locked semantics

ÄrtMatch is a **relative physical/structural ranking**, not a probability that a field can grow processing peas and not a yield prediction.

The following are deliberately **not** part of ÄrtMatch and belong in later **ÄrtKandidat** logic:

- field area,
- rotation/current eligibility,
- processor distance/logistics,
- current crop,
- contracts,
- drought/irrigation/water-risk.

## Freeze anchors

- current Skåne fields: **128,636**
- historical clean CONSERVART fields: **3,079**
- fields with ÄrtMatch score: **120,761**
- `INSUFFICIENT_CORE`: **7,875**
- historical positives with score: **3,015**
- raw historical-selection rank AUC: **~0.700**
- C6 near-twin product pairwise accuracy: **~52.44%**
- historical positives in top ÄrtMatch decile: **712**

Scientific lineage retained in the freeze includes the C5b result that quadratic compositional texture is only a **weak residual component** after matching on geography, area, slope and ÅkerScore.

## Formal freeze procedure

Run:

```bat
CALL FREEZE_AKERFRO_ARTMATCH_V0A.bat
CALL VERIFY_AKERFRO_ARTMATCH_V0A.bat
```

The freeze script:

1. verifies the locked anchors and architecture boundary,
2. snapshots the C6 product artifacts and key scientific lineage,
3. computes SHA-256 for every frozen file,
4. records the current Git HEAD,
5. writes:
   `work/akerfro_ertor_v0a/freeze_artmatch_v0a/artmatch_v0a_freeze_manifest.json`.

The verify script fails if either a frozen source artifact or its snapshot changes.

## What may still change without touching the freeze

UI/web presentation, new ÅkerFrö products, ÄrtKandidat, rotation scenarios, logistics, processor assumptions, water-risk modules and future experimental models may evolve independently.

If the ÄrtMatch formula, weights, component definitions, scientific lineage or frozen output are intentionally changed, that is a **new ÄrtMatch version**, not an edit to v0a.
