#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ÅkerScore ↔ official normskörd validation v0a.

Question:
Can one stable increasing function of ÅkerScore explain the cross-SKO
variation in official 2026 winter-wheat norm yield, when each SKO is represented
by the area-weighted ÅkerScore distribution of fields that actually grew
winter wheat in ÅkerMinne 2015–2025?

This is deliberately a read-only validation experiment. It does not modify or
recalibrate ÅkerScore, ÅkerMinne, SKO, ÅkerDrift or ÅkerVärde.

Primary data rules:
- Frozen compact input package from ÅkerScore × ÅkerMinne validation v1.0.
- Winter wheat = annual official crop code 4 (Vete (höst)).
- Only ÅkerMinne rows with status SINGLE_CROP.
- Valid ÅkerScore Soil P50.
- Clean SKO assignment: dominant_sko_share >= 0.95.
- Area weight = current_area_m2 for each qualifying field-year.
- 2026 official normskörd is one target per SKO; years are pooled to estimate
  each SKO's ÅkerScore distribution and are NOT treated as independent target
  observations.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import lsq_linear
from scipy.stats import t as student_t


VERSION = "akerscore-normskord-validation-v0a"
WINTER_WHEAT_CODE = 4
MIN_DOMINANT_SKO_SHARE = 0.95

EXPECTED_INPUTS = {
    "field_static_context_selected.csv.gz": {
        "rows": 128_636,
        "sha256": "31db31b79b53a4c0aa32621fb7bfa44165ea65b6b46371c32e4e19935f59feea",
    },
    "akerminne_2015_2025_selected.csv.gz": {
        "rows": 1_414_996,
        "sha256": "05423236dc30544f86422d42ce5c9095376a9d5dac58e6ea110f6e6702cecdcf",
    },
    "akerscore_soil_skiften_selected.csv.gz": {
        "rows": 128_636,
        "sha256": "71dfd711a4243b3cbe465de7eaa013725b2d2f9be3a8890d213a89bc095427da",
    },
}

KNOTS = np.array([30., 40., 50., 60., 70., 80., 90., 100.])
LAMBDA_GRID = np.r_[0.0, np.logspace(-4, 4, 17)]


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_inputs(input_dir: Path) -> None:
    failures = []
    for name, expected in EXPECTED_INPUTS.items():
        p = input_dir / name
        if not p.exists():
            failures.append(f"missing {p}")
            continue
        digest = sha256_file(p)
        if digest.lower() != expected["sha256"].lower():
            failures.append(
                f"{name}: SHA256 mismatch\n"
                f"  expected {expected['sha256']}\n"
                f"  got      {digest}"
            )
    if failures:
        raise RuntimeError("Frozen input verification failed:\n" + "\n".join(failures))


def load_inputs(input_dir: Path):
    ctx = pd.read_csv(input_dir / "field_static_context_selected.csv.gz", low_memory=False)
    hist = pd.read_csv(input_dir / "akerminne_2015_2025_selected.csv.gz", low_memory=False)
    score = pd.read_csv(input_dir / "akerscore_soil_skiften_selected.csv.gz", low_memory=False)

    actual = {
        "field_static_context_selected.csv.gz": len(ctx),
        "akerminne_2015_2025_selected.csv.gz": len(hist),
        "akerscore_soil_skiften_selected.csv.gz": len(score),
    }
    bad = [
        f"{name}: rows {actual[name]:,} != {meta['rows']:,}"
        for name, meta in EXPECTED_INPUTS.items()
        if actual[name] != meta["rows"]
    ]
    if bad:
        raise RuntimeError("Frozen input row-count verification failed:\n" + "\n".join(bad))

    if ctx["current_field_id"].astype(str).duplicated().any():
        raise RuntimeError("context has duplicate current_field_id values")
    if score["current_field_id"].astype(str).duplicated().any():
        raise RuntimeError("score has duplicate current_field_id values")
    return ctx, hist, score


