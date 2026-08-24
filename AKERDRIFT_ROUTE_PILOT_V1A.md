# ÅkerDrift ruttpilot V1a

Modellversion: `akerdrift-route-pilot-v1a-rc1.1`

Branch: `feature/akerdrift-route-pilot-v1a`

Detta är ett avgränsat valideringsexperiment, inte en ersättare för den
publicerade ÅkerDrift Fast V1-modellen. Piloten svarar på frågan om den enkla
P/A-modellen rankar hål, kilar, L-former och vändningstäta skiften annorlunda än
en faktisk geometrisk ruttapproximation.

## Vad piloten gör

För varje vald polygon provas parallella kördrag i riktningar 0–175° med 5°
steg. De tre bästa riktningarna förfinas i 1° steg. Motorn räknar:

- produktiv körsträcka med 9 m arbetsbredd,
- separata drag som uppstår av konkavitet, multipolygoner och interna hål,
- icke-produktiv övergång mellan dragen,
- minst en halvcirkel med 8 m radie per övergång,
- arbetstid vid 1,0 m/s och övergångs-/vändtid vid 0,5 m/s,
- ideal tid `T0 = area / (arbetsbredd × arbetshastighet)`,
- `route_geometry_score = 100 × T0 / T_route`, begränsad till 0–100.

Slutvärdet i pilotjämförelsen är:

```text
route_score = route_geometry_score × drift_terrain_factor från Fast V1
```

Fast och ruttpiloten använder därmed samma redan beräknade terrängfaktor. En
skillnad i score beror i denna pilot på geometrimodellen, inte på att lutning
har modellerats på två olika sätt.

## Avsiktliga begränsningar

- Motorn är den deterministiska Shapely-reserven, inte Fields2Cover.
- Vändningsvägarna är konservativa approximationer, inte fordonsdynamiska
  Dubins/Reeds–Shepp-banor.
- Vändtegens 24 m används för att dela upp inre körning och vändteg i
  diagnostiken. All produktiv körning har samma hastighet i RC1.
- TWI och körvägsriktad tvär-/längslutning ingår inte. Fast V1:s terrängfaktor
  återanvänds och TWI förblir utanför score.
- Okända infarter, sten, träd, diken, gröda och aktuell markfukt ingår inte.
- Resultaten ändrar inte webbdata eller UI automatiskt.

Detta gör piloten till ett tydligt test av just den fråga som Fast V1 inte kan
besvara: om total perimeter är en tillräcklig proxy för verkliga drag och
vändningar.

## Körning i Windows

Förutsättning: ÅkerDrift Fast V1 för Lomma ska redan finnas här:

```text
data\derived\akerdrift_fast_v1\by_municipality\lomma.parquet
```

Kör sedan:

```bat
RUN_AKERDRIFT_ROUTE_PILOT.bat
```

Det motsvarar:

```bat
py -3 src\45_akerdrift_route_pilot.py run --kommun Lomma --limit 200
```

Urvalet är deterministiskt och har två kohorter:

- 150 normalfält med en fungerande inåtbuffrad 24-meterskärna, fördelade över
  en 5×5-matris av area- och Fast-score-ranker,
- 50 stressfält som prioriterar tom 24-meterskärna, hål/fragment och komplexa
  gränser.

Hård spärr finns vid 200 skiften. Hela Lomma startas alltså inte av misstag.

Om det efter 24 m vändteg inte ryms en hel 9 m bred inre körlinje klassas
fältet som `SMALL_OR_NARROW_FIELD`. Samma status sätts om den simulerade
inre körsträckan blir noll trots en formellt icke-tom geometrisk kärna. Motorn
kör fortfarande en diagnostisk fullfältssvepning och sparar
`route_score_diagnostic`, men det officiella `route_score` lämnas null. Dessa
fall redovisas separat och ingår aldrig i huvudkorrelationen.

Varje färdigt skifte skrivs atomärt under `results/` och får därefter en egen
`checkpoints/*.done.json`. Om körningen avbryts kör man samma BAT-fil igen;
färdiga skiften skrivs då som `SKIP`.

## Resultat

Standardmapp:

```text
data\derived\akerdrift_route_pilot_v1a_rc1_1\lomma_200\
  sample_manifest.csv
  results\*.json
  checkpoints\*.done.json
  route_pilot_results.parquet
  failures.csv
  qa\comparison_summary.json
  qa\largest_disagreements.csv
  qa\holes_comparison.csv
  qa\stress_fields.csv
  qa\stress_summary.csv
  qa\small_or_narrow_fields.csv
```

`comparison_summary.json` innehåller huvudkohortens Spearman-korrelation,
median absolut scoredifferens och P95 absolut scoredifferens.
`largest_disagreements.csv` och `holes_comparison.csv` innehåller bara normala,
jämförbara fält. Stressfallen och små/smala fält ligger i separata filer så att
de kan granskas utan att förvränga huvudmåtten.

RC0- och RC1-körningarnas mappar och konfigurationer lämnas kvar oförändrade
för reproducerbarhet.

## Test

```bat
py -3 -m unittest tests.test_akerdrift_route_core
```

Testerna täcker stor rektangel, lång rektangel mot kvadrat, L-form, internt hål,
rotationsstabilitet, determinism, 0–100-bounds, exakt 150/50-urval, en
formellt icke-tom men smalare-än-arbetsbredd-kärna samt att
`SMALL_OR_NARROW_FIELD` utesluts ur huvudrapporten.
