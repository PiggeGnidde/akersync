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
