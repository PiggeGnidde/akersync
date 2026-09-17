# ÅkerPuls M4 reimplementation V1 – reproduction and persistence protocol

## Why this exists

The original STOPPUNKT C computations were performed in a transient chat/sandbox environment. The frozen data contract, model card, benchmark results and Technical Note survived, but the executable feature builder and serialized LightGBM model did not.

This reimplementation therefore has two goals:

1. reproduce the frozen M4 behaviour closely enough against the preserved 2021–2025 benchmark;
2. make the implementation and every model artefact durable so the model can never again exist only inside a chat runtime.

## Frozen lineage

- M0 merge satellite-only freeze SHA-256: `fd2536789931cc51466364580b3f32de90da4e405217ee025fffc35fbe917051`
- M4 freeze contract branch/commit: `feature/akerpuls-vaxfoljd-prior-v1a` @ `116d10ee20dd0bc7d3c95507a12d5c381f03c785`
- selected model: M4-hard multiclass
- next true blind year: 2026

Frozen source inputs:

- `akerminne_2015_2025_selected.csv.gz`
  - SHA-256 `05423236dc30544f86422d42ce5c9095376a9d5dac58e6ea110f6e6702cecdcf`
  - 1,414,996 field-years, 128,636 fields
- `field_static_context_selected.csv.gz`
  - SHA-256 `31db31b79b53a4c0aa32621fb7bfa44165ea65b6b46371c32e4e19935f59feea`
  - 128,636 fields
- `akerscore_soil_skiften_selected.csv.gz`
  - SHA-256 `71dfd711a4243b3cbe465de7eaa013725b2d2f9be3a8890d213a89bc095427da`
  - 128,636 fields

Local source directory:

`C:\AkerSyncRepo\work\akerscore_validation_csv_upload`

## Frozen model contract

Target is a probability vector over 16 agronomic classes:

1. höstraps
2. höstvete
3. vårvete
4. höstkorn
5. vårkorn
6. havre
7. råg
8. rågvete
9. sockerbetor
10. matpotatis
11. stärkelsepotatis
12. vall på åkermark
13. majs
14. baljväxter
15. träda/miljöyta
16. annan gröda

`otillräcklig historik/okänd` is history/observation quality, not a target class.

History features are built using years strictly `< prediction_year` and include:

- latest 1–3 dominant valid crops;
- crop-specific time since last occurrence;
- crop counts in 3/5/7/10-year windows;
- long-run crop share;
- valid-history count, coverage and dominant-share quality.

Static context includes municipality, dominant SKO, dominant soil/agricultural class, field area, ÅkerScore Soil p50 and context/soil QA.

Frozen LightGBM candidate parameters:

- objective: multiclass
- `n_estimators=35`
- `num_leaves=31`
- `learning_rate=0.12`
- `min_child_samples=100`
- `colsample_bytree=0.7`
- `reg_lambda=5.0`
- `random_state=20260907`

## Reproduction gate

Before 2026 is predicted, the reimplementation must run the historical year-blind protocol and compare against the frozen M4 benchmark for target years 2021–2025.

Frozen benchmark rows are preserved in:

`analysis/vaxfoljd_prior_v1/results/vaxfoljd_m4_full_paired_comparison.csv`

The comparison must report at minimum: sample count, multiclass log-loss, multiclass Brier score, top-1 accuracy, top-3 accuracy, ECE and mean entropy.

Because the original executable feature builder was not preserved, exact floating-point identity is not assumed in advance. Any tolerance used to declare reproduction PASS must be written into code/config **before** inspecting the reproduction results and must not be tuned on 2026.

## Persistence rule – mandatory

No accepted M4 run may exist only in terminal output or chat state.

For every accepted reproduction/final run we save all of the following:

- source code in Git;
- exact Git commit;
- frozen source-input hashes;
- Python/package versions;
- complete feature schema and feature order;
- crop-class mapping and class order;
- missing-value/categorical encoding policy;
- training cutoff and target year;
- fold metrics and comparison against frozen benchmark;
- LightGBM model for every accepted fold using portable `Booster.save_model(... .txt)`;
- final 2026 model using portable LightGBM text format;
- 2026 per-field probability vector as Parquet;
- top-1, top-3, entropy and history-quality diagnostics;
- SHA-256 manifest over every saved artefact.

The final 2026 package will live under a dedicated immutable directory below:

`C:\AkerSyncRepo\work\akerpuls_m4_2026_prior_freeze_v1`

and will receive a formal freeze JSON plus a Git tag only after review.

## Separation from merge M0/M1

M4 remains pre-satellite. It must not read Sentinel imagery, M0 merge status or human merge labels while generating the 2026 crop prior.

For merge M1, the frozen 2026 field prior will later be projected onto the exact frozen 27,146 M0 pair universe. Pair features such as `P_samecrop`, Jensen–Shannon divergence, top-k overlap and entropy are separate downstream artefacts. No M0 threshold or status is modified by generating M1.
