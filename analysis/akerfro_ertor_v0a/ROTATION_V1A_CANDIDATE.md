# ÅkerFrö Rotation v1.1 — downstream candidate

## Purpose

Rotation v1.1 is a downstream correction candidate above frozen ÅkerFrö v0a/C8.
It does **not** rewrite the v0a freeze.

The motivating failure mode is historical field-boundary spill: a historical
CONSERVART polygon can intersect today's neighbouring field by a microscopic
sliver and v0a's `target_any_component` rule can then create a full
`C_ROTATION_CAUTION`.

## Strict lineage release rule

A recent CONSERVART component is considered strict boundary spill only when:

- another current field captures at least 99.9% of the historical CONSERVART polygon,
- this current field captures less than 0.1% of that historical polygon,
- the component is not `same_admin_key`,
- it is not historical-primary,
- it is not mutual-primary.

A field is released from CONSERVART caution only if **all** of its recent
CONSERVART components satisfy the rule, there is no recent clean CONSERVART,
and no recent clean OTHER_PEA or FABA_BEAN remains.

Released fields retain explicit provenance:

- `rotation_status_v1a = ROTATION_OK_BOUNDARY_SPILL`
- `rotation_v1a_evidence = STRICT_LINEAGE_BOUNDARY_SPILL`

The predecessor prior then determines A versus B exactly as in v0a.

## Frozen empirical anchors

The candidate is expected to produce:

- population: 128,636
- C fields examined (CONSERVART caution, no recent clean CONSERVART): 169
- all-components strict spill: 45
- blocked by OTHER_PEA/FABA: 2
- released: 43
- C -> A: 28
- C -> B: 15

Class counts become:

- A: 7,875
- B: 14,897
- C: 1,381
- D: 104,483

Staffanstorp regression anchors:

- `61723351559|2A`: C -> A, boundary spill
- `61723351559|2B`: C -> A, boundary spill
- `61723353349|94A`: remains C, clean CONSERVART 2021

## BestMatch impact

The impact stage reuses the frozen BestMatch v0b policy unchanged:

`0.50 ÄrtMatch + 0.25 road AreaLogistik + 0.25 ÅkerAccess v0a`

A remains a hard tier before B. Only candidate eligibility can change.
The canonical frozen BestMatch v0b table is never overwritten.

Run everything with:

    BUILD_AKERFRO_ROTATION_V1A.bat

Outputs are candidate/impact artifacts only. Preview remains unchanged until
the impact is reviewed.
