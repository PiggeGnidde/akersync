# ÅkerVatten / VISS VattenTryck — FREEZE v1

**Freeze date:** 2026-09-29  
**Scope:** Skåne, field-level VISS groundwater-withdrawal context for ÅkerPass / ÅkerVatten  
**Status:** FROZEN / PASS

## 1. Purpose

This freeze records the first validated VISS-based groundwater-withdrawal context layer in ÅkerPass. The layer is descriptive context attached to agricultural fields. It is not a permit database, legal assessment, estimate of actual withdrawal by an individual field, or a causal attribution from a field to a groundwater-body problem.

The design principle is occurrence-level provenance: a field may be spatially linked to a VISS groundwater body, and the UI may report VISS classifications and VISS authority motivation for that groundwater body. Statements must not be rewritten as field-level claims.

## 2. Source and API

Source: VISS (VattenInformationsSystem Sverige), accessed through the VISS API using a local API key stored outside version control.

Initial Skåne groundwater inventory returned 181 groundwater records. The investigated API methods included waters, groundwater pressure classifications/motivations, groundwater impacts/motivations, and water risk classifications.

The local API key is never committed, printed, or persisted in generated evidence.

## 3. Frozen pipeline

The frozen VISS/VattenTryck chain is represented by the following scripts:

- `112_viss_vt_a1c_inventory.py` — API method inventory and raw extraction.
- `113_viss_vt_a1d_census.py` — groundwater pressure/impact/risk census.
- `115_viss_vt_a2_spatial_coverage.py` — VISS groundwater geometry and Skåne field coverage.
- `116_viss_vt_a2b_robust_field_join.py` — robust field↔groundwater-body spatial relation and overlap fractions.
- `117_viss_vt_a3_field_fingerprint.py` — field-level VISS fingerprint and water-body evidence.
- `118_viss_vt_a4_patch_web.py` and subsequent A4 UI patches — ÅkerPass VISS/uttag view and wording.
- `120_viss_vt_a5_hallands_vadero_diagnostic.py` — geometry diagnostic.
- `121_viss_vt_a5b_bjare_motivation_diagnostic.py` — Bjärehalvön motivation/provenance diagnostic.
- `123_viss_vt_a4d_groundwater_level_impact.py` — explicit groundwater-level impact flag.
- `124_viss_vt_a5c_provenance_audit.py` — final raw-VISS→A3 provenance audit.

Generated raw/derived datasets under `data/derived` remain intentionally outside Git where applicable.

## 4. Frozen population and spatial join

Skåne field population: **128,636 fields**.

VISS positive-case field coverage from the frozen join:

- any positive VISS case: **16,626 fields**
- agricultural withdrawal pressure: **11,670**
- municipal/public withdrawal pressure: **2,679**
- industrial withdrawal pressure: **2,644**
- generic withdrawal pressure: **1,068**
- other withdrawal pressure: **2,386**
- quantitative-risk signal: **8,670**
- fields linked to more than one positive-case EU_CD: **876**

The A2b join dissolves duplicate geometry features by `EU_CD` before field matching. The positive-case geometry contained 32 raw geometry features representing 16 unique positive-case EU_CD; after dissolve there were 16 water bodies. This removed the earlier apparent 2× relation/area duplication.

Spatial relations are based on positive-area polygon overlap, with overlap area/fraction retained. Representative-point membership is retained as an additional diagnostic, not substituted for polygon overlap.

## 5. Frozen field fingerprint semantics

For each field, the VISS layer may encode:

- spatial relation to a VISS groundwater body (`EU_CD`),
- overlap fraction / dominant groundwater body,
- positive VISS withdrawal-pressure categories,
- agriculture / municipal-public / industry / generic / other withdrawal signals,
- VISS quantitative-risk information,
- explicit positive groundwater-level impact where available,
- VISS authority motivation text tied to the groundwater body.

