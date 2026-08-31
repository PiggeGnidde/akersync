#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generic ÅkerScore ↔ normskörd validation for a named crop.

Designed for geographically concentrated crops (e.g. potato) where official SKO
coverage can be sparse. Score-only fit is allowed from n>=4 SKO and is explicitly
reported as exploratory when n<8. Monotone fit is only attempted for n>=8.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from run_validation import (
    KNOTS, curve_on_grid, fit_monotone, fit_positive_linear, linear_loocv,
    load_inputs, load_norms, select_lambda_loocv, sko_basis_matrix,
    summarize_sko, summarize_years, verify_inputs,
)

MIN_DOMINANT_SKO_SHARE = 0.95


def prepare_crop(ctx, hist, score, crop_code: int, crop_label: str, label_pattern: str):
    base = ctx[["current_field_id", "dominant_sko_id", "dominant_sko_share"]].copy()
    base["dominant_sko_id"] = base["dominant_sko_id"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(4)
    base["dominant_sko_share"] = pd.to_numeric(base["dominant_sko_share"], errors="coerce")
    sc = score[["current_field_id", "akerscore_soil_p50"]].copy()
    sc["akerscore_soil_p50"] = pd.to_numeric(sc["akerscore_soil_p50"], errors="coerce")
    base = base.merge(sc, on="current_field_id", how="left", validate="one_to_one")

    h = hist.copy()
    h["dominant_crop_code_num"] = pd.to_numeric(h["dominant_crop_code_raw"], errors="coerce")
    h["current_area_m2"] = pd.to_numeric(h["current_area_m2"], errors="coerce")
    h["history_year"] = pd.to_numeric(h["history_year"], errors="coerce")
    crop = h[h["status"].eq("SINGLE_CROP") & h["dominant_crop_code_num"].eq(crop_code)].copy()
    labels = crop[["history_year", "dominant_crop_name"]].drop_duplicates().sort_values(["history_year", "dominant_crop_name"])
    bad = labels[~labels["dominant_crop_name"].fillna("").str.lower().str.contains(label_pattern.lower(), regex=False)]
    if len(bad):
        raise RuntimeError(f"Crop code {crop_code} has unexpected labels for {crop_label}:\n{bad.to_string(index=False)}")

    crop = crop.merge(base, on="current_field_id", how="left", validate="many_to_one")
    before = len(crop)
    crop = crop[
        crop["akerscore_soil_p50"].notna()
        & crop["current_area_m2"].gt(0)
        & crop["dominant_sko_share"].ge(MIN_DOMINANT_SKO_SHARE)
        & crop["dominant_sko_id"].notna()
    ].copy()
    crop["weight_m2"] = crop["current_area_m2"].astype(float)
    qa = {
        "crop_code": crop_code, "crop_label": crop_label,
        "field_years_single_crop_before_score_sko_filter": int(before),
        "field_years_primary": int(len(crop)),
        "unique_fields_primary": int(crop["current_field_id"].nunique()),
        "years": sorted(int(v) for v in crop["history_year"].dropna().unique()),
        "observed_crop_labels": labels.to_dict(orient="records"),
    }
    return crop, qa


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input-dir", required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--norm-csv", required=True)
    ap.add_argument("--crop-code", type=int, required=True)
    ap.add_argument("--crop-label", required=True)
    ap.add_argument("--label-pattern", default="potatis")
    ap.add_argument("--min-sko", type=int, default=4)
    args = ap.parse_args()

    input_dir = Path(args.input_dir); out = Path(args.output_dir); out.mkdir(parents=True, exist_ok=True)
    verify_inputs(input_dir)
    ctx, hist, score = load_inputs(input_dir); norms = load_norms(Path(args.norm_csv))
    crop, crop_qa = prepare_crop(ctx, hist, score, args.crop_code, args.crop_label, args.label_pattern)
    sko = summarize_sko(crop, norms)
    yearly, stability = summarize_years(crop)
    sko = sko.merge(stability, on="sko_id", how="left", validate="one_to_one")
    fit_df = sko[sko["norm_t_ha"].notna() & sko["mean_akerscore_areaweighted"].notna()].copy().sort_values("sko_id")
    if len(fit_df) < args.min_sko:
        raise RuntimeError(f"Too few SKO with {args.crop_label} norm yield and crop data: {len(fit_df)} < {args.min_sko}")

    x = fit_df["mean_akerscore_areaweighted"].to_numpy(float); y = fit_df["norm_t_ha"].to_numpy(float)
    linear = fit_positive_linear(x, y); loo_pred, loo = linear_loocv(x, y)
    fit_df["linear_pred_t_ha"] = linear["pred"]; fit_df["linear_residual_t_ha"] = linear["resid"]
    fit_df["linear_loocv_pred_t_ha"] = loo_pred; fit_df["linear_loocv_error_t_ha"] = y - loo_pred

    mono = None
    if len(fit_df) >= 8:
        P = sko_basis_matrix(crop, fit_df["sko_id"].tolist())
        best_lambda, lambda_table = select_lambda_loocv(P, y)
        knot_y, mono_pred = fit_monotone(P, y, best_lambda)
        err = y - mono_pred; sst = float(np.sum((y-y.mean())**2))
        mono = {
            "selected_lambda_by_loocv_rmse": float(best_lambda),
            "in_sample_r2": float(1-np.sum(err**2)/sst),
            "in_sample_rmse_t_ha": float(np.sqrt(np.mean(err**2))),
            "in_sample_mae_t_ha": float(np.mean(np.abs(err))),
            "loocv_rmse_t_ha": float(lambda_table.iloc[0]["loocv_rmse_t_ha"]),
            "loocv_mae_t_ha": float(lambda_table.iloc[0]["loocv_mae_t_ha"]),
        }
        fit_df["monotone_pred_t_ha"] = mono_pred; fit_df["monotone_residual_t_ha"] = err
        pd.DataFrame({"akerscore_knot": KNOTS, "yield_t_ha": knot_y}).to_csv(out / "monotone_knots.csv", index=False, encoding="utf-8-sig")
        curve_on_grid(knot_y).to_csv(out / "akerscore_to_normyield_curve.csv", index=False, encoding="utf-8-sig")
        lambda_table.to_csv(out / "monotone_lambda_loocv.csv", index=False, encoding="utf-8-sig")

    sko.to_csv(out / "sko_all_summary.csv", index=False, encoding="utf-8-sig")
    fit_df.to_csv(out / "sko_fit_table.csv", index=False, encoding="utf-8-sig")
    yearly.to_csv(out / "sko_yearly_crop_score.csv", index=False, encoding="utf-8-sig")

    result = {
        "version": "akerscore-normskord-specialcrop-validation-v0a",
        "crop_code": args.crop_code, "crop": args.crop_label, "target_year": 2026,
        "n_sko": int(len(fit_df)), "sko_ids": fit_df["sko_id"].tolist(), "crop_qa": crop_qa,
        "linear": {
            "intercept_t_ha": linear["intercept_t_ha"], "slope_t_ha_per_score": linear["slope_t_ha_per_score"],
            "effect_t_ha_per_10_score": linear["effect_t_ha_per_10_score"], "r2": linear["r2"],
            "rmse_t_ha": linear["rmse_t_ha"], "mae_t_ha": linear["mae_t_ha"], **loo,
        },
        "monotone": mono,
        "evidence_grade": "exploratory_small_n" if len(fit_df) < 8 else "replication_standard",
        "guardrail": "Special crop may be geographically concentrated. Interpret SKO-level score-only relation cautiously; no Hasund calibration used.",
    }
    (out / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print("="*88); print(f"ÅkerScore ↔ {args.crop_label} normskörd 2026 — replication v0a"); print("="*88)
    print(f"Crop field-years: {len(crop):,}; unique fields: {crop['current_field_id'].nunique():,}")
    print(f"SKO used: {len(fit_df)} -> {', '.join(fit_df['sko_id'])}")
    if len(fit_df) < 8: print("NOTE: n<8 SKO -> exploratory score-only result; monotone/climate validation needs stronger guardrails.")
    print("\nPRIMARY LINEAR FIT")
    print(f"  norm_t_ha = {linear['intercept_t_ha']:.4f} + {linear['slope_t_ha_per_score']:.6f} * ÅkerScore")
    print(f"  effect / +10 ÅkerScore: {linear['effect_t_ha_per_10_score']:.3f} t/ha")
    print(f"  R²:                     {linear['r2']:.3f}")
    print(f"  RMSE:                   {linear['rmse_t_ha']:.3f} t/ha")
    print(f"  LOOCV RMSE:             {loo['loocv_rmse_t_ha']:.3f} t/ha")
    if mono is not None:
        print("\nMONOTONE FIT")
        print(f"  in-sample R²:           {mono['in_sample_r2']:.3f}")
        print(f"  LOOCV RMSE:             {mono['loocv_rmse_t_ha']:.3f} t/ha")
    print("\nSKO TABLE")
    print(fit_df[["sko_id","norm_t_ha","n_companies","unique_fields","field_years","mean_akerscore_areaweighted","linear_residual_t_ha"]].to_string(index=False))
    print(f"\n{args.crop_label.upper()} VALIDATION: PASS")
    return 0


if __name__ == "__main__": raise SystemExit(main())
