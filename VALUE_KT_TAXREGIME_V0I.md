# ÅkerSync Value Regression v0i — K/T taxeringsregimer

## Fråga

v0h modellerade `log(K/T exact)` med ett linjärt kalenderår. v0i testar om den
tidsstrukturen är för grov när taxeringsvärdet i nämnaren uppdateras i diskreta
regimer.

## Input

v0i återanvänder låst v0h-output:

`data/derived/value_regression_v0h_kt_expanded/expanded_kt_features.csv`

Ingen blockrekonstruktion, GIS-matchning eller DSMS-sampling görs om.

## Tidsmodeller

Tre fördeklarerade strukturer jämförs:

1. `LINEAR`: v0h:s `year_centered`.
2. `REGIME`: 2020–22 som referens, dummy för 2023–25 och dummy för 2026+.
3. `REGTREND`: samma regimdummies plus `year_within_taxreg` (0,1,2,...),
   dvs en gemensam marknadstrend mellan omvärderingspunkterna.

Detta är en modellstruktur, inte ett kausalt påstående om varför K/T ändras.

## Modellsteg

Samma fyra sampel som v0h används:

- `S80_NOFOREST`
- `S70_NOFOREST`
- `S50_ALL`
- `ALL_ARABLE`

För varje sample jämförs geo, fastighetsmix och beskaffenhet under linjär,
regim- och regim+trend-tid.

Incrementella tester refittar alltid baslinjen på exakt samma rader som den
utökade modellen.

## Modern soil-surprise

För transaktioner med FerrariScore skapas en separat exact-LOO residual:

`soil_surprise_besk_geo = FerrariScore - E_LOO(FerrariScore | beskaffenhet, mixed, lat, lon)`

Den testas sedan ovanpå `REGTREND_MIX_BESK`.

Detta är ett direkt test av om modern class-10-lik jord som är bättre/sämre än
vad administrativ beskaffenhet + lokal geografi antyder också syns i K/T.

## Output

- `report.txt`
- `tax_regime_summary.csv`
- `kt_regime_features.csv`
- `kt_regime_model_comparison.csv`
- `kt_regime_model_coefficients.csv`
- `kt_regime_incremental_tests.csv`
- `soil_surprise_besk_geo_model.csv`

## Guardrails

- K/T är hela fastighetspaketets marknadspremie/discount mot totalt taxeringsvärde.
- ATL:s taxeringsvärde antas vara relevant för transaktionsposten; v0i verifierar
  inte detta mot separat historiskt taxeringsregister.
- FerrariScore/DSMS är modellerad jorddiagnostik, inte jordprov eller produktionsfacit.
- Negativt Ferrari-/surprise-increment säger inget direkt om jordens intrinsiska
  produktionsvärde; det säger att signalen inte förbättrar K/T-prediktion i samplet.
