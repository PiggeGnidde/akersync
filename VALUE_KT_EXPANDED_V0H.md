# ÅkerSync · Value Regression v0h · expanded K/T sample

## Fråga
Kan ATL:s totala taxeringsvärde användas som package-level normalisering så att bebyggda och delvis blandade lantbruksfastigheter kan bidra till prisanalysen?

Målvariabel:

`log(K/T exact) = log(köpeskilling / totalt taxeringsvärde)`

Detta är inte ett estimat av rent åkerpris. Det är marknadens premie/rabatt relativt hela taxeringspaketet.

## Sample tiers

- `S80_NOFOREST`: minst 80 % åker, ingen skog.
- `S70_NOFOREST`: minst 70 % åker, ingen skog.
- `S50_ALL`: minst 50 % åker, skog tillåts och kontrolleras.
- `ALL_ARABLE`: alla QA-godkända marknadsaffärer med åker.

Main QA: datum >= 2020-07-01, market-sale flag, positiv köpeskilling/taxering, positiv och konsistent areal, koordinater, exact K/T 0.5–6.

## Beskaffenhet

ATL-fältet kommer från fastighetstaxeringens värdefaktor för åkermark. Det beskriver produktionsförmåga och brukningsförhållanden relativt värdeområdet; det är inte pH, P-AL, K-AL eller annan laboratorieanalys.

Textnivåerna mappas diagnostiskt:

- mycket bättre = +2
- bättre = +1
- normal = 0
- sämre = -1
- mycket sämre = -2

Om ATL visar flera värderingsenheter i samma affär används ett oviktat medelvärde av de distinkta textnivåerna och `mixed` flaggas. Detta är en approximation eftersom ATL-CSV:n saknar areavikter per beskaffenhetsenhet.

## Dränering

ATL innehåller både äldre och nyare taxeringsordalydelser. Äldre uppgifter kan skilja mellan system/plantäckdikning, annan tillfredsställande/självdränerad mark och otillfredsställande dränering. Nuvarande system är funktionellt tvåklassigt. v0h behåller därför äldre systemtäckdikning som en separat känslighetskategori i stället för att låtsas att systemen är identiska.

Historiska dräneringsuppgifter ska inte betraktas som säker ground truth.

## Modeller

`GEO`: år + lat + lon.

`MIX`: GEO + taxeringsvärdets storlek + åker/skog/bete-andelar + småhus/economibyggnadsindikatorer och log-kvm.

`MIX_BESK`: MIX + beskaffenhetsscore + mixed-flagga.

Där blockrekonstruktionen klarar ±20 % och DSMS finns testas också:

`MIX_FERRARI` och `MIX_BESK_FERRARI`.

FerrariScore använder samma frusna class-10-referens som v0g/v0c; v0h refittar inte jorddefinitionen mot pris.

Primär jämförelse är exakt leave-one-out R² och delta LOO på samma rader. Zero-variance nuisance-termer tas bort adaptivt inom sample tier (t.ex. `forest_share=0` i NOFOREST).

## Körning

`RUN_VALUE_KT_EXPANDED_V0H.bat`

Output: `data/derived/value_regression_v0h_kt_expanded/`

Viktigast att granska efter körning:

- `report.txt`
- `sample_counts.csv`
- `kt_model_comparison.csv`
- `kt_incremental_tests.csv`
- `kt_model_coefficients.csv`
- `beskaffenhet_summary.csv`
- `drainage_summary.csv`
- `expanded_kt_features.csv`

## Guardrails

- K/T är en fastighetsmix-premie, inte rent åkerpris.
- Taxeringsvärdet kan vara trögt, regionalt och modellbaserat; modellen testar marknadsavvikelse från taxeringen.
- Beskaffenhet är en taxeringsklass, inte en direkt jordmätning.
- DSMS2025 är modellerad jordinformation.
- Blockrekonstruktion är en proxy och används fortfarande med strikt QA.
