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
