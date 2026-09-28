# ÅkerVatten H0 · Stora grundvattenmagasin · Skåne inventory

H0 is a source-inventory checkpoint added after ÅkerVatten v0a STOPPUNKT G.

It does **not** change or reopen the five frozen v0a components and does **not** create a new 0–100 score.

## Source

Official SGU product: `Grundvattenmagasin`.

Bulk source:

`https://resource.sgu.se/data/oppnadata/grundvattenmagasin/grundvattenmagasin.zip`

The product is stored in SWEREF99 TM / EPSG:3006 and includes, among other layers:

- `grundvattenmagasin`
- `magasinsdelomraden`
- `tillrinningsomraden`

The product describes especially larger groundwater magazines in eskers/sand-gravel formations and sedimentary bedrock.

Multiple magazines can be vertically stacked at the same surface location. H0 therefore preserves multiple matches rather than collapsing them before inspection.

## H0 field relation

H0 uses the same deterministic field representative point frozen in STOPPUNKT C.

For every current 2025 field it records:

- direct representative-point intersection with mapped groundwater magazine(s);
- magazine name(s);
- magazine position(s), including J1/J2/J3/S1/S2/S3/K1 where present;
- aquifer and rock/geological metadata;
- matching magazine subarea(s);
- SGU withdrawal-opportunity class(es);
- conservative best known withdrawal class based on the highest stated lower bound;
- matching recharge-area relation(s);
- recharge-area type(s).

The representative-point rule is deliberate for H0 inventory. A direct H0 match means that the representative point lies in the mapped polygon; it does not claim that 100% of the field polygon lies within the magazine.

## Withdrawal classes

H0 preserves SGU's source label.

Where possible it also converts class bounds to l/s for machine-readable diagnostics. Older classes reported in l/h are divided by 3600.

Unknown/not-assessed classes remain missing and are never imputed.

No withdrawal class is interpreted as a legal permission or individual-well guarantee.

## Expected outputs

```
work/akervatten_mvp_v0a/h0_large_groundwater/
  h0_direct_magazine_matches.parquet
  h0_subarea_matches.parquet
  h0_recharge_matches.parquet
  akervatten_h0_large_groundwater_fields_skane.parquet
  h0_withdrawal_class_counts.csv
  h0_municipality_summary.csv
  h0_external_validation_10_extremes.csv
  h0_summary.json
```

## Ystad focus

If the ten-field external-validation file exists, H0 prints and exports the large-magazine relation for all ten extreme ÅkerVatten fields.

It additionally lists mapped groundwater-magazine names represented among Ystad fields. This is intended to test the working hypothesis that Stora Herrestad/Fårarp and the Löderup/Kåseberga area may represent different groundwater settings.

## Guardrail

`HYDROGEOLOGICAL SCREENING != LEGAL WATER WITHDRAWAL RIGHT`.

A mapped SGU withdrawal opportunity is not a vattendom, permit, guaranteed well flow, or proof that a new irrigation withdrawal is legally or physically available at a particular field.
