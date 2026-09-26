# ÅkerFrö – konservärt web MVP v0a

## Purpose

Add the frozen ÅkerFrö konservärt 2026 screening product to the latest full ÅkerPass web application.

The web base is **ÅkerNorm**, not the older preview deployment and not the diverged ÅkerFrö analysis branch.

## Repository lineage

Web branch:

`feature/akerfro-web-v0a`

created from:

`feature/akernorm-product-v1a`

The frozen ÅkerFrö data are read from the separate analysis worktree:

`C:\AkerSync-AkerFro`

Primary frozen product:

`data\derived\akerfro_ertor_v0a\artkandidat_v0a_operational_fields.parquet`

The formal operational MVP freeze must PASS before web build.

## Base preservation

ÅkerFrö web does not recalculate ÅkerNorm or ÅkerFrö.

The builder starts from an already built ÅkerNorm `dist` and protects the base byte-for-byte outside:

- `index.html` – receives small hooks only;
- `data/akerfro/*` – new municipality-lazy sidecars and Top 1000;
- `assets/akerfro_v0a.css`;
- `assets/akerfro_v0a.js`.

Existing ÅkerScore, ÅkerVärde, ÅkerDrift, ÅkerMinne and ÅkerNorm payload files are not rewritten.

## Web product

### Map layer

New layer button:

**ÅkerFrö**

Color classes:

- A · Stark kandidat
- B · Fysisk kandidat
- C · Rotationsvarning
- D · Ej prioriterad

Default display shows A+B.

### Filters

- A/B/C/D checkboxes
- Bjuv distance: all / <60 / <40 / <20 km
- area: all / >=2 / >=5 / 5–12 ha
- historical conservärt 2015–2025 outline

### Field panel

Shows:

- A/B/C/D class
- operational priority rank
- frozen ÄrtMatch
- rotation status
- 2025 predecessor
- predecessor historical signal/enrichment
- field area and AreaFit
- straight-line distance to Bjuv and BjuvProximity
- AreaLogistik
- most recent observed conservärt / other pea / faba history
- historical conservärt flag

The panel explicitly states that this is screening, not a yield forecast, cultivation guarantee or contract assessment.

### Top 1000

A global Top 1000 list is built from the already frozen `operational_priority_rank`.

Clicking a row changes municipality, loads the corresponding field and zooms to it.

## Web data contract

Municipality sidecars are written under:

`data/akerfro/<municipality>.json`

Index:

`data/akerfro/skane_index.json`

Top list:

`data/akerfro/skane_top1000.json`

The builder refuses to proceed unless frozen anchors match:

- 128,636 fields
- A = 7,847
- B = 14,882
- C = 1,424
- D = 104,483
- HIGH = 20,327
- MEDIUM = 34,060
- LOW = 74,249

## Recommended isolated worktree

Use:

`C:\AkerSync-AkerFroWeb`

Do not develop this UI in `C:\AkerSync-AkerFro` or by switching the main checkout away from its current work.

## Local build

The first argument must point to an already built ÅkerNorm web `dist`.

Example:

```bat
CALL BUILD_AKERFRO_WEB_V0A.bat "C:\AkerSyncRepo\dist"
```

The builder validates that the supplied base really contains:

- `AKERNORM_WEB_UI_V1`
- `data/akernorm/skane_index.json`

so a stale ÅkerMinne-only preview base is rejected.

The build performs:

1. formal frozen ÅkerFrö operational MVP verification;
2. ÅkerFrö web regression tests;
3. municipality sidecar + static UI build;
4. independent static verifier.

No deployment is performed.

## Local inspection

After PASS, start the normal local ÅkerPass server from the web worktree and inspect:

- existing ÅkerScore/ÅkerVärde/ÅkerDrift
- existing ÅkerMinne
- existing ÅkerNorm
- new ÅkerFrö layer
- A/B filters
- C and D toggles
- area/distance filters
- historical conservärt outline
- Top 1000 navigation
- field drawer
- mobile layout

Do not upload to preview before local visual QA is accepted.
