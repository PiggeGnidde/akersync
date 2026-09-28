# ÅkerVatten H2 · Product dimensions without composite score · FREEZE

**Status: PASS**

H2 freezes the product architecture for presenting ÅkerVatten evidence without creating an overall water verdict.

The central product principle is:

> ÅkerPass presents the cards on the table; it does not make the legal water-withdrawal decision.

## Frozen product dimensions

ÅkerVatten exposes six separate dimensions:

1. **MarkTorka**
   - relative structural drought sensitivity of the field;
   - frozen 0-100 empirical scale.

2. **MarkVäta**
   - relative structural wetness tendency of the field;
   - frozen 0-100 empirical scale.

3. **GrundvattenTillgång – små magasin**
   - relative SGU-based screening of small groundwater magazines;
   - frozen 0-100 empirical scale.

4. **GrundvattenTorka – historik**
   - historical relative sensitivity to unusually low groundwater levels;
   - frozen 0-100 empirical scale.

5. **YtvattenTorka – historik**
   - historical relative sensitivity to low surface-water flow;
   - frozen 0-100 empirical scale.

6. **Stora grundvattenmagasin**
   - SGU source classifications;
   - magazine identity and vertical J/S/K position;
   - aquifer/rock metadata;
   - mapped subarea withdrawal/median-capacity classes;
   - recharge-area relation where mapped;
   - deliberately **not** converted to a 0-100 score in H2.

## Full-population result

Population: 128,636 fields.

Large-groundwater source coverage:

- direct mapped magazine: 91,662 fields = 71.26%;
- highest mapped capacity class available: 86,234 fields = 67.04%.

Representative field-level highest mapped source classes:

- sedimentary bedrock 20,000-60,000 l/h: 16,336 fields;
- sedimentary bedrock 600-2,000 l/h: 11,156;
- sedimentary bedrock 2,000-6,000 l/h: 10,457;
- sedimentary bedrock 6,000-20,000 l/h: 9,645;
- sedimentary bedrock 60,000-200,000 l/h: 7,985;
- sedimentary bedrock <600 l/h: 7,662;
- >125 l/s: 5,578;
- 1-5 l/s: 5,300;
- <1 l/s: 4,319;
- 5-25 l/s: 3,308;
- 25-125 l/s: 3,197.

All underlying field×subarea source rows remain separately inspectable.

## Frozen no-aggregation policy

H2 explicitly freezes:

- `water_overall_score = NULL / NOT CREATED`;
- `water_overall_verdict = NOT_CREATED`;
- `water_legal_status = NOT_ASSESSED`.

No overall green/yellow/red water verdict is permitted in H2.

The five frozen relative scores may retain descriptive display bands, but those bands are not legal or permit categories.

## Large-groundwater compact summary

For display convenience only, H2 may expose:

> **Högsta kartlagda kapacitetsklass bland träffade magasinsdelområden**

This summary selects the mapped source class with the highest known lower capacity bound among matched subareas.

The source rows remain available for drill-down.

Mandatory warning:

> Sammanfattningen innebär inte tillstånd, hållbart uttag eller garanterad brunnskapacitet.

## Product wording

The water panel intro is frozen conceptually as:

> Flera separata vattenegenskaper visas. De beskriver mark, hydrologi och kartlagda grundvattenmagasin men avgör inte om vattenuttag kan tillåtas.

The legal warning is frozen conceptually as:

> Hydrologiskt underlag är inte en juridisk bedömning. Vattenuttag kan bero på bland annat andra uttag, allmän och enskild vattenförsörjning, miljöpåverkan och gällande tillstånd.

## Future context dimension

H2 reserves, but does not implement:

### ÅkerKontext · VattenTryck

Potential future inputs:

- existing abstractions and competing water uses;
- permanent and seasonal population pressure;
- public water-supply demand;
- industrial demand;
- agricultural irrigation demand;
- ecological/environmental constraints;
- permit/vattendom context where open data allows reliable representation.

This future context dimension must remain separate from hydrogeological capacity and must not itself be presented as a legal decision.

## Frozen conceptual decomposition

```
physical field sensitivity
+ historical hydrological regime
+ mapped groundwater capacity
+ future demand / competition context
+ legal assessment (not performed by ÅkerPass)
```

## QA

H2 full-population run:

- fields: 128,636;
- large-groundwater field×subarea rows: 111,844;
- QA problems: 0;
- overall water score created: NO;
- legal status inferred: NO;
- status: PASS_WITH_REVIEW -> frozen as PASS after review.

## Guardrail

**HYDROLOGICAL / HYDROGEOLOGICAL SCREENING != LEGAL WATER-WITHDRAWAL RIGHT**

ÅkerPass provides evidence and context. It does not decide whether a withdrawal may be permitted.