def load_norms(path: Path) -> pd.DataFrame:
    norms = pd.read_csv(path, dtype={"sko_id": str})
    norms["sko_id"] = norms["sko_id"].astype(str).str.zfill(4)
    norms["norm_t_ha"] = pd.to_numeric(norms["norm_kg_ha"], errors="coerce") / 1000.0
    norms["n_companies"] = pd.to_numeric(norms["n_companies"], errors="coerce")
    return norms


def weighted_mean(x, w):
    x = np.asarray(x, float)
    w = np.asarray(w, float)
    ok = np.isfinite(x) & np.isfinite(w) & (w > 0)
    if not ok.any():
        return np.nan
    return float(np.sum(x[ok] * w[ok]) / np.sum(w[ok]))


def weighted_sd(x, w):
    x = np.asarray(x, float)
    w = np.asarray(w, float)
    ok = np.isfinite(x) & np.isfinite(w) & (w > 0)
    if ok.sum() < 2:
        return np.nan
    mu = np.sum(x[ok] * w[ok]) / np.sum(w[ok])
    var = np.sum(w[ok] * (x[ok] - mu) ** 2) / np.sum(w[ok])
    return float(np.sqrt(var))


def prepare_wheat(ctx, hist, score):
    need_ctx = {"current_field_id", "dominant_sko_id", "dominant_sko_share"}
    need_hist = {
        "current_field_id", "history_year", "current_area_m2",
        "dominant_crop_code_raw", "dominant_crop_name", "status",
    }
    need_score = {"current_field_id", "akerscore_soil_p50"}
    for label, df, need in [
        ("context", ctx, need_ctx), ("history", hist, need_hist), ("score", score, need_score)
    ]:
        missing = sorted(need - set(df.columns))
        if missing:
            raise RuntimeError(f"{label} missing required columns: {missing}")

    base_cols = ["current_field_id", "dominant_sko_id", "dominant_sko_share"]
    if "crosses_sko_boundary" in ctx.columns:
        base_cols.append("crosses_sko_boundary")
    base = ctx[base_cols].copy()
    base["dominant_sko_id"] = (
        base["dominant_sko_id"].astype(str)
        .str.replace(r"\.0$", "", regex=True).str.zfill(4)
    )
    base["dominant_sko_share"] = pd.to_numeric(base["dominant_sko_share"], errors="coerce")

    sc = score[["current_field_id", "akerscore_soil_p50"]].copy()
    sc["akerscore_soil_p50"] = pd.to_numeric(sc["akerscore_soil_p50"], errors="coerce")
    base = base.merge(sc, on="current_field_id", how="left", validate="one_to_one")

    h = hist.copy()
    h["dominant_crop_code_num"] = pd.to_numeric(h["dominant_crop_code_raw"], errors="coerce")
    h["current_area_m2"] = pd.to_numeric(h["current_area_m2"], errors="coerce")
    h["history_year"] = pd.to_numeric(h["history_year"], errors="coerce")

    wheat = h[
        h["status"].eq("SINGLE_CROP")
        & h["dominant_crop_code_num"].eq(WINTER_WHEAT_CODE)
    ].copy()
    wheat = wheat.merge(base, on="current_field_id", how="left", validate="many_to_one")

    n_before = len(wheat)
    wheat = wheat[
        wheat["akerscore_soil_p50"].notna()
        & wheat["current_area_m2"].gt(0)
        & wheat["dominant_sko_share"].ge(MIN_DOMINANT_SKO_SHARE)
        & wheat["dominant_sko_id"].notna()
    ].copy()
    wheat["weight_m2"] = wheat["current_area_m2"].astype(float)

    qa = {
        "winter_wheat_field_years_single_crop_before_score_sko_filter": int(n_before),
        "winter_wheat_field_years_primary": int(len(wheat)),
        "winter_wheat_unique_fields_primary": int(wheat["current_field_id"].nunique()),
        "years": sorted(int(v) for v in wheat["history_year"].dropna().unique()),
        "sko_ids_primary": sorted(wheat["dominant_sko_id"].dropna().astype(str).unique()),
        "min_dominant_sko_share": MIN_DOMINANT_SKO_SHARE,
    }
    return wheat, qa


