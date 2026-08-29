# ÅkerPrestation fas 0 – full Skånekörning

Detta steg körs endast efter godkända STOPPUNKT B och B.1 samt uttryckligt `GO SKÅNE FAS 0`.

## Scope

- exakt overlay av historisk jordbruksklass 1–10 mot samtliga aktuella skånska 2025-skiften,
- exakt SKO-overlay mot samma referensskiften,
- kommunvis checkpointing separat för jordbruksklass och SKO,
- återstart från validerade checkpoints,
- läns-QA och länsmanifest,
- ingen webb, satellit, normskörd, skördeestimering eller ÅkerPrestation-score.

Fryst ÅkerMinne-bas är `akerminne-v1.0` / `4b53ab24e9822f1c36c6cc31931dba3c1855fead`.

## Körning

```bat
RUN_AKERPRESTATION_PHASE0_SKANE.bat
```

Runnern kräver ren worktree och feature-branchen `feature/akerprestation-foundation-v0a`.

Progress skrivs:
- vid start och PASS/FAIL för varje av 33 kommuner,
- separat för jordbruksklass och SKO,
- var 5 000:e skifte inne i ett lager när kommunen är större än så,
- med ackumulerad länsprogress efter varje kommun.

## Checkpoints

Checkpoints ligger under:

```text
data\derived\akerprestation_phase0\checkpoints\<kommun>\soil_class\
data\derived\akerprestation_phase0\checkpoints\<kommun>\sko\
```

En checkpoint återanvänds endast om schema, kommun, referensår, källhashar och overlaykodens hash matchar samt summary-filen har exakt rätt fält-ID-domän. Skurups redan validerade pilotcheckpoint använder samma kontrakt och kan därför återanvändas.

Vid ett isolerat kommunfel kan kodagenten senare instruera om riktad omkörning, t.ex. `--force-municipality-code 1290 --force-layer soil_class`, utan att bygga om andra godkända kommuner.

## Kommun-QA

Varje kommun måste PASS innan länskörningen går vidare. Hårda fel är bland annat:

- saknad/duplicerad summaryrad för ett 2025-skifte,
- ID-set som inte matchar kommunens aktuella referensskiften,
- okänd jordbruksklasskomponent,
- blank/okänd SKO-komponent,
- helt saknad SKO-täckning,
- oreparerbart geometrifel,
- checkpointmanifest som inte stämmer med artefakterna.

Historiska glapp i jordbruksklasskällan är däremot tillåtna om de redovisas som `MISSING_SOIL_CLASS`/partiell täckning. De får inte imputeras eller normaliseras bort. Rå `coverage_raw > 1` bevaras och rapporteras.

## Länsartefakter

```text
data\derived\akerprestation_phase0\skane\field_static_context.parquet
data\derived\akerprestation_phase0\skane\field_soil_class_components.parquet
data\derived\akerprestation_phase0\skane\field_sko_components.parquet
data\derived\akerprestation_phase0\skane\sko_boundary_fields.parquet
data\derived\akerprestation_phase0\skane\sko_boundary_fields.geojson

data\derived\akerprestation_phase0\qa\skane\qa.md
data\derived\akerprestation_phase0\qa\skane\qa.json
data\derived\akerprestation_phase0\qa\skane\municipality_qa.csv
data\derived\akerprestation_phase0\qa\skane\soil_class_by_municipality.csv
data\derived\akerprestation_phase0\qa\skane\sko_distribution.csv
data\derived\akerprestation_phase0\qa\skane\problem_fields.geojson

data\derived\akerprestation_phase0\manifests\skane_phase0_manifest.json
```

`field_static_context.parquet` ska innehålla exakt en statisk rad per aktuellt 2025-skifte. ÅkerMinnes elva årsrader dupliceras inte.

## ÅkerMinne-avstämning

Den genererade frysta historik-parqueten är inte längre lokalt kvar. Därför verifieras länets referens-ID-domän mot:

1. det immutabla kontraktet i `docs/AKERMINNE_V1_FREEZE.md`,
2. exakt samma Jordbruksverket-2025-källhash som passerade Skuruppiloten,
3. exakt samma källhash som passerade verklig klass 1/2/3-gate,
4. 128 636 unika `blockid|skiftesbeteckning`.

Inga historikrader återskapas eller fabriceras.

## STOPPUNKT C

Efter PASS stannar arbetet. Ingen webbvisning, tagg eller merge sker utan nytt uttryckligt beslut. `GO WEB FAS 0` är separat.
