# ÅkerFrö × ÅkerAccess BestMatch v0c — formal freeze candidate

## Purpose

BestMatch v0c is the canonical BestMatch product above frozen **ÅkerFrö
Rotation v1.1**. It preserves the already-frozen BestMatch v0b ranking policy
exactly and changes only candidate eligibility.

Frozen v0b remains read-only.

## Policy

Candidate classes:

- A_STRONG_CANDIDATE
- B_PHYSICAL_CANDIDATE

A is a hard tier before B.

Within each class:

`BestMatch = 0.50 ÄrtMatch + 0.25 road AreaLogistik + 0.25 ÅkerAccess v0a`

The score components and weights are unchanged from v0b.

## Frozen regression anchors

Expected candidate universe:

- v0b: 15,967
- v0c: 16,004
- new: 37
- dropped: 0
- A: 7,447
- B: 8,557

The 37 entrants are the Rotation v1.1 releases that are also inside the
already-frozen D0/BestMatch road-eligible universe. Their split is expected to
be 26 A and 11 B.

Top-N churn versus v0b:

- top 200: 1
- top 500: 3
- top 800: 4
- top 1000: 4
- top 2000: 10
- top 5000: 21

Historical clean CONSERVART hit counts must remain unchanged at:

- 10 / 26 / 37 / 49 / 88 / 201

for top 200 / 500 / 800 / 1000 / 2000 / 5000.

## Guardrails

- Rotation v1.1 and BestMatch v0b must verify before v0c can freeze.
- No score component or weight may be refitted.
- A-before-B remains hard.
- D4 routing semantics and explicit straight-line fallback are unchanged.
- NVDB Slitlager remains excluded.
- BestMatch is a screening/ranking product, not an agronomic/access guarantee.

## Run

    CALL FREEZE_AKERFRO_AKERACCESS_BESTMATCH_V0C.bat

Later verification:

    CALL VERIFY_AKERFRO_AKERACCESS_BESTMATCH_V0C_FREEZE.bat

Canonical product:

    data/derived/akerfro_akeraccess_bestmatch_v0c/bestmatch_v0c_fields.parquet

After PASS, v0c should be used together with Rotation v1.1 when forward-porting
to the unified preview.
