# ÅkerAccess — STOPPUNKT C3b: spatial / area near-twins

C3b addresses the main limitation of C3: historical conservärt fields are
spatially clustered and have a non-random area distribution.

For each positive field, C3b selects 10 nearby current eligible fields with
similar area. Primary caliper:

- centroid distance <= 7.5 km
- control/positive area ratio 0.5–2.0

If too few controls exist, radius is widened to 15 km; further fallback is
recorded explicitly.

Matching ranks candidates by geographic distance plus a penalty for log-area
mismatch. Controls may be reused across positive fields. Bootstrap confidence
intervals resample the positive matched sets, so reuse is not treated as
independent evidence.

Validation windows:

- 2023–2025
- 2020–2025
- 2015–2025

Two control definitions are reported:

- `window_unlabeled`
- `strict_never_pea` (no clean CONSERVART anywhere 2015–2025)

Primary outcomes retain the C3 access metrics. The apparent C3
`FunktionellVägklass in {4,7}` and `Väghållare=kommunal` effects are included
but explicitly labelled post-hoc/exploratory.

Because Sjöbo contains few conservärt positives, C3b is a diagnostic. A
promising effect should next be tested on all Skåne before score design.

Run:

`CALL RUN_AKERACCESS_STOPPC3B.bat`

## Sjöbo result — 2026-09-30

C3b completed successfully. Current eligible population: 4,324 fields.

Positive counts:
- 2023–2025: 56
- 2020–2025: 76
- 2015–2025: 134

Matching quality was strong in all windows. Every matched set stayed inside the
primary caliper. Median control distance was about 0.83–0.88 km and median
control/positive area ratio about 0.98–0.99.

### Main result

The short-last-mile hypothesis does not survive as a useful positive rule.

For 2023–2025, recent conservärt fields were actually less often within 100 m
than their spatial/area twins: 41.1% vs 57.0%, paired difference -15.9 pp
(bootstrap 95% CI approximately -28.4 to -3.0 pp). For 2020–2025 the effect was
smaller and uncertain. Across all 2015–2025 positives the difference vanished:
56.0% vs 54.9%, and connected-field last-mile means were 122.1 m vs 123.3 m.

Therefore C3b gives no basis for a hard 50/100/250 m ÅkerAccess gate.

Road width >=4.5 m also showed essentially no matched signal:
- 2023–2025: 51.2% vs 51.4%
- 2020–2025: 49.1% vs 50.1%
- 2015–2025: 51.4% vs 50.1%

Enskild road keeper and BK1 bearing class likewise showed no stable matched
difference.

### Exploratory functional-road-class signal

The post-hoc indicator `FunktionellVägklass in {4,7}` remained enriched after
spatial and area matching:

- 2023–2025: 46.3% vs 28.8%, +14.0 pp, bootstrap 95% CI +2.8 to +24.8 pp
- 2020–2025: 43.9% vs 27.3%, +13.4 pp, bootstrap 95% CI +4.3 to +22.6 pp
- 2015–2025: 33.3% vs 23.9%, +7.5 pp, bootstrap 95% CI +0.6 to +14.5 pp

The signal also remains under the stricter never-pea control definition.

This is the only access-related signal in C3b that is both directionally stable
and bootstrap-separated from zero across all three history windows. It remains
post-hoc and Sjöbo-specific and must be replicated before any score design.

Municipal road keeper also appears enriched in the 2020–2025 window, but counts
are small and the all-history interval overlaps zero; treat as exploratory only.

### Decision

- Do not freeze a distance threshold.
- Do not freeze a 4.5 m road-width rule.
- Preserve no-OSM-access as CHECK/unknown rather than FAIL.
- Keep functional road class as a candidate variable for replication.
- Next validation should scale to a broader Skåne population before any
  ÅkerAccess scoring policy is designed.
