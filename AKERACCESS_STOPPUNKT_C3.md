# ÅkerAccess — STOPPUNKT C3: historical conservärt validation

C3 asks whether fields that were actually used for clean conservärt production
also have systematically stronger access evidence.

Primary historical window: **2023–2025**.

Secondary robustness windows:
- 2020–2025
- 2015–2025
- each primary year separately (2023, 2024, 2025)

Positive definition is unchanged from ÅkerFrö:
`SINGLE_CROP + semantic CONSERVART`.

A current field is counted once within a window even if it carried conservärt
more than once. Other fields are **unlabeled**, not agronomic negatives.

## Primary tests

C3 compares recent conservärt fields with the other 1-ha+ non-pasture current
Sjöbo fields for:

1. presence of a connected OSM access candidate;
2. operational thresholds <=50/100/250/500/1000 m to the C1 ordinary-road anchor;
3. conditional last-mile distribution among connected fields;
4. area-standardized threshold rates using 1–2, 2–5, 5–8, 8–12, 12–20, 20+ ha strata;
5. NVDB road keeper, width, functional road class and bearing class near the C1 anchor.

The area-standardized comparison is important because historic conservärt fields
have a non-random field-size distribution.

## Interpretation guardrails

- Historical non-use remains positive-unlabeled.
- No connected OSM candidate means insufficient proactive access evidence, not
  physical inaccessibility.
- NVDB road width is not field-entrance width and not a 4.5 m clearance test.
- Missing bearing class means unknown.
- No ÅkerAccess score is fitted or frozen in C3.

Run:

`CALL RUN_AKERACCESS_STOPPC3.bat`

Outputs go to:

`work/akeraccess_v0a/sjobo/pea_validation_c3/`
