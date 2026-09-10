# ÅkerPuls 2026 – C5a third geographic holdout result

C5a selected a third independent 2026 geometry holdout after the C4 post-reveal development step.

Result from local run:

- 19,704 eligible fields remained after four-snapshot footprint and distance guards.
- Selected cell had 3,073 available fields.
- Pilot contains 1,000 fields and 3,143.712 ha.
- WGS84 bbox: `[12.793636, 56.319918, 12.97683, 56.432885]`.
- Minimum geometry distance from B pilot: 58.01 km.
- Minimum geometry distance from C pilot: 116.08 km.

The third holdout is therefore geographically independent of both earlier pilot areas.

Frozen for TEST ONLY before looking at any C5 imagery or results:

- `SPLIT_CANDIDATE`: LCF >= 0.95, edge ratio >= 1.8 in at least 3/4 snapshots, LOO_ALL4.
- `HIGH_CONFIDENCE_SPLIT`: requires `SPLIT_CANDIDATE` and `separation_ratio >= 4.0`.

These are not product-frozen thresholds. No tuning is allowed on C5 before visual holdout review.

Next step C5b: download the same six Sentinel-2 dates and use preprocessing identical to B1/C1. C5c will then apply the frozen test rules without parameter changes.
