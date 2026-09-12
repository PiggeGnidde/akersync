# ÅkerPuls full Skåne D0b sparse normalization — result

Status: **PASS; ZERO PU**

Base D0 found six 20×20 km analysis cells with fewer than 200 normalization fields. D0b applied the predeclared label-free fallback only to those cells: symmetric square expansion by 10 km, then 20 km if needed, choosing the smallest expansion reaching at least 200 intersecting 2025 fields.

All six resolved at the first 10 km expansion:

- `A_E0017_N0309`: 165 → 1,867 fields
- `A_E0017_N0313`: 46 → 3,939 fields
- `A_E0018_N0306`: 157 → 3,051 fields
- `A_E0018_N0313`: 16 → 4,376 fields
- `A_E0021_N0306`: 128 → 5,601 fields
- `A_E0023_N0313`: 2 → 875 fields

No dense base cell was changed. No labels or model outputs were used. No threshold was tuned.

Key hashes:

- resolved normalization windows SHA256: `0e3faedd3da470a261a7348d4d4129d52d938c10f34350ccea328b47581c6dc8`
- base D0 execution contract SHA256: `4cf28a8cf43848f279d06917aadfb1eb0b54499e1acadf57f8296557dff940a1`
- final D1 execution contract SHA256: `d2c2a88d0978cffcd720dbb7a7982049fbc5c09ae41f3f7be2e959ad254aec19`

Guards remain unchanged:

- automatic split: **FALSE**
- automatic merge: **FALSE**
- automatic geometry replacement: **FALSE**
- Sentinel Hub PU used: **0**

Decision: **PASS TO D1 SENTINEL ACQUISITION**.
