# ÅkerPass MVP v1.1 — releasefrysning

## Beslut

ÅkerPass fryses som **MVP v1.1** när den lokala fullbuilden, den automatiska
acceptance-QA:n och den manuella kartkontrollen nedan är godkända. Git-taggen
är den slutliga revisionspunkten:

`akerpass-mvp-v1.1`

Fil- och scriptnamn som fortfarande innehåller `V1` behålls för bakåtkompatibilitet.
Den publika metadataidentifieringen är däremot entydigt v1.1.

## Frysta komponenter

| Del | Fryst intern version | Beslut i v1.1 |
|---|---|---|
| ÅkerScore | `akerscore-soil-v0c` | Oförändrad jordmodell; skiftesvärde P50 och rumslig P10–P90 |
| ÅkerVärde | `akervarde-v1.0-rc1` | Produktionsgodkänd oförändrad BASE-artifact; år, log(area), latitud och longitud |
| ÅkerDrift | `akerdrift-fast-v2-hybrid-rc1` | Route-kalibrerad V2 inom kalibreringsstödet och fryst Fast V1-fallback utanför |
| Publikt dataset | `akerpass-public-v1.1` | 33 skånska kommuner, skifte/block och tre separata dimensioner |
| Produkt | `akerpass-mvp-v1.1` | Publik MVP-release |

ÅkerVärdes interna artifactnamn ändras inte från `v1.0-rc1`. Det bevarar
revisionskedjan till den förblindade modellfrysningen. Godkännandet i ÅkerPass
v1.1 ändrar inga koefficienter och gör ingen ny modellfit.

## Data- och referensår

- Jordbruksblock, skiften, markanvändning och gröda: **2025**.
- ÅkerVärdes referensnivå: **2026**.
- ÅkerVärde 100 är modellens referensnivå; indexet kan vara högre.

## Publika avgränsningar

- ÅkerScore, ÅkerVärde och ÅkerDrift är separata dimensioner.
- ÅkerVärde innehåller inte ÅkerScore eller ÅkerDrift som prisförklarare.
- Inga kronor, implicita hektarpriser eller interna modelljämförelser exporteras.
- Verifierad betesmark, slåtteräng och annan icke-åkermark visas som
  `Ej tillämpligt`; okänd markanvändning visas som okänd.
- P10–P90 betyder rumslig variation för ÅkerScore men bedömt intervall för
  ÅkerVärde.
- GPS-position sparas eller skickas inte.

## Release-QA

Kör från reporoten:

```bat
CHECK_AKERPASS_MVP_V1_1.bat
```

Kontrollen kör relevanta enhetstester, full webbbuild och separat acceptance-QA.
QA:n kräver bland annat:

- exakt 33 kommuner;
- icke-tomma ÅkerScore-, ÅkerVärde- och ÅkerDrift-lager;
- exakt frysta produkt-, dataset- och modellversioner i kommunfilerna;
- inga monetära publika fält;
- målpopulationsspärr för icke-åkermark;
- ÅkerVärdes toppfärg från 95 och uppåt;
- aktiv ÅkerDrift Hybrid RC1 utan publik V1-jämförelse;
- mobilpanel och GPS följ/av-funktioner.

Gör därefter en manuell kontroll i minst Lomma, Trelleborg och en nordlig
kommun:

1. växla mellan alla tre färglager;
2. öppna ett normalt åkerskifte och kontrollera alla tre talen;
3. öppna betes-/slåttermark och kontrollera `Ej tillämpligt`;
4. kontrollera ÅkerVärdes legend och ett värde nära 95–100;
5. kontrollera `Min position`, `Följ mig`, zoom och avslagen följning på mobil.

## HTTPS-kandidat och säker rollback på one.com

Mobilens GPS kräver normalt HTTPS. Paketera därför den redan QA-godkända
builden med:

```bat
PACKAGE_AKERPASS_MVP_V1_1.bat
```

Det skapar följande lokala filer:

```text
release/akerpass_mvp_v1_1_candidate.zip
release/akerpass_mvp_v1_1_candidate.zip.sha256.txt
```

På one.com används följande ordning:

1. Skapa undermappen `_candidate_v1_1` i samma webbrot som nuvarande
   `index.html`.
2. Ladda upp ZIP-filen till `_candidate_v1_1` och extrahera den där. Kontrollera
   att `_candidate_v1_1/index.html` finns direkt i mappen och inte i ytterligare
   en `dist`-mapp.
3. Öppna `https://akerpass.se/_candidate_v1_1/` på mobilen. Kandidaten får då
   HTTPS och kan använda GPS, medan den befintliga livesajten är orörd.
4. Genomför den manuella kontrollen, särskilt `Följ mig`, `+`, `−` och
   fingerzoom.

Först efter godkänt kandidattest:

5. Skapa `_rollback_before_v1_1` i webbroten.
6. Kopiera den nuvarande livesajtens filer och mappar till rollbackmappen.
   Kandidat- och rollbackmapparna ska inte kopieras in i sig själva.
7. Kontrollera att rollbackmappen innehåller den gamla `index.html` och dess
   data-/kommunmappar.
8. Kopiera innehållet i `_candidate_v1_1` till webbroten och ersätt motsvarande
   livefiler.
9. Öppna `https://akerpass.se/` i ett privat fönster eller gör en hård
   omladdning och upprepa ett kort smoke-test.

Om produktionskopieringen ger fel återställs livefilerna från
`_rollback_before_v1_1`. Git-taggen skapas inte förrän även testet på den
ordinarie rotadressen är godkänt.

## Taggning efter godkänd QA

Tagga endast en ren, pushad commit:

```bat
git status --short
git push
git tag -a akerpass-mvp-v1.1 -m "Freeze ÅkerPass MVP v1.1"
git push origin akerpass-mvp-v1.1
```

Lokala, orelaterade otrackade filer kan ligga kvar, men inga ocommittade
ändringar i de versionshanterade releasefilerna får finnas när taggen skapas.

## Utanför v1.1

ÅkerKontext, satellit-/väderlager, flerårig produktionsstabilitet och en ny
ÅkerVärde-modell med eventuellt verifierat bidrag från ÅkerScore eller
ÅkerDrift hör till senare versioner. Kandidater med hög fysisk kvalitet relativt
lokal marknadsnivå får inte beskrivas som undervärderade utan separat evidens.
