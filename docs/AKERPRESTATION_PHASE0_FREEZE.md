# ÅkerPrestation fas 0 — freeze v0a

Freeze tag: `akerprestation-phase0-v0a`

Denna freeze låser ÅkerPrestations statiska datagrund före webbkoppling och före all normskörd-, satellit- eller prestationsmodellering.

## Frozen implementation lineage

- Frozen ÅkerMinne baseline: `akerminne-v1.0`
- ÅkerMinne base commit: `4b53ab24e9822f1c36c6cc31931dba3c1855fead`
- Validated ÅkerPrestation phase 0 Skåne build commit: `92c1e92535ac636e50b522f93c0e675c2b6f63ed`
- Freeze branch: `feature/akerprestation-phase0-freeze-v0a`
- Freeze tag: `akerprestation-phase0-v0a`

Freeze-taggen skapas på en efterföljande metadata-commit som får innehålla endast detta freeze-dokument, freeze-runnern, freeze-verifieraren och dess test. Själva validerade Skåne-builden är därför explicit låst till committen ovan.

## Frozen scope

Fas 0 innehåller endast statisk referenskontext för dagens Jordbruksverket-2025-skiften i Skåne:

- historisk jordbruksklass 1–10,
- råa klasskomponenter och arealandelar,
- dominant jordbruksklass,
- officiellt skördeområde (SKO),
- råa SKO-komponenter och arealandelar,
- dominant SKO,
- QA-flaggor för blandklass, partiell täckning, råa överlapp och SKO-gränser,
- exakt koppling till samma 2025-referensidentitet som fryst ÅkerMinne v1.0.

Fas 0 innehåller **inte**:

- normskörd,
- satellit/NDVI/radar,
- skördeestimering,
- ÅkerPrestation-score,
- ny ÅkerScore-/ÅkerDrift-/ÅkerVärde-logik,
- webbimplementation.

## Frozen inventory

Full Skåne-körning och oberoende återläsning gav PASS:

- Kommuner: **33/33 PASS**
- Referensskiften: **128,636 / 128,636**
- Jordbruksklasser i verkliga komponenter: **1–10**
- Soil component rows: **132,036**
- Okända jordbruksklasskomponenter: **0**
- Helt oklassade skiften: **17,540**
- Partiellt klasstäckta skiften: **22,775**
- Blandklassfält: **18,439**
- `soil coverage_raw > 1`: **148**
- Oklassad unik area: cirka **518,437,399.5 m²**
- SKO-ID i verkliga komponenter: **18**
- SKO component rows: **130,838**
- Helt saknad SKO-täckning: **0**
- Okända/blank SKO-komponenter: **0**
- Råa SKO-gränsfält: **2,195**
- `SKO coverage_raw > 1`: **1,718**
- ÅkerMinne-referensmatch: **128,636 / 128,636**
- Problemkommuner: **0**

Observed SKO domain:

`0731, 1011, 1111, 1112, 1121, 1122, 1123, 1124, 1131, 1211, 1212, 1213, 1214, 1215, 1216, 1221, 1222, 1321`

## Frozen source hashes

- Jordbruksverket 2025 reference fields SHA256: `63f256c012a8f8aab75f22699bc729e60036913429caeb070306f57c19b31706`
- Historical soil-class source cache SHA256: `6f4375a1e0ba1f1abde13ddae70e28b6defa853019e1a3663a9ee6e9903ff4a1`
- SKO source cache SHA256: `04ebf07a2e6b0646af0f65056fe59d198f23965fa12fb896b004e3d8fca02f31`
- Overlay core SHA256: `ee28c510082ee0c87360ad728d84318ddccac32671f869590309d0cbcdd737b9`
- 2025 reference-field ID digest: `3ef3dd23e1a91dd216f1d99497da8de8297fe16d4902ca0dc7dcaa95a366e1a0`

## Soil-class semantics

- The source domain is agricultural class 1–10.
- Classes 5–10 existed before this phase; phase 0 completes the static domain with classes 1–4.
- Exact positive intersections are preserved as raw components.
- Dominant class is derived from exact intersection area.
- No missing class is imputed.
- A present-day field may legitimately be completely or partially outside the historical classification source.
- `coverage_raw > 1` is preserved as QA evidence rather than silently normalized away.
- Source geometries that are repairable are repaired deterministically on analysis copies; raw source data is not rewritten.

The ArcGIS source metadata inspected during discovery did **not** state an exact classification year. The product must therefore not assert a precise year such as 1971 unless a separate authoritative source is added later.

## SKO semantics

- SKO comes from Jordbruksverket's official open WFS source discovered reproducibly.
- SKO identifiers are stored as strings so leading zeros such as `0731` are preserved.
- Exact positive intersections are preserved as raw components.
- Dominant SKO is the largest exact intersection for the field.
- Raw multiple-SKO hits are retained, including microscopic GIS slivers.
- Product/UI layers may later distinguish material SKO splits from raw sliver intersections, but raw phase 0 data must remain unchanged.

## ÅkerMinne integration contract

ÅkerPrestation phase 0 is static context for the same current 2025 field identity used by frozen ÅkerMinne v1.0.

The generated canonical ÅkerMinne municipality history parquet is not retained locally because `data/derived` is Git-ignored. Therefore the full-Skåne phase 0 run verifies identity through the immutable `akerminne-v1.0` freeze contract plus the exact same 2025 reference source/hash. No historical rows are reconstructed or fabricated.

## Passed gates

1. Discovery / STOPPUNKT A — PASS with only the explicit unknown-source-year warning.
2. Skurup exact overlay / STOPPUNKT B — PASS.
3. Real class 1/2/3 integration gate / STOPPUNKT B.1 — PASS.
4. Full Skåne 33-municipality build / STOPPUNKT C — PASS.
5. Independent full-Skåne artifact and ID reconciliation — PASS.

## Canonical generated artifacts

Generated artifacts remain Git-ignored but are integrity-locked through `skane_phase0_manifest.json` hashes:

- `data/derived/akerprestation_phase0/skane/field_static_context.parquet`
- `data/derived/akerprestation_phase0/skane/field_soil_class_components.parquet`
- `data/derived/akerprestation_phase0/skane/field_sko_components.parquet`
- `data/derived/akerprestation_phase0/skane/sko_boundary_fields.parquet`
- `data/derived/akerprestation_phase0/skane/sko_boundary_fields.geojson`
- `data/derived/akerprestation_phase0/qa/skane/qa.json`
- `data/derived/akerprestation_phase0/qa/skane/qa.md`
- `data/derived/akerprestation_phase0/qa/skane/municipality_qa.csv`
- `data/derived/akerprestation_phase0/qa/skane/soil_class_by_municipality.csv`
- `data/derived/akerprestation_phase0/qa/skane/sko_distribution.csv`
- `data/derived/akerprestation_phase0/qa/skane/problem_fields.geojson`
- `data/derived/akerprestation_phase0/manifests/skane_phase0_manifest.json`

## Freeze policy

The tag `akerprestation-phase0-v0a` is immutable.

Any future change to the source hashes, field identity domain, soil-class/SKO overlay semantics, raw-component preservation rules or frozen schemas requires a new version/tag. Web presentation may evolve independently as long as it consumes this frozen phase-0 contract without silently changing its semantics.
