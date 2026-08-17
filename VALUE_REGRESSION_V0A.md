# ÅkerSync · Value Regression v0a

Första medvetet naiva testet av hur mycket ÅkerSync-lager tillför utöver en enkel geografisk prisbaseline.

## Input

ATL Fastigheter CSV från det lokala Tampermonkey-scriptet v0.3. ATL-filen är privat/lokal input och ska **inte** committas. `.gitignore` blockerar `ATL_AkerSync_*.csv`.

Befintliga lokala ÅkerSync-inputs läses via `config/local_paths.json`:

- Jordbruksverkets block/skifte 2025
- jord-ZIP (lera/sand/silt/organiskt)
- Whitebox hydrologi-workdir med TWI, slope, DEM och SCA

## Rent regressionsurval v0a

Efter deduplicering på fastighetsbeteckning(ar) + datum + köpeskilling:

- köpeskilling > 0
- exakt 0 ha skog
- objekttyp innehåller `obebyggd`
- åkerandel >= 80 %
- positiv åker- och totalareal
- åkerareal <= totalareal (ingen areal-QA-avvikelse)
- K/T saknas eller ligger inom 0,5–6
- giltigt år och lat/lon

För `ATL_AkerSync_2026-08-17_315_poster_v03.csv` ska detta ge **32 rena case**.

## Baseline

Respons:

`log(köpeskilling / åker-ha)`

Baseline:

`intercept + (år-2024) + log(åker-ha/20) + (lat-55,5) + (lon-13,0)`

Referens för 315-postersfilen:

- R² = 0,708934
- justerat R² = 0,665813
- leave-one-out R² = 0,512813
- LOO median absolute percentage error ≈ 22,11 %

Primärt beslutsmått är **Δ leave-one-out R² relativt baseline på exakt samma complete-case-rader**.

## Spatial enrichment

ATL:s lat/lon används som spatial probe. Ingen fastighetsidentifiering görs.

- jord: punkt + 100 m cirkel (lera/sand/silt)
- TWI: punkt + 100 m cirkel
- topografi: slope/höjd/relief från hydrologi-workraster
- SCA: lokal hydrologivariabel
- geometri: bara om ATL-punkten faktiskt ligger i ett 2025-skifte/block; skifte prioriteras

Detta är avsiktligt ett billigt första experiment, inte en färdig värderingsmodell.

## Körning

Dubbelklicka `RUN_VALUE_REGRESSION_V0A.bat` och välj ATL CSV-filen.

Output hamnar under:

`data/derived/value_regression_v0a/`

Viktigast att skicka tillbaka för granskning:

- `report.txt`
- `model_comparison.csv`
- gärna `point_features.csv` för QA
