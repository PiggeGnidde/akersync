# ÅkerSync – reproducible build v1

## ÅkerDrift route pilot

En begränsad 200-skiftesjämförelse mellan ÅkerDrift Fast och simulerade
parallella kördrag finns i [AKERDRIFT_ROUTE_PILOT_V1A.md](AKERDRIFT_ROUTE_PILOT_V1A.md).
RC1.1 delar urvalet i 150 normalfält och 50 stressfält; fält utan en hel
inre körlinje efter vändteg hålls utanför huvudkorrelationen. Den körs separat
med `RUN_AKERDRIFT_ROUTE_PILOT.bat` och ändrar inte den publika kartan.

Den frysta Fast V2 RC0-kandidaten och leave-one-municipality-out-resultaten
finns i [AKERDRIFT_FAST_V2_ROUTE_CALIBRATION.md](AKERDRIFT_FAST_V2_ROUTE_CALIBRATION.md).
Kör `CALIBRATE_AKERDRIFT_FAST_V2.bat` för att återskapa kalibreringen från de
tre 200-skiftespiloterna. Kandidaten ändrar inte Fast V1 eller webbdata.

Målet är att kunna återskapa **ÅkerSync v0.92 från rådata** utan att vara
beroende av historiska v0.4/v0.7/v0.9-filer.

## ÅkerPass MVP UI V1

Den separata integrationsgrenen `feature/akerpass-ui-v1` bygger ÅkerPass för
alla 33 skånska kommuner med fryst ÅkerScore, publikt ÅkerVärde-index,
ÅkerDrift Fast V1, mobil drawer/bottom sheet och GPS-följning.

Kör `BUILD_AKERPASS_WEB_V1.bat` och därefter `START_AKERPASS_LOCAL.bat`.
Full metod, inputs, output och QA finns i [AKERPASS_UI_V1.md](AKERPASS_UI_V1.md).

ÅkerDrift körs separat och restart-säkert kommun för kommun med
`RUN_AKERDRIFT_FAST_V1.bat`. Kör sedan billig QA/sensitivitet med
`CHECK_AKERDRIFT_FAST_V1.bat`. Formel, checkpoints och körordning finns i
[AKERDRIFT_FAST_V1.md](AKERDRIFT_FAST_V1.md).

## Första gången

1. Packa upp repot i en enkel arbetsmapp, exempelvis `C:\AkerSyncRepo`.
2. Kör `INSTALL_REQUIREMENTS.bat`.
3. Kör `SETUP_PATHS.bat`.
4. Peka ut fyra rådatakällor:
   - `arslager_block.gpkg`
   - `arslager_skifte.gpkg`
   - `akermarkens-jordarter.zip`
   - DEM-mappen med Markhöjdmodell `.tif`
5. Kör `CHECK_INPUTS.bat`.

## Rebuild från noll

Kör:

`BUILD_ALL.bat`

Pipeline:

    rådata
      │
      ├─ 01_geometry.py
      ├─ 02_soil.py
      ├─ 03_topography.py
      ├─ 04_hydrology.py
      ├─ 05_farmland_twi.py
      ├─ 06_finalize_hydrology.py
      ├─ 07_build_web.py
      └─ 08_verify.py
            │
            ▼
        dist/index.html

### Steg 1 – geometri
Input: Jordbruksverket block + skiften.

Output:
- `geometry_payload.json`
- `geometry_summary.csv`

Beräknar även skifte↔block alignment.

### Steg 2 – jord
Input: block/skiften + SLU/DSMS ZIP.

Lager:
- ler
- sand
- silt
- organisk klass

Output:
- `soil_payload.json`
- `soil_features_blocks.csv`
- `soil_features_skiften.csv`
- `soil_summary.csv`

### Steg 3 – topografi
Input: Lantmäteriet DEM + block.

Känt fungerande topografiscript från v0.8c.
1 m källa → 5 m arbetsgrid.

Output:
- `topography_features_blocks.csv`
- `topography_features_blocks.gpkg`
- QA

### Steg 4 – hydrologi
Input: hela DEM-mosaiken + block.

Känt fungerande Whitebox-pipeline från v0.9c:
- 10 m mosaik
- FillDepressions + fix_flats
- slope
- D∞ Specific Contributing Area
- TWI

Whitebox-mellanraster ligger utanför OneDrive i den lokala arbetsmapp som
står i `config/local_paths.json`.

Output:
- `hydrology_features_blocks.csv`
- hydrology QA
- `twi_10m.tif` i Whitebox-workdir

### Steg 5 – åkermarks-TWI
Maskar TWI mot samtliga jordbruksblock och räknar P90/P95 bara på åkermark.
Ger även andelen av varje block bland de topografiskt våtaste 10/5 procenten.

### Steg 6 – final hydrology table
Slår ihop hydrologin med åkermarkströsklar och räknar block-/kommunpercentiler.

### Steg 7 – webb
`web/template_v092.html` innehåller UI/CSS/JavaScript men **inga data**.
Buildsteget injicerar:
- DATA (block/skiften)
- SOIL
- TOPO
- HYDRO

Slutprodukten är en fristående `dist/index.html`.

### Steg 8 – QA
Jämför mot referens från den validerade 2026-08-15-builden:
- 5919 block
- 7364 skiften
- median elevation ≈59.4 m
- median mean slope ≈1.54°
- farmland TWI P90 ≈11.7508
- farmland TWI P95 ≈14.5651

## Git

Git ska innehålla:
- kod
- webbtemplate
- README/dokumentation
- QA-regler
- eventuellt input-manifest/checksummor

Git ska INTE innehålla:
- 325 MB jord-ZIP
- GeoPackages
- 231 DEM-rutor
- Whitebox mellanraster
- genererad 30–40 MB HTML

Detta regleras av `.gitignore`.

När du vill skapa repo:

    git init
    git add .
    git commit -m "ÅkerSync reproducible v0.92 baseline"

Sedan kan det kopplas till GitHub.

## Två buildlägen

`BUILD_ALL.bat`
: full analys från rådata.

`BUILD_ALL_REUSE_HYDRO.bat`
: återanvänder Whitebox-mellanraster när de redan finns.

`BUILD_WEB_ONLY.bat`
: bygger bara HTML från redan existerande `data/derived`.
Bra när vi ändrar popup/UI men inte matematiken.

## Viktig designprincip

Blockgränser påverkar inte hydrologiberäkningen.
Hydrologi/TWI räknas på hela DEM-landskapet först; zonstatistik per block görs
därefter. Vatten från uppströms grannfält kan därför bidra till ett blocks SCA/TWI.
