# ÅkerPrestation fas 0 – overlay + Skuruppilot

Detta steg börjar först efter godkänd STOPPUNKT A.

## Scope

- Exakt polygonoverlay i EPSG:3006 mellan 2025 års referensskiften och verifierad jordbruksklass 1–10.
- Exakt polygonoverlay mot Jordbruksverkets verifierade SKO-cache.
- Råa komponentareor och `coverage_raw` bevaras; överlapp normaliseras inte bort.
- Ogiltiga geometrier repareras deterministiskt på arbetskopior och flaggas.
- Skurup (1264, 2 944 referensskiften) körs först.
- Om Skurup saknar någon integrationstestkategori väljs ett litet verkligt kompletterande subset från andra skånska kommuner. Det blir inte del av Skurups statiska huvudtabell.
- Ingen Skåneexpansion, webb, satellit, normskörd eller ÅkerPrestation-score ingår.

## Progress

Pilotrunnern skriver live-status var 250:e Skurupskifte för varje lager. Konfigurationen för en senare Skånekörning anger minst kommunvis status och var 5 000:e skifte.

Exempel:

```text
[Skurup][soil_class] 250/2,944 fields (8.5%)
[Skurup][soil_class] 500/2,944 fields (17.0%)
...
[Skurup][sko] 2,944/2,944 fields (100.0%)
```

## Checkpoints

Separata validerade checkpoints skrivs för:

```text
data/derived/akerprestation_phase0/checkpoints/Skurup/soil_class/
data/derived/akerprestation_phase0/checkpoints/Skurup/sko/
```

`--resume` återanvänder endast checkpoints vars schema-, käll-, fält- och kodhash fortfarande stämmer. Ofullständiga `.tmp`-filer räknas inte som checkpoints. Runnern gör efter första pilotkörningen en andra `--resume --resume-probe` och kräver att båda lagren återanvänds.

## Outputs

```text
data/derived/akerprestation_phase0/pilot_skurup/
  field_static_context.parquet
  field_soil_class_components.parquet
  field_sko_components.parquet
  phase0_pilot_qa.json
  phase0_pilot_qa.md
  akerminne_context_join_qa.json
  manual_checklist.json
  problem_fields.geojson
  unverified_class_codes.csv
  supplemental_real_cases.parquet        (endast vid behov)
  supplemental_real_cases.geojson        (endast vid behov)

data/derived/akerprestation_phase0/manifests/run_manifest.json
```

## ÅkerMinne-regression

Piloten söker registrerade Git-worktrees efter den redan byggda frysta ÅkerMinne-Skåneartefakten. Den kräver att Skurups 2 944 referens-ID matchar 1:1, att varje ID har 11 årsrader och att den frysta artefaktens SHA-256 är oförändrad under pilotkörningen. Ingen ÅkerMinne-fil skrivs av fas 0.

## STOPPUNKT B

`RUN_AKERPRESTATION_PHASE0_PILOT_SKURUP.bat` stoppar efter pilot, resume-test och verifiering. Ingen Skånekörning eller webb körs automatiskt.
