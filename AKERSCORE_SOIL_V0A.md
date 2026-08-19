# ÅkerSync / ÅkerScore · jordfyrtupel v0a

## Syfte

Första MVP-hypotesen för **ÅkerScore Soil**: kan den moderna topsoil-signaturen

`(lera, silt, sand, mullproxy)`

återskapa en kontinuerlig del av den historiska svenska produktivitetsgradienten och samtidigt rangordna ett oberoende tyskt veteförsök i rätt riktning?

ÅkerScore är avsiktligt skilt från:

- **ÅkerVärde** – marknadspris / indikativ värdering,
- **ÅkerDrift** – maskinell brukningseffektivitet, geometri, access och framtida Fields2Cover-simulering.

## Träningssignal

v0a bygger vidare på den redan QA:ade `feature/agri-class-v0a`-analysen. Historisk klass 5–10 korsas med dagens DSMS2025 20 m-lager inom nuvarande 2025-jordbruksmark.

Historisk klass används **endast** när referensmolnen byggs. När en ny jordfyrtupel scoreas matas ingen historisk klass in. Därmed kan exempelvis en historisk klass-6-yta med modern klass-10-lik jord få ett mycket högt ÅkerScore.

## Varför inte regressa rå sand+silt+lera?

De tre mineralfraktionerna summerar ungefär till 100 %. De är därför kompositionsdata med bara två frihetsgrader. v0a använder två ILR-koordinater:

`z1 = 1/sqrt(2) * ln(clay/silt)`

`z2 = sqrt(2/3) * ln(sqrt(clay*silt)/sand)`

Mull lagras i DSMS2025 som klasser. De görs till en explicit **mullproxy**, inte till påstådda laboratorievärden. Modellfeaturen är `log1p(mullproxy)`.

## Klassmoln och score

För varje historisk klass 5–10 skattas ett multivariat referensmoln i det transformerade jordrummet. Kovariansen regulariseras.

Modellen använder lika klasspriorer så att stora klassarealer inte automatiskt får högre posterior sannolikhet.

För en ny jordpunkt beräknas:

1. posterior sannolikhet för varje historisk klass,
2. Mahalanobis-avstånd till varje klasscentrum,
3. empirisk centralitet inom varje klassmoln.

Varje historisk klass får ett nominellt 10-poängsband:

- klass 5: 40–50,
- klass 6: 50–60,
- klass 7: 60–70,
- klass 8: 70–80,
- klass 9: 80–90,
- klass 10: 90–100.

En typisk punkt i en klass ligger ungefär mitt i bandet; en mycket central klass-10-signatur kan närma sig 100. Slutscoren är posteriorvägd över samtliga klassband, så övergångarna blir kontinuerliga.

Det är ett designmål att få dynamik över skalan, men om fyrtupeln inte kan skilja historiska klasser som historiken skiljde åt ska detta redovisas som resultat – inte döljas genom att den sanna klassen injiceras i scoren.

## Tysk extern kontroll

Efter svensk fit scoreas publicerade klustermedel från:

**Groß et al. (2023), Plant and Soil 493:79–97, DOI 10.1007/s11104-023-06212-2.**

Triesdorf 2016, Table 5, innehåller tre jordtexturkluster per djup samt observerad höstveteskörd. För 0–10 cm var exempelvis:

- LS: 18.0 % lera, 34.3 % silt, 47.8 % sand, SOC 16.4 mg/g, 10.8 t/ha,
- HS-HC: 17.6 / 28.7 / 53.7, SOC 16.4 mg/g, 10.4 t/ha,
- HS-LC: 14.1 / 27.9 / 57.9, SOC 10.9 mg/g, 10.1 t/ha.

Den tyska skörden används **inte** i fitten. H1 är att svensk ÅkerScore ska ge samma rangordning som den observerade tyska skörden, särskilt i topsoil-lagren.

SOC omvandlas endast diagnostiskt till ungefärlig mull med den traditionella faktorn `SOM ≈ 1.724 × SOC`. Därför rapporteras även en texture-only-score som renare extern kontroll.

## Oberoende svensk produktivitetsreferens

**Hasund, Knut Per (1986), _Jordbruksmarken i naturresursekonomiskt perspektiv_, Sveriges Lantbruksuniversitet, Institutionen för ekonomi och statistik, Rapport 269, Uppsala.**

Hasunds senare fysiska produktivitetsklassning är inte samma karta som 1971 års klassning. Den är en separat referens där normskörd av korn standardiserades för bland annat kvävegiva. I den återgivning som finns i SOU 1991:38 är klassbredden 300 kg korn/ha vid 90 kg N/ha och gränsen mellan klass 1 och 2 är 2350 kg/ha.

Den referensen används i v0a som fysisk sanity-check för skaldynamik, inte som träningslabel.

## Första körning

1. Säkerställ att `RUN_AGRI_CLASS5_10_V0B.bat` redan har körts och att `data/derived/agri_class5_10_v0b/` finns.
2. Kör `RUN_AKERSCORE_SOIL_V0A.bat`.
3. Skicka tillbaka:
   - `report.txt`
   - `class_soil4_signature.csv`
   - `training_class_score_summary.csv`
   - `german_triesdorf_reference_scores.csv`

## Viktiga outputs

`data/derived/akerscore_soil_v0a/`

- `training_sample.csv.gz` – deterministiskt balanserat, parat pixelprov,
- `class_soil4_signature.csv` – klassvis beskrivning av fyrtupeln,
- `training_class_score_summary.csv` – hur mycket av 0–100-dynamiken fyrtupeln faktiskt återskapar,
- `german_triesdorf_reference_scores.csv` – helt separat tysk external-check,
- `model_metadata.json` – frysta transforms, moln och metadata,
- `report.txt` – körsammanfattning.

## Nästa beslut

v0a ska inte optimeras mot de tyska tre skördeutfallen. Först granskas om den fördefinierade svenska modellen rangordnar dem rätt. Om den gör det fryses resultatet som första externa konceptvalidering. Om den inte gör det undersöks varför innan modellen ändras.

Nästa naturliga steg är att utöka referensen från klass 5–10 till 1–10 och därefter lägga till separata ÅkerScore-dimensioner för z-profil, vatten/dränering och flerårig produktionsstabilitet.