def summarize_sko(wheat: pd.DataFrame, norms: pd.DataFrame):
    rows = []
    for sko, g in wheat.groupby("dominant_sko_id", sort=True):
        rows.append({
            "sko_id": str(sko),
            "field_years": int(len(g)),
            "unique_fields": int(g["current_field_id"].nunique()),
            "wheat_area_fieldyear_ha": float(g["weight_m2"].sum() / 10_000.0),
            "mean_akerscore_areaweighted": weighted_mean(g["akerscore_soil_p50"], g["weight_m2"]),
            "sd_akerscore_areaweighted": weighted_sd(g["akerscore_soil_p50"], g["weight_m2"]),
            "min_akerscore": float(g["akerscore_soil_p50"].min()),
            "max_akerscore": float(g["akerscore_soil_p50"].max()),
        })
    sko = pd.DataFrame(rows)
    sko = sko.merge(norms, on="sko_id", how="left", validate="one_to_one")
    sko["published_norm"] = sko["norm_t_ha"].notna()
    return sko


def summarize_years(wheat: pd.DataFrame):
    rows = []
    for (sko, year), g in wheat.groupby(["dominant_sko_id", "history_year"], sort=True):
        rows.append({
            "sko_id": str(sko),
            "year": int(year),
            "field_years": int(len(g)),
            "unique_fields": int(g["current_field_id"].nunique()),
            "wheat_area_ha": float(g["weight_m2"].sum() / 10_000.0),
            "mean_akerscore_areaweighted": weighted_mean(g["akerscore_soil_p50"], g["weight_m2"]),
        })
    out = pd.DataFrame(rows)
    if out.empty:
        return out, pd.DataFrame()
    stability = (
        out.groupby("sko_id")
        .agg(
            years=("year", "nunique"),
            yearly_mean_score_mean=("mean_akerscore_areaweighted", "mean"),
            yearly_mean_score_sd=("mean_akerscore_areaweighted", "std"),
            yearly_mean_score_min=("mean_akerscore_areaweighted", "min"),
            yearly_mean_score_max=("mean_akerscore_areaweighted", "max"),
        )
        .reset_index()
    )
    stability["yearly_mean_score_range"] = (
        stability["yearly_mean_score_max"] - stability["yearly_mean_score_min"]
    )
    return out, stability


def fit_positive_linear(x, y):
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    xm = x.mean()
    ym = y.mean()
    denom = np.sum((x - xm) ** 2)
    slope = 0.0 if denom <= 0 else float(np.sum((x - xm) * (y - ym)) / denom)
    slope = max(0.0, slope)
    intercept = float(np.mean(y - slope * x))
    pred = intercept + slope * x
    resid = y - pred
    sse = float(np.sum(resid ** 2))
    sst = float(np.sum((y - ym) ** 2))
    r2 = float(1 - sse / sst) if sst > 0 else np.nan
    rmse = float(np.sqrt(np.mean(resid ** 2)))
    mae = float(np.mean(np.abs(resid)))

    slope_se = np.nan
    slope_ci = [np.nan, np.nan]
    if len(x) > 2 and denom > 0 and slope > 0:
        sigma2 = sse / (len(x) - 2)
        slope_se = float(np.sqrt(sigma2 / denom))
        crit = float(student_t.ppf(0.975, df=len(x) - 2))
        slope_ci = [float(slope - crit * slope_se), float(slope + crit * slope_se)]

    return {
        "intercept_t_ha": intercept,
        "slope_t_ha_per_score": slope,
        "effect_t_ha_per_10_score": slope * 10.0,
        "slope_se": slope_se,
        "slope_ci95": slope_ci,
        "r2": r2,
        "rmse_t_ha": rmse,
        "mae_t_ha": mae,
        "pred": pred,
        "resid": resid,
    }


