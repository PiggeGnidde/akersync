# ÅkerFrö × ÅkerAccess D6c — paved-road BestMatch

D6b showed that replacing the administrative roadkeeper distance with distance
to a **paved statlig/kommunal road** preserves the out-of-sample historical
conservärt signal almost unchanged at 50/100/250 m.

D6c therefore rebuilds the candidate BestMatch rankings with:

- ÄrtMatch unchanged,
- road-based AreaLogistik to Bjuv unchanged,
- local Väglogistik changed from old public-roadkeeper proximity to the D6b
  paved-public proximity score.

The same three transparent policies are retained:
- match-first 60/25/15
- balanced 50/25/25
- logistics-forward 45/30/25

D6c is still candidate-only and not frozen.

Run:

CALL RUN_AKERFRO_AKERACCESS_D6C.bat

The BAT also rebuilds the whole-Skåne web preview.
