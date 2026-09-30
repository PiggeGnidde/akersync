# ÅkerAccess — STOPPUNKT C3c: enclave / no-direct-road test

Motivation: a field can have a short mapped distance to a road yet still lack
direct road frontage because another skifte lies between it and the road.

C3c therefore tests a stricter, geometry-based "enclave" hypothesis using the
already generated C3b spatial/area near-twin matches.

Definitions:

- `no_drivable_within_15m`: nearest mapped drivable OSM way is >15 m from the
  current field polygon.
- `interior_skifte`: <1% of the current field perimeter lies within 2 m of the
  outer boundary of its Jordbruksverket block.
- `mapped_enclave_15m`: interior_skifte AND no drivable OSM way within 15 m.
- `mapped_enclave_50m`: stricter version with 50 m.

These are **mapped-evidence classes**, not proof that a farmer lacks a private
route over neighbouring land.

C3c reuses C3b matching; no new matching or score is fitted.

Run:

`CALL RUN_AKERACCESS_STOPPC3C.bat`
