# ÅkerMinne v1.0 — freeze

Freeze tag: `akerminne-v1.0`

This document defines the frozen ÅkerMinne v1.0 contract. The implementation lineage was developed as `v1a`; this freeze promotes the validated Skåne implementation to v1.0.

## Scope

- Geography: all 33 municipalities in Skåne.
- Current/reference geometry: Jordbruksverket 2025 current fields.
- History years: 2015–2025 inclusive.
- Historical identity is geographic and always interpreted from the perspective of the current 2025 field.
- Historical administrative IDs are supporting metadata only and never override geometry.

## Frozen result inventory

- Current 2025 fields: **128,636**.
- Field-years: **1,414,996** (`128,636 × 11`).
- Raw historical overlap/crop components: **2,935,686**.
- Unknown official crop-code combinations after year-specific dictionaries: **0**.
- Municipalities completed: **33/33**.

## Frozen geometry matching rules

For current field `C` and historical field `H`:

- `A_cap` = exact intersection area.
- `A_C` = current field area.
- `A_H` = historical field area.
- `F_C = A_cap / A_C`.
- `F_H = A_cap / A_H`.

Identity thresholds:

- Strict 1:1: `min(F_C, F_H) >= 0.90`.
- Relaxed split/merge graph: `max(F_C, F_H) >= 0.50`.
- Relative near-tie threshold: `0.02`.
- Primary correspondence uses maximum exact intersection; centroid distance is only an exact-area tie-breaker.
- All positive raw intersections are preserved, including those below the relaxed graph threshold.

Frozen identity classes:

- `direct_id`
- `one_to_one_strict`
- `one_to_one_relaxed`
- `split`
- `merge`
- `ambiguous`
- `unmatched`

## Frozen history/status rules

- Minimum material public match: **1%**.
- Complete historical coverage: **95%**.
- `MIXED_CROPS`: second grouped crop share at least **5%**.
- Web-visible crop component: at least **1%**.
- Material raw-overlap excess used for QA: more than **0.5%**.

Product statuses:

- `SINGLE_CROP`
- `MIXED_CROPS`
- `PARTIAL_COVERAGE`
- `NO_PUBLIC_MATCH`

Raw overlap anomalies remain separate QA information and do not replace the agronomic/coverage status.

## Crop-code contract

- Official Jordbruksverket annual crop-code lists are used year by year for 2015–2025.
- Exact `(crop_code_raw, crop_subcategory_raw)` is tried first.
- Fallback, when needed, is only to the main code from the **same year**.
- There is never fallback to another year's dictionary.
- Raw `grdkod_mar` and `grdkod_und` are preserved.
- The v1.0 Skåne result has zero unresolved official crop-code combinations.

## 2025 reference-year rule

2025 is a fixed exact reference row for each current field. It is not produced by self-intersecting the 2025 layer.

Every current field must therefore have exactly 11 rows, 2015 through 2025.

## Data provenance

Primary public source:

- Jordbruksverket historical annual agricultural block and field layers through the official WFS endpoint: `https://epub.sjv.se/inspire/inspire/wfs`.
- Historical field layer: `inspire:arslager_skifte`.
- Historical block layer: `inspire:arslager_block`.
- Historical skifte layers do not provide `region_kod`; municipality is derived locally through the same-year block layer/block ID relationship.
- Official annual crop-code workbooks 2015–2025 supplied/published by Jordbruksverket and normalized without cross-year inference.

Raw official data remains outside git under `C:\AkerSyncRaw` with manifests/hashes/checkpoints.

## QA and validation basis

The freeze is based on:

- Full Skåne batch QA PASS: 33/33 municipalities, 128,636 fields, 1,414,996 field-years, 2,935,686 components, zero unknown crop combinations.
- Skurup pilot used to establish/freeze thresholds and visual interpretation.
- General Skåne pipeline designed to reproduce the frozen Skurup semantics.
- Full web sidecars cover all 33 municipalities and the 128,636 current fields.
- Manual visual spot-checking across municipalities.
- Independent real-world spot validation in Lomma on fields where historical crops were already known; sampled years were consistent with ÅkerMinne output.

The local freeze runner performs unit tests, Skurup regression QA and full Skåne web QA immediately before creating the tag.

## UI interpretation frozen for v1.0

The ÅkerMinne panel is read backwards from today's 2025 field: *what occupied the land that constitutes this current field in each historical year?*

Important UI language:

- `historisk täckning`: share of today's field with material historical public-field coverage.
- `flera grödor`: at least two material crop components, with the second at least 5% of today's field.
- `dagens skifte bestod av flera skiften`: multiple historical fields contribute to today's single field (`merge`).
- `dagens skifte var del av ett större skifte`: one historical field contributes to multiple current fields (`split`).
- `annan gränsdragning`: relaxed 1:1 geometry match.
- `komplex gränsändring` / complex identity: the historical/current relationship cannot be represented safely as a simple 1:1, split or merge; e.g. many-to-many topology or primary-overlap ambiguity.
- `Ingen offentlig skiftesmatch`: below the frozen 1% material public-match threshold; it does **not** mean the land was un-farmed.

## Freeze policy

The tag `akerminne-v1.0` is the immutable baseline for this version.

Future work may add derived summaries, crop-rotation analysis, prediction, additional data sources or UI improvements, but changes to the frozen geometry/history semantics must use a new version rather than silently changing v1.0.
