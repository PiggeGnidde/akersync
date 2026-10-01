# ÅkerFrö × ÅkerAccess D3 — interactive map sanity check

D3 deliberately comes before ÅkerKombinatorik.

It loads the D2 joined field table, restores current field polygons, and builds
one local interactive Leaflet map containing the union of the top 5,000 fields
from:

- frozen C10 baseline,
- Access-first,
- Balanced BestMatch.

The map can switch ranking and top 200/500/800/1000/2000/5000 in the browser.
A checkbox limits the view to A_STRONG_CANDIDATE.

Clicking a field shows:
- A/B class,
- ÄrtMatch,
- AreaLogistik,
- RoadAccess,
- Balanced BestMatch,
- field area,
- nearest drivable OSM distance,
- nearest statlig/kommunal NVDB-roadkeeper distance,
- Bjuv straight-line distance,
- rotation/predecessor state,
- historical conservärt flag.

The HTML embeds the field GeoJSON inline so it can be opened directly from
Windows without a local web server. Leaflet and OSM basemap tiles require an
internet connection.

Run:

    CALL RUN_AKERFRO_AKERACCESS_D3_MAP.bat

Output:

    work/akeraccess_v0a/bestmatch_d3_map/bestmatch_d3_map.html

No product weights are frozen by D3.
