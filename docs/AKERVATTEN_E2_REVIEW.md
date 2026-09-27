# ÅkerVatten MVP v0a · STOPPUNKT E2 focused review

E2 resolves the two main review questions left by STOPPUNKT E before any component feature set is frozen.

## Groundwater

SGU defines both fyllnadsgrad and grundvattensituation on a 0–100 scale where low values mean historically low groundwater level.

They differ in reference frame:

- grundvattensituation: comparison with the corresponding week of the year;
- fyllnadsgrad: comparison with all historical levels independent of season.

E2 therefore tests whether the apparent directional tension between persistence of low grundvattensituation and low summer fyllnadsgrad can be explained by seasonal structure rather than a sign error.

For all 786 SGU-HYPE units it extracts:

- dates of the longest small-magasin grundvattensituation <=10 event;
- dates of the longest small-magasin fyllnadsgrad <=10 event;
- start-year distributions of those events;
- monthly-median fyllnadsgrad amplitude;
- correlations stratified by seasonal-amplitude quartile.

## Surface water

E2 reviews the four E candidates:

- MLQ/MQ total;
- specific MLQ total;
- MLQ/MQ natural;
- specific MLQ natural.

The provisional design keeps the two total-flow metrics as primary candidates and the natural-flow counterparts as diagnostics. This is not frozen until E2 output is reviewed.

## Local feature schema

E2 scans local soil, hydrology and D-field schemas for column names related to:

- slope/lutning;
- relief/elevation/DEM;
- flow accumulation/SCA;
- TWI/wetness.

This checks whether the optional slope candidate was merely missed by the E aliases.

## TWI

The exact -1 correlation between MarkTorka/low_twi and MarkVata/high_twi is expected by construction: both use the same raw TWI variable with opposite directional interpretation.

No score is frozen in E2.
