# ÅkerSwap – STOPPUNKT A + B1/B2/B3

**Datum:** 2026-10-05  
**Branch:** `feature/akerswap-mvp-v0a`  
**Status:** STOPP efter prioriterad feasibility/falsifieringssprint  
**Nästa steg:** endast efter projektledarprioritering

---

## 1. Fråga

Kan ÅkerSwap skapa värde genom att hitta agronomiskt ungefär likvärdiga skiften som kan bytas mellan brukare för att minska geografisk fragmentering och körning, utan att vi först behöver veta vem som arrenderar varje skifte?

Projektordern var:

1. ÅkerSwap A – Sjöbo substitutions-feasibility.
2. Om A PASS/MARGINAL: B1+B2+B3 som en sammanhållen falsifieringssprint:
   - B1 single hub,
   - B2 multi-hub,
   - B3 sparse-swap.
3. Stanna därefter. Ingen webb och ingen riktig pilot.

---

# 2. STOPPUNKT A – substitutions-feasibility

## Data

Sjöbo 2025:

- råa skiften: **7 717**
- eligible med både ÅkerScore och ÅkerDrift: **7 342**
- ÅkerScore coverage: **95,2 %**
- ÅkerDrift coverage: **100,0 %**

CORE-match:

- arealskillnad <= 20 %
- |Δ ÅkerScore| <= 10
- |Δ ÅkerDrift| <= 10

STRICT-match:

- arealskillnad <= 10 %
- |Δ ÅkerScore| <= 5
- |Δ ÅkerDrift| <= 5

Direkt angränsande kandidater exkluderades även i ett robusthetstest med polygonavstånd <= 10 m.

## Resultat

- CORE: minst 1 kandidat inom 2 km: **94,3 %**
- CORE: minst 5 kandidater inom 2 km: **68,1 %**
- CORE: minst 1 kandidat inom 5 km: **99,0 %**
- CORE: minst 5 kandidater inom 5 km: **92,7 %**
- STRICT: minst 1 kandidat inom 2 km: **71,8 %**
- CORE utan direkt angränsande skiften: minst 1 kandidat inom 2 km: **93,6 %**
- CORE utan direkt angränsande skiften: minst 1 kandidat inom 5 km: **98,9 %**
- medianavstånd till närmaste CORE-likvärdiga kandidat: **0,427 km**

## A-dom

**PASS – starkt.**

Tolkning:

> Brist på ungefär likvärdiga lokala substitut verkar inte vara ÅkerSwaps huvudproblem i Sjöbo.

Resultatet överlever både stramare likvärdighetskrav och exkludering av direkt angränsande skiften.

---

# 3. STOPPUNKT B1 – single-hub

24 automatiskt skapade lokala Sjöbo-cases med 180 riktiga fält vardera.

Tre scenarier:

- CONTROL – geografiskt rationell tvåbrukar-baseline
- FRAG10 – ca 10 % likvärdig areal korsbytt syntetiskt
- FRAG20 – ca 20 % likvärdig areal korsbytt syntetiskt

Single-hub median logistisk förbättring:

- CONTROL: **0,0 %**
- FRAG10: **25,3 %**
- FRAG20: **28,1 %**

## Tolkning

CONTROL = 0,0 % är ett viktigt sanity check-resultat.

Solvelogiken skapar inte automatiskt stora förbättringar där basportföljen redan är geografiskt rationell.

Syntetisk fragmentering ger däremot en stark och tydlig signal.

FRAG10 -> FRAG20 ökar bara från 25,3 till 28,1 %, vilket antyder kraftigt avtagande marginalnytta: de mest skadliga geografiska korsningarna står för en stor del av potentialen.

---

# 4. STOPPUNKT B2 – multi-hub falsifiering

FRAG20 median gain:

- 1 hub: **28,1 %**
- 2 hubbar: **5,5 %**
- 3 hubbar: **7,5 %**

Survival relativt single-hub:

- 2 hubbar: **19,5 %**
- 3 hubbar: **26,6 %**

## Tolkning

Detta är ett viktigt **konservativt falsifieringstest**, men ska inte tolkas som en realistisk standardmodell för en typisk lokal Sjöbo-gård.

I B2 fick varje syntetisk brukarportfölj fritt använda 2–3 optimalt placerade operationella hubbar inom ett relativt begränsat lokalt område. Detta är sannolikt en betydligt generösare multi-hub-modell än vad som normalt är ekonomiskt eller praktiskt motiverat inom en liten skånsk kommun.

När flera hubbar tillåts på detta sätt försvinner ungefär 3/4–4/5 av den naiva single-hub-vinsten. Resultatet visar därför:

> ÅkerSwap-värdet kan överskattas kraftigt om man antar att all mark måste betjänas från en enda punkt, men det kan också underskattas om man tillåter extra hubbar utan geografisk eller ekonomisk kostnad.

Det svenska exempel som motiverade multi-hub-idén, Kulla Gunnarstorp/Österlen, gäller geografiskt tydligt separerade driftområden på mycket längre avstånd än de lokala Sjöbo-casen.

### Praktisk designhypotes

