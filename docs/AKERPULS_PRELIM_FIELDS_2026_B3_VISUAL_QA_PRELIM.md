# ÅkerPuls preliminära skiften 2026 – B3 visuell QA, preliminär

Datum: 2026-09-09

Detta är en preliminär manuell bildgranskning av de 12 högst rankade
MERGE_CANDIDATE- och 12 högst rankade SPLIT-kandidaterna från B3.

VIKTIGT: etiketten bygger endast på de fyra true-colour QA-panelerna
(april, maj, juni, juli) och är inte ground truth. Den används för att
diagnostisera modellens felmoder, inte för att ändra 2025-geometri.

## Merge

| Rank | Kandidat | conf | Visuell QA | Kort motiv |
|---|---|---:|---|---|
| 1 | 2025\|62003596612\|3A + 2025\|62003596612\|3B | 0.876 | TYDLIG | Likartad fenologi på båda sidor; gammal gräns saknar tydlig bildkant. |
| 2 | 2025\|62003595860\|12A + 2025\|62003596756\|13A | 0.874 | TYDLIG | Mycket lika över samtliga fyra snapshots. |
| 3 | 2025\|61963605596\|9A + 2025\|61963615707\|10A | 0.863 | FALSK/Tveksam | Synlig sid-skillnad särskilt april/juli. |
| 4 | 2025\|61983612306\|1A + 2025\|61983612620\|9A | 0.858 | TYDLIG | Två långsmala delar följer samma säsongsutveckling. |
| 5 | 2025\|61983619797\|1A + 2025\|61993610374\|2A | 0.858 | TVEKSAM | Skillnad synlig framför allt juli. |
| 6 | 2025\|61983620802\|22A + 2025\|61983623806\|15A | 0.847 | FALSK/Komplex | Mycket heterogen/komplex geometri; ej övertygande gemensam brukningsyta. |
| 7 | 2025\|61973623611\|19A + 2025\|61973624710\|22A | 0.845 | FALSK | Tydlig fenologisk skillnad, särskilt juni. |
| 8 | 2025\|61963577343\|157A + 2025\|61963578080\|155A | 0.830 | TYDLIG | Liten och stor del ser konsekvent sambrukade ut. |
| 9 | 2025\|62013590756\|3A + 2025\|62013592157\|18A | 0.829 | FALSK | Delarna har återkommande olika ton/fenologi. |
| 10 | 2025\|62003563337\|8A + 2025\|62003563337\|8C | 0.824 | TVEKSAM | Komplex liten geometri och viss skillnad mellan delarna. |
| 11 | 2025\|61963619022\|123A + 2025\|61973610418\|119A | 0.814 | TVEKSAM | Gammal gräns sammanfaller delvis med stabil skillnad. |
| 12 | 2025\|62013600180\|34A + 2025\|62013610802\|25A | 0.809 | MÖJLIG | Relativt lik signal men geometrin är komplex; bör inte auto-merge. |

Preliminärt: 4 tydliga, 1 möjlig, 3 tveksamma, 4 falska/komplexa av de 12 högst rankade.
Detta visar att LOO-stabilitet ensam inte räcker för merge: samtliga 33 B2-merge-kandidater
var B3 LOO_ALL4, men flera högt rankade har visuellt bestående skillnad.

## Split

| Rank | Kandidat | conf | Visuell QA | Kort motiv |
|---|---|---:|---|---|
| 1 | 2025\|62013602526\|16A | 0.990 | TYDLIG | Två långsträckta delytor med återkommande spektral/fenologisk skillnad. |
| 2 | 2025\|62013612135\|30A | 0.990 | TYDLIG | Stabil tvådelning genom säsongen. |
| 3 | 2025\|61983623806\|15A | 0.990 | TVEKSAM/Komplex | Mycket långsmal/heterogen och omgiven av vegetation; risk för icke-brukningssignal. |
| 4 | 2025\|61963618273\|9B | 0.985 | FALSK | Ring/T-liknande intern segmentering är inte en plausibel enkel skiftesdelning. |
| 5 | 2025\|61963607277\|8A | 0.976 | TYDLIG | Två naturliga lober med tydlig skillnad, särskilt juni/juli. |
| 6 | 2025\|61973610418\|119A | 0.969 | MÖJLIG | Stabil inomfältskillnad men gränsen är inte lika självklar visuellt. |
| 7 | 2025\|61993563095\|12A | 0.944 | FALSK/Tveksam | Inre patch/gradient snarare än övertygande ny brukningsgräns. |
| 8 | 2025\|62013590756\|3A | 0.940 | FALSK | Nästan ringformad inre zon; typisk inomfältsvariation, ej plausibel split. |
| 9 | 2025\|61983609385\|18A | 0.938 | TYDLIG | Klar vänster/höger-skillnad genom flera snapshots. |
| 10 | 2025\|61983602247\|10A | 0.938 | MÖJLIG/Komplex | Stark heterogenitet men kandidatgränsen är geometriskt komplex. |
| 11 | 2025\|62003604626\|14A | 0.890 | TYDLIG | Stabil längsgående tvådelning. |
| 12 | 2025\|61983602501\|8A | 0.887 | MÖJLIG | Återkommande vänster/höger-skillnad men med intern hål/komplexitet. |

Preliminärt: 5 tydliga, 3 möjliga, 1 tveksam/komplex och 3 falska/tveksamma.
Topprankad confidence är inte kalibrerad: två 0.99-fall är tydliga, men ett 0.99-fall
är komplext och ett 0.985-fall ser falskt ut.

## Modellinsikter före tröskeländring

1. LOO testar stabilitet men inte agronomisk/geometrisk plausibilitet.
2. SPLIT behöver ett morphology-gate: båda barnen bör vara sammanhängande, ha rimlig
   kontakt med yttergränsen och en intern gräns som faktiskt delar polygonen; ring-/ö-segment
   bör normalt avvisas.
3. SPLIT bör kompletteras med explicit edge support längs den föreslagna interna gränsen,
   separat per snapshot.
4. MERGE bör göras mer konservativ. Ett enda starkt edge-snapshot är sannolikt för mycket
   att tillåta i V0; kandidat bör helst sakna stark gammal gräns på samtliga diagnostiska snapshots.
5. MERGE bör väga per-snapshot fenologisk skillnad hårdare så att en stark diagnostisk
   månad inte späds ut av likhet i övriga månader.
6. Ingen tröskel ändras utifrån dessa 24 bilder ännu. Nästa steg bör vara ett lokalt B4
   sensitivity/morphology-diagnostic på hela 34/33 kandidatsetet och därefter ny visuell QA.
