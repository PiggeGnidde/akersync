# ÅkerFrö – Ärter MVP v0a · C7 Rotation + förfrukt

C7 ligger **nedströms om fryst ÄrtMatch v0a** och ändrar inga frysta ÄrtMatch-filer.

## A. Rotation / eligibility

Kandidatår: 2026.

Scenarier körs för 6, 7 och 8 års observerat avstånd, med fyra separata historikdefinitioner:

1. clean CONSERVART,
2. any detected CONSERVART component (clean + mixed/complex sensitivity),
3. clean CONSERVART eller OTHER_PEA,
4. clean CONSERVART / OTHER_PEA / FABA_BEAN.

Ingen av dessa är ännu en fryst agronomisk regel. De är känslighetsscenarier.

## B. Förfrukt

Historiska clean CONSERVART-händelser jämförs med clean non-target controls inom:

`target year × municipality × dominant SKO × current-area decile`.

T-1 är primär analys. T-2 och T-2→T-1-sekvenser rapporteras som sekundära analyser.

Det reducerar confounding från år, lokal grödmix, jordbruksområde och fältstorlek. Det eliminerar inte kontrakt, gårdsstruktur, bevattning eller andra latenta odlarval.

## Guardrails

- ÅkerMinne 2015–2025 är vänstercensurerat. "Ingen observerad ärt" betyder inte "aldrig ärt".
- Mixed/complex konservärt behandlas separat som strängare känslighetsvariant.
- OTHER_PEA och FABA_BEAN hålls separata; de antas inte vara biologiskt identiska med konservärt.
- Förfrukts-enrichment beskriver historisk selektion, inte kausal skörderespons.
