# ÅkerPuls 2026 – C3 blind visual labels, pre-reveal

Date: 2026-09-10

These labels were assigned from C3_01.png–C3_20.png **before opening or reading**
`c3_BLIND_KEY_DO_NOT_OPEN_BEFORE_REVIEW.csv`.

Purpose: freeze the visual judgement before the hidden PASS/REJECT source labels are revealed.
These are visual QA labels, not ground truth.

| Blind | Field | Visual label | Short rationale |
|---:|---|---|---|
| 01 | `2025|61524022845|6A` | FALSK | Fragmented/speckled internal pattern; no clean management partition. |
| 02 | `2025|61483971029|44A` | FALSK | Interior island/ring pattern rather than a boundary dividing the parent. |
| 03 | `2025|61524016147|8A` | TVEKSAM | Two spectral lobes are visible, but field is small and geometry is not a convincing clean split. |
| 04 | `2025|61564023062|22A` | FALSK | Very narrow field and essentially uniform temporal behaviour; no convincing internal boundary. |
| 05 | `2025|61483957161|65C` | MÖJLIG | Recurrent upper/lower contrast, but geometry is complex and not a clean two-part division. |
| 06 | `2025|61503954423|2A` | TYDLIG | Two coherent parts with strong, recurring phenological contrast and a plausible partition. |
| 07 | `2025|61543971717|12C` | TYDLIG | Left arm and right block behave differently across snapshots; natural split at the neck. |
| 08 | `2025|61543996618|7A` | FALSK | Thin edge-strip signal plus poor July coverage; looks edge/resolution dominated. |
| 09 | `2025|61514015168|14A` | FALSK | Large interior patch/ring-like pattern rather than two independently managed regions. |
| 10 | `2025|61543972237|16A` | TYDLIG | Main left body and right lobe show persistent divergent temporal behaviour. |
| 11 | `2025|61514020299|1A` | TYDLIG | Top arm and long lower arm form two coherent regions with strong repeated contrast. |
| 12 | `2025|61524013308|6A` | TYDLIG | Small cap and main body remain consistently distinct over the season; simple plausible boundary. |
| 13 | `2025|61534023314|2B` | MÖJLIG | Stable longitudinal contrast, but long narrow strip geometry makes mixed-pixel/soil effects plausible. |
| 14 | `2025|61503952967|1B` | MÖJLIG | Persistent upper-left vs remainder contrast, but internal hole/complexity weakens certainty. |
| 15 | `2025|61514043034|25A` | MÖJLIG | Stable diagonal two-part pattern, but small field and narrow geometry make it less secure. |
| 16 | `2025|61514033926|7A` | FALSK | Central lens/island structure; not a boundary that cleanly partitions the field. |
| 17 | `2025|61534034964|8A` | FALSK | Small fragmented internal patch pattern; not a plausible simple split. |
| 18 | `2025|61494010198|11A` | FALSK | Complex patching around an internal obstacle/yard-like feature; likely local heterogeneity. |
| 19 | `2025|61543969088|35A` | MÖJLIG | Straight internal contrast is plausible in April–June, but July invalidity and farm-edge context reduce confidence. |
| 20 | `2025|61514000820|55C` | FALSK | Nested/curved banding inside the field looks like within-field structure rather than a new field boundary. |

## Frozen counts

- TYDLIG: 5
- MÖJLIG: 5
- TVEKSAM: 1
- FALSK: 9

For binary diagnostics after reveal, use two views rather than silently collapsing ambiguity:

1. **Strict-positive:** TYDLIG = positive; MÖJLIG/TVEKSAM/FALSK = non-positive.
2. **Liberal-positive:** TYDLIG + MÖJLIG = positive; TVEKSAM + FALSK = non-positive.

Do not alter these labels after the blind key is revealed; any later reinterpretation must be recorded separately.
