# ÅkerPuls 2026 – C3 blind reveal

Blind visual labels were fixed before opening the key. The blind key SHA256 reported by the C3 runner was:

`79572b3c1ec2235504ae01002aca704c84943351f2fa98010cd8a811f67013e9`

## Frozen visual labels

- 01 FALSK
- 02 FALSK
- 03 TVEKSAM
- 04 FALSK
- 05 MÖJLIG
- 06 TYDLIG
- 07 TYDLIG
- 08 FALSK
- 09 FALSK
- 10 TYDLIG
- 11 TYDLIG
- 12 TYDLIG
- 13 MÖJLIG
- 14 MÖJLIG
- 15 MÖJLIG
- 16 FALSK
- 17 FALSK
- 18 FALSK
- 19 MÖJLIG
- 20 FALSK

Totals: 5 TYDLIG, 5 MÖJLIG, 1 TVEKSAM, 9 FALSK.

## Revealed algorithm groups

LOCKED_PASS_REPRESENTATIVE: 04, 06, 07, 08, 09, 10, 11, 13, 14, 18.

LOCKED_REJECT_CHALLENGE: 01, 02, 03, 05, 12, 15, 16, 17, 19, 20.

### Visual composition by algorithm group

Locked PASS (n=10):
- 4 TYDLIG: 06, 07, 10, 11
- 2 MÖJLIG: 13, 14
- 0 TVEKSAM
- 4 FALSK: 04, 08, 09, 18

Locked REJECT challenge (n=10):
- 1 TYDLIG: 12
- 3 MÖJLIG: 05, 15, 19
- 1 TVEKSAM: 03
- 5 FALSK: 01, 02, 16, 17, 20

## Strict binary view

Define visual positive = TYDLIG only.

- TP = 4
- FP = 6
- FN = 1
- TN = 9
- apparent precision on this challenge set = 4/10 = 0.40
- apparent recall on this challenge set = 4/5 = 0.80
- apparent specificity = 9/15 = 0.60
- apparent accuracy = 13/20 = 0.65

These are NOT population precision/recall estimates because C3 deliberately used a balanced diagnostic challenge set: 10 representative locked passes and 10 difficult near-threshold rejects.

## Liberal binary view

Define visual positive = TYDLIG or MÖJLIG; TVEKSAM is counted with the negative side for this simple binary display.

- TP = 6
- FP = 4
- FN = 4
- TN = 6
- apparent precision = 0.60
- apparent recall = 0.60
- apparent specificity = 0.60
- apparent accuracy = 0.60

Again, these are challenge-set diagnostics, not population accuracy estimates.

## What the reveal says

1. The locked rule enriches clear cases: 4/10 PASS cases were visually TYDLIG versus 1/10 among the difficult REJECT set. For TYDLIG+MÖJLIG, enrichment is 6/10 versus 4/10.
2. The rule is not yet safe for automatic geometry replacement. Four locked PASS examples were visually FALSK.
3. The current C3 separation is driven almost entirely by the LCF gate. Every REJECT challenge example has LCF < 0.95, while every PASS example has LCF >= 0.95; edge-support and LOO generally pass on both sides.
4. LCF is useful but insufficient as an agronomic topology test. Example 12 is visually TYDLIG but rejected at LCF=0.9462, only 0.0038 below the cutoff. Conversely false PASS examples include LCF 0.9706, 0.9846 and 1.0.
5. A stronger candidate-quality signal is visible in total separation ratio among the clear PASS examples: 06=4.635, 07=8.252, 10=5.282, 11=4.211. The false PASS examples were 04=2.379, 08=1.980, 09=3.233, 18=3.766. This suggests a possible high-confidence tier, but any threshold inferred from C3 is post-hoc and must be validated on a new geographic holdout before freeze.

## Decision

STOPPUNKT C is not a model freeze.

Recommended next step is a no-PU diagnostic on the existing C data to reconstruct richer topology/morphology features for all locked-pass and near-reject candidates. The goal is to identify a second-stage HIGH_CONFIDENCE_SPLIT rule (e.g. stronger temporal separation plus topology guards), while retaining the current locked rule as SPLIT_CANDIDATE. Any new rule learned from C3 must then be validated on another independent geographic patch before whole-Skåne processing.
