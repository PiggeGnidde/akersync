# ÅkerPuls 2026 – TRUE leave-one-date-out diagnostic v0 result

Status: PASS. Zero Sentinel Hub PU. No threshold tuning. No product split rule frozen.

## Candidate population

- C: 226 split candidates; TRUE_LOO_STABLE 194 (85.84%)
- C5: 141 split candidates; TRUE_LOO_STABLE 111 (78.72%)
- Total: 367 split candidates; TRUE_LOO_STABLE 305 (83.11%)

Median continuous stability:
- C min child Dice 0.8983; mean child Dice 0.9639
- C5 min child Dice 0.8707; mean child Dice 0.9579

## Frozen blind-review cases (32 total)

Strict positive = TYDLIG only:
- min child Dice AUC 0.836, p=0.0028; median positive 0.9932 vs negative 0.9440
- mean child Dice AUC 0.841, p=0.0024; median positive 0.9983 vs negative 0.9815

Liberal positive = TYDLIG or MÖJLIG:
- min child Dice AUC 0.730, p=0.0274; median positive 0.9782 vs negative 0.9433
- mean child Dice AUC 0.727, p=0.0302; median positive 0.9906 vs negative 0.9721

Binary TRUE_LOO_STABLE is too permissive for discrimination:
- strict: 10/10 positives stable, 20/22 negatives stable
- liberal: 15/16 positives stable, 15/16 negatives stable

## Within preselected Sentinel groups

### C3 locked-pass, liberal visual view
- continuous min child Dice AUC 0.917, p=0.0422
- median positive 0.9942 vs negative 0.8721
- binary stable: 6/6 positives and 4/4 negatives stable, so the frozen binary threshold adds no useful discrimination here

### C5D high-confidence census, strict visual view
- continuous min child Dice AUC 0.778, p=0.4000 (n=3 positive, n=3 negative)
- median positive 0.9965 vs negative 0.9823
- binary stable: 3/3 positives and 3/3 negatives stable

The C5D sample is too small for significance but the rank direction is favorable, in contrast with the previously rejected separation>=4 rule.

## Decision

1. TRUE leave-one-date-out refitting is informative as a **continuous stability score**.
2. The pre-frozen binary criterion (`minimum each-child Dice >=0.75`, mean Dice >=0.80, all four refits and child-fraction guard) is **not selective enough** and must not be promoted as a product gate.
3. Do not redefine the historical pseudo-LOO metric; retain it for provenance only.
4. Do not tune a new TRUE-LOO threshold on these C/C5 blind-review cases and call it validated.
5. Development evidence now supports three complementary signals for split assessment:
   - historical geometry-change prior from ÅkerMinne rolling backtest;
   - Sentinel spectral/temporal separation;
   - TRUE-LOO segmentation reproducibility as a continuous score.
6. Before any automatic split rule is frozen, define a fusion contract on development data and validate it on a new independent geographic holdout.

No automatic geometry replacement is approved by this result.
