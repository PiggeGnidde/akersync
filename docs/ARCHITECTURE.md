# Arkitektur

## Data lineage

| Featurefamilj | Råkälla | Transform | Huvudoutput |
|---|---|---|---|
| Geometri | Jordbruksverket block/skiften | reprojicering, alignment, simplifiering | geometry_payload.json |
| Jord | SLU DSMS 20 m | zonstatistik + rasteroverlay | soil_payload.json |
| Topografi | LM Markhöjdmodell 1 m | 5 m DEM, gradient/TPI | topography_features_blocks.csv |
| Hydrologi | LM Markhöjdmodell 1 m | 10 m, fill, D∞, SCA, TWI | hydrology_features_blocks.csv |
| Relativ TWI | TWI + block | jordbruksmarksmask, P90/P95 | hydrology_features_final.csv |
| UI | alla derived outputs | JSON injection | dist/index.html |

## Vad som är “source of truth”

- Polygon-ID: Jordbruksverket `blockid`.
- Jord: DSMS-raster.
- Höjd: Lantmäteriet MHM / RH2000.
- Hydrologi: deterministiskt derivat av DEM enligt Whitebox-konfiguration.
- Slut-HTML: artefakt, **inte** source of truth.

## Varför template + injektion?

Den historiska v0.92-HTML:n innehåller tiotals MB inbäddade data.
I detta repo har vi separerat:
- UI-kod = `web/template_v092.html`
- data = `data/derived/*`
- build = `src/07_build_web.py`

Det gör UI-ändringar oberoende av analysen.
