# ÅkerPuls 2026 – C5D blind visual labels

These labels were fixed from the rendered C5D_01..C5D_12 images before opening `c5d_BLIND_KEY_DO_NOT_OPEN_BEFORE_REVIEW.csv`.

The visual task is to judge whether the proposed two-region geometry looks like a plausible 2026 field split, using the four frozen Sentinel-2 snapshots only. Labels are intentionally conservative.

## Frozen labels

| Blind index | Label | Short rationale |
|---:|---|---|
| 01 | MÖJLIG | Coherent upper/lower contrast across dates, but the lower child is small and could still be a local management/headland effect. |
| 02 | TYDLIG | Two coherent regions with repeated spectral/phenological separation and a plausible internal boundary. |
| 03 | FALSK | Inner-island/ring-like topology rather than a plausible bisecting field boundary. |
| 04 | TVEKSAM | Persistent contrast exists, but the geometry is dominated by a small cap/patch and is not a clean two-field division. |
| 05 | FALSK | Long narrow parallel-band structure is more consistent with within-field strip/management pattern than a new field boundary. |
| 06 | TYDLIG | Two sizeable coherent regions with a plausible bisecting boundary and repeated temporal contrast. |
| 07 | TYDLIG | Natural upper/lower lobes separated by a narrow neck, with strong and persistent phenological difference. |
| 08 | TYDLIG | Two natural arms of the parent geometry behave differently through the season; split is geometrically plausible. |
| 09 | TVEKSAM | Small triangular/end patch differs from the main strip, but could be an edge/headland effect rather than a true split. |
| 10 | FALSK | Small internal cap/island-like region; contrast is present but topology does not look like a clean field division. |
| 11 | TYDLIG | Two broad full-length strips with strong persistent contrast and a simple plausible dividing boundary. |
| 12 | FALSK | Complex C/ring-like morphology around an internal obstacle; not a plausible simple field split. |

Totals: **5 TYDLIG, 1 MÖJLIG, 2 TVEKSAM, 4 FALSK**.

## Evaluation convention after reveal

Two binary views should be reported without relabelling:

- **Strict visual positive:** TYDLIG only.
- **Liberal visual positive:** TYDLIG + MÖJLIG.

C5D contains all six HIGH_CONFIDENCE_SPLIT cases from the independent 1000-field holdout plus six deliberately difficult candidate controls below the `separation_ratio = 4.0` threshold. Therefore post-reveal precision can be reported for the high-confidence census in this holdout, while the control set must not be treated as a random negative sample.

No threshold or rule was changed while assigning these labels.
