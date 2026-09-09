# ÅkerPuls preliminära skiften 2026 – datum- och coveragebeslut efter A0

## Beslut

V0 behåller Bengts ursprungliga snapshots oförändrade:

- APRIL: 2026-04-08 + 2026-04-09
- MAY: 2026-05-25
- JUNE: 2026-06-26 + 2026-06-27
- JULY: 2026-07-09

Rescue-datumen från A0b/A0c/A0d är QA/diagnostik och ingår **inte** i V0-snapshotdefinitionen.

## Motiv

A0 visar footprint-coverage ungefär 94.91 % i april, 100 % i maj,
95.26 % i juni och 100 % i juli. Luckorna i april/juni är huvudsakligen
saknade Sentinel-footprints i östra Skåne, inte små spridda molnhål.

Rescue-testet visar att juni kan förbättras med extra datum, men då skulle
snapshotten spänna över flera dygn utanför det frysta 26/27-junifönstret.
April saknar dessutom en robust enkel rescue-kombination nära 8/9 april.

V0 väljer därför temporal renhet framför artificiell full coverage.

## Konsekvens i produkten

- `valid_april=false` där april-snapshotten saknar tillräcklig coverage.
- `valid_june=false` där juni-snapshotten saknar tillräcklig coverage.
- May/july fortsätter ge två oberoende snapshots i footprint-luckan.
- Confidence skall sänkas när färre snapshots stödjer en gräns.
- Fält med otillräcklig evidens blir `UNCERTAIN`; 2025-priorn behålls.
- Rescue-datum får senare studeras i en separat V0.1/V1 utan att ändra V0 i efterhand.

Detta följer grundkontraktet att 2025-geometrin är prior och att osäker satellittäckning
ska uttryckas som validity/confidence, inte döljas genom att flytta observationsdatum.
