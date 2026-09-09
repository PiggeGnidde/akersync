# ÅkerPuls 2026 – B5b true-holdout review

Datum: 2026-09-09

B5b korrigerade B5:s QA-leakage genom att exkludera samtliga 12 splitfall som redan
visats i B3.

Resultat:
- 34 B2 split-kandidater totalt.
- 12 tidigare visade exkluderades.
- 22 true-holdout-kandidater återstod.
- Den provisoriska regeln behöll 1 och avvisade 21.

Visuell granskning av den enda behållna true-holdout-kandidaten
`2025|61993604265|5A` bedöms som plausibel split.

Bland åtta granskade avvisade true-holdout-fall:
- flera är tydligt komplexa/ring-/kantmönster som det är önskvärt att avvisa,
- minst ett fall (`2025|61973608273|3A`) ser ut som en möjlig false negative,
- ytterligare några (`2025|61993621901|8A`, `2025|61993609360|33A`) är möjliga/tveksamma.

Tolkning: den provisoriska splitregeln är precision-first och sannolikt har lägre recall.
För V0 är detta en önskad bias. Regeln skall inte trimmas ytterligare på B-piloten.

STOPPUNKT B beslut: PASS_TO_C.
- split-regeln hålls fast under C-validering,
- merge förblir MERGE_CANDIDATE_ONLY,
- ingen automatisk geometriändring,
- ingen threshold freeze för hela produkten ännu.
