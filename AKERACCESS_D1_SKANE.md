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

## Result — 2026-10-01

D1 completed successfully on the frozen D0 feature layer.

Population:
- full Skåne eligible fields: 67,073
- holdout scope (Skåne excluding Sjöbo): 62,749
- holdout clean CONSERVART positives: 846 (2023–2025), 1,437 (2020–2025), 2,513 (2015–2025)

Matching quality was strong. For the primary 2023–2025 strict-never-pea test,
all 8,460 control matches stayed inside the primary 7.5 km caliper. Median
match distance was 905 m and median control/positive area ratio was 0.989.

### Primary replication: PASS

Primary endpoint:
`no_drivable_50m = nearest_drivable_osm_m > 50 m`

Holdout, 2023–2025, strict-never-pea controls:

- conservärt: 8.51%
- matched controls: 12.17%
- paired difference: -3.66 percentage points
- bootstrap 95% CI: -5.53 to -1.74 pp

This replicates the Sjöbo C3c direction out of sample. Historical conservärt
fields are about 30% less likely (relative prevalence ~0.70x) to lack a mapped
drivable OSM way within 50 m than nearby, current-area-matched controls.

The effect is stable across history windows:
- 2020–2025: 8.4% vs 11.9%, -3.5 pp
- 2015–2025: 9.4% vs 12.2%, -2.8 pp

### Statlig/kommunal roadkeeper proximity: strong secondary signal

The D0 straight-line distance to nearest NVDB Väghållare geometry with
`Väghållartyp in {statlig, kommunal}` also shows a stable positive selection
signal in the holdout.

2023–2025 strict-never-pea:
- within 50 m: 54.5% vs 47.6%, +6.9 pp, bootstrap 95% CI +3.7 to +10.0
- within 100 m: 58.0% vs 52.6%, +5.4 pp, CI +2.3 to +8.6
- within 250 m: 70.7% vs 66.5%, +4.1 pp, CI +1.3 to +7.0

The same direction remains for 2020–2025 and 2015–2025.

Interpretation: this is useful as a **ranking proxy** for logistics/access. It is
not claimed to be a legal `allmän väg` classification and the analysis does
not establish causality.

### Functional road class: Sjöbo signal did not replicate

The Sjöbo post-hoc `FunktionellVägklass in {4,7}` signal does not replicate.
In the 2023–2025 holdout it reverses direction:
- 35.9% conservärt vs 39.1% controls, -3.2 pp, CI -6.3 to -0.1

Natural functional-class groups (0–3, 4–5, 6–8, 9) show no meaningful stable
difference.

Decision: functional road class should not be promoted into the pea-access
ranking based on current evidence. This is a useful falsification of the
Sjöbo-only result.

### D1 decision

Validated road-access features for the next ÅkerFrö / ÅkerKombinatorik stage:

1. `nearest_drivable_osm_m`, with `>50 m` as a validated negative screening
   indicator.
2. `nearest_statlig_kommunal_nvdb_m` as a continuous logistics-ranking proxy;
   50/100/250 m bands are useful descriptive thresholds.

Do not freeze:
- a hard product FAIL at 50 m,
- functional road class,
- a 4.5 m road-width rule,
- legal "allmän väg" semantics from roadkeeper alone.

The evidence supports ranking before hard classification.
