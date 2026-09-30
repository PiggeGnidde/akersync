# ÅkerAccess MVP v0b — STOPPUNKT B visual QA

STOPPUNKT A gav i Sjöbo 7 753 skiften och 8 498 accesskandidater.

Fördelning:
- STRONG_OSM_EVIDENCE: 1 274 (16.43 %)
- POSSIBLE_OSM_EVIDENCE: 1 674 (21.59 %)
- ADJACENCY_ONLY: 1 516 (19.55 %)
- NO_OSM_ENTRY_EVIDENCE: 3 289 (42.42 %)

## Varför B kommer före score

OSM ger användbar evidens men täcker inte allt. Nästa fråga är därför precision/miss-rate mot verklig geometri, inte scorevikter.

Det frysta 100-fältsurvalet innehåller exakt 25 fält från vardera STOPPUNKT A-status.

## Reviewer

Kör:

`RUN_AKERACCESS_REVIEW_V0B.bat`

Verktyget visar:
- fältpolygon,
- samtliga OSM accesskandidater för fältet,
- kandidatens OSM-väggeometri,
- grindmarkörer,
- flygbild som default-basemap,
- OSM som alternativ basemap.

Human labels:
- CORRECT_ENTRY
- WRONG_ENTRY
- MISSED_ENTRY
- NO_VISIBLE_ENTRY
- UNCLEAR

Labels sparas i browser localStorage. När reviewen är klar används knappen **Ladda ner QA CSV**.

Ladda tillbaka `sjobo_akeraccess_visual_qa_v0b.csv` till kodchatten.

STOPPUNKT B ska därefter mäta precision per evidensklass och uppskatta hur stor del av NO_OSM-gruppen som faktiskt har en visuellt tydlig men missad infart.
