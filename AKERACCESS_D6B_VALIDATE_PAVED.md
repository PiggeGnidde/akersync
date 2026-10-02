# ÅkerAccess D6b — validate paved public-road proximity

D6a resolved the Manhemsvägen QA case:

- OSM nearest mapped drivable road: about 2 m
- NVDB Väghållare: kommunal, Helsingborgs kommun, about 2 m
- NVDB Slitlager: grus, about 2 m
- nearest paved statlig/kommunal road: about 692 m

The old metric was therefore administratively correct but too easy to interpret as road quality.

D6b reuses the frozen D1 near-twin matches and tests whether the new paved-public distance retains the out-of-sample conservärt selection signal.

It also builds a candidate RoadAccess v0b from equal-weight inverse percentiles of nearest drivable OSM road and nearest paved statlig/kommunal NVDB road.

No existing score or web product is overwritten.

Run:

CALL RUN_AKERACCESS_D6B_VALIDATE_PAVED.bat