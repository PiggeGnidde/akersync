# ÅkerFrö × ÅkerAccess D2 — BestMatch candidate join

D2 is downstream of two frozen/read-only inputs:

- ÅkerFrö operational MVP v0a (C10),
- ÅkerAccess D0 road feature layer.

The purpose is to test whether the validated road dimensions add useful
ranking information among fields already judged good by ÅkerFrö.

## Candidate universe

D2 does **not** let road convenience rescue a weak physical field.

Only C10 classes:

- A_STRONG_CANDIDATE
- B_PHYSICAL_CANDIDATE

enter the BestMatch candidate universe.

## RoadAccess candidate score

Two D1-supported continuous variables are converted to inverse empirical
percentiles (shorter distance = higher score):

- nearest mapped drivable OSM way,
- nearest statlig/kommunal NVDB roadkeeper geometry.

Initial candidate policy:

    RoadAccess = 0.50 * DrivableAccess + 0.50 * PublicRoadkeeperAccess

This is transparent and deliberately not optimized against the pea labels.

## Three rankings compared

1. **C10 baseline** — frozen operational priority restricted to road-eligible A/B.
2. **Access-first** — A before B, then RoadAccess, AreaLogistik, ÄrtMatch.
3. **Balanced BestMatch candidate** — A before B, then:

       0.50 ÄrtMatch + 0.25 AreaLogistik + 0.25 RoadAccess

The third score is a candidate product policy, not a freeze.

## Diagnostic

Recent clean CONSERVART 2023–2025 is used to compare incremental lift at
top 200/500/800/1000/2000/5000. The diagnostic reports hits, recall,
enrichment and road-distance characteristics.

This is a product sanity check, not a causal estimate.

## Map-ready output

D2 writes a top-5000 WGS84 point GeoJSON carrying the key ÅkerFrö and
ÅkerAccess attributes. The next stage can turn it into the interactive map
without recomputing the ranking.

## Run

    CALL RUN_AKERFRO_AKERACCESS_D2.bat

## Important correction after first D2 run

The first D2 run reported zero recent 2023–2025 positives inside the A/B
candidate universe. This is expected from the frozen C8 semantics, not a data
failure:

- A/B requires `ROTATION_OK` for candidate year 2026.
- recent pea observations trigger `C_ROTATION_CAUTION`.
- therefore recent 2023–2025 clean CONSERVART cannot be used as an
  incremental-lift label inside current A/B without structural leakage.

D2 has been corrected so the ranking diagnostic uses the frozen C10
`is_positive` lineage (clean CONSERVART 2015–2025) within the current A/B
candidate universe. The script still reports recent and 2015–2019 labels as
sanity checks.

This preserves the frozen rotation policy and prevents the diagnostic from
grading A/B against fields that the policy deliberately excludes.
