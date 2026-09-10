# ÅkerPuls 2026 – C4 beslut och C5-plan

C4 utvärderade rikare topologi/morfologi på 226 baseline-splitkandidater i den oberoende C-piloten.

Nyckelresultat:
- 226 baseline split-kandidater.
- 43 klarade den sedan B låsta SPLIT_CANDIDATE-regeln.
- 14 robusta near-rejects inkluderades i C4:s diagnostik.
- Den enkla post-hoc-regeln `SPLIT_CANDIDATE AND separation_ratio >= 4.0` behöll 17/43.
- På C3:s frysta visuella decisive labels behöll denna regel 4/5 TYDLIG och 0/9 FALSK.
- C4:s bästa multifeature-grid behöll 18 i stället för 17 men gav samma 4/5 TYDLIG och 0/9 FALSK. Den tillförde därför komplexitet utan observerad förbättring på C3.

## Beslut

För nästa geografiskt oberoende holdout används den enklaste regeln:

`HIGH_CONFIDENCE_SPLIT = SPLIT_CANDIDATE AND separation_ratio >= 4.0`

Detta är en **testfrysning**, inte en produktfrysning. Regeln har valts efter C3 reveal och får därför inte påstås vara validerad av B/C. Den måste testas helt orörd på ett tredje geografiskt område.

Den befintliga SPLIT_CANDIDATE-regeln ändras inte:
- min largest-component fraction för båda barn >= 0.95
- edge-ratio >= 1.8 i minst 3 av 4 snapshots
- LOO_ALL4

Merge-policy förblir `MERGE_CANDIDATE_ONLY`.

## C5

C5a väljer ett nytt kompakt 20x20 km holdoutområde med cirka 1000 fält, full Sentinel-2 footprint för de fyra frysta snapshotsen och minst 45 km geometriskt avstånd från både B- och C-piloterna.

C5a använder endast offentlig STAC och 0 Sentinel Hub PU.

Efter C5a:
1. C5b hämtar samma sex frysta Sentinel-2-dagar med exakt samma preprocessing som B1/C1.
2. Kandidatupptäckt och SPLIT_CANDIDATE-regel körs oförändrade.
3. HIGH_CONFIDENCE_SPLIT-regeln `candidate AND separation_ratio>=4.0` appliceras utan tuning.
4. Visuell blind QA görs innan beslut om produktfreeze eller STOPPUNKT D.

Inga parametrar får ändras under C5-holdouten.
