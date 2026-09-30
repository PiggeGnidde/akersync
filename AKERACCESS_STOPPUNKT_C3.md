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

## Sjöbo result — 2026-09-30

Primary window 2023–2025 gave 56 unique current eligible fields with at least
one clean CONSERVART observation.

### Access distance

| metric | recent conservärt | unlabeled | RR |
| --- | ---: | ---: | ---: |
| connected OSM candidate | 73.2% | 69.2% | 1.06 |
| <=50 m | 39.3% | 43.9% | 0.89 |
| <=100 m | 41.1% | 47.4% | 0.87 |
| <=250 m | 51.8% | 54.9% | 0.94 |
| <=500 m | 66.1% | 61.8% | 1.07 |
| <=1000 m | 73.2% | 67.7% | 1.08 |

None of these primary comparisons was statistically distinguishable at ordinary
levels; Fisher p-values ranged from 0.419 to 0.686 except connected access at
0.563 and <=1000 m at 0.472.

Area-standardisation did not reveal a hidden short-last-mile advantage. The
corresponding enrichments were 1.01x for connected access and
0.84x/0.82x/0.90x/1.02x/1.03x for <=50/100/250/500/1000 m.

Among connected fields, recent conservärt had median last mile 28.5 m versus
10.5 m for unlabeled fields. The distributions were not statistically
distinguishable (Mann–Whitney p=0.202).

### NVDB at the ordinary-road anchor

Recent conservärt road-keeper matches (n=41):
- statlig 19
- enskild 18
- kommunal 4

Unlabeled matches (n=2,936):
- statlig 1,472
- enskild 1,437
- kommunal 27

The small municipal-road count in the recent-positive group is conspicuous but
must be treated as exploratory: only four positive fields carry that category,
and spatial/geographic confounding has not yet been controlled.

Road width did not show a meaningful 4.5 m threshold signal:
- recent conservärt median 4.8 m; 20/41 below 4.5 m
- unlabeled median 4.0 m; 1,521/2,934 below 4.5 m

Thus road width at the ordinary-road anchor should not be interpreted as an
Apetit-style >=4.5 m gate.

### C3 interpretation

The original hypothesis that successful conservärt fields should be
systematically closer to an ordinary road is **not supported by this Sjöbo
primary-window test**. In particular, there is no empirical basis here for
choosing a 50, 100 or 250 m hard last-mile threshold.

This does not invalidate ÅkerAccess. Instead it suggests that:
- existence/plausibility of access can still be a proactive screening gate;
- mapped last-mile length alone is a poor proxy for actual heavy-machine access;
- road/path quality and physical restrictions are more plausible next targets;
- spatially matched validation is needed before interpreting the apparent
  road-class / road-keeper differences.

No score or threshold is frozen.
