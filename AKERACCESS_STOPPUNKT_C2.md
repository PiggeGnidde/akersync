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
