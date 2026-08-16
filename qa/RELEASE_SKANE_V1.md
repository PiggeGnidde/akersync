# ÅkerSync · Skåne v1.0 release freeze

Release candidate: `skane-v1.0`

This file records the first full-Skåne ÅkerSync build that passed automated QA and manual visual review. The purpose is to create a stable regression anchor before new feature work starts.

## Scope

Core pipeline:

`Geometry → Soil → Topography → Hydrology/TWI → Final features → Web → QA`

External inputs are frozen for the 2025 Skåne MVP. Satellite data is intentionally not included in this release.

## Full-build result

Final verifier result:

`SKÅNE BUILD VERIFICATION: PASS`

Key counts and QA values from the validated build:

- Jordbruksverket blocks: **122,970**
- Jordbruksverket skiften: **128,636**
- Municipalities: **33 / 33**
- DEM source tiles: **2,271**
- DEM coverage on blocks: **100.0% for all 122,970 blocks**
- Hydrology/TWI valid blocks: **122,968 / 122,970**
- Explicit hydrology exceptions: **2 × SUBPIXEL_10M**, total block area **0.022015 ha**
- Farmland TWI P90 threshold: **12.143241**
- Farmland TWI P95 threshold: **15.312701**
- Municipality web pages: **33 / 33**
- Web output total: **617.6 MB**
- Largest municipality page: **68.5 MB**

The two missing TWI values are not DEM or Whitebox failures. Both polygons contain zero 10 m raster-cell centres under the defined `all_touched=False` sampling rule. They are explicitly audited and accepted by QA; no TWI values are interpolated or invented.

## Hydrology method frozen in v1.0

- Source DEM: Lantmäteriet MHM legacy 2.5 × 2.5 km tiles
- Working resolution: 10 m
- 1 m → 10 m resampling: average
- Conditioning: Whitebox `FillDepressions` + `fix_flats`
- Slope: degrees
- Flow accumulation: D-infinity, Specific Contributing Area
- TWI: Whitebox WetnessIndex, `ln(SCA / tan(slope))`

No numerical hydrology change was made while scaling from the original three-municipality baseline to full Skåne.

## Input completeness

The 2025 Jordbruksverket geometry download contains all 33 Skåne municipalities and has 0 orphan skifte→block references.

The DEM gap audit found no actual farmland without DEM coverage. Remaining planned rectangle cells are coastal/sea-edge gaps; the eight initially flagged core cells were verified as buffer-only, with **0.000 ha actual farmland without DEM**.

## Regression anchors

Lomma, Kävlinge and Eslöv remain regression anchors for absolute terrain and soil features. Full-Skåne relative distributions and percentile thresholds are expected to differ from the original three-municipality MVP.

## Manual visual QA

The project owner reviewed multiple municipalities in the generated web UI and reported that geometry, soil, topography and hydrology looked reasonable and consistent with the earlier three-municipality test experience. No obvious systematic visual anomaly was found before this freeze.

## Exploratory outputs included but not part of the core model contract

The branch also contains exploratory `#Nyfiken` analyses for soil extremes, water-prospect heuristics and a four-class water-regime map. These are explicitly exploratory and are not agronomic diagnoses or part of the frozen core scoring model.

## What is deliberately NOT frozen as a model

- No final ÅkerScore / Geometry Score
- No calibrated machineability model
- No observed drainage status
- No irrigation-need model
- No satellite time series
- No crop-yield prediction

The next feature branch starts **Geometry V1a**: transparent raw field-shape descriptors first, with no composite score.
