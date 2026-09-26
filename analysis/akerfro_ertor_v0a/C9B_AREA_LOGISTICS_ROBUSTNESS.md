# ÅkerFrö – Ärter MVP v0a · C9b Area/logistics robustness

C9b testar om C9:s observerade area- och Bjuv-avståndssignaler är stabila nog för att senare få påverka en C10-produktpolicy.

Ingen C8-klass ändras och fryst ÄrtMatch v0a förblir read-only.

## Kandidatuniversum

Endast fält som i C8 är:

- A_STRONG_CANDIDATE
- B_PHYSICAL_CANDIDATE

Det betyder hög ÄrtMatch och ROTATION_OK.

## Test 1 – area inom distansband

För varje Bjuv-avståndsband beräknas historisk konservärtandel för varje areaband och enrichment relativt just det avståndsbandets basnivå.

Syfte: kontrollera om 5–12 ha fortfarande ser attraktivt ut när geografisk närhet hålls ungefär konstant.

## Test 2 – distans inom areaband

Motsvarande analys åt andra hållet.

Syfte: kontrollera om kortare Bjuv-avstånd fortfarande bär signal när fältstorlek hålls ungefär konstant.

## Test 3 – kommunstruktur

För varje distansband redovisas kommunernas:

- antal kandidatfält,
- andel av fälten i bandet,
- antal historiska konservärtsfält,
- andel av positiva i bandet,
- historisk positiv rate.

Det visar om ett distansband i praktiken drivs av en eller ett fåtal kommuner.

## Test 4 – post-hoc sweet zone

C9 observerade ungefär 5–12 ha och <60 km som en intressant operativ zon.

C9b testar därför denna zon mot övriga A/B-fält globalt och inom kommun.

Detta är uttryckligen **post-hoc diagnostik**, inte en fryst regel.

Kommuner räknas som evaluerbara vid minst 100 A/B-fält totalt och minst 20 sweet-zone-fält.

## Test 5 – leave-one-municipality-out

En enkel logistisk modell tränas om med en kommun i taget helt utelämnad.

Features:

- standardiserad log(area),
- log(area)^2,
- standardiserat Bjuv-avstånd,
- distance^2.

Ingen kommunfeature används.

Vi redovisar:

- AUC per utelämnad kommun,
- pooled leave-one-municipality-out AUC,
- koefficienter per fold,
- teckenstabilitet för area-kurvatur och distans,
- implied optimum bara när kvadrattermen är konkav.

Modellen är en robusthetsdiagnostik för historisk selektion, inte sannolikhet för agronomisk framgång.

## Beslutspunkt efter C9b

Först om area- och distanssignalerna är rimligt stabila går vi vidare till C10 och definierar en transparent AreaLogistik-komponent. Annars behålls area/distans som informationslager utan rankingeffekt.
