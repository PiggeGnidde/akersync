# ÅkerFrö × ÅkerAccess D5 — road-logistics BestMatch

D5 is the candidate-ranking stage immediately before the full ÅkerPass web-map
integration.

It keeps frozen ÅkerFrö C10 read-only and replaces only the downstream Bjuv
logistics proxy:

- old C10: straight-line distance to Bjuv,
- D5: D4 mapped OSM road-network distance to Bjuv where available.

The frozen C10 AreaFit curve and the frozen 55/45 AreaFit/BjuvProximity policy
are reused. The same BjuvProximity piecewise curve is evaluated on road
distance instead of straight-line distance.

Fields lacking a valid D4 route remain in the screening universe with an
explicit frozen-C10 straight-line fallback.

## Predeclared policy candidates

D5 compares three transparent policies inside A/B class:

- Match-first: 60% ÄrtMatch + 25% road-based AreaLogistik + 15% local Väglogistik
- Balanced: 50% + 25% + 25%
- Logistics-forward: 45% + 30% + 25%

They are not label-fitted and are not frozen.

Diagnostics at top 200/500/800/1000/2000/5000 compare historical positive
capture, mean ÄrtMatch, road-based logistics, local road access, Bjuv road
distance, public-road proximity and total hectares.

## Workflow decision

After D5:

1. inspect D5 rankings in the local map,
2. integrate the chosen D5 screening layer into the real ÅkerPass web map with
   a whole-Skåne ÅkerFrö screening view,
3. only then freeze a BestMatch candidate,
4. only after that start ÅkerKombinatorik.

Run:

    CALL RUN_AKERFRO_AKERACCESS_D5.bat
