# ÅkerFrö Rotation v1.1 — formal freeze

Rotation v1.1 is a lineage-aware downstream correction to frozen ÅkerFrö v0a/C8.

## Frozen policy

A recent CONSERVART component may be ignored as a rotation trigger only when:

- another current field captures at least 99.9% of the historical CONSERVART polygon,
- this current field captures less than 0.1%,
- the component is not same-admin-key,
- it is not historical-primary,
- it is not mutual-primary,
- **all** recent CONSERVART components on the current field satisfy the rule,
- no recent clean CONSERVART, OTHER_PEA or FABA remains.

Released fields retain explicit provenance:

- `rotation_status_v1a = ROTATION_OK_BOUNDARY_SPILL`
- `rotation_v1a_evidence = STRICT_LINEAGE_BOUNDARY_SPILL`

No ÄrtMatch, predecessor, logistics, access or BestMatch weight is retuned.

## Frozen anchors

- population: 128,636
- released C fields: 43
- C -> A: 28
- C -> B: 15
- A/B/C/D = 7,875 / 14,897 / 1,381 / 104,483

Discovery-case regression:

- Staffanstorp 2A: C -> A, boundary spill
- Staffanstorp 2B: C -> A, boundary spill
- Staffanstorp 94A: remains C, clean CONSERVART 2021

BestMatch v0b impact is diagnostic only:

- 15,967 -> 16,004 candidate fields under v1.1 eligibility
- 37 of the 43 released fields are in D5
- 6 are excluded by the already frozen D0 area >=1 ha rule
- historical-positive top-N hits unchanged at 200/500/800/1000/2000/5000

## Freeze

    CALL FREEZE_AKERFRO_ROTATION_V1A.bat

Later verification:

    CALL VERIFY_AKERFRO_ROTATION_V1A_FREEZE.bat

BestMatch v0b remains separately frozen and unchanged. A future BestMatch v0c
must explicitly use Rotation v1.1 eligibility while preserving the frozen
50/25/25 score policy and hard A-before-B class order.
