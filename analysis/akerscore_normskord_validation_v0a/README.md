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

## Run normskörd-only validation

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

## SMHI PTHBV climate extension

The climate extension tests whether long-run growing-season climate explains part of the SKO residual structure left by ÅkerScore.

Frozen exploratory climate definition:

- source: SMHI PTHBV 4×4 km gridded temperature and precipitation,
- years: 2011–2025 inclusive,
- growing period: April–July,
- temperature covariate: mean April–July temperature, °C,
- precipitation covariate: mean annual April–July precipitation sum, mm,
- spatial matching: exact current-field polygon × PTHBV grid-cell overlap,
- SKO aggregation: same winter-wheat field-years and area weights as the normskörd validation.

Download from SMHI's PTHBV page using **Hela Sverige (NetCDF)**, years **2011–2025**, **Månadsvärden**, **Nederbörd och temperatur**. Save or rename the file to:

```text
C:\AkerSyncRaw\smhi\pthbv_2011_2025_monthly.nc
```

Then update the worktree and run:

```cmd
git pull origin feature/akerscore-normskord-validation-v0a
analysis\akerscore_normskord_validation_v0a\RUN_CLIMATE_VALIDATION.bat
```

A different NetCDF path can be supplied as the first argument.

The workflow:

1. verifies the frozen ÅkerScore/ÅkerMinne compact input hashes,
2. opens PTHBV NetCDF and identifies temperature, precipitation, time and grid coordinates,
3. computes 2011–2025 April–July climatology,
4. intersects PTHBV cells exactly with the current 2025 wheat-field polygons,
5. aggregates climate with the same wheat-field-year area weighting as the norm-yield experiment,
6. compares `score only`, `climate only`, and `score + climate` models,
7. reports both in-sample metrics and leave-one-SKO-out RMSE/MAE,
8. repeats the climate model excluding `1321`, `1124`, and `1221` as a robustness run.

Main outputs:

```text
C:\AkerSyncRepo\work\akerscore_normskord_climate_v0a\climate\sko_climate_2011_2025_apr_jul.csv
C:\AkerSyncRepo\work\akerscore_normskord_climate_v0a\all_sko\climate_results.json
C:\AkerSyncRepo\work\akerscore_normskord_climate_v0a\all_sko\sko_climate_model_table.csv
C:\AkerSyncRepo\work\akerscore_normskord_climate_v0a\excl_sparse\climate_results.json
```

If the SMHI NetCDF uses an unexpected schema/CRS, the BAT runner automatically prints the dataset structure with `inspect_pthbv.py`; no silent CRS or variable-name guess is forced beyond guarded common CF conventions.

## Guardrail

This is an aggregate bridge/validation experiment. Normskörd is an SKO-level long-run target, not measured field yield. Even a strong fit does not by itself constitute direct ton/ha validation at individual field level. The climate extension has only about 15 SKO observations, so leave-one-SKO-out performance matters more than an impressive in-sample R². Hasund-derived yield gradients and other independent agronomic estimates must remain outside the fit and be compared only after the result is obtained.
