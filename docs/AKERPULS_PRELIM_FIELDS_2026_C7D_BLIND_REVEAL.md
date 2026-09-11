# ÅkerPuls preliminära 2026-fält — C7D blind reveal

Status: **REVEALED AFTER HUMAN LABELS**

## Chronology and blinding note

The human visual labels were provided in the ChatGPT project conversation before the blind key was opened. The blind key was then revealed with SHA256:

`d2553241211545cb8c0ffdb110e3f063680024af3b17eef818e6fb4cf9a14879`

The frozen fusion artifact remained:

`3ab2fcdd06284c15cbcffb20fba8da7de9f6b10ca102bd4026fc73a9ee0a7316`

This repository result note is written after reveal; therefore the repository commit itself is not the pre-reveal proof of the labels. The conversation chronology is the pre-reveal record.

## Human label vocabulary

- `TY`: tydlig
- `M/TY`: intermediate label; typically three of four snapshots visually clear, with the exact clear snapshots retained where supplied
- `M`: möjlig
- `TV`: tveksam
- `F`: falsk

Frozen labels supplied before reveal:

| Blind | Label |
|---:|---|
| 01 | M/TY (2-4) |
| 02 | M/TY (2-4) |
| 03 | TY |
| 04 | F |
| 05 | M/TY (2-4) |
| 06 | M/TY (1,3-4) |
| 07 | M/TY (1,3-4) |
| 08 | M |
| 09 | M |
| 10 | TY |
| 11 | M/TY (2-4) |
| 12 | M/TY (2-4) |
| 13 | TV |
| 14 | TY |
| 15 | TV |
| 16 | M |
| 17 | M/TY (2-4) |
| 18 | TY |
| 19 | TY |
| 20 | M |

For reporting, three predeclared interpretation levels are used:

- **strict**: `TY` only
- **intermediate**: `TY + M/TY`
- **liberal**: `TY + M/TY + M`

`TV` and `F` are not positive at any of those three levels.

## Reveal groups

Frozen DEV-P95 census, n=9:

`01, 05, 07, 08, 09, 16, 17, 18, 19`

Frozen DEV-P90-to-P95 census, n=6:

`03, 06, 10, 12, 13, 15`

Therefore the full DEV-P90 census, n=15, is the union of the two groups above.

Near-P90 June-GE80 controls, n=5:

`02, 04, 11, 14, 20`

The controls were deliberately selected as the highest fusion scores just below DEV-P90 and are not a random negative sample.

## Primary C7 holdout results

### DEV-P95 census — all 9 cases

Labels:

`M/TY, M/TY, M/TY, M, M, M, M/TY, TY, TY`

- strict (`TY`): **2/9 = 22.2%**
- intermediate (`TY + M/TY`): **6/9 = 66.7%**
- liberal (`TY + M/TY + M`): **9/9 = 100.0%**
- `TV`: **0/9**
- `F`: **0/9**

Thus every C7 candidate above the frozen development P95 fusion threshold was visually at least plausible, and none was judged doubtful or false.

### DEV-P90 census — all 15 cases

Labels:

`M/TY, TY, M/TY, M/TY, M/TY, M, M, TY, M/TY, TV, TV, M, M/TY, TY, TY`

- strict (`TY`): **4/15 = 26.7%**
- intermediate (`TY + M/TY`): **10/15 = 66.7%**
- liberal (`TY + M/TY + M`): **13/15 = 86.7%**
- `TV`: **2/15 = 13.3%**
- `F`: **0/15 = 0.0%**

There were no visually false cases in the full C7 DEV-P90 census. The two non-liberal cases were `TV`, not `F`.

### Near-P90 controls — five deliberately difficult cases

Labels:

`M/TY, F, M/TY, TY, M`

- strict: **1/5 = 20.0%**
- intermediate: **3/5 = 60.0%**
- liberal: **4/5 = 80.0%**
- `F`: **1/5 = 20.0%**

Because these controls are the highest-scoring cases just below P90, this is a challenge set and cannot estimate population false-positive rate below the threshold.

## Scientific interpretation

The frozen three-signal fusion passed its first independent geographic blind review as a **candidate-ranking / QA system**:

- DEV-P95: 9/9 visually at least plausible, with zero `TV` and zero `F`.
- DEV-P90: 13/15 visually at least plausible and zero `F`.
- The only explicit `F` among the 20 blind cases occurred in the deliberately hard just-below-P90 controls.

However, the result does **not** justify equating P90/P95 with an automatically proven administrative split. Only 2/9 P95 and 4/15 P90 were labelled fully `TY` across the visual series. The majority are visually plausible rather than unequivocally proven.

A useful product interpretation is therefore:

- frozen fusion P95: very strong **high-priority split candidate / QA tier**;
- frozen fusion P90: strong **split candidate / QA tier**;
- automatic geometry replacement remains **NO** at this stopping point.

The near-P90 controls also show that the threshold boundary is not a sharp biological discontinuity. Four of five hard controls were still visually plausible. Therefore C7D must not be used to retune the threshold downward.

## Comparison with earlier failed scalar high-confidence rule

The earlier `separation_ratio >= 4` high-confidence rule failed independent C5D review because two of six high-confidence cases were visually false and Sentinel separation ranked in the wrong direction within that tiny census.

C7D is materially different: the fusion was frozen before C7 and combines independent history, Sentinel separation, and TRUE-LOO reproducibility. In the independent C7 P90/P95 census it produced zero visually false cases. This is the strongest evidence so far that the three-signal architecture is preferable to a single Sentinel scalar threshold.

## Guards / decision

- Fusion refit on C7: **FALSE**
- Threshold tuning on C7D: **FALSE**
- Product rule frozen automatically: **FALSE**
- Automatic geometry change: **FALSE**
- Sentinel Hub PU used in C7D: **0**

Recommended stopping-point decision: **PASS AS QA/RANKING EVIDENCE; DO NOT YET FREEZE AUTOMATIC SPLIT PRODUCT RULE.**
