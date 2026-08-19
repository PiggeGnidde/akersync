# ÅkerSync · skifte-Ferrari · v0c

## Frågan

Finns det 2025-skiften i historisk klass 5–9 som har en jordprofil som ser ut som klass 10? Och finns det skiften inne i klass 10 som **inte** gör det?

Det här steget använder medvetet **bara jord**. Mikroklimat, topografi, hydrologi och dränering hålls utanför så att de senare kan användas som oberoende förklaringar till anomalierna.

## Klassning per skifte

Skiftets historiska klass 5–10 bestäms av dess representativa punkt i 1970-talets klasspolygon. Därefter räknas den exakta andelen av skiftets yta som ligger i den tilldelade klassen.

Huvudscore kräver minst:

- 80 % klassöverlapp,
- 80 % giltig DSMS-jordtäckning,
- 1 ha skiftesarea.

Det gör att gränsfall i gamla penndragningen finns kvar i output men inte får smyga in i huvudresultatet.

## Jordfeatures per skifte

Från DSMS2025 20 m:

- medel lera, silt, sand,
- SD lera, silt, sand,
- P10/P90,
- `texture_heterogeneity_rms` = RMS av de tre SD-värdena.

Eftersom sand+silt+lera ≈ 100 använder centrumdelen bara lera+silt; sand är implicit.

## FerrariScore

Två separata komponenter:

1. **Texture center score** – hur nära skiftets medel lera+silt ligger klass-10-signaturen.
2. **Homogeneity score** – hur låg den interna texturvariationen är jämfört med klass-10-skiften.

Kombination:

`FerrariScore = sqrt(texture_center_score * homogeneity_score)`

Båda delarna måste alltså vara bra för att totalscoren ska bli hög.

## Anti-circularity / spatial holdout

För varje skifte byggs klass-10-referensen utan klass-10-skiften i samma 10×10 km-ruta. Det minskar risken att en lokal jordmodellstruktur bara återupptäcks i sin egen geografi.

Ferrari-tröskeln sätts sedan till P20 av de spatialt hållna-ut klass-10-scorerna. Ungefär 80 % av klass 10 definierar alltså den empiriska Ferrari-domänen.

Det viktiga resultatet är hur många klass 5–9 som ändå kommer in i samma domän.

## Output

`data/derived/agri_class5_10_v0c_ferrari/`

- `report.txt`
- `skifte_soil_features.csv`
- `skifte_ferrari_scores.csv`
- `ferrari_by_historic_class.csv`
- `ferrari_outside_class10.csv`
- `non_ferrari_inside_class10.csv`
- `ferrari_skifte_qa.gpkg`
- `ferrari_anomaly_map.html`
- `method_metadata.json`

## Tolkning

Ett Ferrari-likt skifte utanför klass 10 betyder **klass-10-lik jord**, inte bevisad klass-10-produktion.

Ett icke-Ferrari-skifte inne i klass 10 kan vara:

- gammal klassgräns/penndragning,
- lokal jordmodellmiss,
- eller viktigast: bevis för att jord inte räcker och att mikroklimat/topografi/hydrologi bidrar.

Det är precis de anomalierna som blir nästa experiment.
