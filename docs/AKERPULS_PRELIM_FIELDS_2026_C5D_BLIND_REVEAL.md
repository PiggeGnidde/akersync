# ÅkerPuls prelim fields 2026 — C5D blind reveal

## Status

STOPPUNKT C5D completed on the third geographically independent 1000-field holdout.

The visual labels below were committed before the blind key was opened. The hidden key was then revealed without any parameter changes.

## Frozen pre-reveal visual labels

| Blind # | Visual label |
|---:|---|
| 01 | MÖJLIG |
| 02 | TYDLIG |
| 03 | FALSK |
| 04 | TVEKSAM |
| 05 | FALSK |
| 06 | TYDLIG |
| 07 | TYDLIG |
| 08 | TYDLIG |
| 09 | TVEKSAM |
| 10 | FALSK |
| 11 | TYDLIG |
| 12 | FALSK |

Totals: 5 TYDLIG, 1 MÖJLIG, 2 TVEKSAM, 4 FALSK.

## Blind-key reveal

HIGH_CONFIDENCE_CENSUS cases were #03, #05, #06, #07, #09, #11.

Their frozen visual labels were therefore:

- #03 FALSK — separation_ratio 5.2833
- #05 FALSK — separation_ratio 7.3973
- #06 TYDLIG — separation_ratio 4.0497
- #07 TYDLIG — separation_ratio 5.8013
- #09 TVEKSAM — separation_ratio 4.1760
- #11 TYDLIG — separation_ratio 4.6956

Result for all six HIGH_CONFIDENCE_SPLIT cases in this holdout:

- TYDLIG: 3/6
- MÖJLIG: 0/6
- TVEKSAM: 1/6
- FALSK: 2/6

The six deliberately difficult near-threshold SPLIT_CANDIDATE controls were #01, #02, #04, #08, #10, #12, with labels:

- TYDLIG: 2/6
- MÖJLIG: 1/6
- TVEKSAM: 1/6
- FALSK: 2/6

Thus, with strict visual positives (TYDLIG), the high-confidence group was 3/6 versus 2/6 among near-threshold controls. With liberal positives (TYDLIG+MÖJLIG), both groups were 3/6.

The control group is not a random negative sample and these fractions must not be interpreted as population-level precision/recall. However, the HIGH_CONFIDENCE_CENSUS is complete: all six high-confidence predictions among the 1000 third-holdout fields were visually inspected.

## Scientific decision

The post-C3 rule

`HIGH_CONFIDENCE_SPLIT = SPLIT_CANDIDATE AND separation_ratio >= 4.0`

**fails as a product-freeze precision gate.**

Reason:

1. Two of six high-confidence cases were visually false in a fully independent geographic holdout.
2. One additional case was visually doubtful.
3. Separation ratios as high as 5.2833 and 7.3973 still produced visually false geometry.
4. The near-threshold controls were not materially worse under the liberal visual criterion.

Therefore:

- do **not** product-freeze `separation_ratio >= 4.0`;
- do **not** promote C5C high-confidence geometries to automatic 2026 splits;
- retain the existing locked rule only as `SPLIT_CANDIDATE` evidence;
- keep `MERGE_CANDIDATE_ONLY` unchanged;
- no threshold retuning on C5D.

## Implication for V0

The current evidence supports a conservative V0 interpretation:

- 2025 geometry remains the operative prior/default;
- `SPLIT_CANDIDATE` is a QA/evidence flag, not an automatic geometry mutation;
- `MERGE_CANDIDATE` is likewise advisory only;
- `UNCERTAIN` remains data/geometry uncertainty;
- automatic split/merge requires a stronger geometric-identifiability method than scalar temporal separation.

A useful next scientific step is a genuinely stronger leave-one-date-out segmentation test and/or a topology-aware boundary model. The previous LOO checks tested snapshot support after fitting the all-date segmentation; they were not a full re-segmentation under each omitted snapshot. Any further model development must be validated on new holdout data and must not reinterpret C5D as validation evidence for newly tuned rules.
