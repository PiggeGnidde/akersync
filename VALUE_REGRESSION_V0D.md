# ÅkerSync Value Regression v0d

## Syfte

v0d fryser huvudsamplet till rena ATL-affärer från 2020-07-01 och framåt och
ställer en smal fråga:

> Överlever lera/TWI när lat/lon-baselinen görs mer flexibel?

Detta är en robusthetsstudie, inte ny feature mining.

## Baselines

### G1 — linjär geografi

`log(kr/åker-ha) ~ year + log(area) + lat + lon`

### G2 — modest kvadratisk geografi

`G1 + lat^2 + lon^2 + lat*lon`

Lat/lon är centrerade innan kvadrering/interaktion.

G2 har bara tre extra geografitermer. Med n≈56 vill vi inte passa en mycket
flexibel spatial yta som kan äta upp all lokal fysisk variation.

## Fördeklarerade fysiska test

Varje fysisk modell jämförs med sin baseline på exakt samma complete-case-rader:

- clay point
- clay 100 m mean
- TWI point
- TWI 100 m P90
- clay point + TWI point (fördeklarerad tvåvariabelmodell)

Primärt mått är delta LOO R2.

## Delete-one robusthet

För clay point, clay 100 m mean och TWI point körs dessutom en delete-one-studie
under både G1 och G2. Den rapporterar:

- min/median/max för fysisk koefficient
- hur ofta koefficientens tecken överlever
- min/median/max för delta LOO R2
- andel delete-one-körningar med positiv delta LOO R2

Syftet är att upptäcka om ett enda köp driver signalen.

## Output

`data/derived/value_regression_v0d/`

Viktigast:

- `report.txt`
- `geography_baseline_comparison.csv`
- `physics_model_comparison.csv`
- `robustness_summary.csv`
- `delete1_robustness.csv`
- `point_features.csv`

## Geometri

v0d ändrar inte multi-block-geometrin. v0c sparas som separat experiment.
Detta gör att frågan om fysisk jord/TWI-signal inte blandas ihop med den ännu
osäkra rekonstruktionen av vilka jordbruksblock som ingick i respektive köp.
