# ÅkerAccess D0 — Skåne road feature build

D0 scales the tested Sjöbo road pipeline to all 33 Skåne municipalities and
produces one reusable field-level Parquet. D0 is a **feature layer**, not a
score.

The implementation follows the ÅkerPass working rule "few man hours – many
AI-tokens": one resumable BAT, municipality OSM caches, one county-wide NVDB
download, no manual GIS work.

## Eligibility

Same current-field universe as the Sjöbo pilot:

- current Jordbruksverket fields,
- area >=1 ha,
- explicit pasture/slåtteräng excluded from frozen ÅkerMinne 2025 crop names.

## OSM features

Per field:

- nearest mapped drivable OSM way (track/service included),
- nearest ordinary OSM anchor road,
- nearest major OSM road (primary/secondary/tertiary),
- field-entry evidence status,
- mapped last-mile from selected entry candidate to first ordinary-road anchor,
- OSM path tags/restriction evidence.

OSM is cached separately per municipality. A failed full run can be rerun
without redoing completed municipalities.

## NVDB

D0 calculates one padded WGS84 bbox around the eligible Skåne fields and fetches
the selected NVDB v1.2 products once for the county-scale build:

- Vägbredd
- Bärighet
- FunktionellVägklass
- Höjdhinder_upp_till_45_dm
- Väghållare

The Trafikverket API credential is read from the existing repo-root `.env` and
is never logged or stored in outputs.

Anchor attributes are retained only for a <=20 m match to the C1 ordinary-road
anchor.

D0 additionally computes straight-line field-polygon distance to the nearest
NVDB roadkeeper geometry with `Väghållartyp in {statlig, kommunal}`.
This is named explicitly rather than being called legal "allmän väg": road
keeper and legal road category are not assumed identical.

## Important non-freezes

D0 does **not** freeze:

- any 50/100/250 m product threshold,
- a 4.5 m road-width rule,
- the post-hoc Sjöbo `FunktionellVägklass in {4,7}` grouping,
- an ÅkerAccess score.

Functional road class 0–9 is stored raw so D1 can perform a clean Skåne
replication.

## Run

Full Skåne:

`CALL RUN_AKERACCESS_D0_SKANE.bat`

Optional cheap smoke/debug run, OSM-only on Sjöbo:

`CALL RUN_AKERACCESS_D0_SJOBO_SMOKE.bat`

Main outputs:

- `work/akeraccess_v0a/skane_d0/skane_akeraccess_road_features_d0.parquet`
- `work/akeraccess_v0a/skane_d0/skane_akeraccess_d0_municipality_summary.csv`
- `work/akeraccess_v0a/skane_d0/skane_akeraccess_d0_report.json`

## Next stop

D1 uses the frozen D0 feature table for an out-of-sample Skåne conservärt
replication. Primary candidate hypotheses from Sjöbo are:

1. historical conservärt fields are less likely than local area-matched controls
   to have no mapped drivable OSM road within 50 m;
2. functional-road-class composition differs between conservärt and matched
   controls, tested using raw class 0–9 rather than freezing the post-hoc 4/7
   combination.

The statlig/kommunal-distance features are also carried into D1 as product
ranking diagnostics.
