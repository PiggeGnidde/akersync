# ÅkerVatten MVP v0a · STOPPUNKT B FREEZE

**Status: PASS**

Freeze accepted after the deterministic 100-field pilot and B2 NADIA validation.

## Frozen evidence

- 100 deterministic fields across 33 Skåne municipalities.
- Local-status mix: 66 OLD_ROBUST, 30 AVAILABLE_BUT_NOT_OLD_ROBUST, 4 DATA_MISSING.
- SGU small-magasin: 100/100 fields matched.
- SGU-HYPE: 100/100 fields matched, 97 unique areas.
- Five actual SGU-HYPE historical series retrieved.
- SVAR2022 Delavrinningsområden: 100/100 fields matched in EPSG:3006.
- Frozen surface-water key chain: ARO_UUID <-> Vattenwebb Aroid -> Subid.
- ARO_UUID -> Aroid: 100/100.
- Subid mapped: 100/100.
- B2 NADIA validation: PASS.
- Requested SUBIDs 101, 103, 106, 107 and 11 were all present in the official 2025 daily download.
- Daily-series evidence: sheet "S-Hype Tidsserier", 489 detected date rows, 2447 numeric cells.

## Rejected paths discovered during B

- Vattenförekomstavrinningsområden_2022 / VAROID is not the direct S-HYPE linkage geometry.
- A prior crop_code -> Subid 100% match was a false positive caused by attribute leakage.
- Anonymous direct access to the separate realtime S-HYPE delivery is not part of the open-data pipeline.
- Large/GeoJSON WFS requests are not part of the frozen path; the working pilot path uses negotiated WFS GetFeature with default GML and small point windows.
- The Vattenwebb flow-statistics workbook is legacy XLS, not XLSX.

## Guardrails

STOPPUNKT B freezes data access, spatial linkage and identifier semantics only. No MarkTorka, MarkVäta, GrundvattenTillgång, GrundvattenTorka, YtvattenTorka or combined score is frozen.

SGU small-magasin is screening information, not individual well yield. SGU-HYPE and S-HYPE/Vattenwebb are modelled hydrological context. Physical/hydrological screening is not an assessment of legal withdrawal rights.

## Next checkpoint

Proceed to STOPPUNKT C: scale only the proven spatial and identifier linkage to the full 128,636-field Skåne population, quantify coverage/missingness and preserve source provenance. Historical drought feature engineering remains STOPPUNKT D.
