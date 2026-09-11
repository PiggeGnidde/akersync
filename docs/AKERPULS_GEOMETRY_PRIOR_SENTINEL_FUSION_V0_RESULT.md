# ÅkerPuls geometry prior + Sentinel fusion v0 — result

Run date: 2026-09-11

Status: **PASS (diagnostic only)**

This zero-PU diagnostic joined the prototype 2026 field-specific geometry prior from the true adjacent-year rolling backtest to the already frozen/revealed C3 and C5D Sentinel split QA cases. No threshold was tuned, no new split rule was defined, and no product prior was frozen.

## Sample

- Total cases: 32
- C3: 20
- C5D: 12
- Missing prior joins: 0

Frozen visual labels were retained. Two binary views were used:

- strict visual positive = TYDLIG
- liberal visual positive = TYDLIG + MÖJLIG

## All 32 cases

Strict visual target:

- history prior `prototype_p_splitmerge_2026`: AUC 0.634, median positive 0.1138, median negative 0.0286, gap +0.0853, p=0.2292
- Sentinel `separation_ratio`: AUC 0.841, median positive 4.4228, median negative 2.9759, gap +1.4469, p=0.0025

Liberal visual target:

- history prior `prototype_p_splitmerge_2026`: AUC 0.789, median positive 0.1388, median negative 0.0286, gap +0.1102, p=0.0047
- Sentinel `separation_ratio`: AUC 0.672, median positive 3.6806, median negative 2.9806, gap +0.7001, p=0.1011

Interpretation: Sentinel separation is strongest for the strict TYDLIG distinction, while field-history prior is strongest for the broader TYDLIG+MÖJLIG notion of a plausible split. The signals therefore appear complementary rather than interchangeable.

## C3 locked-pass cases only

Among the ten C3 cases already passing the locked Sentinel candidate rule, using the liberal visual target:

- history prior: AUC **1.000**, median positive 0.2560, median negative 0.0193, gap +0.2367, p=0.0128
- Sentinel separation: AUC 0.833, median positive 4.4228, median negative 2.8060, gap +1.6168, p=0.1143

This is a particularly strong diagnostic signal: within a group that had already passed the same Sentinel candidate gate, the independent field-history prior perfectly ranked the six visually plausible cases above the four visually false cases in this small C3 challenge subset.

This must not be interpreted as a population-level accuracy estimate: C3 is a deliberately constructed diagnostic challenge set and was already used during model development.

## C5D high-confidence census only

Among all six C5D HIGH_CONFIDENCE_SPLIT cases from the geographically independent third holdout, using strict TYDLIG as positive:

- history prior: AUC 0.778, median positive 0.0286, median negative 0.0193, gap +0.0093, p=0.3687
- Sentinel separation: AUC 0.333, median positive 4.6956, median negative 5.2833, gap -0.5877, p=0.7000

The C5D sample is only 3 positives and 3 negatives, so uncertainty is large. Nevertheless, the direction is important: within the failed `separation_ratio >= 4` high-confidence tier, separation ratio ranked the visually clear cases worse than the non-clear cases, while the independent history prior ranked them in the expected direction.

This supports the hypothesis that geometry history contains information not captured by scalar Sentinel separation.

## Scientific decision

1. The field-specific geometry prior is useful and should remain part of the candidate architecture.
2. Sentinel evidence remains essential: history alone is not sufficient for detecting a current-year change.
3. A universal scalar `separation_ratio` threshold remains rejected as an automatic split gate.
4. Do not define a production fusion threshold from these 32 cases. C3 and C5D have now both contributed to model development/diagnosis.
5. Any automatic fusion rule learned from these results requires a new geographic holdout.
6. Before a new holdout is spent, the outstanding **true leave-one-date-out re-segmentation** test should be evaluated as a separate zero-PU diagnostic. The historical prior and true-LOO geometric stability are natural complementary signals for a future predeclared fusion rule.

## Guardrails

- `THRESHOLDS_TUNED=FALSE`
- `NEW_SPLIT_RULE_DEFINED=FALSE`
- `PRODUCT_PRIOR_FROZEN=FALSE`
- `SENTINEL_HUB_PU_USED=0`

Current conservative product status remains unchanged: 2025 geometry is the default; split/merge outputs are evidence/QA only; no automatic geometry mutation is yet approved.
