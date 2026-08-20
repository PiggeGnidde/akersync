# ÅkerPass MVP UI V1

## Status och Git-gren

UI-integrationen finns endast på `feature/akerpass-ui-v1`. Den är inte mergad
till `main`. De två frysta modellgrenarna har inte ändrats.

Integrationsgrenen utgår från `feature/value-regression-v0a` vid `6ff6550` och
har kontrollerat tagit in `feature/akerscore-v1a` vid `6cc4810`. Båda grenarna
har samma kart-/geometribas, `df67125`.

## Inventerade grenar

| Gren | Inventerat innehåll | Användning i V1 |
|---|---|---|
| `main` (`4075344`) | Reproducerbar trekommuns-bas | Historisk bas, inte UI source of truth |
| `feature/skane-scale` / `release/skane-v1.0` (`f91b88d`) | Skånes 33 kommuner, regionbygg, jord/topografi/hydrologi | 33-kommuners datakedja |
| `feature/geometry-v1a` / `release/skane-geometry-v1.1` (`df67125`) | Senaste fungerande kartbas, skiftesgeometri och mobil/GPS-fix | Direkt kartbas |
| `feature/akerscore-v1a` (`6cc4810`) | Fryst ÅkerScore soil v0c och skiftesoutput | Läser v0c P10/P50/P90 utan modelländring |
| `feature/value-regression-v0a` (`6ff6550`) | Fryst ÅkerVärde v1.0-rc1, BASE-artifact och blindtestdokumentation | Läser de frysta BASE-koefficienterna |
| `feature/agri-class-v0a` (`5f1ec93`) | Historisk klassreferens och ÅkerScore-förutsättningar | Medföljer ÅkerScore-historiken |
| `feature/satellite-v1a` (`c5cc4b2`) | Satellit-/väderexperiment | Inte publicerat i MVP V1; ännu inget fryst huvudlager |

Ingen feature-gren har mergats till `main`.

## Tidigare source → build → dist

Den produktionsnära 33-kommunerskartan byggdes så här:

```text
web/template_v092.html
    ↓ src/07_build_web.py
dist/index.html + dist/municipalities/*.html
    ↓ src/07b_enhance_web_geometry_mobile.py
Geometry V1a + förbättrad skiftesklick/mobil/GPS
```

`dist/` är genererad och versionshanteras inte. Den aktuella filen på Bengts
dator är därför ett lokalt buildresultat, inte en källfil i Git.

## ÅkerPass V1 source → build → dist

V1 behåller Leaflet och de befintliga validerade derived-filerna men byter till
en explicit publik, kommunvis dataladdning:

```text
fryst ÅkerVärde-artifact + aktuella skiften
    ↓ src/40_build_akervarde_public_index.py
data/derived/akerpass_public_v1/akervarde_public_skiften.csv

geometry + soil + topography + hydrology + Geometry V1a
+ fryst ÅkerScore v0c + publikt ÅkerVärde-index
    ↓ src/41_build_akerpass_public_data.py
data/derived/akerpass_public_v1/municipalities/*.json
    ↓ kopieras som deploybara chunks
dist/data/municipalities/*.json

web/akerpass_v1.html + dist/municipalities.json
    ↓ src/42_build_akerpass_frontend.py
dist/index.html
    ↓ src/43_verify_akerpass_web_v1.py
statisk acceptance-QA
```

Hela kedjan körs av `BUILD_AKERPASS_WEB_V1.bat` via
`src/build_akerpass_web_v1.py`.

## Frysta modeller

### ÅkerScore

- Modell: ÅkerScore Soil v0c från `feature/akerscore-v1a`.
- Skiftesdefinition: P50 av pixelwise ÅkerScore.
- P10–P90: spatial variation inom skiftet, inte konfidensintervall.
- UI-text: **Inomfältsvariation P10–P90**.
- Input: `data/derived/akerscore_soil_v0c/akerscore_soil_skiften.csv`.

### ÅkerVärde

- Modell: `akervarde-v1.0-rc1`, fryst `S70_NOFOREST / BASE`.
- BASE-koefficienter läses från den lokala, immutabla freeze-artifacten.
- Modellår: 2026.
- Area: skiftets geometri i SWEREF 99 TM.
- Position: skiftets geometriska centroid, transformerad till WGS84.
- Punktindex: fryst BASE-rate normaliserad enligt det frysta produktbeslutet.
- P10: `0.8256 × punktindex`.
- P90: `1.4886 × punktindex`.
- Ingen cap vid 100.
- UI-text: **Prediktionsintervall P10–P90**.

Punktvärdet använder BASE och inte den efterkalibrerade P50-multiplikatorn.

## Publik export och monetär brandvägg

`40_build_akervarde_public_index.py` skapar ÅkerVärdes monetära BASE-rate endast
som en lokal array i minnet. Den läggs aldrig i en DataFrame eller fil.

Den publika ÅkerVärde-CSV:n har exakt följande kolumner:

```text
blockid
skiftesbeteckning
kommun
akervarde
akervarde_p10
akervarde_p90
akervarde_model_version
akervarde_reference_year
```

Public-buildern använder en vitlista och avbryter dessutom om ett förbjudet
internt/monetärt fältnamn skulle förekomma i en publik kommunfil. QA:n skannar
både publika JSON-nycklar och UI-text.

