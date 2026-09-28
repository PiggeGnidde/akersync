# ÅkerVatten H2 · Product dimensions without composite water score

H2 converts the frozen hydrological evidence into a product-ready data contract without turning it into a single water verdict.

## Product principle

ÅkerPass should **show the cards on the table**.

It should not imply:

- that a hydrogeologically favourable field will receive a permit;
- that a high-capacity mapped aquifer can legally be used by a particular farm;
- that a low-risk historical signal means current water is available;
- that one combined score can substitute for a water-law assessment.

Therefore H2 explicitly prohibits an overall ÅkerVatten score and an overall green/yellow/red permission verdict.

## Six displayed dimensions

H2 exposes:

1. **MarkTorka** — relative structural drought sensitivity of the field.
2. **MarkVäta** — relative structural wetness tendency of the field.
3. **GrundvattenTillgång – små magasin** — relative SGU-based screening of small groundwater magazines.
4. **GrundvattenTorka – historik** — historical relative sensitivity to unusually low groundwater levels.
5. **YtvattenTorka – historik** — historical relative sensitivity to low surface-water flow.
6. **Stora grundvattenmagasin** — SGU source classifications, vertical magazine layers and mapped withdrawal/median-capacity classes.

The first five retain their frozen 0-100 scales and descriptive display bands.

The sixth is deliberately **not** converted to 0-100 in H2.

## Large-groundwater presentation

All field×subarea layers remain inspectable.

For convenience only, H2 may expose:

> Högsta kartlagda kapacitetsklass bland träffade magasinsdelområden

This selects the mapped source class with the highest known lower capacity bound.

It is a compact display summary, not an optimization result or legal verdict.

The UI must keep the warning:

> Sammanfattningen innebär inte tillstånd, hållbart uttag eller garanterad brunnskapacitet.

## Legal status

Every field receives:

`water_legal_status = NOT_ASSESSED`

H2 does not infer a legal status from hydrogeology.

## Future ÅkerKontext · VattenTryck

H2 reserves a separate future context dimension for pressure/competition around the resource.

Potential inputs include:

- existing licensed/known abstractions where open data permits;
- public water-supply demand;
- permanent and seasonal population;
- industrial demand;
- agricultural irrigation demand;
- ecological/environmental constraints;
- permit/vattendom context where it can be represented reliably.

This future dimension must remain separate from hydrogeological capacity and must not itself be presented as a legal decision.

The conceptual decomposition is therefore:

```
physical field sensitivity
+ groundwater/surface-water historical regime
+ mapped groundwater capacity
+ future demand/competition context
+ legal assessment (not performed by ÅkerPass)
```

## Outputs

```
work/akervatten_mvp_v0a/h2_product_dimensions/
  akervatten_h2_field_water_dimensions_skane.parquet
  akervatten_h2_large_groundwater_layers.parquet
  h2_product_schema.json
  h2_product_copy.json
  h2_summary.json
```

No composite water score is written.
