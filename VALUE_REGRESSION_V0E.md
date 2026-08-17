# ÅkerSync Value Regression v0e — soil texture

## Syfte

v0e pausar geometri som prisvariabel och testar i stället om jordens texturbalans och variation bär information om pris per hektar utöver geografi.

Huvudsample är samma som v0d: rena ATL-försäljningar från 2020-07-01 och framåt. Med 436-posterfilen är det 56 case.

## Låsta geografibaselines

- **G1**: år + log(åkerarea) + lat + lon
- **G2**: G1 + lat² + lon² + lat·lon

Primärt mått är fortfarande **delta LOO R² mot baseline på exakt samma rader**.

## Textur är kompositionsdata

Sand + silt + lera summerar ungefär till 100 %. Därför stoppas de inte in som tre oberoende råa regressorer.

v0e testar i stället:

- lera linjärt,
- lera + lera²,
- lera + silt, där sand är implicit,
- två log-ratios: log(lera/sand) och log(silt/sand),
- en försiktig kvadratisk tvåkomponentsmodell för lera/silt.

Kvadratiska lertermer centreras kring 25 % bara för numerik/tolkning; centreringen ändrar inte modellens fit. Ett beräknat turning point redovisas som maximum/minimum men ska inte tolkas agronomiskt utan CV-stöd.

## Tre rumsliga jordmått

1. **ATL-punkt** — exakt DSMS-pixel vid ATL-koordinaten.
2. **100 m** — medel över cirkel runt ATL-punkten.
3. **Transaction-level** — DSMS-pixlar över blocken som valts av v0c:s multi-block-rekonstruktion.

Transaction-level jord släpps in i huvudregressionen endast när rekonstruerad blockarea ligger inom **±20 %** från såld åkerarea.

Multi-block-urvalet använder bara läge/närhet + såld area. Jordtextur och geometri påverkar inte vilka block som väljs.

## Variation inom affären

För de rekonstruerade blocken beräknas bland annat:

- clay mean / SD / P10 / P50 / P90,
- clay P90-P10,
- motsvarande texturstatistik för silt och sand,
- RMS-heterogenitet i sand/silt/lera över alla 20 m-pixlar,
- areaviktad texturspridning mellan blockens medelvärden,
- areaviktad spridning i blockmedel för lera.

Det gör att en affär med två olika jordtyper kan skiljas från en affär med samma medeltextur men helt homogen jord.

## Mull / organisk halt

DSMS-lagret är kategoriskt och kodas enligt befintlig ÅkerSync-definition:

- 2: <2,5 %
- 3: 2,5–3,5 %
- 4: 3,5–4,5 %
- 5: 4,5–5,5 %
- 6: 5,5–6,5 %
- 9: 6,5–12 %
- 16: 12–20 %
- 30: ≥20 %

v0e sparar mode, klassandelar, dominant klassandel och Shannon-entropi. **Klasskoden behandlas inte som ett kontinuerligt procenttal.** Endast klass-entropi testas explorativt som ett neutralt variationsmått; mullnivå får ingen påhittad linjär skala.

## Fördeklarerade modellfamiljer

- punktlera linjär / kvadratisk,
- 100 m lera linjär / kvadratisk,
- punkttextur clay+silt,
- 100 m textur clay+silt,
- punkt/100 m log-ratio-textur,
- 100 m kvadratisk textur,
- transaction clay linjär / kvadratisk,
- transaction clay+silt,
- transaction log-ratio-textur,
- transaction kvadratisk textur,
- transaction clay P90-P10,
- transaction pixelheterogenitet,
- transaction mellan-block-diversitet,
- organisk klass-entropi (explorativ).

## Robusthet

Delete-one körs för:

- punktlera linjär,
- 100 m lera linjär,
- transaction clay linjär,
- transaction log-ratio-textur,

under både G1 och G2.

## Output

`data/derived/value_regression_v0e/`

Viktigast:

- `report.txt`
- `soil_model_comparison.csv`
- `soil_model_coefficients.csv`
- `soil_robustness_summary.csv`
- `soil_features_all.csv`
- `transaction_soil_block_features.csv`
- `organic_class_summary.csv`
- `multiblock_members.csv`

## Tolkning

v0e är fortfarande explorativt. Transaction-level jord bygger på en närhets/area-rekonstruktion av 2025 års jordbruksblock, inte på bevisad fastighetsgeometri. Positiv delta LOO är därför en signal att undersöka vidare, inte en kausal värderingskoefficient.
