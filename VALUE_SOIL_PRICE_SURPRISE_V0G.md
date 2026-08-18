# ÅkerSync Value Regression v0g — modern jord-surprise mot marknadspris

## Fråga

Har marknaden redan prisat in den moderna jordinformation som Ferrari/Königsegg-hypotesen fångar, eller finns det affärer där jordkvaliteten ser ovanligt stark ut relativt den historiska 1971-klassen samtidigt som priset är lågt relativt lokal marknadsgeografi?

Detta är ett diagnostiskt test av informationsinnehåll och möjlig felprissättning — inte ett bevis på arbitrage.

## Låst urval

v0g återanvänder exakt v0f:s huvudsample och multiblock-rekonstruktion:

- `value_regression_v0f_class1971/class1971_main_sample.csv`
- `value_regression_v0f_class1971/multiblock_members.csv`

Ingen ny blockselektion görs i v0g.

## Modern jordscore

DSMS2025 samplas över de redan låsta rekonstruerade blocken. Transaktionsjordens lera/silt-medel och texturheterogenitet jämförs mot den redan frusna klass-10-referensen från agri-class v0c (`skifte_ferrari_scores.csv`).

Varje transaktion får en spatialt hållen-out referens: klass-10-skiften i samma 10×10 km-cell exkluderas innan score beräknas.

Transaktionshjälparen använder `sqrt(sum(sd^2))`, medan Ferrari v0c använde `sqrt(mean(sd^2))`. v0g dividerar därför transaktionsmåttet med `sqrt(3)` innan jämförelse så att heterogeniteten ligger på samma skala som v0c.

## Jord-surprise

Två leave-one-out-diagnostikmått beräknas:

- `soil_surprise_class`: FerrariScore minus LOO-förväntad FerrariScore från 1971-klass.
- `soil_surprise_class_geo`: motsvarande men med 1971-klass + lat + lon som förklarande variabler.

Positiv surprise betyder modern jord som ser bättre ut än väntat givet den gamla etiketten.

## Prismodeller

Två enkla marknadsbaselines från v0f hålls kvar:

- `MARKET_YLL`: år + lat + lon.
- `MARKET_G1`: år + log(area) + lat + lon.

Därefter testas samma-row LOO-förbättring av:

- + transaction FerrariScore
- + soil-surprise relativt 1971-klass

Om modern jord inte förbättrar LOO men samtidigt producerar tydliga high-soil/low-price-kandidater är det förenligt med möjlig informationsineffektivitet. Det är inte bevis på att marken är felprissatt.

## Kandidatmatris

`pricing_soil_candidate_ranking.csv` markerar diagnostiska kvartiler:

- `high_soil_low_price`: jord-surprise >= P75 och marknadsprisratio <= P25
- `low_soil_high_price`: jord-surprise <= P25 och prisratio >= P75
- `high_soil_high_price`: marknaden kan ha fångat kvaliteten
- `low_soil_low_price`: pris och jordbild går åt samma håll

En robust-z-baserad `candidate_underpricing_index` används endast för sortering av manuella kandidater.

## Guardrails

- Sampelstorleken är liten.
- Affärsgeometrin är rekonstruerad från ATL-position + såld åkerareal och är inte fastighetsrättsligt facit.
- DSMS2025 är modellerad jordinformation.
- FerrariScore är en jord-only diagnostik; klimat, topografi, hydrologi och dränering kan förklara avvikelser.
- Lokala köpare, arrondering, rättigheter, byggnader, konkurrens och framtida exploateringsvärde kan påverka priset rationellt.
- Resultatet skall beskrivas som pricing-anomaly candidates, inte som säker arbitrage.

## Körning

```bat
cd /d C:\AkerSyncRegression
git pull
RUN_VALUE_SOIL_PRICE_SURPRISE_V0G.bat
```

Normalt hittas Ferrari-referensen automatiskt i:

`C:\AkerSyncClass910\data\derived\agri_class5_10_v0c_ferrari\skifte_ferrari_scores.csv`

Om den inte hittas öppnas en filväljare.
