# B5 holdout correction

B5 labelled as "unreviewed" every B2 split candidate that was not one of the 8
CLEAR/FALSE visual anchors. This was too weak: all top-12 split candidates had
already been rendered and manually viewed during B3, including four that were
classified as MÖJLIG/TVEKSAM rather than CLEAR/FALSE.

Therefore B5 visual holdout was partially contaminated. This affects the QA
interpretation only, not B2/B4 metrics or the provisional split rule.

B5b preserves B5 as historical output and creates a corrected TRUE HOLDOUT by
excluding all first 12 entries of B3 split_loo_robustness.csv (the exact cases
rendered in B3). No thresholds are changed or frozen.

The B5 provisional rule remains:
- largest-component fraction >= 0.95 for both children
- split edge-ratio >= 1.8 in at least 3/4 snapshots
- LOO_ALL4

If the corrected B5b has too few retained positive examples, the rule should be
validated on an independent geographic STOPPUNKT C pilot rather than further tuned
on the B pilot.
