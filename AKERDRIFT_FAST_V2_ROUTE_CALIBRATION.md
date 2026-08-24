# ÅkerDrift Fast V2 – ruttkalibrerad RC0-kandidat

Modellversion: `akerdrift-fast-v2-routecal-rc0`

Detta är en fryst **kandidatmodell**, inte en automatisk ändring av publicerad
ÅkerDrift eller ÅkerPass. Den ersätter Fast V1:s enkla P/A-geometripoäng med en
billig surrogate som har kalibrerats mot ruttpilot RC1.1. Terrängfaktorn är
oförändrad och TWI ligger fortsatt utanför score.

## Underlag

- Lomma, Eslöv och Simrishamn: 200 deterministiskt valda skiften per kommun.
- 450 normalfält och 75 jämförbara stressfält används i kalibreringen.
- 75 `SMALL_OR_NARROW_FIELD` hålls helt utanför regressionsmodellen.
- Inga ruttfel förekom i de 600 pilotkörningarna.

Urvalet är avsiktligt stratifierat för modellval och är inte ett slumpmässigt
urval av alla skånska skiften. Ruttscoren är dessutom en deterministisk
simuleringsreferens, inte uppmätt bränsle- eller tidsdata.

## Fryst modell

Modellen är en additiv, styckvis linjär ridge-modell med tre knutar per
kontinuerlig variabel (träningskvantilerna 25, 50 och 75 procent). Den använder
bara redan billigt tillgängliga Geometry V1a/Fast V1-mått:

- Fast V1-geometripoäng,
- log(areal i hektar),
- rectangularity,
- compactness,
- log(ERL i meter),
- indikator för minst ett hål,
- antal hål begränsat till högst fem.

Varje kontinuerlig variabel klipps till kalibreringsintervallet före
prediktion. Den frysta JSON-filen innehåller intervall, knutar,
standardisering, koefficienter och intercept. Produktion kräver endast NumPy;
scikit-learn är inte ett nytt körberoende.

Slutvärdet är:

```text
ÅkerDrift Fast V2 = klipp(geometriprediktion, 0, 100) × befintlig terrängfaktor
```

## Validering mot helt osedd kommun

Vid varje fold tränas modellen på två kommuners normal- och jämförbara
stressfält. Den tredje kommunen hålls helt utanför träningen.

| Kohort | Modell | n | Spearman | Median \|Δ\| | P95 \|Δ\| |
|---|---|---:|---:|---:|---:|
| Normal | Fast V1 | 450 | 0,810 | 6,19 | 15,94 |
| Normal | Fast V2 RC0 | 450 | 0,936 | 1,94 | 8,73 |
| Stress, jämförbar | Fast V1 | 75 | 0,917 | 5,00 | 15,82 |
| Stress, jämförbar | Fast V2 RC0 | 75 | 0,925 | 2,84 | 11,66 |

Fast V2 generaliserar i alla tre utelämnade kommuner. Normalfältens Spearman
är 0,932 i Eslöv, 0,914 i Lomma och 0,941 i Simrishamn. Stresskohorten är liten
(25 jämförbara fält per kommun), så dess kommunvisa P95 ska inte övertolkas.

## Reproducerbar körning

Pilotmapparna ska finnas under:

```text
data\derived\akerdrift_route_pilot_v1a_rc1_1\lomma_200
data\derived\akerdrift_route_pilot_v1a_rc1_1\eslov_200
data\derived\akerdrift_route_pilot_v1a_rc1_1\simrishamn_200
```

Kör:

```bat
CALIBRATE_AKERDRIFT_FAST_V2.bat
```

Resultatet hamnar i `data\derived\akerdrift_fast_v2_calibration`:

- `akerdrift_fast_v2_routecal_rc0.json`
- `leave_one_municipality_out.csv`
- `fast_v1_baseline.csv`
- `held_out_predictions.csv`

Repo-konfigurationen `config/akerdrift_fast_v2_routecal_rc0.json` är den frysta
modellen från de tre verifierade pilotkörningarna.

## Beslut före publicering

Kör den frysta modellen över alla skånska skiften med:

```bat
APPLY_AKERDRIFT_FAST_V2_SKANE.bat
```

Körningen läser den befintliga sammanslagna Fast V1-filen och Geometry V1a,
men skriver endast till `data\derived\akerdrift_fast_v2_routecal_rc0`. Fast V1
sparas sida vid sida i resultatet. QA redovisar extrapolationsandel,
fördelningsskifte, kommunjämförelser, hålskiften och de 250 största
scoreförändringarna.

Webbens ÅkerDrift ska inte bytas till V2 förrän denna kontroll och ett visuellt
stickprov är godkända.
