# ÅkerVärde v1.0-rc1 — freeze before blind backtest

Purpose: freeze the already selected `S70_NOFOREST / BASE` model before using 2018–2019 transactions as external historical blind validation.

## Frozen production candidate

- Target: observed purchase price in SEK.
- Tax-assessed value: not used as target or predictor.
- Sample used for fitting: `S70_NOFOREST` from v0j.
- Arable rate terms: `year_centered`, `log_area_20`, `lat_centered`, `lon_centered`.
- Mixed-property nuisance components remain those selected by the frozen v0j code.
- Validation already used for model selection: deterministic 10-fold spatial-group CV; 10 km sale cells stay together.
- Strict-anchor diagnostics are kept separate.

`FREEZE_AKERVARDE_V1RC.bat` reruns exactly this specification and writes a local immutable artifact under:

`data/derived/akervarde_v1_0_rc1_freeze/`

The artifact includes full-fit coefficients, held-out spatial-CV predictions, strict-anchor empirical P10/P50/P90 calibration ratios, validation metrics, pre-registered blind-test rules and SHA256 hashes of the source feature file/model code/artifacts.

Training data and derived model outputs are intentionally not committed to this public repository.

## Blind backtest protocol

The planned historical blind set is 2018–2019 transactions selected without regard to model error or price level:

- market transaction;
- at least 5 ha arable land;
- unbuilt: no small house and no economic building;
- no forest;
- no pasture;
- no forest impediment;
- residual `other_ha <= 0.5`;
- valid coordinates.

Primary metrics:

1. median absolute percentage error;
2. median observed/predicted ratio (bias);
3. log-price R²;
4. coverage of the frozen empirical P10–P90 interval.

Pragmatic MVP green-light guidance, frozen before results are inspected:

- preferably at least 20 transactions combined;
- median APE <= 25%;
- median observed/predicted ratio 0.85–1.15;
- at least 70% inside the nominal P10–P90 interval (small-n tolerance; nominal target 80%).

These are product-development criteria, not regulatory appraisal standards.

## Non-negotiable blind-test rule

If the model, coefficients, calibration interval or selection logic is changed after inspecting 2018/2019 outcomes, those transactions cease to be blind validation for the changed model. A new untouched validation set is then required.

## Recommended Git marker

After running the freeze successfully:

```bat
git tag -a akervarde-v1.0-rc1 -m "Frozen before 2018-2019 blind backtest"
git push origin akervarde-v1.0-rc1
```

If the blind backtest is acceptable, the same frozen model can then be promoted/documented as ÅkerVärde v1.0; otherwise create a new candidate version and preserve rc1 unchanged.
