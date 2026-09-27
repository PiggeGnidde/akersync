# ÅkerVatten MVP v0a · STOPPUNKT E AMENDMENT 1

The original STOPPUNKT E freeze is preserved unchanged.

F2-F4 subsequently identified an existing organic-soil feature family that was not included in the original E candidate inventory. The evidence showed that organic-soil information is largely independent of clay, TWI and MarkTorka and captures a substantial field population missed by the clay+TWI wetness branch.

This amendment adds one raw feature to the MarkVäta candidate contract:

- `organic_ge20_share_pct`

Directional semantics:

- zero means no organic-soil evidence;
- higher positive share means stronger organic-soil evidence for the MarkVäta component.

Because the feature is strongly zero-inflated, it must not use the ordinary full-population rank transform. The approved candidate transform for F review is:

- missing -> missing;
- zero -> 0;
- positive values -> empirical percentile among positive values only.

The original MarkVäta primary candidates remain:

- `clay_mean` higher = more wetness-prone;
- `twi_mean` higher = more wetness-prone.

The approved F-level candidate structure is an OR of two physical evidence branches:

1. mineral/topographic wetness: joint evidence from clay and TWI;
2. organic-soil wetness: zero-aware organic-soil evidence.

No 0-100 MarkVäta score is frozen by this amendment.
