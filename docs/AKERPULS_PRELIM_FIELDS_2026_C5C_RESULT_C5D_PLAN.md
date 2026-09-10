# ÅkerPuls prelim 2026 – C5C result and C5D blind QA plan

## C5C frozen third-holdout result

Third geographically independent 1000-field holdout, northwest Skåne. Preprocessing remained IDENTICAL_TO_B1 and the split rules were unchanged.

Observed C5C result:

- PILOT_FIELDS = 1000
- ALL_VALID_PIXEL_FRACTION = 0.9899
- BASELINE_SPLITS = 141 (14.10%)
- SPLIT_CANDIDATES = 21 (2.10%; 14.89% retention of baseline)
- HIGH_CONFIDENCE_SPLITS = 6 (0.60%; 28.57% retention of split candidates)
- UNCERTAIN_FIELDS = 4
- ADJACENCY_PAIRS = 711
- MERGE_CANDIDATES = 75 (10.55%), policy remains MERGE_CANDIDATE_ONLY
- thresholds tuned = FALSE
- product thresholds frozen = FALSE
- Sentinel Hub PU used in C5C = 0

The lower split frequencies relative to the C pilot should not by themselves be interpreted as model failure. The full chain moved down together (baseline, candidate, high-confidence), while C5B provided nearly complete valid coverage for all four snapshots. The next test is therefore visual precision, not rate matching.

## C5D plan

C5D is a blind visual QA designed to test the frozen HIGH_CONFIDENCE_SPLIT rule without revealing which images passed it.

The blind set contains exactly 12 images:

- all 6 HIGH_CONFIDENCE_SPLIT cases from the third holdout (a census, not a sample), and
- 6 difficult controls selected from SPLIT_CANDIDATE cases below separation_ratio=4.0, choosing the highest separation ratios below the frozen threshold.

The 12 are deterministically shuffled. The rendered image title exposes only the blind index. The key is written separately and must not be opened before visual labels are fixed.

Visual labels to freeze before reveal:

- TYDLIG
- MÖJLIG
- TVEKSAM
- FALSK

After reveal, the six high-confidence cases can be used to report visual precision within this specific 1000-field holdout because every high-confidence case is included. The six controls are deliberately difficult near-threshold controls and must not be treated as a random negative sample or used to estimate population specificity.

No threshold tuning, product freeze, geometry commit, automatic merge, crop classification, or full-Skåne run is allowed during C5D.