A positive signal means that **VISS has classified the groundwater occurrence as having the corresponding significant pressure/context**. It does not mean that the selected field itself withdraws water, has a permit, lacks a permit, causes the pressure, or is legally restricted.

## 6. Groundwater-level impact

The final pre-freeze impact inventory found one groundwater body with a positive VISS impact classification for changed groundwater levels: **Bjärehalvön, SE625674-131386**, with the VISS motivation `Kvantitativ status är otillfredsställande`.

The A4d patch propagated this occurrence-level flag to **5,495 fields** spatially linked to that occurrence.

Chemical impacts were deliberately **not** added to the VattenTryck field signal in this freeze.

## 7. Provenance audit — STOPPUNKT PASS

The final VT-A5c audit checked the positive VISS cases against the raw VISS pressure-motivation rows.

Result:

- positive case water bodies audited: **15**
- A3→raw provenance failures: **0**
- Köpingebro/Glemmingebro raw-text hits: **1**
- final result: **VT-A5c PROVENANCE AUDIT: PASS**

Text comparison normalizes whitespace only; `EU_CD`, pressure type and date remain exact provenance constraints.

The apparently surprising Köpingebro/Glemmingebro text was confirmed to originate directly from VISS for **Vombsänkan, SE615867-137086**, `Vattenuttag - Jordbruk`, classification `Y`, dated 2019-04-29. It is therefore preserved as VISS source information rather than corrected or geographically reinterpreted by ÅkerPass.

The audit also confirmed that identical/general motivation text can legitimately occur for multiple VISS groundwater bodies. Text identity is therefore never used as a join key.

## 8. UI semantics frozen

The ÅkerPass VISS/uttag view follows these rules:

1. Wording refers to the **groundwater occurrence / VISS assessment**, not to the selected field as causal actor.
2. Authority motivation is displayed as VISS source text/context.
3. No field-level statement is made that a farmer withdraws water, has/does not have a permit, or is responsible for a VISS pressure.
4. A missing VISS groundwater relation is not interpreted as absence of groundwater, absence of irrigation, or absence of legal constraints.
5. VISS groundwater occurrence geometry is conceptually distinct from the separate SGU large-groundwater-reservoir layer. A field can therefore intersect a VISS groundwater occurrence while the SGU `Stora grundvattenmagasin` panel reports no direct hit.

Hallands Väderö was used as an explicit diagnostic of point 5: the selected field/pasture geometry overlaps the VISS Bjärehalvön occurrence 100%, despite no direct hit in the separate large-groundwater-reservoir panel. This is not treated as a contradiction between datasets.

## 9. Explicit non-goals / exclusions

This freeze does **not** create:

- a composite `VattenTryck` score,
- a legal or permit inference,
- a water-right / water-court decision database,
- an estimate of field-level irrigation volume,
- proof that a particular field or farmer withdraws groundwater,
- proof of illegal withdrawal,
- a causal attribution of groundwater-level or chemical impacts to a field,
- a chemical-pollution score for fields,
- a replacement for VISS, SGU, SMHI, permit records or legal review.

These exclusions are intentional.

## 10. Freeze rule

The above data semantics, field↔VISS relation logic, positive-case interpretation, provenance requirements and UI causal disclaimers are **FROZEN as VISS/VattenTryck v1**.

Future cosmetic/UI changes may be made without breaking the freeze if they preserve the semantics above.

Any future change to case definition, spatial join semantics, source interpretation, provenance rules, pressure categorisation, quantitative-risk logic, or field-level meaning requires a new version and renewed validation rather than silently modifying v1.

## 11. Freeze decision

**STOPPUNKT VISS/VT-v1: PASS — FREEZE APPROVED 2026-09-29.**

Basis: API inventory completed; Skåne census completed; spatial coverage and duplicate-geometry issue resolved; robust field join validated; field fingerprint generated; UI wording corrected to occurrence-level semantics; Hallands Väderö/Bjärehalvön diagnostics completed; groundwater-level impact separated; final provenance audit passed with zero A3→raw provenance failures.