## Publika skiftesfält

Varje GeoJSON-skifte innehåller:

- identitet: `id`, `block_id`, `skifte_id`, `kommun`;
- `area_ha`;
- `akerscore`, `akerscore_p10`, `akerscore_p90`;
- `akervarde`, `akervarde_p10`, `akervarde_p90`;
- `akerdrift: null`;
- jorddetaljer på skiftesnivå;
- Geometry V1a på skiftesnivå;
- topografi och hydrologi på blocknivå, uttryckligen märkta med `data_scope`;
- historisk jordbruksklass som referensdata;
- grödkod och referensnamn;
- coverage/QA och modellversioner.

Block publiceras som en tunn, icke-klickbar gränsoverlay. Inga blockaggregat av
ÅkerScore eller ÅkerVärde fabriceras.

## Frontend

- En karta med kommunväljare för alla 33 skånska kommuner.
- Endast ett huvudfärglager i taget: ÅkerScore eller ÅkerVärde.
- ÅkerDrift finns som disabled placeholder.
- ÅkerVärde-legenden fortsätter över 100 och markerar referensnivån.
- Skiftesklick öppnar höger drawer på desktop och bottom sheet på mobil.
- Sammanfattningen visar de tre dimensionerna först; nörddata ligger i
  expanderbara sektioner.
- Stort stängkryss, intern scroll och touch targets på minst cirka 42–48 px.
- `Min position` använder `getCurrentPosition`.
- `Följ mig` använder `watchPosition` och anropar `clearWatch` när läget stängs
  av eller sidan lämnas.
- Positionsdata sparas eller skickas inte.

## Förutsättningar

Följande lokala derived outputs ska redan finnas:

```text
data/derived/geometry_payload.json
data/derived/soil_payload.json
data/derived/topography_features_blocks.csv
data/derived/hydrology_features_final.csv
data/derived/geometry_v1a_skiften.csv
data/derived/akerscore_soil_v0c/akerscore_soil_skiften.csv
data/derived/akervarde_v1_0_rc1_freeze/model_coefficients.csv
```

Om Geometry V1a saknas bygger BAT-filen den automatiskt. Frysta modelloutputs
byggs aldrig automatiskt om: då får användaren ett tydligt fel och rätt runner.

## Bygg lokalt på Windows

Från `C:\AkerSyncRepo`:

```bat
git fetch --all
git switch feature/akerpass-ui-v1
git pull
BUILD_AKERPASS_WEB_V1.bat
```

Om bygget säger att en fryst output saknas:

```bat
RUN_AKERSCORE_SOIL_V0C.bat
FREEZE_AKERVARDE_V1RC.bat
BUILD_AKERPASS_WEB_V1.bat
```

Starta sedan den lokala statiska servern:

```bat
START_AKERPASS_LOCAL.bat
```

Öppna `http://localhost:8000/`. Använd inte dubbelklick på `index.html`, eftersom
kommunfilerna laddas med browserns `fetch` och därför ska köras via HTTP.

Direkt QA utan ombyggnad:

```bat
py -3 src\43_verify_akerpass_web_v1.py
```

## Output

```text
dist/index.html
dist/municipalities.json
dist/data/municipalities/1214-svalov.json
...
dist/data/municipalities/1293-hassleholm.json
```

Hela `dist/` deployas som en vanlig statisk webbplats.

## Kända begränsningar i V1

- ÅkerDrift är medvetet tom tills modellen fryses.
- ÅkerVärde är ett marknadsindex, inte en individuell värdering eller
  regulatorisk bankvärdering.
- Topografi och hydrologi är i nuvarande pipeline blockmått och märks så i UI.
- Satellitdata är ännu inte ett fryst publikt ÅkerPass-lager.
- Visuell mobiltest på Bengts faktiska iPhone/Android och browser återstår efter
  att hela lokala Skåne-outputen byggts.
- Leaflets JavaScript och bakgrundskartor hämtas externt. Leaflets kritiska
  layout-CSS är inbakad i frontendfilen och själva ÅkerPass-datan är statisk.
- Gröda och markanvändning avser Jordbruksverkets skiftesdata för 2025.
  ÅkerVärde visas endast för verifierad åkermark; tydlig betes-/slåttermark,
  annan icke-åkermark och okänd markanvändning visas som ej tillämpligt.
- Skyddad natur/naturreservat är ännu inte ett integrerat datalager. En åkerkod
  innanför skyddad natur kan därför inte spärras enbart på reservatsstatus i V1.
- Den historiska jordbruksklassningen från 1971 är i V1 importerad endast för
  klass 5–10. Ett tomt klassvärde betyder därför inte saknade moderna jorddata
  och bevisar inte klass 1–4; det betyder att skiftets representativa punkt inte
  ligger i det importerade 5–10-underlaget.
- ÅkerDrift använder `akerdrift-fast-v1-rc0`: en empiriskt förankrad
  perimeter/area-proxy i SI-enheter med en konservativ lutningsjustering.
  Skiftesvis TWI visas diagnostiskt men påverkar inte ÅkerDrift-poängen.
- ÅkerDrift-resultaten byggs restart-säkert kommunvis innan denna publika build.
  Se `AKERDRIFT_FAST_V1.md` och `RUN_AKERDRIFT_FAST_V1.bat`.
