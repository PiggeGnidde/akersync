# ÅkerPuls 2026 – C5B result and C5C plan

C5B third-holdout raster preprocessing PASS.

Observed validity on the 1000-field northwest-Skåne holdout:
- April valid pixels 0.9977; 996/1000 fields >=80% valid.
- May valid pixels 0.9969; 994/1000 fields >=80% valid.
- June valid pixels 0.9952; 993/1000 fields >=80% valid.
- July valid pixels 0.9999; 1000/1000 fields >=80% valid.
- Reported Sentinel Hub PU: 153.222193.

This is a particularly clean external holdout because all four frozen snapshots have near-complete coverage. No preprocessing rule changed relative to B1/C1.

## C5C

C5C is zero-PU and applies, without tuning:
1. Candidate discovery identical to B2.
2. Frozen SPLIT_CANDIDATE gate: LCF >=0.95, edge ratio >=1.8 in >=3/4 snapshots, LOO_ALL4.
3. Frozen test-only HIGH_CONFIDENCE_SPLIT: SPLIT_CANDIDATE AND separation_ratio >=4.0.
4. Merge remains MERGE_CANDIDATE_ONLY.

No product threshold is frozen by C5C itself. The next step after C5C is blinded visual QA on this third geographic holdout before any product-freeze decision.
