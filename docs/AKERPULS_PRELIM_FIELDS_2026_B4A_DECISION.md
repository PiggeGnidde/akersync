# ÅkerPuls 2026 – B4a beslut inför B5

B4a visar att split och merge bör behandlas olika.

## SPLIT

På de preliminärt visuellt granskade ankaren finns ett tydligt gap:

- Tydliga split: minsta largest-component fraction = 0.963.
- Falska/tveksamma split: största motsvarande värde = 0.912.
- Alla fem tydliga har edge-ratio >= 1.8 i minst 3 av 4 snapshots.
- Alla fem tydliga är LOO_ALL4.
- Regeln LCF >= 0.95 på båda barnen + edge >= 1.8 i minst 3 snapshots + LOO_ALL4
  är därför vald som en *provisional holdout rule*, inte som freeze.

Värdena är avrundade och ligger inne i observerade gaps, inte satta exakt på ett ankare.

## MERGE

De fyra visuellt tydliga och fyra visuellt falska merge-ankarna separeras inte robust av
nuvarande Sentinel-2-mått. Flera falska har svagare gammal gränssignal än de tydliga.
Detta är förenligt med ett identifikationsproblem: två separata administrativa fält med
samma gröda kan vara spektralt oskiljbara från ett verkligt sammanslaget brukningsskifte.

V0 får därför endast skapa MERGE_CANDIDATE. Ingen automatic merge och ingen sannolikhets-
tolkning av nuvarande confidence. Senare version kan lägga till oberoende evidens, t.ex.
historisk gränspersistens/skiftesgeometri, men detta ingår inte i B5.

## B5

B5 använder den provisoriska splitregeln på samtliga 34 B2 split-kandidater och skapar
blind/unreviewed QA-bilder från fall som inte ingick i den manuella anchor-granskningen.
Ingen threshold freeze görs innan dessa holdout-bilder har granskats.
