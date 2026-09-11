# ÅkerPuls preliminära 2026-fält — C7D blind fusion-QA

Status: **PLAN FROZEN BEFORE VISUAL LABELS**

## Syfte

C7D är den blinda visuella utvärderingen av den fusion som frystes före den fjärde geografiska holdouten C7. Fusionen använder tre signaler med lika vikt efter empirisk midrank-CDF-transform mot de 367 utvecklingskandidaterna från C + C5:

1. `prototype_p_splitmerge_2026` från ÅkerMinne-historiken,
2. Sentinel `separation_ratio`,
3. TRUE-LOO `true_loo_min_child_dice`.

Fusionen refittas inte på C7 och inga C7-etiketter används vid urvalet.

Frozen fusion SHA256:

`3ab2fcdd06284c15cbcffb20fba8da7de9f6b10ca102bd4026fc73a9ee0a7316`

Frozen utvecklingströsklar:

- DEV-P90 = `0.781017`
- DEV-P95 = `0.843688`

## C7C-resultat som styr census-storlek, inte modellparametrar

C7C gav 131 baseline `SPLIT_CANDIDATE`, varav 15 ligger över frusen DEV-P90 och 9 över frusen DEV-P95. Alla 15 DEV-P90-fall ligger i juni-validitetsstratum `GE80`.

Detta används endast för att fastställa storleken på den blinda reviewn. Inga trösklar ändras.

## Blind urvalsregel

Review-setet består av exakt 20 fall:

- **alla 15** C7-kandidater med `fusion_score >= DEV-P90` (full census), inklusive alla 9 DEV-P95-fall;
- **5 svåra kontroller**: de fem högsta fusion-scorerna under DEV-P90 bland kandidater med juni-validitet `GE80`.

Därmed kan post-reveal precision rapporteras exakt för C7:s DEV-P90- och DEV-P95-census. De fem kontrollerna är däremot en avsiktligt svår near-threshold challenge set och får inte tolkas som ett slumpmässigt negativt urval.

De 20 fallen blandas deterministiskt med SHA256-baserad ordning och visas endast som `C7D_01` ... `C7D_20`. Grupp, fält-ID, fusion-score, delsignaler, P90/P95-status och övrig metadata lagras i en separat blindnyckel som inte ska öppnas före att samtliga visuella etiketter är frysta.

## Visuell etikett

Varje fall märks med exakt en av:

- `TYDLIG`
- `MÖJLIG`
- `TVEKSAM`
- `FALSK`

Bilderna visar april, maj, juni och juli. Parent-geometri visas vit, modellens två föreslagna child-geometrier svarta och ogiltiga pixlar rosa/röda. Ingen fusion-score eller hidden group visas i bilden.

## Primära utfall efter reveal

Rapportera separat:

- DEV-P95 strict precision: andel `TYDLIG` bland alla 9 P95-fall;
- DEV-P95 liberal precision: andel `TYDLIG + MÖJLIG` bland alla 9 P95-fall;
- DEV-P90 strict precision: andel `TYDLIG` bland alla 15 P90-fall;
- DEV-P90 liberal precision: andel `TYDLIG + MÖJLIG` bland alla 15 P90-fall.

Sekundärt får fusion-score rankas mot de 20 visuella etiketterna, men inga nya trösklar får väljas på C7D.

## Guards

- 0 Sentinel Hub PU.
- Ingen fusion-refit.
- Ingen threshold tuning.
- Ingen automatisk geometriändring.
- Ingen produktregel fryses i C7D.
- Ingen merge-utvärdering i detta steg.
- C7D är sista blinda kontrollen av den nu frysta split-fusionen; eventuell produktregel beslutas först efter reveal och explicit stoppunkt.