def linear_loocv(x, y):
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    pred = np.empty(len(y), dtype=float)
    for i in range(len(y)):
        keep = np.arange(len(y)) != i
        fit = fit_positive_linear(x[keep], y[keep])
        pred[i] = fit["intercept_t_ha"] + fit["slope_t_ha_per_score"] * x[i]
    err = y - pred
    return pred, {
        "loocv_rmse_t_ha": float(np.sqrt(np.mean(err ** 2))),
        "loocv_mae_t_ha": float(np.mean(np.abs(err))),
    }


def hat_basis(scores, knots=KNOTS):
    s = np.asarray(scores, float)
    B = np.zeros((len(s), len(knots)), dtype=float)
    for r, v in enumerate(s):
        if v <= knots[0]:
            B[r, 0] = 1.0
        elif v >= knots[-1]:
            B[r, -1] = 1.0
        else:
            j = int(np.searchsorted(knots, v) - 1)
            frac = (v - knots[j]) / (knots[j + 1] - knots[j])
            B[r, j] = 1.0 - frac
            B[r, j + 1] = frac
    return B


def sko_basis_matrix(wheat: pd.DataFrame, sko_ids):
    rows = []
    for sko in sko_ids:
        g = wheat[wheat["dominant_sko_id"].eq(sko)]
        B = hat_basis(g["akerscore_soil_p50"].to_numpy(float))
        w = g["weight_m2"].to_numpy(float)
        rows.append(np.average(B, axis=0, weights=w))
    return np.vstack(rows)


def increment_map(n_knots):
    C = np.zeros((n_knots, n_knots), dtype=float)
    C[:, 0] = 1.0
    for j in range(n_knots):
        if j > 0:
            C[j, 1:j + 1] = 1.0
    return C


def second_difference_matrix(n):
    if n < 3:
        return np.empty((0, n))
    D = np.zeros((n - 2, n), dtype=float)
    for i in range(n - 2):
        D[i, i:i + 3] = [1.0, -2.0, 1.0]
    return D


def fit_monotone(P, y, lam):
    n_knots = P.shape[1]
    C = increment_map(n_knots)
    X = P @ C
    D2 = second_difference_matrix(n_knots)
    if lam > 0 and len(D2):
        A = np.vstack([X, math.sqrt(lam) * (D2 @ C)])
        b = np.r_[y, np.zeros(D2.shape[0])]
    else:
        A, b = X, y

    lb = np.r_[-np.inf, np.zeros(n_knots - 1)]
    ub = np.full(n_knots, np.inf)
    res = lsq_linear(A, b, bounds=(lb, ub), lsmr_tol="auto", verbose=0)
    theta = res.x
    knot_y = C @ theta
    pred = P @ knot_y
    return knot_y, pred


def select_lambda_loocv(P, y):
    records = []
    for lam in LAMBDA_GRID:
        preds = np.empty(len(y), dtype=float)
        for i in range(len(y)):
            keep = np.arange(len(y)) != i
            knot_y, _ = fit_monotone(P[keep], y[keep], float(lam))
            preds[i] = float(P[i] @ knot_y)
        err = y - preds
        records.append({
            "lambda": float(lam),
            "loocv_rmse_t_ha": float(np.sqrt(np.mean(err ** 2))),
            "loocv_mae_t_ha": float(np.mean(np.abs(err))),
        })
    tab = pd.DataFrame(records).sort_values(["loocv_rmse_t_ha", "lambda"]).reset_index(drop=True)
    return float(tab.iloc[0]["lambda"]), tab


def curve_on_grid(knot_y):
    grid = np.arange(30.0, 100.0001, 1.0)
    B = hat_basis(grid)
    return pd.DataFrame({"akerscore": grid, "yield_t_ha": B @ knot_y})


