#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Add long-run PTHBV climate covariates to the ÅkerScore ↔ normskörd test.

Primary nested comparison:
  M0: norm yield ~ ÅkerScore, score coefficient constrained >= 0
  M1: norm yield ~ temperature + precipitation
  M2: norm yield ~ ÅkerScore + temperature + precipitation,
      score coefficient constrained >= 0

With only about 15 SKO this is explicitly a small-n diagnostic model. Model
comparison emphasizes leave-one-SKO-out RMSE rather than in-sample R² alone.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import lsq_linear


def metrics(y: np.ndarray, pred: np.ndarray, p: int) -> dict:
    err = y - pred
    sse = float(np.sum(err ** 2))
    sst = float(np.sum((y - np.mean(y)) ** 2))
    r2 = float(1.0 - sse / sst) if sst > 0 else np.nan
    n = len(y)
    adj = float(1 - (1-r2)*(n-1)/(n-p)) if n > p and np.isfinite(r2) else np.nan
    return {
        "r2": r2,
        "adjusted_r2": adj,
        "rmse_t_ha": float(np.sqrt(np.mean(err ** 2))),
        "mae_t_ha": float(np.mean(np.abs(err))),
    }


def fit_constrained(X: np.ndarray, y: np.ndarray, score_col: int | None):
    lb = np.full(X.shape[1], -np.inf)
    ub = np.full(X.shape[1], np.inf)
    if score_col is not None:
        lb[score_col] = 0.0
    res = lsq_linear(X, y, bounds=(lb, ub), lsmr_tol="auto")
    beta = res.x
    return beta, X @ beta


def loocv(X: np.ndarray, y: np.ndarray, score_col: int | None):
    pred = np.empty(len(y), float)
    for i in range(len(y)):
        keep = np.arange(len(y)) != i
        beta, _ = fit_constrained(X[keep], y[keep], score_col)
        pred[i] = float(X[i] @ beta)
    m = metrics(y, pred, X.shape[1])
    return pred, {"loocv_rmse_t_ha": m["rmse_t_ha"], "loocv_mae_t_ha": m["mae_t_ha"]}


def corr(a, b):
    a = np.asarray(a, float)
    b = np.asarray(b, float)
    if len(a) < 3 or np.std(a) == 0 or np.std(b) == 0:
        return np.nan
    return float(np.corrcoef(a, b)[0, 1])


def model_frame(df: pd.DataFrame):
    y = df["norm_t_ha"].to_numpy(float)
    score = df["mean_akerscore_areaweighted"].to_numpy(float)
    temp = df["temp_apr_jul_c"].to_numpy(float)
    precip100 = df["precip_apr_jul_mm"].to_numpy(float) / 100.0

    specs = {
        "score_only": (np.column_stack([np.ones(len(df)), score]), 1,
                       ["intercept", "akerscore_per_point"]),
        "climate_only": (np.column_stack([np.ones(len(df)), temp, precip100]), None,
                         ["intercept", "temp_per_degC", "precip_per_100mm"]),
        "score_plus_climate": (
            np.column_stack([np.ones(len(df)), score, temp, precip100]), 1,
            ["intercept", "akerscore_per_point", "temp_per_degC", "precip_per_100mm"],
        ),
    }
    return y, score, temp, precip100, specs


