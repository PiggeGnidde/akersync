# ÅkerSync · Jordbruksklass 9/10 · v0a

## Syfte

Beskriv den faktiska sand/silt/lera/mull-profilen i de historiskt högsta svenska åkermarksklasserna utan att på förhand anta ett "perfekt" texturrecept.

Primär fråga: hur ser fördelningen av DSMS2025-jordegenskaper ut i historisk klass 10 jämfört med klass 9?

## Population

Kommuner används inte som statistisk enhet. Själva klasspolygonerna definierar populationen och alla giltiga 20x20 m-pixlar får lika areavikt.

Två populationer redovisas:

A. `historic_class_area`: hela den historiska klasspolygonen.
B. `current_2025_farmland`: klasspolygonens pixlar som fortfarande ligger i Jordbruksverkets 2025 jordbruksblock.

Det gör att vi både kan beskriva den historiska superjorden och kontrollera hur resultatet ser ut när senare exploaterad/icke-jordbruksmark tas bort.

## Klasskälla

Programmet hämtar endast `KLASS IN (9,10)` från ett ArcGIS Feature Layer som publiceras i Ystads kartportal:

`https://kartportal.ystad.se/arcgis/rest/services/SAM/SAM_OP_Hansyn/MapServer/32`

Lagrets beskrivning anger att det är tidigare LstM Jord- och skogsklassificering för Malmöhus och Kristianstads län. Länsstyrelsen Skåne beskriver fortfarande samma klassificering och länkar till lagret `LstM Jord- och skogsklassificering Skåne` i sin webbkarta.

Källpolygonerna cachas lokalt under output-katalogen. Kör med `--refresh` om de ska hämtas om.

## Jorddata

DSMS2025 20 m:

- lera
- silt
- sand
- organisk klass

Sand+silt+lera kontrolleras även som textursumma. Mull behandlas som kategorisk klass, inte som ett påhittat kontinuerligt procenttal.

## Statistik per klass och population

För lera, silt och sand:

- mean
- standardavvikelse
- P10
- P25
- median
- P75
- P90

Dessutom:

- textursumma QA
- kovarians och korrelation mellan lera/silt/sand
- andel per organisk klass
- rastertäckning
- pixelbaserad areal

## Output

`data/derived/agri_class9_10_v0a/`

- `report.txt`
- `class9_10_soil_summary.csv`
- `class9_10_texture_covariance.csv`
- `class9_10_organic_summary.csv`
- `class9_10_dissolved.gpkg`
- `qa_class9_10_and_current_blocks.gpkg`
- `source_metadata.json`
- `source/jord_skogsklassificering_class9_10.gpkg`

QA-GPKG:n innehåller både de historiska klass 9/10-polygonerna och dagens närliggande jordbruksblock för visuell kontroll i QGIS.

## Statistisk försiktighet

20 m-pixlarna är en areabeskrivning av populationen, inte oberoende statistiska observationer. Grannpixlar är spatialt korrelerade. Om vi senare vill sätta konfidensintervall kring klassmedel ska det därför göras med spatial block-bootstrap, inte med `n = antal pixlar` som om varje pixel vore ett nytt jordprov.

Klassningen är från cirka 1970 och bygger på produktionsförmåga/spannmålsavkastning. DSMS2025 är modern kartlagd matjord. Analysen är därför ett medvetet overlay över tid, inte ett påstående om att jordens tillstånd 2025 är exakt samma som 1970.
