#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerSync Satellite V1a — Step 28: decompose season, vegetation state and weather.

Purpose
-------
The all-year TWI×weather experiment produced up to 36 year×season-window
observations. This step asks the important confounding question before we call
anything a weather/water-robustness signal:

    Does weather add predictive information beyond season and the vegetation
    state actually observed by Sentinel at the same date?

No satellite download is performed here. The script only reuses local CSV
outputs from step 27.

Independent unit
----------------
The regression unit is one accepted YEAR × WINDOW observation, not individual
10 m pixels and not individual fields. Field-level NDVI is used only to build a
population vegetation-state covariate (median field NDVI) for that date. This
avoids pseudo-replication from the ~15k field-date rows.

Nested models
-------------
M0: Q5-Q1 ~ window
M1: Q5-Q1 ~ window + P30 + T30
M2: Q5-Q1 ~ window + vegetation_state
M3: Q5-Q1 ~ window + vegetation_state + P30 + T30

All continuous predictors are standardized. In leave-one-year-out (LOYO)
validation, standardization is learned on the training years only.

Sensitivity
-----------
The same nested comparison is repeated after requiring SCL QA field shares of
50, 60, 75 and 80 percent (configurable). We also fit both all windows and a
W2-W4-only subset because April was nearly flat in the preceding experiments.

Guardrails
----------
This remains observational/descriptive. Temperature can proxy phenology as well
as evaporative demand; precipitation is a regional station proxy; 2025 field
footprints are fixed geographic sampling areas for all historical years.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from common import load_config

ROOT = Path(__file__).resolve().parents[1]

MODELS = {
    "M0_window": [],
    "M1_window_weather": ["precip_30d_mm", "tmean_30d_c"],
    "M2_window_veg": ["median_field_ndvi"],
    "M3_window_veg_weather": ["median_field_ndvi", "precip_30d_mm", "tmean_30d_c"],
}


def parse_thresholds(s: str) -> list[float]:
    vals = []
    for part in str(s).split(","):
        part = part.strip()
        if not part:
            continue
        x = float(part)
        if x < 0 or x > 100:
            raise ValueError("QA thresholds måste ligga mellan 0 och 100")
        vals.append(x)
    if not vals:
        raise ValueError("Minst en QA threshold krävs")
    return sorted(set(vals))


def load_inputs(outdir: Path, year_start: int, year_end: int):
    stem = f"lomma_multiyear_twi_weather_{year_start}_{year_end}"
    yw_path = outdir / f"{stem}_year_window_curve.csv"
    fd_path = outdir / f"{stem}_field_date_quintiles.csv"
    plan_path = outdir / f"{stem}_selected_plan.csv"
    for p in (yw_path, fd_path, plan_path):
        if not p.exists():
            raise FileNotFoundError(
                f"Saknar {p}. Kör SATELLITE_LOMMA_MULTIYEAR_TWI_WEATHER.bat först."
            )

    yw = pd.read_csv(yw_path)
    fd = pd.read_csv(fd_path)
    plan = pd.read_csv(plan_path)

    required_yw = {
        "year", "window", "q5_minus_q1", "precip_30d_mm", "tmean_30d_c",
        "qa_good_field_share_pct",
    }
    missing = sorted(required_yw - set(yw.columns))
    if missing:
        raise RuntimeError(f"year_window_curve saknar kolumner: {missing}")
    if "ndvi_field_median" not in fd.columns:
        raise RuntimeError("field_date_quintiles saknar ndvi_field_median")

    for d in (yw, fd, plan):
        d["year"] = pd.to_numeric(d["year"], errors="coerce").astype("Int64")
        d["window"] = d["window"].astype(str)
    if "date" in yw.columns:
        yw["date"] = pd.to_datetime(yw["date"], errors="coerce")
    if "date" in fd.columns:
        fd["date"] = pd.to_datetime(fd["date"], errors="coerce")
    if "selected_date" in plan.columns:
        plan["selected_date"] = pd.to_datetime(plan["selected_date"], errors="coerce")

    veg = (
        fd.groupby(["year", "window"], as_index=False)
        .agg(
            median_field_ndvi=("ndvi_field_median", "median"),
            mean_field_ndvi=("ndvi_field_median", "mean"),
            p10_field_ndvi=("ndvi_field_median", lambda x: pd.to_numeric(x, errors="coerce").quantile(0.10)),
            p90_field_ndvi=("ndvi_field_median", lambda x: pd.to_numeric(x, errors="coerce").quantile(0.90)),
            vegetation_fields=("ndvi_field_median", lambda x: int(pd.to_numeric(x, errors="coerce").notna().sum())),
        )
    )
    data = yw.merge(veg, on=["year", "window"], how="left", validate="one_to_one")
    data["year"] = data["year"].astype(int)

    # Date is useful for audit output; selected plan is authoritative if the
    # year-window curve happened to serialize date differently.
    if "selected_date" in plan.columns:
        p = plan[["year", "window", "selected_date"]].drop_duplicates(["year", "window"])
        p["year"] = p["year"].astype(int)
        data = data.merge(p, on=["year", "window"], how="left")
    return data, yw_path, fd_path


