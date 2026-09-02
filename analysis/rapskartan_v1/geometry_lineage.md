# Rapskartan Skåne V1 – field geometry lineage

- Current 2025 source: `C:\AkerSyncRaw\jv_skane_2025\arslager_skifte_skane_2025.gpkg`
- Current source SHA256: `63f256c012a8f8aab75f22699bc729e60036913429caeb070306f57c19b31706`
- Frozen expected SHA256: `63f256c012a8f8aab75f22699bc729e60036913429caeb070306f57c19b31706`
- Hash status: `PASS`
- Frozen current field identities: `128,636`
- Blind guard: Only geometry/identity columns may be projected for 2025 model input; crop attributes remain behind the blind-label gate.

## Historical official field files

| Year | Files | Expected | Complete | GiB | Inventory SHA256 |
|---:|---:|---:|---|---:|---|
| 2015 | 33 | 33 | True | 0.072 | `8611396e5de820afc7fd2756ee07c77e5226755f5a464cfe36c0e998a6216214` |
| 2016 | 33 | 33 | True | 0.066 | `80f52d0cf7b1055699b94bafd8f2762549e7c79297f4b00e2a8417a381e2856a` |
| 2017 | 33 | 33 | True | 0.068 | `e809d69fca2bc2c577a7a4bfdcb9d0727248463081a39d10bfa844936c7e1f64` |
| 2018 | 33 | 33 | True | 0.073 | `2eaf33382a3700401b4c8e48be93661fb41c7819d1fb8490ae3068440ac54344` |
| 2019 | 33 | 33 | True | 0.074 | `073a51a6def51a0c23509f880d58ed50452ec1f79a9201fcafac19efc2304d6d` |
| 2020 | 33 | 33 | True | 0.078 | `9c42e86d6b4aee2eadab1f3d7609209700ab8eef1292f4d62499b0a74514a50a` |
| 2021 | 33 | 33 | True | 0.078 | `f7673969a086c1c815c5f19ed2e1a424861ae43c99d34465a1253a681d4cb536` |
| 2022 | 33 | 33 | True | 0.079 | `b6ec8c5f64975ee768b107612af3c2f9fec479fa68b1bb28b5a5badabedc6ffe` |
| 2023 | 33 | 33 | True | 0.079 | `6305476729bbf29a0526c782de4762cca6ef038e9e52799d8afe49f7236ad109` |
| 2024 | 33 | 33 | True | 0.081 | `0ffb0cd99406c7437872d345eb4f78736ae06972b1e2e8ae76c2a0aeeeaa7175` |

## Frozen discovery decision

- Complete year-specific geometry years: `[2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024]`
- Classification basis proposal: Use each development year's official field geometry and same-year crop label; use exact 2025 field geometry for blind predictions with crop columns projected out.
- Split/merge: Train/evaluate on the field definition of each target year. ÅkerMinne split/merge mapping is prior-only metadata, never a replacement geometry for satellite labels.
- ÅkerMinne relation: ÅkerMinne 2015-2024 maps historical polygons to fixed 2025 reference fields; those harmonized shapes are not accepted as year-specific satellite training geometry.
- `AMBIGUOUS_UNTIL_S2_PILOT`: exact Sentinel-2 usability per historical year is not inferred from file presence and must be measured without 2025 labels.
