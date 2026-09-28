# ÅkerVatten H1 · Ystad / Löderup focused validation · FREEZE

**Status: PASS**

H1 is a diagnostic validation of H0 and the frozen ÅkerVatten groundwater architecture.

No score is created or modified.

## Focus points

### 1. Ystad · frozen GrundvattenTillgång minimum

Field: `61513794526/9C`

Location: 55.479311, 13.897066

Large-magazine result:

- unique magazine: `B9636A8C-456F-4F7F-B2EC-312403DAB799`
- position: S1 sedimentary bedrock
- aquifer: pore- and fracture aquifer
- rock: claystone, siltstone/mudstone, sandstone
- subarea: `21300330-0D2B-4378-88CB-E8EB586384EC`
- median capacity: <600 l/h
- machine-readable upper bound: 0.1667 l/s
- SGU-HYPE omrade_id: 70038
- S-HYPE Subid: 30

### 2. Ystad · frozen GrundvattenTorka maximum

Field: `61453869647/22B`

Location: 55.430847, 14.010638

Large-magazine result:

- unique magazine: `88C23EC6-5407-41AC-991F-7C86F6E1AAA9`
- position: S1 sedimentary bedrock
- aquifer: pore- and fracture aquifer
- rock: limestone
- subarea: `0AB1E372-0E9F-4046-8789-A0EF08D5354C`
- median capacity: 60,000-200,000 l/h
- equivalent: 16.67-55.56 l/s
- SGU-HYPE omrade_id: 72037
- S-HYPE Subid: 25

### 3. Löderups Växt public address reference

Address reference: Norra Strandbadsvägen 134, Löderup.

This point is an address reference only; it is not a farm-boundary or ownership assertion.

Large-magazine result:

- same unique large-magazine ID as Ystad GrundvattenTorka maximum:
  `88C23EC6-5407-41AC-991F-7C86F6E1AAA9`
- same magazine subarea:
  `0AB1E372-0E9F-4046-8789-A0EF08D5354C`
- position: S1 sedimentary bedrock
- rock: limestone
- median capacity: 60,000-200,000 l/h = 16.67-55.56 l/s
- SGU-HYPE omrade_id: 73036
- S-HYPE Subid: 11

## Pairwise result

Ystad GrundvattenTillgång MIN vs Ystad GrundvattenTorka MAX:

- distance: 8.98 km
- same SGU-HYPE unit: NO
- same SVAR ARO: NO
- same S-HYPE Subid: NO
- same large-magazine set: NO

Ystad GrundvattenTillgång MIN vs Löderup reference:

- distance: 16.21 km
- same SGU-HYPE unit: NO
- same SVAR ARO: NO
- same S-HYPE Subid: NO
- same large-magazine set: NO

Ystad GrundvattenTorka MAX vs Löderup reference:

- distance: 7.34 km
- same SGU-HYPE unit: NO
- same SVAR ARO: NO
- same S-HYPE Subid: NO
- same large-magazine set: YES

## Interpretation frozen from H1

The Ystad municipality is hydrogeologically heterogeneous at field scale.

A high-capacity regional sedimentary groundwater magazine can extend beneath multiple local SGU-HYPE groundwater units and multiple surface-water catchments.

Therefore the following are distinct information dimensions and must not be collapsed without a separate modelling checkpoint:

1. small-magazine/local groundwater availability;
2. historical groundwater-drought sensitivity;
3. large-magazine mapped withdrawal/median-capacity class.

The apparent conflict between a low small-magazine field in Ystad and documented strong irrigation opportunity farther east is therefore resolved by the source data: the compared locations are in different large groundwater magazines, while the Löderup reference lies in the same high-capacity limestone magazine/subarea as the second Ystad focus field.

## Guardrail

Hydrogeological screening != legal water-withdrawal right.

H1 validates hydrogeological differentiation only.
