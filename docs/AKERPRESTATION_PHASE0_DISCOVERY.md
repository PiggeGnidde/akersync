# ÅkerPrestation fas 0 – discovery v0a

Detta steg implementerar endast discovery enligt fas-0-specifikationen. Det skapar ingen per-skifte-overlay och ändrar inte fryst ÅkerMinne v1.

## Verifierad bas

- Tagg: `akerminne-v1.0`
- Commit: `4b53ab24e9822f1c36c6cc31931dba3c1855fead`
- Referensår: 2025
- Referensskiften i freeze: 128 636

## Jordbruksklass

Klass 5 är redan implementerad tillsammans med 6–10 i befintlig ÅkerPass/ÅkerScore-linje. Discovery verifierar därför källdomänen 1–10 och behandlar den nya kompletteringen som klass 1–4.

Den tidigare använda källan är Ystads ArcGIS-spegel `Jord- och skogsklassificering Skåne` (lager 32). Discovery läser service-metadata, rå klassdomän, objektantal, geometrier och källtäckning utan att modifiera källan.

## SKO

Discovery använder Jordbruksverkets öppna WFS som reproducerbar vektorkälla. Lagernamnet för skördeområden identifieras från WFS `GetCapabilities` i stället för att hårdkodas. SKO-ID, schema, geometri, ledande nollor och täckning QA-redovisas.

## Output

Under `data/derived/akerprestation_phase0/` skapas endast discoveryartefakter och källcache:

- `discovery/discovery_report.md`
- `discovery/repository_summary.json`
- `discovery/soil_class_schema.json`
- `discovery/sko_schema.json`
- `manifests/discovery_manifest.json`
- `logs/discovery_tests.log`
- `logs/discovery.log`

`data/derived/` är redan Git-ignorerad i repositoryt.

## Stoppunkt

När `RUN_AKERPRESTATION_PHASE0_DISCOVERY.bat` är klar gäller **STOPPUNKT A**. Ingen overlaymotor, Skuruppilot, Skånekörning eller webbimplementation får påbörjas före uttryckligt GO.
