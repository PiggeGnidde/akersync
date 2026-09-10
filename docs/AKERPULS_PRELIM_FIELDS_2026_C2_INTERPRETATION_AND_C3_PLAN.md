# ÅkerPuls preliminära skiften 2026 – C2 interpretation och C3-plan

C2 independent validation (1000 fields) was run with candidate discovery identical to B2 and the split rule locked from B5/B5b.

Observed C2 result:
- baseline split candidates: 226/1000 = 22.60%
- locked split candidates: 43/1000 = 4.30%
- retention of baseline: 19.03%
- uncertain fields: 113/1000
- adjacency pairs: 1237
- merge candidates: 129/1237 = 10.43%, candidate-only
- all-four-snapshot valid pixel fraction: 83.29%
- no threshold tuning, zero additional Sentinel Hub PU.

Comparison with B pilot:
- B baseline splits: 34/221 = 15.38%
- B locked splits: 7/221 = 3.17%
- B locked retention: 7/34 = 20.59%
- C locked retention: 43/226 = 19.03%

The almost unchanged retention ratio is encouraging because C is geographically independent and has materially worse July coverage. The difference in raw baseline rate must not be interpreted as an accuracy change without accounting for geography, field-size mix and validity.

C1 July validity is 83.30% at pilot-pixel level, while April/May/June are almost complete. C2 currently requires pixels valid in all four snapshots, so C3 must diagnose whether the 113 UNCERTAIN outcomes are driven by July missingness before any algorithmic conclusion is drawn.

C3 therefore performs:
1. field-level outcome stratification by July validity (>=80%, 50-80%, <50%);
2. a 20-image blinded diagnostic challenge set, containing 10 representative locked positives and 10 difficult baseline candidates rejected by the locked rule;
3. deterministic hidden mixing; the key is written locally but must not be opened before visual labels are fixed.

The C3 set is diagnostic, not a random accuracy sample; its raw visual pass fraction is not an estimator of precision or recall. No thresholds, dates, preprocessing, merge policy or geometry are changed.

Implementation note: `src/122_akerpuls_prelim_fields_2026_c3_blind_qa.py` was superseded before first execution by corrected `src/123_akerpuls_prelim_fields_2026_c3_blind_qa_fixed.py`; the public runner calls only the corrected script.
