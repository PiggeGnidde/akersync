# ÅkerDrift Fast MVP V1

Modellversion: `akerdrift-fast-v1-rc0`  
Branch: `feature/akerdrift-fast-v1a`

ÅkerDrift är ett index 0–100 för strukturell maskinell brukbarhet. Högre värde
innebär att skiftet enligt modellen är mer maskinellt lättbrukat. Det är inte
exakt trösktid, bränsleförbrukning eller besked om dagens bärighet.

## Fryst modell

All geometri mäts i SWEREF 99 TM med area i m² och perimeter i meter:

```text
pa_ratio = perimeter_m / area_m2
FE_geom_raw = 0.179 - 0.145 * ln(pa_ratio)
FE_geom = clip(FE_geom_raw, 0, 1)
geometry_score = 100 * FE_geom
```

För slope-pixlar i grader är svårigheten 0 till och med 5°, 1 från 16,7° och
linjär däremellan. Medelvärdet `D_slope` ger:

```text
terrain_factor = 1 - 0.20 * D_slope
akerdrift_score = clip(100 * FE_geom * terrain_factor, 0, 100)
```

Alla parametrar ligger i `config/akerdrift_fast_v1_rc0.json`. TWI-trösklarna
12,143241 och 15,312701 används bara för diagnostik och påverkar aldrig score.

## Inputs

Sökvägarna `blocks`, `skiften`, `whitebox_work_dir` och `build_dir` hämtas från
`config/local_paths.json`. Som standard används:

```text
<whitebox_work_dir>/slope_10m_deg.tif
<whitebox_work_dir>/twi_10m.tif
```

Alternativ kan anges som `akerdrift_slope_raster` och
`akerdrift_twi_raster` i lokal config, eller med CLI-flaggorna
`--slope-raster` och `--twi-raster`. Slope krävs. Saknad TWI ger status
`MISSING` men påverkar inte huvudscoren.

`geometry_v1a_skiften.csv` återanvänds endast för förklarande mått. Area och
total polygonperimeter för score mäts direkt på reparerad skiftesgeometri.
Rastercoverage följer repoets etablerade pixelcentrumkonvention: giltiga
pixelcentrum dividerat med alla pixelcentrum inom skiftet.

## Restart-säker körordning

Installera först uppdaterade beroenden, inklusive `pyarrow`:

```bat
INSTALL_REQUIREMENTS.bat
```

Checkpoint B, endast Lomma:

```bat
py -3 src\44_akerdrift_fast_v1.py run --kommun Lomma
```

Checkpoint C, tre referenskommuner:

```bat
py -3 src\44_akerdrift_fast_v1.py run --kommun Lomma --kommun Eslöv --kommun Kävlinge
```

Kör samma kommando igen. Det ska skriva `SKIP <kommun>: valid checkpoint`.

Hela Skåne:

```bat
RUN_AKERDRIFT_FAST_V1.bat
```

BAT-filen kör `run --all --resume`. Varje kommun skrivs först till
`<kommun>.tmp.parquet`, valideras och flyttas atomärt. Först därefter skrivs
`<kommun>.done.json`. Ett avbrott kräver därför maximalt omkörning av pågående
kommun. Efter alla 33 kommuner byggs den globala Parquet-filen. Ingen QA eller
ruttmotor startas automatiskt.

Output under `data/derived/akerdrift_fast_v1/`:

```text
by_municipality/<kommun>.parquet
checkpoints/<kommun>.done.json
failures/<kommun>.csv
akerdrift_fast_v1_skane.parquet
run_manifest.json
```

Separat billig QA och sensitivitet:

```bat
CHECK_AKERDRIFT_FAST_V1.bat
```

Detta läser endast färdig Parquet. Ingen rasterläsning eller route generation
görs.

## Publik build

När den globala Skånefilen finns:

```bat
BUILD_AKERPASS_WEB_V1.bat
```

Den publika kartan får ett tredje färglager, ÅkerDrift, och detaljpanelen visar
geometrisk effektivitetsproxy, terrängfaktor, lutning P95, slope coverage,
TWI P95-yta som diagnostik, ERL och rectangularity.

## Status och begränsningar

- Den tidigare route-/Fields2Cover-motorn importeras eller körs inte.
- P/A fångar både storlek och gränskomplexitet men inte optimal körriktning,
  kilar eller exakt antal vändningar.
- Topografistraffet känner inte kör- eller tvärlutning och hålls därför till
  högst 20 procent.
- TWI beskriver topografisk våtrisk, inte observerad markfukt eller dränering.
- Infarter, hinder, gröda, aktuell markfukt och förare ingår inte.

Källan till geometrirelationen är Griffel et al. (2020), *Agricultural field
shape descriptors as predictors of field efficiency for perennial grass
harvesting: An empirical proof*, Computers and Electronics in Agriculture 168,
105088.
