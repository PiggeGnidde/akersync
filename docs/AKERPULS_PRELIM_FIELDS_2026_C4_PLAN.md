# ÅkerPuls 2026 – STOPPUNKT C4 plan

C3 is now development data because the blind key has been revealed. Its purpose in C4 is not to provide a new validation estimate, but to help construct a stricter second-stage `HIGH_CONFIDENCE_SPLIT` candidate that can later be tested unchanged on new geography.

The existing C2/B5 rule remains untouched and continues to define `SPLIT_CANDIDATE`:

- largest-component fraction >= 0.95 for both children,
- edge-ratio >= 1.8 in at least 3 of 4 snapshots,
- `LOO_ALL4=true`.

C4 reconstructs all 226 C baseline split candidates with the exact C2 spectral scaling and k=2 clustering. It computes richer topology/morphology diagnostics, including:

- number of connected components per child,
- whether each largest child component itself reaches the parent boundary,
- largest-child boundary-contact fractions,
- internal-interface component count and endpoint components,
- child holes / ring topology,
- interface normalized length and anisotropy,
- total and per-snapshot spectral separation,
- median/min/max edge-ratio.

The analysis set contains all 43 locked `SPLIT_CANDIDATE` cases plus temporally robust near-rejects close to the LCF gate. This is intended to expose ring/island/fragmentation pathologies and potential false negatives without changing the candidate rule.

A deliberately simple post-hoc core development candidate is also evaluated:

`HIGH_CONFIDENCE_SPLIT_CANDIDATE = SPLIT_CANDIDATE AND separation_ratio >= 4.0`

The value 4.0 is explicitly post-hoc: it was suggested by the revealed C3 examples and is therefore not validated by C3. C4 also runs a morphology/topology sensitivity grid using only frozen `TYDLIG` and `FALSK` C3 labels as decisive development anchors. `MÖJLIG` and `TVEKSAM` are retained in the diagnostic output but not used for choosing the strict high-confidence rule.

No thresholds are frozen in C4. No geometry is committed. No Sentinel API calls are made. Merge remains `MERGE_CANDIDATE_ONLY`.

The next scientific step after C4 is to select one simple high-confidence development rule, freeze it for testing only, and evaluate it unchanged on a third independent geographic patch. Whole-Skåne processing remains blocked until that independent test is satisfactory.
