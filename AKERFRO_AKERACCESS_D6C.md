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


## Result / decision

**REJECTED as product default after visual QA.**

Field `62263103013|20C` beside Horsarydsvägen showed a decisive false negative:
Street View clearly shows a paved road directly beside the field, while NVDB
Slitlager returned `grus` and therefore produced ~958 m to the nearest
"belagd statlig/kommunal" segment.

The join itself is not the cause: the nearest Väghållare and Slitlager
geometries both match the field at ~2.6 m. The conflicting attribute is the
Slitlagertyp value itself.

Therefore:
- D6c remains an experiment / diagnostic artifact only.
- Slitlager is not used in BestMatch or customer-facing Väglogistik.
- Web screening reverts to D5 RoadAccess and the precise label
  "Till statligt/kommunalt väghållen väg".
- Slitlager may still be useful as an auxiliary evidence flag, never as a hard
  product truth without additional corroboration.