def build_design(frame: pd.DataFrame, continuous: list[str], levels: list[str],
                 means: dict[str, float], sds: dict[str, float]):
    baseline = levels[0]
    dummies = levels[1:]
    cols = [np.ones(len(frame), dtype=float)]
    names = ["intercept"]

    w = frame["window"].astype(str).to_numpy()
    for lev in dummies:
        cols.append((w == lev).astype(float))
        names.append(f"window_{lev}")

    for c in continuous:
        sd = sds[c]
        if not np.isfinite(sd) or sd <= 1e-12:
            raise RuntimeError(f"Prediktor {c} har noll/ogiltig variation")
        cols.append((frame[c].to_numpy(float) - means[c]) / sd)
        names.append(c + "_z")
    return np.column_stack(cols), names, baseline


def fit_full(frame: pd.DataFrame, continuous: list[str], levels: list[str]):
    means = {c: float(frame[c].mean()) for c in continuous}
    sds = {c: float(frame[c].std(ddof=0)) for c in continuous}
    X, names, baseline = build_design(frame, continuous, levels, means, sds)
    y = frame.q5_minus_q1.to_numpy(float)
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    pred = X @ beta
    resid = y - pred
    sse = float(np.sum(resid ** 2))
    sst = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - sse / sst if sst > 0 else np.nan
    n, k = len(y), X.shape[1]
    adj = 1.0 - (1.0 - r2) * (n - 1) / (n - k) if np.isfinite(r2) and n > k else np.nan
    coef = pd.DataFrame({
        "term": names,
        "coefficient": beta,
        "baseline_window": baseline,
        "n": n,
        "k": k,
        "r2": r2,
        "adj_r2": adj,
    })
    return coef, pred, resid, r2, adj, k


def loyo_predict(frame: pd.DataFrame, continuous: list[str], levels: list[str]):
    rows = []
    for yr in sorted(frame.year.unique()):
        tr = frame[frame.year != yr].copy()
        te = frame[frame.year == yr].copy()
        if te.empty or len(tr) < 6:
            continue
        means = {c: float(tr[c].mean()) for c in continuous}
        sds = {c: float(tr[c].std(ddof=0)) for c in continuous}
        if any((not np.isfinite(sds[c]) or sds[c] <= 1e-12) for c in continuous):
            continue
        Xtr, _, _ = build_design(tr, continuous, levels, means, sds)
        Xte, _, _ = build_design(te, continuous, levels, means, sds)
        b, *_ = np.linalg.lstsq(Xtr, tr.q5_minus_q1.to_numpy(float), rcond=None)
        pred = Xte @ b
        for i, (_, rr) in enumerate(te.iterrows()):
            rows.append({
                "year": int(rr.year),
                "window": str(rr.window),
                "observed": float(rr.q5_minus_q1),
                "predicted": float(pred[i]),
                "error": float(rr.q5_minus_q1 - pred[i]),
            })
    out = pd.DataFrame(rows)
    if out.empty:
        return out, np.nan, np.nan
    rmse = float(np.sqrt(np.mean(out.error.to_numpy(float) ** 2)))
    mae = float(np.mean(np.abs(out.error.to_numpy(float))))
    return out, rmse, mae


