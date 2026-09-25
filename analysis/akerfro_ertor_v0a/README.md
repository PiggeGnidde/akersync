# ÅkerFrö – Ärter MVP v0a

This folder starts the ÅkerFrö demonstrator with **STOPPUNKT A only**.

## Contract

The crop identity path is deliberately year-specific:

year + official crop code/subcode -> ÅkerMinne official name -> ÅkerFrö semantic group

ÅkerFrö never interprets a historical numeric crop code by borrowing its meaning from another year.
The existing ÅkerMinne CropRegistry is reused for lookup semantics.

Primary semantic groups for this MVP:

- CONSERVART
- OTHER_PEA
- FABA_BEAN

Relevant other pulse/legume labels are retained as OTHER_LEGUME for audit only at this checkpoint.

## STOPPUNKT A outputs

RUN_AKERFRO_ERTOR_STOPPA.bat reads, but does not modify, frozen ÅkerMinne data under
C:\AkerSync-Minne and writes:

- work/akerfro_ertor_v0a/crop_mapping_audit.csv
- work/akerfro_ertor_v0a/yearly_counts.csv
- work/akerfro_ertor_v0a/checkpoint_a.json

The primary yearly pea counts use SINGLE_CROP field-years. An additional
n_conservart_all_dominant column is printed for audit transparency.

## Current source audit observation

The official workbooks supplied for 2015–2025 currently resolve main codes
30 = Ärter (ej konservärter), 31 = Konservärter, and 32 = Åkerbönor in every year.
This is an observed property of these source files, **not a code contract**. The implementation
still resolves every year independently.

No ÅkerScore, ÅkerMinne, ÅkerDrift, geometry, overlap or other frozen model artifact is recomputed.
