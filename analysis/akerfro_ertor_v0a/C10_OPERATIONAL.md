# ÅkerFrö – Ärter MVP v0a · C10 Transparent Operational Layer

C10 gör ÅkerFrö mer produktnära utan att blanda ihop fysisk lämplighet och kommersiell logistik.

## Bevarade huvudmått

- **ÄrtMatch** – fryst fysisk/strukturell match.
- **C8 A/B/C/D** – rotation/förfrukt + hög fysisk match.
- **AreaFit** – nytt transparent operativt storleksmått.
- **BjuvProximity** – nytt transparent avståndsmått.
- **AreaLogistik** – operativ kombination av de två senare.

C10 skapar medvetet **ingen** enda totalscore som blandar ÄrtMatch med AreaLogistik.

## AreaFit

Piecewise-linear policy, 0–100:

| Area | Score |
|---|---:|
| 0 ha | 25 |
| 2 ha | 40 |
| 5 ha | 100 |
| 12 ha | 100 |
| 20 ha | 75 |
| 40 ha | 55 |
| 100+ ha | 40 |

Mellan knutarna interpoleras linjärt.

5–12 ha är en bred högplatå, inte ett påstående om exakt agronomiskt optimum. Formen baseras på C9/C9b:s robusta operativa historik men parametrarna är en transparent produktpolicy, inte label-optimerade.

## BjuvProximity

Monotont avtagande piecewise-linear policy:

| Fågelvägsdistans | Score |
|---|---:|
| 0–20 km | 100 |
| 40 km | 85 |
| 60 km | 70 |
| 80 km | 50 |
| 100 km | 35 |
| 140+ km | 15 |

Ingen hård 60-km-gräns används.

## AreaLogistik

    AreaLogistik = 0.55 * AreaFit + 0.45 * BjuvProximity

Vikterna är fasta policyvikter och har **inte optimerats mot historiska konservärtsfält**.

Operativa band:

- HIGH >= 80
- MEDIUM >= 60 och <80
- LOW <60

## Ranking

För kartor/listor används en lexikografisk ranking:

1. A före B före C före D.
2. Inom klassen: högre AreaLogistik först.
3. Därefter högre fryst ÄrtMatch.
4. Därefter field-id för deterministiska ties.

Detta undviker att en kommersiellt bekväm men fysiskt svag åker kan "köpa sig förbi" en starkare fysisk kandidat via en dold totalscore.

## Diagnostik

Efter att C10 policyn redan är fixerad redovisas historisk konservärt-enrichment per AreaLogistik-decil som sanity check.

Den diagnostiken får inte användas för att retuna C10 v0a i samma analys.

## Fortfarande utanför

- verklig väg-/skördetid till fabrik,
- kontrakt,
- bevattning/vattenrisk,
- farmer-ID och maskinpark,
- faktisk gröda 2026.
