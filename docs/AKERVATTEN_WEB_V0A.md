# ÅkerVatten web v0a

## Purpose

Add ÅkerVatten to the **latest completed ÅkerPass map that already contains ÅkerFrö**.

Web lineage:

`feature/akervatten-web-v0a`

created from:

`feature/akerfro-web-v0a`

The completed ÅkerFrö dist remains the immutable web base:

`C:\AkerSync-AkerFroWeb\dist`

ÅkerVatten data are read from the frozen/reviewed water worktree:

`C:\AkerSync-Vatten`

No ÅkerNorm, ÅkerFrö or ÅkerVatten model is recalculated by the web build.

## Product philosophy

ÅkerPass shows separate evidence dimensions; it does not issue a water-right verdict.

The web therefore creates:

- **no combined ÅkerVatten score**;
- **no green/yellow/red permit signal**;
- **no inferred legal status**.

Field panel wording states:

`Vattenrätt: ej bedömd`

## Main layer

A new top-level map button is added:

**ÅkerVatten**

It opens six sublayers.

### 1. MarkTorka

Geometry: field polygons.

Colour: frozen 0–100 relative field scale.

Meaning: structural drought sensitivity from field soil/topography.

### 2. MarkVäta

Geometry: field polygons.

Colour: frozen 0–100 relative field scale.

Meaning: structural wetness tendency from field soil/topography.

### 3. Små magasin

Geometry: field polygons.

Colour: frozen 0–100 relative SGU small-magazine screening scale.

This is explicitly presented as an overview/local indicator, not a well-yield promise.

### 4. GrundvattenTorka

Geometry: **SGU-HYPE groundwater-area polygons**, not field polygons.

Colour: frozen historical groundwater-drought score.

This visual distinction makes the information scale explicit: the field lies inside a regional hydrological unit.

Expected units: 786.

### 5. Stora magasin

Geometry: **SGU mapped groundwater-magazine subareas**.

No 0–100 score is created.

Colour represents only broad mapped capacity magnitude for visual navigation. The field panel retains SGU's exact source capacity class, vertical J/S/K position, aquifer/rock information and magazine relation.

Mandatory semantics:

> Kartlagd kapacitetsklass innebär inte tillstånd, hållbart uttag eller garanterad brunnskapacitet.

### 6. YtvattenTorka

Geometry: **SVAR/S-HYPE catchment polygons**, not field polygons.

Colour: frozen historical low-flow sensitivity.

Expected hydrological units: 502 Subid.

## Field drawer

Every selected field receives an **ÅkerVatten** section containing all six dimensions together:

- MarkTorka
- MarkVäta
- small-magazine availability
- historical groundwater drought
- historical surface-water drought
- large-groundwater magazine/capacity information
- explicit legal-status warning

This is intentionally an evidence card, not a recommendation.

## Lazy/static architecture

Field values are municipality-lazy sidecars:

`data/akervatten/<municipality>.json`

Regional static layers:

- `data/akervatten/groundwater_history.geojson`
- `data/akervatten/surfacewater_history.geojson`
- `data/akervatten/large_groundwater.geojson`

The builder simplifies web geometry for rendering but does not alter source classifications or scores.

## Protected base

The builder refuses a base without both:

- `AKERNORM_WEB_UI_V1`
- `AKERFRO_ERTOR_WEB_UI_V0A`

Outside of:

- `index.html`
- `data/akervatten/*`
- `assets/akervatten_v0a.css`
- `assets/akervatten_v0a.js`

the completed ÅkerFrö dist must remain byte-identical.

## Local worktree

Recommended:

`C:\AkerSync-AkerVattenWeb`

## Build

From that worktree:

```bat
CALL BUILD_AKERVATTEN_WEB_V0A.bat
```

Defaults:

- ÅkerFrö base: `C:\AkerSync-AkerFroWeb\dist`
- water source: `C:\AkerSync-Vatten`
- output: local `dist`

No deployment is performed.

## Visual QA

After PASS inspect locally:

- existing ÅkerScore / ÅkerVärde / ÅkerDrift
- ÅkerMinne / ÅkerNorm
- ÅkerFrö
- all six ÅkerVatten sublayers
- field drawer
- SGU-HYPE regional boundaries
- S-HYPE regional boundaries
- large-groundwater subareas and capacity labels
- mobile controls

Do not deploy before local visual QA.
