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

## Sjöbo result — 2026-10-01

Current eligible population: 4,324 fields.

The strict block-interior enclave definition was too rare to be a useful Sjöbo
validation endpoint:
- interior skifte: 18 fields
- mapped enclave >15 m: 8 fields
- mapped enclave >50 m: 3 fields

Therefore the strict `mapped_enclave_*` classes are underpowered and should
not be used for scoring.

The broader and operationally more useful signal was distance to any mapped
drivable OSM way.

### No drivable OSM way within 50 m

Spatial/area near-twin comparison:

| history window | conservärt | matched controls | paired difference | bootstrap 95% CI |
| --- | ---: | ---: | ---: | ---: |
| 2023–2025 | 8.9% | 15.9% | -7.0 pp | -13.6 to +0.7 pp |
| 2020–2025 | 9.2% | 14.2% | -5.0 pp | -10.7 to +1.3 pp |
| 2015–2025 | 9.7% | 15.3% | -5.6 pp | -10.2 to -0.7 pp |

The strict-never-pea control definition gives essentially the same result.

This is directionally stable across all three windows. The all-history interval
is separated from zero; the two recent windows have similar effect size but are
underpowered because Sjöbo contains only 56 and 76 positives respectively.

Relative prevalence is about 0.56x, 0.65x and 0.63x across the three windows,
i.e. historical conservärt fields are roughly 35–45% less likely to lack a
mapped drivable OSM way within 50 m than their local area-matched controls.

### Other definitions

`NO_OSM_ENTRY_EVIDENCE` did not show a stable negative signal. This reinforces
that the candidate detector's absence class is an evidence-quality state, not a
physical no-access label.

The 5 m and 15 m nearest-road definitions were also weaker. The 50 m radius is
therefore the most promising negative access indicator from C3c, but it remains
a post-hoc Sjöbo result until replicated.

### Decision

- Treat strict block-interior enclave as too rare for current use.
- Keep `no mapped drivable OSM way within 50 m` as a candidate negative access
  feature for replication.
- Do not freeze 50 m as a product rule yet.
- Replicate on a broader Skåne population using the same spatial/area matched
  design before any ÅkerAccess score or exclusion gate is defined.
