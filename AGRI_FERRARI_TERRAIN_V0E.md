# ÅkerSync · Ferrari terrain contrast · v0e

## Fråga

Efter den jord-only Ferrari-analys som låstes i v0c/v0d testar v0e kandidatförklaringar som **inte användes för att skapa FerrariScore**.

### A – Vollsjö mot Bjärred/Lomma

Fyra grupper:

1. `Vollsjo_superFerrari`: v0d Super-Ferrari (>= klass-10 P90) inom 22 km från Vollsjö-diagnostikcentret.
2. `Vollsjo_local_control_class5_9`: övriga score-eligible klass 5–9 inom samma radie, deterministiskt max 300.
3. `Bjarred_extreme_nonFerrari`: v0d extrem non-Ferrari (<= klass-10 P05) inom 18 km från Bjärred-diagnostikcentret.
4. `Bjarred_local_class10_control`: övriga score-eligible klass-10-skiften inom samma radie, deterministiskt max 300.

Radierna är diagnostiska fönster och inte kommun-/naturgeografiska gränser.

### B – global kontrast

Alla v0d Super-Ferrari utanför klass 10 jämförs med alla extrema non-Ferrari inne i klass 10.

## Topografi

Lantmäteriets MHM från `dem_dir` samplas direkt över skiftena på ett 5 m arbetsgrid:

- höjd medel/SD
- relief P95–P05 inom skiftet
- slope medel/P50/P90/P95
- andel <0,5°, <1°, >3°, >5°
- samma typ av relief/slope i 500 m kontext runt skiftet

Detta testar bl.a. den visuella hypotesen att Bjärred/Lomma är mycket platt medan Vollsjö-klustret kan ligga i mer kuperad terräng.

## Hydrologi

Scriptet letar efter **redan byggda** Whitebox-raster (`twi_10m`, SCA etc.) via `whitebox_work_dir` och tidigare `hydrology_intermediate_files.txt`.

Om de finns och täcker området samplas TWI/SCA. Om de saknas slutförs analysen med topografi. Scriptet skapar medvetet inte en lokal TWI-genväg, eftersom TWI kräver korrekt uppströms kontext.

## Statistik

Ingen naiv p-värdesmaskin används – skiftena är spatialt korrelerade och grupperna är extremselekterade.

För B redovisas:

- gruppmedianer
- median skillnad
- rank-biserial effektstorlek (positiv = högre i Super-Ferrari utanför klass 10)

Nästa steg, om terrängsignal finns, är spatialt matchad modellering och mikroklimat/kustexponering.

## Output

`data/derived/agri_class5_10_v0e_terrain_contrast/`

- `report.txt`
- `A_vollsjo_bjarred_skiften.csv`
- `A_vollsjo_bjarred_summary.csv`
- `A_vollsjo_vs_bjarred_contrast.csv`
- `A_vollsjo_bjarred_map.html`
- `B_global_anomaly_skiften.csv`
- `B_global_anomaly_summary.csv`
- `B_global_contrast.csv`
- `topography_selected_skiften_cache.csv`
- `hydrology_selected_skiften.csv`
