# ÅkerAccess D1 — Skåne conservärt road-feature replication

D1 is the out-of-sample replication stage after the Sjöbo C3/C3b/C3c pilot.

## Primary replication

Because Sjöbo generated the road-access hypotheses, the primary replication
scope is **Skåne excluding Sjöbo**.

Primary window: 2023–2025.

Primary controls: current eligible fields with **no clean CONSERVART observation
anywhere in 2015–2025** (`strict_never_pea`).

Primary endpoint frozen before inspecting the D1 result:

> Historical conservärt fields have a lower prevalence of
> `nearest_drivable_osm_m > 50 m` than spatial/current-area matched controls.

Ten controls are selected per positive using the same basic C3b design:
7.5 km primary radius, 15 km fallback, current-area ratio 0.5–2.0, with ranking
by geographic distance plus log-area mismatch penalty.

Controls can be reused. Bootstrap inference resamples positive matched sets.

## Secondary/descriptive road features

D1 also reports:

- statlig/kommunal roadkeeper geometry within 50/100/250 m,
- raw NVDB functional road classes 0–9,
- natural broad functional-class groups 0–3, 4–5, 6–8, 9,
- the Sjöbo-generated `4 OR 7` indicator, labelled explicitly post-hoc,
- roadkeeper type,
- road width >=4.5 m,
- bearing/BK1,
- nearest-road distances and connected last-mile.

Full-Skåne results are reported descriptively in addition to the true holdout.

## Important guardrails

- Historical non-use is positive-unlabeled, not a true negative.
- D1 validates road features; no ÅkerAccess score is fitted.
- `statlig/kommunal` is a roadkeeper proxy, not claimed to be identical to the
  legal term `allmän väg`.
- The 4/7 combination is not an official NVDB category.

## Run

`CALL RUN_AKERACCESS_D1_SKANE.bat`

No API calls are made in D1; it uses the frozen local D0 Parquet plus ÅkerMinne.

Main outputs:

- `work/akeraccess_v0a/skane_d1/skane_d1_neartwin_summary.csv`
- `work/akeraccess_v0a/skane_d1/skane_d1_matches.parquet`
- `work/akeraccess_v0a/skane_d1/skane_d1_positive_counts_by_municipality.csv`
- `work/akeraccess_v0a/skane_d1/skane_d1_report.json`
