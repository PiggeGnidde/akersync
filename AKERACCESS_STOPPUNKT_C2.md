# ÅkerAccess — STOPPUNKT C2 NVDB coverage at the C1 road anchor

C2 uses the exact NVDB Open API v1.2 schemas verified from live one-row probes.

Expected local raw files under:

`data/raw/akeraccess_nvdb_sjobo_c2/`

- `Vägbredd_v12_sjobo.json`
- `Bärighet_v12_sjobo.json`
- `FunktionellVägklass_v12_sjobo.json`
- `Höjdhinder_upp_till_45_dm_v12_sjobo.json`
- `Väghållare_v12_sjobo.json`
- `Vägtrafiknät_v12_sjobo.json`

The raw directory is ignored by Git.

## Match definition

For each of the 2,993 C1-connected eligible fields, C2 reconstructs the SWEREF99
TM coordinate of the C1 OSM ordinary-road anchor node and finds the nearest NVDB
feature in each dataset.

Coverage is reported at 5, 10, 20, 30 and 50 metres. Attribute distributions are
reported for matches within 20 metres.

This deliberately measures **NVDB coverage of the road reached by the last
mile**, not yet the physical width of the field entrance.

Height-obstacle proximity is warning-only. A nearby obstacle is not yet proven
to lie on the eventual crop-logistics route.

No ÅkerAccess score or Apetit PASS/FAIL is frozen in C2.

## Sjöbo result — 2026-09-30

C2 completed successfully for 2,993 C1-connected eligible fields.

| NVDB product | Raw rows | anchors <=20 m | coverage |
| --- | ---: | ---: | ---: |
| Vägbredd | 14,958 | 2,975 | 99.4% |
| Bärighet | 3,322 | 1,825 | 61.0% |
| FunktionellVägklass | 14,362 | 2,977 | 99.5% |
| Väghållare | 15,040 | 2,977 | 99.5% |
| Vägtrafiknät | 15,535 | 2,977 | 99.5% |

Vägbredd among the 2,975 <=20 m matches had p10/p50/p90 = 3.0/4.0/6.0 m.
1,541 (51.8%) were below 4.5 m. This is **road-width information**, not an
Apetit clearance verdict and not the physical width of the field entrance.

Bärighet among the 1,825 <=20 m matches:
- BK 1: 1,304
- BK 4 - Särskilda villkor: 402
- BK 4: 86
- BK 2: 31
- BK 3: 2

Väghållartyp among the 2,977 <=20 m matches:
- statlig: 1,491
- enskild: 1,455
- kommunal: 31

All 2,977 matched Vägtrafiknät objects were `bilnät`.

The Sjöbo bbox contained five registered `Höjdhinder_upp_till_45_dm` objects.
None were within 100 m of a C1 anchor; two anchors had an obstacle within 500 m.
This remains proximity-only evidence, not route-level evidence.

### Interpretation

C2 answers the coverage question positively: NVDB fills nearly all of the OSM
ordinary-road anchors with road width, functional road class, road keeper and
road-network type. Bearing-class coverage is materially lower (61%), so absence
of a bearing-class object must remain `unknown`, not be interpreted as poor
bearing capacity.

C2 therefore supports an ÅkerAccess architecture where OSM supplies candidate
field entrances and last-mile geometry, while NVDB supplies attributes of the
road reached by that last mile.

No combined score is frozen.

### Explicit next validation

Before selecting score thresholds, validate these access variables against
historical conserved-pea fields, prioritising recent years. Compare pea fields
with the full eligible-field population for at least:

- C1 last-mile distance to ordinary OSM road;
- whether the reached NVDB road is statlig, kommunal or enskild;
- NVDB road width;
- functional road class;
- bearing class where observed;
- missing/no-entry-candidate status.

Do not treat missing NVDB bearing class as a failure. Keep an explicit
`unknown` category.

