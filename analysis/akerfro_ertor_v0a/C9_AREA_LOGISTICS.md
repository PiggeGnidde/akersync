# ÅkerFrö – Ärter MVP v0a · C9 Area + Bjuv-logistik

C9 är en **diagnostik före policy**. Den ändrar inte ÄrtMatch v0a och ändrar inte C8:s A/B/C/D-klasser.

## C8b före C9

C8 körs om med skärpt stödkrav: en t-1-gröda får ge POSITIVE predecessor prior för A-klassen först vid minst **50 historiska positiva konservärt-händelser**.

Det gör att små signaler som rågvete/stärkelsepotatis inte ensamma kan lyfta ett fält till A.

## Area

C9 använder fältarealen som ett operativt urvalslager, inte som fysisk ÄrtMatch.

Diagnostiska bins:

- <2 ha
- 2–5 ha
- 5–8 ha
- 8–12 ha
- 12–20 ha
- 20+ ha

För varje bin redovisas historisk konservärtandel och enrichment både i hela populationen och bland fält med hög ÄrtMatch + rotation OK.

## Bjuv-logistik

Processorankare:

- Apetit Sverige / Bjuv frozen pea factory
- Billesholmsvägen 4, 267 40 Bjuv
- WGS84 56.0731 N, 12.9395 E

C9 försöker read-only återanvända befintliga lokala koordinat-/geometrifiler i C:\AkerSync*-träden.

Första diagnostiken använder **haversine/fågelvägsdistans**, inte vägdistans.

Bins:

- <20 km
- 20–40 km
- 40–60 km
- 60–80 km
- 80–100 km
- 100+ km

Om koordinater inte kan upptäckas automatiskt ska C9 fortfarande ge arearesultatet och PASS; coordinate_source_discovery.csv används då för nästa deterministiska patch.

## Area × distans

När koordinater finns byggs också en 2D-tabell bland:

**high ÄrtMatch + ROTATION_OK**

Det är denna tabell som ska avgöra om en senare C10-produktpolicy bör ha t.ex. minsta praktisk area, logistikband eller båda.

## Guardrail

C9 mäter historisk selektion och operativ struktur. Den tolkar inte area eller Bjuv-avstånd som biologisk ärtlämplighet.
