# ÅkerFrö – Ärter MVP v0a

## Core crop-code contract

The crop identity path is deliberately year-specific:

year + official crop code/subcode -> ÅkerMinne official name -> ÅkerFrö semantic group

ÅkerFrö never interprets a historical numeric crop code by borrowing its meaning from another year.
The existing ÅkerMinne CropRegistry is reused for lookup semantics.

Primary semantic groups:

- CONSERVART
- OTHER_PEA
- FABA_BEAN

Relevant other pulse/legume labels are retained as OTHER_LEGUME.

## STOPPUNKT A – crop-code/source audit

Outputs:

- work/akerfro_ertor_v0a/crop_mapping_audit.csv
- work/akerfro_ertor_v0a/yearly_counts.csv
- work/akerfro_ertor_v0a/checkpoint_a.json

Accepted anchors from the frozen ÅkerMinne history:

- 3,210 clean CONSERVART field-years
- 3,079 unique current fields with at least one clean CONSERVART year

The official workbooks supplied for 2015–2025 currently resolve main codes
30 = Ärter (ej konservärter), 31 = Konservärter, and 32 = Åkerbönor in every year.
This is an observed source property, not a code contract.

## STOPPUNKT B – pea history by current field

RUN_AKERFRO_ERTOR_STOPPB.bat reads frozen ÅkerMinne outputs under
C:\AkerSync-Minne and writes:

- data/derived/akerfro_ertor_v0a/pea_history_by_field.parquet
- data/derived/akerfro_ertor_v0a/pea_positive_field_years.parquet
- data/derived/akerfro_ertor_v0a/pea_mixed_or_complex_target_field_years.parquet
- data/derived/akerfro_ertor_v0a/pea_history_summary.json

The primary positive definition is strictly:

SINGLE_CROP + semantic CONSERVART

Mixed/complex target observations are retained separately and never silently
mixed into the primary positive set.

The field table derives, among other variables:

- n_target_pea_years_2015_2025
- first_target_pea_year
- last_target_pea_year
- years_since_last_target_pea
- target_pea_years_list
- n_other_pea_years
- n_faba_bean_years
- legume_years_list
- usable_history_years

years_since_last_target_pea is measured relative to the available history end
year 2025. It is not yet a 2026/2027 agronomic rotation decision variable.

### Bjuv processor-shock caution

The strong drop in clean conservärt observations around 2017 coincides with the
processor transition in Bjuv and is therefore a useful reminder of the
positive-unlabeled framing: absence of pea cultivation is not evidence that a
field was agronomically unsuitable. Processor capacity, contracts and logistics
can move historical usage independently of soil suitability.

No frozen ÅkerMinne geometry/matching/status, ÅkerScore or ÅkerDrift artifact is
recomputed or modified.