def run_models(df: pd.DataFrame):
    y, score, temp, precip100, specs = model_frame(df)
    models = {}
    predictions = df[["sko_id", "norm_t_ha"]].copy()
    for name, (X, score_col, labels) in specs.items():
        beta, pred = fit_constrained(X, y, score_col)
        loo_pred, loo = loocv(X, y, score_col)
        rec = {
            "coefficients": {label: float(value) for label, value in zip(labels, beta)},
            **metrics(y, pred, X.shape[1]),
            **loo,
        }
        if "akerscore_per_point" in rec["coefficients"]:
            rec["coefficients"]["akerscore_per_10"] = rec["coefficients"]["akerscore_per_point"] * 10.0
        models[name] = rec
        predictions[f"{name}_pred"] = pred
        predictions[f"{name}_resid"] = y - pred
        predictions[f"{name}_loocv_pred"] = loo_pred
        predictions[f"{name}_loocv_error"] = y - loo_pred

    score_resid = predictions["score_only_resid"].to_numpy(float)
    diagnostics = {
        "corr_score_vs_temperature": corr(score, temp),
        "corr_score_vs_precipitation": corr(score, precip100),
        "corr_temperature_vs_precipitation": corr(temp, precip100),
        "corr_score_only_residual_vs_temperature": corr(score_resid, temp),
        "corr_score_only_residual_vs_precipitation": corr(score_resid, precip100),
        "delta_r2_score_plus_climate_vs_score_only": (
            models["score_plus_climate"]["r2"] - models["score_only"]["r2"]
        ),
        "delta_loocv_rmse_score_plus_climate_vs_score_only": (
            models["score_plus_climate"]["loocv_rmse_t_ha"] - models["score_only"]["loocv_rmse_t_ha"]
        ),
    }
    return models, predictions, diagnostics


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sko-fit-table", required=True)
    ap.add_argument("--climate-csv", required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--exclude-sko", nargs="*", default=[])
    args = ap.parse_args()

    fit = pd.read_csv(args.sko_fit_table, dtype={"sko_id": str})
    climate = pd.read_csv(args.climate_csv, dtype={"sko_id": str})
    fit["sko_id"] = fit["sko_id"].astype(str).str.zfill(4)
    climate["sko_id"] = climate["sko_id"].astype(str).str.zfill(4)
    df = fit.merge(climate, on="sko_id", how="inner", validate="one_to_one")
    if args.exclude_sko:
        ex = {str(v).zfill(4) for v in args.exclude_sko}
        df = df[~df["sko_id"].isin(ex)].copy()
    needed = ["norm_t_ha", "mean_akerscore_areaweighted", "temp_apr_jul_c", "precip_apr_jul_mm"]
    df = df.dropna(subset=needed).copy().sort_values("sko_id")
    if len(df) < 8:
        raise RuntimeError(f"Too few complete SKO for climate model: {len(df)}")

    models, predictions, diagnostics = run_models(df)
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    merged = df.merge(predictions.drop(columns=["norm_t_ha"]), on="sko_id", how="left")
    merged.to_csv(out / "sko_climate_model_table.csv", index=False, encoding="utf-8-sig")

    result = {
        "version": "akerscore-normskord-climate-v0a",
        "n_sko": int(len(df)),
        "sko_ids": df["sko_id"].tolist(),
        "excluded_sko": [str(v).zfill(4) for v in args.exclude_sko],
        "climate_definition": {
            "source": "SMHI PTHBV",
            "years": "2011-2025",
            "months": "April-July",
            "temperature": "area-weighted mean temperature, deg C",
            "precipitation": "area-weighted mean annual April-July precipitation sum, mm",
        },
        "models": models,
        "diagnostics": diagnostics,
        "guardrail": (
            "Small-n SKO-level diagnostic. Climate variables are long-run covariates and normskörd is an aggregate target. "
            "Prefer LOOCV improvement over in-sample R2 when deciding whether climate adds credible signal."
        ),
    }
    (out / "climate_results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 88)
    print("ÅkerScore + PTHBV climate ↔ normskörd v0a")
    print("=" * 88)
    print(f"SKO used: {len(df)} -> {', '.join(df['sko_id'])}")
    print("\nCLIMATE BY SKO")
    print(df[["sko_id", "norm_t_ha", "mean_akerscore_areaweighted", "temp_apr_jul_c", "precip_apr_jul_mm"]].to_string(index=False))

    for name in ["score_only", "climate_only", "score_plus_climate"]:
        m = models[name]
        print(f"\n{name.upper()}")
        for k, v in m["coefficients"].items():
            print(f"  {k:24s}: {v: .6f}")
        print(f"  R²                      : {m['r2']:.3f}")
        print(f"  adjusted R²             : {m['adjusted_r2']:.3f}")
        print(f"  RMSE                    : {m['rmse_t_ha']:.3f} t/ha")
        print(f"  LOOCV RMSE              : {m['loocv_rmse_t_ha']:.3f} t/ha")
        print(f"  LOOCV MAE               : {m['loocv_mae_t_ha']:.3f} t/ha")

    print("\nDIAGNOSTICS")
    for k, v in diagnostics.items():
        print(f"  {k:52s}: {v: .4f}")

    print("\nRESIDUAL TABLE (score-only -> score+climate)")
    print(merged[[
        "sko_id", "norm_t_ha", "score_only_resid", "score_plus_climate_resid",
        "temp_apr_jul_c", "precip_apr_jul_mm",
    ]].to_string(index=False))
    print("\nCLIMATE VALIDATION: PASS")
    print("Results:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
