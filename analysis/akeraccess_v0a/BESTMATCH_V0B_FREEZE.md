# ÅkerFrö × ÅkerAccess BestMatch v0b — formal freeze

## Selected product

BestMatch v0b freezes the **balanced** whole-Skåne screening policy on top of
the already-frozen ÅkerFrö C10 and ÅkerAccess v0a inputs.

Candidate universe:

- A_STRONG_CANDIDATE
- B_PHYSICAL_CANDIDATE
- 15,967 fields total
- A is a hard tier before B

Within each class:

[
BestMatch_{v0b}
=
0.50,ÄrtMatch
+
0.25,AreaLogistik_{väg}
+
0.25,ÅkerAccess_{v0a}
]

The weighted score does **not** allow a C/D field into the A/B universe.

## Road-based AreaLogistik

The frozen C10 AreaFit component is retained.

The Bjuv proximity component uses D4 approximate OSM road-network distance
where available. The same frozen C10 Bjuv-proximity scoring curve is evaluated
on road distance.

Current A/B route coverage:

- routed with D4: 12,075 / 15,967 = 75.62%
- explicit frozen-C10 straight-line fallback: 3,892 fields

The fallback is a known product limitation and is preserved explicitly rather
than silently dropping fields.

D4 is not certified truck navigation. It respects OSM one-way tags but does
not include turn restrictions, dynamic closures, traffic, or complete
vehicle-specific weight/height constraints.

## Selected local road-access component

The local road component is exactly frozen **ÅkerAccess v0a**.

The freeze builder verifies field-by-field numerical equality between D5
`road_access_score` and frozen `akeraccess_score_v0a`.

## Diagnostics

Historical clean CONSERVART 2015–2025 is used only as a diagnostic label; the
50/25/25 policy was not fitted to that label.

Frozen balanced-policy historical-positive hits:

- top 200: 10
- top 500: 26
- top 800: 37
- top 1000: 49
- top 2000: 88
- top 5000: 201

Top 800 contains about 8,491 ha.

## Explicitly outside the freeze

- ÅkerKombinatorik / eight-year portfolio grouping
- hard customer-specific truck clearance gates
- legal right-of-way / ownership
- verified entrance width / turning radius
- live closures / traffic routing
- NVDB Slitlager
- D5 match-first and logistics-forward as product defaults

The whole-Skåne map remains a presentation/QA layer. The frozen product is the
canonical ranked field table.

## Run

    FREEZE_AKERFRO_AKERACCESS_BESTMATCH_V0B.bat

Canonical product:

    data/derived/akerfro_akeraccess_bestmatch_v0b/bestmatch_v0b_fields.parquet

Freeze manifest:

    work/akeraccess_v0a/bestmatch_v0b_freeze/bestmatch_v0b_freeze_manifest.json

Later verification:

    VERIFY_AKERFRO_AKERACCESS_BESTMATCH_V0B_FREEZE.bat

After PASS, BestMatch v0b is read-only. Portfolio optimization belongs
downstream in ÅkerKombinatorik.
