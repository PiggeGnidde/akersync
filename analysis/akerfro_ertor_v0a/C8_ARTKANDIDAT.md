# ÅkerFrö – Ärter MVP v0a · C8 ÄrtKandidat

C8 är första produktnära screeninglagret ovanpå den formellt frysta **ÄrtMatch v0a**.

## Inputs

- fryst ÄrtMatch v0a,
- C7 rotation eligibility,
- C7 matchad t-1-förfrukts-enrichment,
- ÅkerMinne 2025 för aktuell t-1-gröda.

Ingen ny ML tränas.

## MVP-policy

**Hög ÄrtMatch** = topp 20 % bland scorebara Skånefält. Detta är en transparent produkttröskel, inte en biologisk gräns.

Förfruktsprior:
- POSITIVE: minst 50 historiska positiva händelser och enrichment >= 1.25,
- NEGATIVE: minst 50 och enrichment <= 0.80,
- NEUTRAL: däremellan,
- LOW_SUPPORT/UNKNOWN: otillräckligt underlag.

Rotation:
- clean/mixed konservärt inom 6 år => caution,
- annan clean ärt inom 6 år => caution,
- åkerböna inom 6 år => caution,
- annars ROTATION_OK.

Åkerböna/annan ärt behandlas uttryckligen som **caution**, inte som bevisat biologiskt veto.

## Klasser

- **A_STRONG_CANDIDATE** – hög ÄrtMatch + rotation OK + positiv t-1-prior.
- **B_PHYSICAL_CANDIDATE** – hög ÄrtMatch + rotation OK + ingen positiv t-1-prior.
- **C_ROTATION_CAUTION** – hög ÄrtMatch men aktuell rotationsvarning.
- **D_NOT_HIGH_PHYSICAL_MATCH** – under den transparenta fysiska produkttröskeln eller otillräcklig core-data.

## Inte med ännu

Processoravstånd/logistik, kontraktsläge, bevattnings-/vattenrisk, farmer-ID/maskinpark och faktisk gröda 2026 ligger utanför C8.