def json_clean(value):
    if isinstance(value, dict):
        return {str(k): json_clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_clean(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input-dir", required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument(
        "--norm-csv",
        default=str(Path(__file__).with_name("normskord_hostvete_2026.csv")),
    )
    args = ap.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    norm_csv = Path(args.norm_csv)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 88)
    print("ÅkerScore ↔ Normskörd validation v0a")
    print("=" * 88)
    print("Input :", input_dir)
    print("Output:", output_dir)
    print("Norm  :", norm_csv)

    verify_inputs(input_dir)
    print("Frozen input SHA256: PASS")

    ctx, hist, score = load_inputs(input_dir)
    print(f"Rows: context={len(ctx):,} history={len(hist):,} score={len(score):,}")

    norms = load_norms(norm_csv)
    wheat, wheat_qa = prepare_wheat(ctx, hist, score)
    sko = summarize_sko(wheat, norms)
    yearly, stability = summarize_years(wheat)
    sko = sko.merge(stability, on="sko_id", how="left", validate="one_to_one")

    fit_df = sko[sko["published_norm"]].copy()
    fit_df = fit_df[
        fit_df["mean_akerscore_areaweighted"].notna()
        & fit_df["norm_t_ha"].notna()
    ].copy().sort_values("sko_id")

    if len(fit_df) < 8:
        raise RuntimeError(f"Too few SKO with published norm and wheat data: {len(fit_df)}")

    x = fit_df["mean_akerscore_areaweighted"].to_numpy(float)
    y = fit_df["norm_t_ha"].to_numpy(float)

    linear = fit_positive_linear(x, y)
    linear_loo_pred, linear_loo = linear_loocv(x, y)
    fit_df["linear_pred_t_ha"] = linear["pred"]
    fit_df["linear_residual_t_ha"] = linear["resid"]
    fit_df["linear_loocv_pred_t_ha"] = linear_loo_pred
    fit_df["linear_loocv_error_t_ha"] = y - linear_loo_pred

    sko_ids = fit_df["sko_id"].astype(str).tolist()
    P = sko_basis_matrix(wheat, sko_ids)
    best_lambda, lambda_table = select_lambda_loocv(P, y)
    knot_y, mono_pred = fit_monotone(P, y, best_lambda)
    mono_curve = curve_on_grid(knot_y)

    fit_df["monotone_pred_t_ha"] = mono_pred
    fit_df["monotone_residual_t_ha"] = y - mono_pred
    mono_rmse = float(np.sqrt(np.mean((y - mono_pred) ** 2)))
    mono_mae = float(np.mean(np.abs(y - mono_pred)))
    mono_sst = float(np.sum((y - y.mean()) ** 2))
    mono_r2 = float(1 - np.sum((y - mono_pred) ** 2) / mono_sst)

    knots_table = pd.DataFrame({"akerscore_knot": KNOTS, "yield_t_ha": knot_y})

    robust_df = fit_df[fit_df["n_companies"].fillna(0).ge(100)].copy()
    robust_linear = None
    if len(robust_df) >= 8:
        robust_linear0 = fit_positive_linear(
            robust_df["mean_akerscore_areaweighted"], robust_df["norm_t_ha"]
        )
        robust_linear = {
            k: v for k, v in robust_linear0.items() if k not in {"pred", "resid"}
        }

    supported = np.quantile(
        wheat["akerscore_soil_p50"].to_numpy(float), [0.025, 0.50, 0.975]
    ).tolist()

    result = {
        "version": VERSION,
        "scientific_question": (
            "Can one stable increasing ÅkerScore-to-normal-winter-wheat-yield "
            "function explain official 2026 norm-yield differences across Skåne SKO?"
        ),
        "target_year": 2026,
        "crop": "Höstvete / Vete (höst)",
        "winter_wheat_crop_code": WINTER_WHEAT_CODE,
        "input_lineage": {
            "akerscore_akerminne_validation_tag": "akerscore-akerminne-validation-v1.0",
            "akerscore_akerminne_validation_commit": "9ca92418d6c100793dcaf3ae70705c97e556a9d5",
            "combined_context_tag": "akerpass-akerminne-context-v1.0",
            "akerminne_tag": "akerminne-v1.0",
            "akerscore_source": "akerscore_soil_v0c",
        },
        "wheat_qa": wheat_qa,
        "published_sko_used": int(len(fit_df)),
        "published_sko_ids_used": sko_ids,
        "linear_primary": {
            **{k: v for k, v in linear.items() if k not in {"pred", "resid"}},
            **linear_loo,
        },
        "linear_robustness_n_companies_ge_100": robust_linear,
        "monotone": {
            "knots": KNOTS.tolist(),
            "selected_lambda_by_loocv_rmse": best_lambda,
            "in_sample_r2": mono_r2,
            "in_sample_rmse_t_ha": mono_rmse,
            "in_sample_mae_t_ha": mono_mae,
            "loocv_rmse_t_ha": float(lambda_table.iloc[0]["loocv_rmse_t_ha"]),
            "loocv_mae_t_ha": float(lambda_table.iloc[0]["loocv_mae_t_ha"]),
        },
        "observed_wheat_score_support_p2_5_p50_p97_5": supported,
        "guardrail": (
            "Validation/bridge experiment only. Normskörd is an aggregated SKO target, "
            "not direct field yield. The fitted curve must not be treated as direct "
            "field-level yield validation without independent yield measurements."
        ),
    }

    sko.to_csv(output_dir / "sko_all_summary.csv", index=False, encoding="utf-8-sig")
    fit_df.to_csv(output_dir / "sko_fit_table.csv", index=False, encoding="utf-8-sig")
    yearly.to_csv(output_dir / "sko_yearly_wheat_score.csv", index=False, encoding="utf-8-sig")
    lambda_table.to_csv(output_dir / "monotone_lambda_loocv.csv", index=False, encoding="utf-8-sig")
    knots_table.to_csv(output_dir / "monotone_knots.csv", index=False, encoding="utf-8-sig")
    mono_curve.to_csv(output_dir / "akerscore_to_normyield_curve.csv", index=False, encoding="utf-8-sig")
    (output_dir / "results.json").write_text(
        json.dumps(json_clean(result), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("\nPRIMARY LINEAR FIT")
    print(
        f"  norm_t_ha = {linear['intercept_t_ha']:.4f} "
        f"+ {linear['slope_t_ha_per_score']:.6f} * ÅkerScore"
    )
    print(f"  effect / +10 ÅkerScore: {linear['effect_t_ha_per_10_score']:.3f} t/ha")
    print(f"  R²:                     {linear['r2']:.3f}")
    print(f"  RMSE:                   {linear['rmse_t_ha']:.3f} t/ha")
    print(f"  MAE:                    {linear['mae_t_ha']:.3f} t/ha")
    print(f"  LOOCV RMSE:             {linear_loo['loocv_rmse_t_ha']:.3f} t/ha")
    print(f"  LOOCV MAE:              {linear_loo['loocv_mae_t_ha']:.3f} t/ha")
    if np.isfinite(linear["slope_ci95"][0]):
        print(
            "  slope 95% CI:            "
            f"{linear['slope_ci95'][0]:.6f} .. {linear['slope_ci95'][1]:.6f}"
        )

    print("\nMONOTONE FIT")
    print(f"  selected lambda:        {best_lambda:g}")
    print(f"  in-sample R²:           {mono_r2:.3f}")
    print(f"  in-sample RMSE:         {mono_rmse:.3f} t/ha")
    print(f"  LOOCV RMSE:             {lambda_table.iloc[0]['loocv_rmse_t_ha']:.3f} t/ha")
    print("  knot yields:")
    for s, yy in zip(KNOTS, knot_y):
        print(f"    ÅkerScore {s:5.1f} -> {yy:5.3f} t/ha")

    print("\nSKO TABLE")
    cols = [
        "sko_id", "norm_t_ha", "n_companies", "unique_fields",
        "field_years", "mean_akerscore_areaweighted",
        "linear_pred_t_ha", "linear_residual_t_ha",
    ]
    print(fit_df[cols].to_string(index=False))

    print("\nVALIDATION: PASS")
    print(f"Results written to: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
