# ÅkerSync · Value Regression v0f · 1971 jordbruksklass

## Fråga

Hur mycket av dagens observerade åkermarkspris per hektar förklaras av den historiska svenska produktivitetsklassen 1–10 från omkring 1971?

Den viktigaste jämförelsen är om klassinformationen:

1. ensam bär mycket prisinformation,
2. kan ersätta en stor del av lat/lon-gradienten,
3. eller fortfarande tillför information ovanpå G1/G2-geografin.

## Target

`log(köpeskilling / åkermark_ha)`

Samma rena ATL-urval och datumfönster som v0e används som utgångspunkt.

## Huvudklassfeature

ATL-punkten används inte som huvudklass. I stället återanvänds v0c multi-block-rekonstruktion:

- urval av block använder endast ATL-läge + såld åkerareal,
- historisk klass påverkar aldrig vilka block som väljs,
- de låsta blocken korsas sedan mot klasspolygonerna 1–10,
- transaktionens klass blir areaviktad över klassificerad blockyta.

Huvudvariabel:

`class1971_tx_mean_aw`

Main sample kräver:

- rekonstruktion inom ±20 % av såld åkerareal,
- minst 80 % historisk klasskartetäckning över de rekonstruerade blocken.

Dessutom exporteras mode, SD, min/max och klassandelar.

## Fördeklarerad modellstege

- `K_ONLY_class1971`: endast klass
- `K_ONLY_class1971_quadratic`: klass + klass²
- `YEAR_CLASS`: år + klass
- `TA_year_area`: år + log(area)
- `TA_CLASS`: år + log(area) + klass
- `TA_CLASS_QUAD`: år + log(area) + klass + klass²
- `YEAR_LAT_LON`: år + lat + lon
- `G1_year_area_lat_lon`: år + log(area) + lat + lon
- `G1_CLASS`: G1 + klass
- `G2_quadratic_geo`: G1 + lat² + lon² + lat×lon
- `G2_CLASS`: G2 + klass
- `G2_CLASS_QUAD`: G2 + klass + klass²

Primärt mått är LOO-R². Klassens inkrementella värde redovisas på exakt samma rader för:

- TA → TA + klass
- G1 → G1 + klass
- G2 → G2 + klass

## Punktklass

Historisk klass där ATL-koordinaten ligger exporteras också och testas separat som känslighetsanalys. Den är inte huvudresultat eftersom ATL-punkten kan vara adress/gårdscentrum snarare än faktisk såld åker.

## Pricing residuals

`class1971_pricing_residual_candidates.csv` använder LOO-modellen `år + area + klass` och exporterar bland annat:

- observerat pris/ha,
- LOO-predikterat pris/ha,
- observed/predicted ratio,
- log-residual.

Det är ett diagnostiskt underlag för nästa test: om modern jordkvalitet systematiskt förklarar vilka objekt som är billigare eller dyrare än vad den gamla klassen implicerar.

Residualerna är **candidate mispricing**, inte bevis på arbitrage.

## Viktiga begränsningar

- Historisk klass är en produktivitetsklass, inte en direkt jordmätning.
- Transaktionsklass bygger på rekonstruerade 2025-block, inte fastighetsrättslig geometri.
- Klass och geografi är starkt relaterade; därför måste G1/G2-jämförelserna göras.
- Samplet är litet. Ingen predictor-stuffing och inga efterhandsvalda outlierborttagningar.
