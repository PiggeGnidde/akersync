# DATA FREEZE v1 — Skåne 2025

Status: **GRÖN för ÅkerSync MVP-rådata**

Fastställd efter lokal kontroll 2026-08-16.

## Jordbruksverket 2025

- Block: **122 970**
- Skiften: **128 636**
- Skiften vars `blockid` saknas i blocklagret: **0**
- Alla 33 skånska kommuner har block och skiften i input-QA.
- Skifteskommun härleds via `blockid` mot blocklagrets `region_kod`, eftersom `arslager_skifte` saknar `region_kod`.

## Jorddata

Följande DSMS 2025-lager finns och passerar input-QA:

- `dsms2025_ler.tif`
- `dsms2025_sand.tif`
- `dsms2025_silt.tif`
- `dsms2025_organisk_klasser.tif`

## DEM — legacy MHM 2.5 km

Full Skåne-plan från komplett blockgeometri:

- Core farmland + 170 m kontext: **1 951** planrutor
- Core + one-ring: **2 257** planrutor
- Kontinuerlig rektangel: **3 136** planrutor
- Plan-bbox EPSG:3006: **337500, 6130000, 477500, 6270000**
- Plan-bbox WGS84: **12.3567275, 55.2895769, 14.6454731, 56.5737554**
- Befintliga före sista hämtningen: **561** DEM-rutor
- Ytterligare legacy-rutor hittade och hämtade: **1 710 / 1 710**, 0 fel
- Kvarvarande planluckor: **865**

Topologi för de 865 kvarvarande luckorna:

- En enda sammanhängande komponent
- Komponenten når rektangelns ytterkant
- Inga isolerade inlandshål
- Typer: C=8, R=175, M=682

Detaljaudit av de 8 C-rutorna:

- Buffer-only: **8 / 8**
- Med faktisk åkermark: **0 / 8**
- Faktisk åkermark utan DEM: **0.000 ha**

Slutsats: de saknade legacy-rutorna utgör kust/hav/yttre kontextluckor; **ingen faktisk åkermark i den planerade Skåne-MVP:n saknar DEM**.

## Betydelse

Från denna milstolpe behandlas ovanstående rådata som fryst input för ÅkerSync Skåne 2025. Nya fel i geometry/soil/topography/hydrology/final/web/QA ska i första hand reproduceras mot denna fasta input innan extern datainsamling ändras.

Satellitdata ingår inte i Data Freeze v1 och är en senare separat datapipeline.
