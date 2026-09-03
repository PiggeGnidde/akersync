# Rapskartan Skåne V1 – pre-blind model candidate

This phase is restricted to development years 2018–2024. It produces three independently reported
arms at each of the nine frozen spring cutoffs:

1. `PRIOR_ONLY` – crop-history information from strictly earlier years;
2. `SATELLITE_ONLY` – causal Sentinel-2 L2A observations through the cutoff;
3. `PRIOR_PLUS_SATELLITE` – the two sources combined.

The development sample contains 60 winter-rapeseed fields and 180 controls per year. Controls are
stratified into winter crops, spring crops and other crops. Sampling is deterministic,
municipality-balanced and weighted back to the eligible year/group population. Model selection uses
whole target years as folds. A second robustness table holds out five deterministic municipality
groups. Platt and isotonic calibration are cross-fitted by development year.

The original field polygon is frozen as the V1 edge rule. STOPPUNKT B showed small median edge
sensitivity while inward buffers made five pilot field/rule combinations empty. SCL classes 2, 4 and
5 remain valid; the other SCL classes remain excluded. CLD remains diagnostic only.

The runner creates a hash-locked model bundle for every arm and cutoff, plus feature, threshold,
calibration and model contracts. A separate verifier must print both required pre-blind declarations
before the package may proceed.

The phase never reads row-level 2025 crop labels and never generates 2025 predictions. It contains no
Sentinel-1, full-Skåne prediction, web, deployment, tag or merge operation.
