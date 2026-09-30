# ÅkerAccess — STOPPUNKT C0 road-network connectivity

Motivation: a crop-sourcing shortlist should not proactively recommend a field
merely because an OSM line touches the field. The candidate must also connect
through the mapped drivable OSM network to an ordinary road.

C0 therefore separates:

- `CONNECTED_TO_ROAD_NETWORK`
- `LOCAL_OSM_COMPONENT_ONLY`
- `NO_ENTRY_CANDIDATE`

The last two map to `HOLD_MANUAL_CHECK`, not FAIL. Absence of mapped access is
not proof that physical access does not exist.

Ordinary-road anchors in C0 are:
`road, unclassified, residential, living_street, tertiary, secondary, primary`.

Tracks and service roads are allowed as last-mile connectors but are not by
themselves road anchors.

For ÅkerFrö/Apetit screening, C0 introduces a conservative **proactive gate**:
only fields with at least one entry candidate connected to an ordinary-road
anchor pass the network screen. Width, height, bearing capacity and other
vehicle constraints are later ÅkerAccess stages, not part of C0.
