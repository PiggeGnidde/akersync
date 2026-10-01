# ÅkerAccess D4 — road distance to Bjuv

D4 replaces the display-only straight-line proxy with an approximate road
network distance while preserving frozen C10 unchanged.

## Method

A Skåne OSM routing network is downloaded/cached in a 4×4 tile grid. It
includes ordinary roads plus trunk/motorway and link roads. The 16 cached
queries are merged by OSM node/way ID.

For each field D4 reuses the D0/C1 selected ordinary-road anchor and its mapped
field last-mile. One **reverse Dijkstra from Bjuv** then gives distance from
all connected road nodes to the processor. This avoids thousands of external
routing API calls.

Field road distance is:

    mapped field last-mile
    + ordinary-road network distance to Bjuv
    + Bjuv point-to-network snap

OSM one-way tags and roundabouts are respected. D4 is not certified truck
navigation: turn restrictions, live closures, congestion, vehicle-specific
weight/height restrictions and exact factory-gate movements are not yet
modeled.

## Frozen-boundary rule

C10 AreaLogistik/BjuvProximity remains frozen and read-only. D4 writes a new
downstream field table. No C10 score is silently changed.

## Run

    CALL RUN_AKERACCESS_D4_BJUV_ROUTE.bat

The BAT also rebuilds D3 so the new road distance appears in the popup.
