# ÅkerScore × normskörd validation v0a

Status: exploratory validation branch. No ÅkerScore recalibration.

## Scientific question

Can a single increasing function of ÅkerScore explain official 2026 winter-wheat norm-yield differences across Skåne SKO, when each SKO is represented by the area-weighted ÅkerScore distribution of fields that actually grew winter wheat in ÅkerMinne 2015–2025?

## Frozen lineage

- Base tag: `akerscore-akerminne-validation-v1.0`
- Base commit: `9ca92418d6c100793dcaf3ae70705c97e556a9d5`
- Combined context: `akerpass-akerminne-context-v1.0`
- ÅkerMinne: `akerminne-v1.0`
- ÅkerScore: `akerscore_soil_v0c`

The analysis consumes the exact hash-locked compact CSV.GZ package already used by the frozen behavioural validation. It verifies all three SHA256 hashes before analysis.

## Primary cohort

- Winter wheat: official annual crop code `4 = Vete (höst)`.
- ÅkerMinne `status == SINGLE_CROP` only.
- Valid `akerscore_soil_p50`.
- `dominant_sko_share >= 0.95` to avoid assigning materially split SKO fields wholly to one area.
- Area weight: `current_area_m2` for each qualifying field-year.
- ÅkerMinne years 2015–2025 are pooled to estimate each SKO's score distribution. They are **not** treated as 11 independent norm-yield target observations.

## Official target

`normskord_hostvete_2026.csv` stores Jordbruksverket's official 2026 winter-wheat norm yield and enterprise count for the 17 dominant Skåne SKO IDs in the combined context. Published norm yield is available for 15 of them; `0731` and `1131` are blank.

Source table: Jordbruksverket statistikdatabas, `Normskörd efter skördeområde och gröda. År 2003–2026`, table `JO0602A03`.

## Models

### 1. Primary constrained linear bridge

`norm_t_ha = a + b * mean_areaweighted_AkerScore`, with `b >= 0`.

Reported:

- `b` in t/ha per score point,
- effect per +10 ÅkerScore,
- R²,
- RMSE and MAE,
- leave-one-SKO-out RMSE/MAE,
- classical slope interval when the fitted slope is positive.

A robustness fit excludes official SKO targets based on fewer than 100 enterprises.

### 2. Smooth monotone curve

A piecewise-linear curve is fitted at ÅkerScore knots 30, 40, ..., 100 with non-negative increments. A second-difference smoothness penalty is selected by leave-one-SKO-out RMSE over a fixed lambda grid.

This model uses each SKO's **whole area-weighted ÅkerScore distribution**, not only its mean.

## Run

From a checkout/worktree containing this branch:

```cmd
analysis\akerscore_normskord_validation_v0a\RUN_VALIDATION.bat
```

Default input:

```text
C:\AkerSyncRepo\work\akerscore_validation_csv_upload
```

Default output:

```text
C:\AkerSyncRepo\work\akerscore_normskord_validation_v0a
```

Expected successful ending:

```text
VALIDATION: PASS
RUN_VALIDATION: PASS
```

Return the full terminal output plus `results.json` and `sko_fit_table.csv` for interpretation.

## Guardrail

This is an aggregate bridge/validation experiment. Normskörd is an SKO-level long-run target, not measured field yield. Even a strong fit does not by itself constitute direct ton/ha validation at individual field level. Hasund-derived yield gradients and other independent agronomic estimates must remain outside the fit and be compared only after the result is obtained.
