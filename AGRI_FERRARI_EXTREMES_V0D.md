# ÅkerSync · extrema Ferrari-anomalier · v0d

## Varför v0d?

v0c använde en bred Ferrari-like-gräns vid klass-10:s out-of-fold P20. Det var bra för att se överlappningen mellan jordklasserna, men gav många kandidater utanför klass 10.

v0d gör i stället ett avsiktligt extremt natural-experiment-urval:

- **Super-Ferrari utanför klass 10**: `FerrariScore >= klass-10 OOF P90`
- **Extrem icke-Ferrari inne i klass 10**: `FerrariScore <= klass-10 OOF P05`
- **Ultra-Ferrari** markeras dessutom vid klass-10 OOF P95.

Trösklarna är diagnostiska och räknas om från den aktuella v0c-scorefilen. De är inte universella agronomiska gränsvärden.

## Avstånd till klass 10

För varje Super-Ferrari utanför klass 10 räknas två avstånd i SWEREF99 TM:

1. minsta avstånd från skiftets polygonkant till närmaste historiska klass-10-polygon,
2. avstånd från skiftets representativa punkt till klass 10.

Huvudanalysen använder polygonkant-avståndet och delar in kandidaterna i:

- 0–2 km
- 2–5 km
- 5–10 km
- >10 km

Det hjälper oss att skilja möjliga gräns-/penndragningseffekter från geografiskt isolerade jordanaloger.

## Fortfarande SOIL ONLY

Klimat, topografi och hydrologi används **inte** i v0d. De hålls avsiktligt utanför för att senare kunna användas som oberoende förklaringsvariabler för anomalierna.

## Input

Kör v0c först. v0d behöver:

`data/derived/agri_class5_10_v0c_ferrari/skifte_ferrari_scores.csv`

samt samma lokala `skiften`-fil och historiska klasspolygon-cache som tidigare steg.

## Output

`data/derived/agri_class5_10_v0d_extremes/`

- `report.txt`
- `super_ferrari_outside_class10.csv`
- `extreme_non_ferrari_inside_class10.csv`
- `super_ferrari_by_historic_class.csv`
- `super_ferrari_distance_bins.csv`
- `ferrari_extreme_anomalies.gpkg`
- `ferrari_extreme_anomaly_map.html`
- `method_metadata.json`

Kartan färgar Super-Ferrari efter avstånd till klass 10 och visar extrema låg-score-skiften inne i klass 10 separat.

## Nästa vetenskapliga steg

När anomalierna är låsta kan vi fråga vilka held-out variabler som skiljer:

- isolerade Super-Ferrari i klass 5–9 från riktiga klass-10-skiften,
- extrema icke-Ferrari inne i klass 10 från normala klass-10-skiften.

Kandidater är bland annat kust-/mikroklimat, höjd, lutning, hydrologi/TWI och dräneringsrelaterade proxyvariabler.