def residual_weather_association(frame: pd.DataFrame, levels: list[str]):
    # Residuals after controlling for window + observed vegetation state (M2).
    coef, pred, resid, *_ = fit_full(frame, ["median_field_ndvi"], levels)
    x = frame.copy()
    x["m2_residual"] = resid
    rp = spearmanr(x.m2_residual, x.precip_30d_mm, nan_policy="omit")
    rt = spearmanr(x.m2_residual, x.tmean_30d_c, nan_policy="omit")
    return {
        "n": len(x),
        "rho_resid_p30": float(rp.statistic),
        "p_resid_p30": float(rp.pvalue),
        "rho_resid_t30": float(rt.statistic),
        "p_resid_t30": float(rt.pvalue),
    }


def run_scope(data: pd.DataFrame, scope: str, qa: float):
    x = data[data.qa_good_field_share_pct >= qa].copy()
    if scope == "W2_W4_only":
        x = x[x.window != "W1_early_april"].copy()

    # Fair nested-model comparison: all models use exactly the same rows.
    needed = [
        "q5_minus_q1", "window", "year", "median_field_ndvi",
        "precip_30d_mm", "tmean_30d_c",
    ]
    x = x.dropna(subset=needed).copy()
    levels = sorted(x.window.astype(str).unique())
    if len(x) < 10 or len(levels) < 2:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), None

    metrics = []
    coefs = []
    preds = []
    baseline_metrics = None
    m2_metrics = None

    for model, continuous in MODELS.items():
        coef, ins_pred, resid, r2, adj, k = fit_full(x, continuous, levels)
        cv, rmse, mae = loyo_predict(x, continuous, levels)
        row = {
            "scope": scope,
            "qa_threshold_pct": qa,
            "model": model,
            "n": len(x),
            "years": x.year.nunique(),
            "windows": len(levels),
            "k": k,
            "r2_in_sample": r2,
            "adj_r2_in_sample": adj,
            "loyo_rmse": rmse,
            "loyo_mae": mae,
        }
        if model == "M0_window":
            baseline_metrics = row.copy()
        if model == "M2_window_veg":
            m2_metrics = row.copy()
        metrics.append(row)

        coef.insert(0, "model", model)
        coef.insert(0, "qa_threshold_pct", qa)
        coef.insert(0, "scope", scope)
        coefs.append(coef)

        if not cv.empty:
            cv.insert(0, "model", model)
            cv.insert(0, "qa_threshold_pct", qa)
            cv.insert(0, "scope", scope)
            preds.append(cv)

    met = pd.DataFrame(metrics)
    if baseline_metrics is not None:
        met["delta_r2_vs_M0"] = met.r2_in_sample - baseline_metrics["r2_in_sample"]
        met["delta_loyo_rmse_vs_M0"] = met.loyo_rmse - baseline_metrics["loyo_rmse"]
        met["loyo_rmse_improvement_vs_M0_pct"] = 100.0 * (
            baseline_metrics["loyo_rmse"] - met.loyo_rmse
        ) / baseline_metrics["loyo_rmse"]
    if m2_metrics is not None:
        met["delta_loyo_rmse_vs_M2"] = met.loyo_rmse - m2_metrics["loyo_rmse"]

    assoc = residual_weather_association(x, levels)
    assoc.update({"scope": scope, "qa_threshold_pct": qa})
    return met, pd.concat(coefs, ignore_index=True), (pd.concat(preds, ignore_index=True) if preds else pd.DataFrame()), assoc


