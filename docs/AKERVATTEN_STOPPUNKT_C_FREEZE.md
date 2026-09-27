# ÅkerVatten MVP v0a · STOPPUNKT C FREEZE

**Status: PASS**

STOPPUNKT C is frozen after successful full-Skåne execution.

## Frozen population and coverage

- Current Skåne field population: 128,636 fields.
- SGU small-magasin matched: 128,632 / 128,636.
- SGU-HYPE matched: 128,636 / 128,636.
- SVAR2022 Delavrinningsområden ARO_UUID matched: 128,636 / 128,636.
- S-HYPE/Vattenwebb Subid matched: 128,636 / 128,636.

The four small-magasin misses remain data-coverage observations and do not invalidate STOPPUNKT C.

## Frozen hydrological reuse

- SGU-HYPE: 786 unique omrade_id.
  - fields/unit median: 162
  - P90: 287
  - max: 585
- SVAR2022 ARO_UUID: 502 unique units.
  - fields/unit median: 176
  - P90: 620.9
  - max: 1,620
- S-HYPE Subid: 502 unique units.
  - fields/unit median: 176
  - P90: 620.9
  - max: 1,620

The one-to-one count equality between unique ARO_UUID and unique Subid is consistent with the frozen B semantic linkage contract.

## Performance and resumability

The full 128,636-field local linkage phase completed at approximately 1,606 fields/s at the end of the run.

Field processing was checkpointed every 1,000 fields in 129 deterministic chunks. SVAR2022 source acquisition was checkpointed independently in 56 deterministic tiles.

The pipeline is therefore resumable after interruption without restarting completed source tiles or completed field chunks.

## Frozen output

Primary field linkage:

    work/akervatten_mvp_v0a/c_full_linkage/akervatten_c_spatial_links_skane.parquet

Summary:

    work/akervatten_mvp_v0a/c_full_linkage/c_summary.json

## Guardrails

STOPPUNKT C freezes only full-population spatial linkage and source identifiers.

No historical groundwater drought features, historical surface-water low-flow features, MarkTorka, MarkVäta, GrundvattenTillgång, GrundvattenTorka, YtvattenTorka or combined ÅkerVatten score is frozen here.

Physical/hydrological screening is not an assessment of legal water-withdrawal rights.

## Next checkpoint

Proceed to STOPPUNKT D: historical hydrological feature engineering per unique hydrological unit, not per field.

- SGU-HYPE history should be processed once per unique omrade_id.
- S-HYPE/NADIA history should be processed once per unique Subid.
- The resulting historical-unit features are then joined back to all fields through the C-frozen identifiers.
