# ÅkerAccess v0a — formal freeze

## Scope

ÅkerAccess v0a freezes the **generic Skåne road-access screening layer**. It is
deliberately separate from customer-specific ÅkerFrö/BestMatch/Bjuv logic.

Frozen geography/population:

- all 33 Skåne municipalities,
- current 2025 field geometry,
- fields >= 1 ha,
- explicit pasture/slåtteräng excluded,
- **67,073 eligible fields**.

## Frozen product semantics

### ÅkerAccess score v0a

The generic screening score is:

[
ÅkerAccess_{v0a}
=
0.5,P^{-1}(d_{m mapped drivable OSM})
+
0.5,P^{-1}(d_{m statlig/kommunal roadkeeper})
]

where each component is the inverse empirical percentile over the eligible
Skåne population.

Customer-facing labels are frozen as:

- **Till närmaste körbara väg**
- **Till statligt/kommunalt väghållen väg**
- **Estimerad infart**

The score is a ranking/screening score. It is **not** a probability that a
machine or truck can legally/physically reach the field.

### Estimated entrance

The selected entrance is machine-estimated from field geometry and mapped road
geometry. It may be metres off and is not field-verified.

The selected mapped last-mile path is supporting QA/navigation evidence, not
certified truck routing.

Weak or absent map evidence means **CHECK / UNKNOWN**, not physical FAIL.

## Frozen Skåne anchors

D0:

- eligible fields: **67,073**
- mapped entry connected to ordinary OSM road: **46,633**
- no mapped drivable OSM way within 50 m: **11,216**
- <=50 m statlig/kommunal roadkeeper geometry: **27,686**
- <=100 m: **31,058**
- <=250 m: **40,527**

D1 independent replication primary holdout:

- geography: Skåne excluding Sjöbo,
- positive window: clean CONSERVART 2023–2025,
- controls: strict-never-pea spatial/area near-twins,
- endpoint: no mapped drivable OSM way within 50 m,
- historical conservärt: about **8.51%**,
- matched controls: about **12.17%**,
- paired difference: about **−3.66 percentage points**,
- bootstrap 95% CI: about **−5.53 to −1.74 pp**.

This supports the access signal as a screening/ranking dimension. It does not
establish causal yield or prove actual access.

## Explicitly outside v0a

Not frozen into the generic score:

- ÅkerFrö / BestMatch policy,
- Bjuv-specific road distance,
- Apetit-specific clearance rules,
- hard 4.5 m width gate,
- functional-road-class 4-or-7 grouping,
- legal right-of-way / ownership,
- certified truck navigation,
- exact verified field entrance,
- NVDB Slitlager.

### Why Slitlager is excluded

Visual QA around Horsarydsvägen / Manhemsvägen exposed a decisive false
negative: field `62263103013|20C` lies directly beside a visibly paved road in
recent Street View, while NVDB Slitlager reports the nearby segment as
`grus`. The geometry join itself matched at about 2.6 m, so the conflict is in
the attribute value rather than the join.

Slitlager remains useful as auxiliary evidence, but not as product truth in
ÅkerAccess v0a.

## Freeze procedure

Run:

    FREEZE_AKERACCESS_V0A.bat

This:

1. builds the generic frozen product table from D0,
2. validates the frozen D0 population and D1 independent-replication anchors,
3. creates SHA-256 hashes for code/config/core outputs,
4. writes the formal manifest,
5. runs freeze verification.

Frozen product:

    data/derived/akeraccess_v0a/akeraccess_v0a_fields.parquet

Manifest:

    work/akeraccess_v0a/freeze_v0a/akeraccess_v0a_freeze_manifest.json

Verify later with:

    VERIFY_AKERACCESS_V0A_FREEZE.bat

After PASS, ÅkerAccess v0a is read-only. Changes to score semantics, entry
selection, data sources or hard gates require a new version downstream rather
than silent modification.
