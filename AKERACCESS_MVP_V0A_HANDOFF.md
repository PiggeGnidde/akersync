# ÅkerAccess MVP v0a — STOPPUNKT A

## Syfte

Första discovery-steget för ÅkerAccess. Ingen score eller Apetit-policy fryses här.

Frågan är: **hur stor andel av skiftena i Sjöbo får faktisk OSM-evidens för en möjlig fältinfart?**

## Evidensklasser

1. OSM track/service/road penetrerar skiftespolygonen.
2. OSM-vägens endpoint ligger inom 5 m från skiftesgränsen.
3. Endpoint ligger inom 15 m.
4. Vägen ligger högst 5 m från gränsen men utan tydlig endpoint/penetration: adjacency only.
5. Grind/lift_gate/swing_gate nära både skiftesgräns och kandidatväg förstärker evidensen.

En väg ritad längs skiftesgränsen räknas **inte** automatiskt som att den går in på fältet. Penetration testas mot en liten negativ buffer av fältpolygonen.

## Input

Körningen återanvänder Jordbruksverkets block/skiften från ett existerande `config/local_paths.json`. Eftersom ignored config inte delas mellan Git-worktrees söker koden read-only i kända ÅkerSync-worktrees, bl.a. ÅkerMinne, ÅkerFrö, ÅkerPrestation och huvudrepon.

OSM-vägar och grindar hämtas via Overpass och cacheas under:

`data/raw/akeraccess_osm/`

Den katalogen är redan git-ignored.

## Körning

`RUN_AKERACCESS_ENTRY_DISCOVERY_V0A.bat`

Default är Sjöbo.

## Output

Under `work/akeraccess_v0a/sjobo/`:

- `sjobo_field_entry_summary.csv` — en rad per skifte.
- `sjobo_entry_candidates.csv` — alla kandidater.
- `sjobo_entry_candidates.geojson` — kandidatpunkter.
- `sjobo_manual_review_sample.csv` — deterministiskt 100-skiftes QA-urval.
- `sjobo_manual_review_fields.geojson` — samma QA-urval som polygoner.
- `sjobo_stoppunkt_a.json` — sammanfattning för nästa iteration.

## STOPPUNKT A

Efter första lokala körningen granskar vi:

- andel STRONG / POSSIBLE / ADJACENCY / NO EVIDENCE,
- fördelning track/service/övriga vägar,
- antal OSM-grindar,
- manuellt QA-urval.

Först därefter bestämmer vi om OSM räcker som entry detector och hur ortofoto/NVDB ska kopplas in.