def fmt(x, nd=4):
    return "nan" if pd.isna(x) else f"{float(x):.{nd}f}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/local_paths.json")
    ap.add_argument("--year-start", type=int, default=2018)
    ap.add_argument("--year-end", type=int, default=2026)
    ap.add_argument("--qa-thresholds", default="50,60,75,80")
    ap.add_argument("--primary-qa", type=float, default=50.0)
    args = ap.parse_args()

    thresholds = parse_thresholds(args.qa_thresholds)
    if args.primary_qa not in thresholds:
        thresholds = sorted(set(thresholds + [float(args.primary_qa)]))

    cfg = load_config(ROOT / args.config)
    outdir = ROOT / cfg.get("build_dir", "data/derived") / "satellite_poc"
    outdir.mkdir(parents=True, exist_ok=True)
    data, yw_path, fd_path = load_inputs(outdir, args.year_start, args.year_end)

    print("=" * 126)
    print("ÅkerSync · Satellite V1a · STEP 28 MODEL DECOMPOSITION")
    print("=" * 126)
    print(f"Input year×window: {len(data)}")
    print(f"År: {args.year_start}–{args.year_end}")
    print("Ingen satellithämtning: endast lokala CSV-filer används.")
    print("Nested: M0 window | M1 +weather | M2 +vegetation state | M3 +vegetation state +weather")
    print("LOYO = leave one whole year out. QA thresholds:", ", ".join(f"{q:g}%" for q in thresholds))

    all_metrics, all_coefs, all_preds, all_assoc = [], [], [], []
    for qa in thresholds:
        for scope in ("all_windows", "W2_W4_only"):
            met, coef, pred, assoc = run_scope(data, scope, qa)
            if met.empty:
                print(f"VARNING: {scope} QA>={qa:g}% har för få kompletta observationer; skippar.")
                continue
            all_metrics.append(met)
            all_coefs.append(coef)
            if not pred.empty:
                all_preds.append(pred)
            if assoc is not None:
                all_assoc.append(assoc)

    if not all_metrics:
        raise RuntimeError("Ingen modell kunde skattas")

    metrics = pd.concat(all_metrics, ignore_index=True)
    coefs = pd.concat(all_coefs, ignore_index=True)
    preds = pd.concat(all_preds, ignore_index=True) if all_preds else pd.DataFrame()
    assoc = pd.DataFrame(all_assoc)

    stem = f"lomma_twi_model_decomposition_{args.year_start}_{args.year_end}"
    input_csv = outdir / f"{stem}_analysis_table.csv"
    metrics_csv = outdir / f"{stem}_metrics.csv"
    coefs_csv = outdir / f"{stem}_coefficients.csv"
    preds_csv = outdir / f"{stem}_loyo_predictions.csv"
    assoc_csv = outdir / f"{stem}_residual_weather.csv"
    summary_txt = outdir / f"{stem}_summary.txt"

    data.to_csv(input_csv, index=False, encoding="utf-8-sig", date_format="%Y-%m-%d")
    metrics.to_csv(metrics_csv, index=False, encoding="utf-8-sig")
    coefs.to_csv(coefs_csv, index=False, encoding="utf-8-sig")
    preds.to_csv(preds_csv, index=False, encoding="utf-8-sig")
    assoc.to_csv(assoc_csv, index=False, encoding="utf-8-sig")

    primary = metrics[np.isclose(metrics.qa_threshold_pct, args.primary_qa)].copy()
    lines = [
        "ÅkerSync Satellite V1a — Step 28 model decomposition",
        f"Years: {args.year_start}-{args.year_end}",
        f"Year-window rows available: {len(data)}",
        "Regression unit: year × season window.",
        "Vegetation state: median of field-level Sentinel NDVI for that accepted date.",
        "M0 window; M1 window+P30+T30; M2 window+vegetation; M3 window+vegetation+P30+T30.",
        "LOYO standardizes continuous variables on training years only.",
        "",
        f"PRIMARY QA >= {args.primary_qa:g}%:",
    ]
    for scope in ("all_windows", "W2_W4_only"):
        z = primary[primary.scope.eq(scope)]
        if z.empty:
            continue
        lines.append(f"  {scope}:")
        for r in z.itertuples(index=False):
            lines.append(
                f"    {r.model:24s} n={int(r.n):2d} R2={r.r2_in_sample:.3f} adjR2={r.adj_r2_in_sample:.3f} "
                f"LOYO_RMSE={r.loyo_rmse:.4f} MAE={r.loyo_mae:.4f} "
                f"RMSE_impr_vs_M0={r.loyo_rmse_improvement_vs_M0_pct:+.1f}%"
            )
        a = assoc[(assoc.scope == scope) & np.isclose(assoc.qa_threshold_pct, args.primary_qa)]
        if not a.empty:
            r = a.iloc[0]
            lines.append(
                f"    M2 residual Spearman: P30 rho={r.rho_resid_p30:+.3f}; T30 rho={r.rho_resid_t30:+.3f}; n={int(r.n)}"
            )

    lines += ["", "QA SENSITIVITY — M3 incremental weather beyond M2:"]
    for scope in ("all_windows", "W2_W4_only"):
        for qa in thresholds:
            m2 = metrics[(metrics.scope == scope) & np.isclose(metrics.qa_threshold_pct, qa) & metrics.model.eq("M2_window_veg")]
            m3 = metrics[(metrics.scope == scope) & np.isclose(metrics.qa_threshold_pct, qa) & metrics.model.eq("M3_window_veg_weather")]
            if m2.empty or m3.empty:
                continue
            r2, r3 = m2.iloc[0], m3.iloc[0]
            lines.append(
                f"  {scope:12s} QA>={qa:4.0f}% n={int(r3.n):2d} | M2 RMSE {r2.loyo_rmse:.4f} -> M3 {r3.loyo_rmse:.4f} "
                f"(delta {r3.loyo_rmse-r2.loyo_rmse:+.4f})"
            )

    lines += [
        "",
        "GUARDRAILS:",
        "  High in-sample R2 alone is not evidence of a weather mechanism; LOYO and nested increments are primary.",
        "  T30 can encode phenology as well as heat/water demand; M2/M3 explicitly test weather after observed NDVI state.",
        "  Weather is regional station data, not measured field soil moisture or evapotranspiration.",
        "  Missing/cloudy year-windows are not imputed.",
        "  2025 field footprints are fixed geographic samples for historical years, not historical boundary truth.",
    ]
    summary_txt.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n" + "=" * 126)
    print("MODEL DECOMPOSITION KLAR")
    print("=" * 126)
    for scope in ("all_windows", "W2_W4_only"):
        z = primary[primary.scope.eq(scope)]
        if z.empty:
            continue
        print(f"\n{scope} · QA >= {args.primary_qa:g}%")
        for r in z.itertuples(index=False):
            print(
                f"  {r.model:24s} | n={int(r.n):2d} | R2 {r.r2_in_sample:.3f} | adjR2 {r.adj_r2_in_sample:.3f} | "
                f"LOYO RMSE {r.loyo_rmse:.4f} | MAE {r.loyo_mae:.4f} | improvement vs M0 {r.loyo_rmse_improvement_vs_M0_pct:+.1f}%"
            )
        a = assoc[(assoc.scope == scope) & np.isclose(assoc.qa_threshold_pct, args.primary_qa)]
        if not a.empty:
            r = a.iloc[0]
            print(f"  M2 residual weather: Spearman P30 {r.rho_resid_p30:+.3f} | T30 {r.rho_resid_t30:+.3f} | n={int(r.n)}")

    print("\nQA sensitivity · M2 vegetation -> M3 vegetation+weather (LOYO RMSE):")
    for scope in ("all_windows", "W2_W4_only"):
        print(" ", scope)
        for qa in thresholds:
            m2 = metrics[(metrics.scope == scope) & np.isclose(metrics.qa_threshold_pct, qa) & metrics.model.eq("M2_window_veg")]
            m3 = metrics[(metrics.scope == scope) & np.isclose(metrics.qa_threshold_pct, qa) & metrics.model.eq("M3_window_veg_weather")]
            if m2.empty or m3.empty:
                continue
            r2, r3 = m2.iloc[0], m3.iloc[0]
            print(f"    QA>={qa:4.0f}% | n={int(r3.n):2d} | {r2.loyo_rmse:.4f} -> {r3.loyo_rmse:.4f} | delta {r3.loyo_rmse-r2.loyo_rmse:+.4f}")

    print("\nOutput:")
    for p in (input_csv, metrics_csv, coefs_csv, preds_csv, assoc_csv, summary_txt):
        print(" ", p)
    print("\nSTEP 28: OK")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