I Skåne, med relativt små kommuner, är det rimligt att anta att fullvärdiga separata operationella hubbar oftast blir relevanta först när markinnehavet bildar större geografiskt separerade kluster, ofta:

- interkommunalt, eller
- över flera kommuner,
- och på avstånd där egen maskinpark, lager eller satellitdrift faktiskt kan motiveras.

Lokal fragmentering inom samma eller närliggande små kommunområden bör därför normalt först testas mot en **single-hub-modell**, medan multi-hub används som separat korrigering för verkliga fjärrkluster.

En framtida multi-hub-modell bör därför inte få skapa hubbar gratis. Den bör minst innehålla:

- minsta geografiska separation mellan hubbar,
- minsta areal/volym i ett fjärrkluster,
- alternativt en explicit kostnad/penalty för att etablera extra hubb.

ÅkerSwap får fortfarande aldrig ranka fjärrmark som ineffektiv enbart utifrån avstånd till juridiskt gårdscentrum. Ett stort separat fjärrkluster med egen driftbas kan vara helt rationellt.

Samtidigt ska B2-resultatet inte användas som argument för att den realistiska lokala ÅkerSwap-vinsten i Sjöbo endast är 5–8 %. **5–8 % är ett konservativt worst-case efter en mycket generös multi-hub-korrigering**, inte en skattning av normal lokal verklighet.

Notera att 3-hub-resultatet är något bättre än 2-hub-resultatet. Detta ska inte övertolkas. Hubbarna infereras separat och greedy pair-swap är inte ett globalt optimerat joint hub+swap-problem.

---

# 5. STOPPUNKT B3 – sparse-swap

För FRAG20 med 2 hubbar:

- 5 % swap-budget fångar median **36,6 %** av full greedy gain
- 10 % swap-budget fångar median **64,7 %** av full greedy gain

## Tolkning

Detta stödjer hypotesen att ÅkerSwap inte behöver omfördela stora delar av en gård.

En relativt liten mängd väl valda skiften kan fånga en stor del av den kvarvarande logistiska förbättringen.

Detta är praktiskt viktigt eftersom små, riktade swaps sannolikt är lättare att:

- förstå,
- förhandla,
- juridiskt hantera,
- prova i pilot.

---

# 6. Samlad dom

## A: **PASS**

Substitutionsmarknaden är mycket tät i Sjöbo.

## B1+B2+B3: **MARGINAL / konservativt test**

Mekanismen finns och sparse-swap-resultatet är lovande.

Single-hub-modellen kan överskatta nyttan för verkliga fjärrkluster med egen driftbas. Samtidigt är B2:s fria 2–3-hubmodell sannolikt för generös för typisk lokal fragmentering inom Sjöbo och ska därför ses som ett konservativt worst-case, inte som normal lokal driftmodell.

---

# 7. Vad resultaten faktiskt visar

### Observerat / direkt beräknat från riktiga fältdata

- Sjöbo har mycket hög lokal tillgång på ungefär likvärdiga fält.
- Detta överlever strikta toleranser och adjacency-kontroll.

### Beräknat från syntetiska brukarportföljer

- artificiell geografisk fragmentering skapar stor optimeringspotential,
- rationella multi-hubbar tar bort merparten av den potentialen,
- en liten andel riktade swaps kan fånga en stor del av kvarvarande vinst.

### INTE visat

Vi har fortfarande inte visat:

- hur fragmenterade riktiga svenska brukningsportföljer är,
- hur många lantbrukare som faktiskt har "bad fingers",
- om 5–8 % area-km-proxy motsvarar tillräckligt ekonomiskt värde,
- vilka swaps som juridiskt eller avtalsmässigt är möjliga.

B-sprinten testar mekanismen, inte prevalensen.

---

# 8. Produktimplikation

ÅkerSwap bör inte beskrivas som:

> "Vi optimerar om hela gårdens mark."

Mer lovande positionering:

> "Vi hittar de få skiften som orsakar oproportionerligt mycket logistisk ineffektivitet och rankar lokala, agronomiskt likvärdiga substitut."

Det passar resultaten bättre.

En framtida produkt måste vara **multi-hub aware** från början.

---

# 9. Rekommendation till projektledarchatten

**Behåll ÅkerSwap i portföljen, men inte som omedelbar produktbyggnation.**

Argument för:

- mycket stark A-signal,
- verkligt och litteraturstödd problemklass,
- kontrolltestet beter sig korrekt,
- sparse-swap ser praktiskt intressant ut.

Argument emot / osäkerheter:

- multi-hub reducerar naiv vinst kraftigt,
- verklig brukar-/arrendedata saknas,
- ekonomisk effekt i kronor är ännu inte validerad.

Nästa steg, om projektledarchatten senare prioriterar ÅkerSwap, bör vara en **minimal riktig tvåbrukarstudie** eller annan billig källa till verklig portföljgeometri – inte webb och inte mer syntetisk optimering.

---

# 10. STOPP

Arbetet stoppas här enligt projektordern.

Ingen:

- webb,
- riktig pilot,
- vidare solverutveckling,
- Skåne-skalning,

görs innan ÅkerSwap återprioriteras av projektledarchatten.
