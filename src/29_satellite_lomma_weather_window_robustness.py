#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerSync Satellite V1a — Step 29: weather-window robustness + yearwise LOYO.

Purpose
-------
Stress-test the weather signal found in steps 27–28 without downloading any new
satellite pixels.

Questions
---------
1) Does the result survive changing the weather lookback from 30 days to
   14 or 45 days?
2) Is precipitation alone, temperature alone, or their combination carrying the
   predictive signal?
3) Is the aggregate LOYO gain broad across years, or driven by one/two unusual
   years?
4) Does the same pattern remain after adding observed Sentinel vegetation state
   (median field NDVI) as a coarse phenology control?

Regression unit
---------------
One accepted YEAR × WINDOW observation. Field-level rows are used only to form
median vegetation state per year×window. We do not treat pixels or fields as
independent weather experiments.

Models
------
B0: window
BV: window + vegetation_state
For h in {14,30,45} days:
  P_h:   window + precipitation_h
  T_h:   window + temperature_h
  PT_h:  window + precipitation_h + temperature_h
  VPT_h: window + vegetation_state + precipitation_h + temperature_h

Validation
----------
Leave-one-year-out (LOYO). Predictor means/SDs are learned on training years
only. A held-out observation is skipped if its seasonal window has no training
example in that fold. Per-year RMSE/MAE are reported, as well as total LOYO.

Sensitivity
-----------
Both all windows and W2–W4 only are evaluated at SCL QA thresholds 50, 60, 75
and 80 percent by default.

Guardrails
----------
This is observational/descriptive, not causal inference. Temperature may proxy
phenology and evaporative demand. Regional station precipitation does not fully
capture local convective rain. 2025 field footprints remain fixed geographic
sampling areas for historical years.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from common import load_config

ROOT = Path(__file__).resolve().parents[1]
HORIZONS = (14, 30, 45)


def parse_thresholds(text: str) -> list[float]:
    vals: list[float] = []
    for part in str(text).split(","):
        part = part.strip()
        if not part:
            continue
        x = float(part)
        if not 0 <= x <= 100:
            raise ValueError("QA thresholds måste ligga mellan 0 och 100")
        vals.append(x)
    if not vals:
        raise ValueError("Minst en QA threshold krävs")
    return sorted(set(vals))


def load_data(outdir: Path, year_start: int, year_end: int) -> pd.DataFrame:
    stem = f"lomma_multiyear_twi_weather_{year_start}_{year_end}"
    yw_path = outdir / f"{stem}_year_window_curve.csv"
    fd_path = outdir / f"{stem}_field_date_quintiles.csv"
    for p in (yw_path, fd_path):
        if not p.exists():
            raise FileNotFoundError(
                f"Saknar {p}. Kör SATELLITE_LOMMA_MULTIYEAR_TWI_WEATHER.bat först."
            )

    yw = pd.read_csv(yw_path)
    fd = pd.read_csv(fd_path)

    required = {"year", "window", "q5_minus_q1", "qa_good_field_share_pct"}
    for h in HORIZONS:
        required.update({f"precip_{h}d_mm", f"tmean_{h}d_c"})
    missing = sorted(required - set(yw.columns))
    if missing:
        raise RuntimeError(f"year_window_curve saknar kolumner: {missing}")
    if "ndvi_field_median" not in fd.columns:
        raise RuntimeError("field_date_quintiles saknar ndvi_field_median")

    yw["year"] = pd.to_numeric(yw.year, errors="coerce")
    fd["year"] = pd.to_numeric(fd.year, errors="coerce")
    yw = yw[yw.year.notna()].copy()
    fd = fd[fd.year.notna()].copy()
    yw["year"] = yw.year.astype(int)
    fd["year"] = fd.year.astype(int)
    yw["window"] = yw.window.astype(str)
    fd["window"] = fd.window.astype(str)

    veg = (
        fd.groupby(["year", "window"], as_index=False)
        .agg(
            median_field_ndvi=("ndvi_field_median", "median"),
            vegetation_fields=(
                "ndvi_field_median",
                lambda x: int(pd.to_numeric(x, errors="coerce").notna().sum()),
            ),
        )
    )
    data = yw.merge(veg, on=["year", "window"], how="left", validate="one_to_one")
    return data.sort_values(["year", "window"]).reset_index(drop=True)


def model_specs() -> list[dict]:
    specs = [
        {"model": "B0_window", "horizon": 0, "predictors": [], "baseline": "B0_window"},
        {
            "model": "BV_window_veg",
            "horizon": 0,
            "predictors": ["median_field_ndvi"],
            "baseline": "BV_window_veg",
        },
    ]
    for h in HORIZONS:
        p = f"precip_{h}d_mm"
        t = f"tmean_{h}d_c"
        specs += [
            {"model": f"P{h}", "horizon": h, "predictors": [p], "baseline": "B0_window"},
            {"model": f"T{h}", "horizon": h, "predictors": [t], "baseline": "B0_window"},
            {"model": f"PT{h}", "horizon": h, "predictors": [p, t], "baseline": "B0_window"},
            {
                "model": f"VPT{h}",
                "horizon": h,
                "predictors": ["median_field_ndvi", p, t],
                "baseline": "BV_window_veg",
            },
        ]
    return specs


def make_design(
    frame: pd.DataFrame,
    predictors: list[str],
    levels: list[str],
    means: dict[str, float],
    sds: dict[str, float],
):
    if not levels:
        raise RuntimeError("Inga window-levels")
    baseline = levels[0]
    dummies = levels[1:]
    cols = [np.ones(len(frame), dtype=float)]
    names = ["intercept"]
    w = frame.window.astype(str).to_numpy()
    for lev in dummies:
        cols.append((w == lev).astype(float))
        names.append(f"window_{lev}")
    for c in predictors:
        sd = float(sds[c])
        if not np.isfinite(sd) or sd <= 1e-12:
            raise RuntimeError(f"Prediktor {c} har noll/ogiltig variation")
        cols.append((frame[c].to_numpy(float) - float(means[c])) / sd)
        names.append(c + "_z")
    return np.column_stack(cols), names, baseline


def fit_full(frame: pd.DataFrame, predictors: list[str], levels: list[str]):
    means = {c: float(frame[c].mean()) for c in predictors}
    sds = {c: float(frame[c].std(ddof=0)) for c in predictors}
    X, names, baseline = make_design(frame, predictors, levels, means, sds)
    y = frame.q5_minus_q1.to_numpy(float)
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    pred = X @ beta
    sse = float(np.sum((y - pred) ** 2))
    sst = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - sse / sst if sst > 0 else np.nan
    n, k = len(y), X.shape[1]
    adj = 1.0 - (1.0 - r2) * (n - 1) / (n - k) if np.isfinite(r2) and n > k else np.nan
    coef = pd.DataFrame(
        {
            "term": names,
            "coefficient": beta,
            "baseline_window": baseline,
            "n": n,
            "k": k,
            "r2_in_sample": r2,
            "adj_r2_in_sample": adj,
        }
    )
    return coef, r2, adj, k


def loyo(frame: pd.DataFrame, predictors: list[str], levels: list[str]) -> pd.DataFrame:
    rows: list[dict] = []
    for yr in sorted(frame.year.unique()):
        train = frame[frame.year != yr].copy()
        test = frame[frame.year == yr].copy()
        if test.empty or len(train) < 6:
            continue

        train_levels = set(train.window.astype(str))
        test = test[test.window.astype(str).isin(train_levels)].copy()
        if test.empty:
            continue

        means = {c: float(train[c].mean()) for c in predictors}
        sds = {c: float(train[c].std(ddof=0)) for c in predictors}
        if any((not np.isfinite(sds[c]) or sds[c] <= 1e-12) for c in predictors):
            continue

        Xtr, _, _ = make_design(train, predictors, levels, means, sds)
        Xte, _, _ = make_design(test, predictors, levels, means, sds)
        beta, *_ = np.linalg.lstsq(Xtr, train.q5_minus_q1.to_numpy(float), rcond=None)
        pred = Xte @ beta
        obs = test.q5_minus_q1.to_numpy(float)
        err = obs - pred
        for i, rr in enumerate(test.itertuples(index=False)):
            rows.append(
                {
                    "heldout_year": int(yr),
                    "window": str(rr.window),
                    "observed": float(obs[i]),
                    "predicted": float(pred[i]),
                    "error": float(err[i]),
                }
            )
    return pd.DataFrame(rows)


def cv_metrics(cv: pd.DataFrame):
    if cv.empty:
        return np.nan, np.nan
    e = cv.error.to_numpy(float)
    return float(np.sqrt(np.mean(e * e))), float(np.mean(np.abs(e)))


def year_metrics(cv: pd.DataFrame) -> pd.DataFrame:
    if cv.empty:
        return pd.DataFrame()
    rows = []
    for yr, g in cv.groupby("heldout_year", sort=True):
        e = g.error.to_numpy(float)
        rows.append(
            {
                "heldout_year": int(yr),
                "n_test": len(g),
                "rmse": float(np.sqrt(np.mean(e * e))),
                "mae": float(np.mean(np.abs(e))),
                "mean_error": float(np.mean(e)),
            }
        )
    return pd.DataFrame(rows)


def evaluate_scope(data: pd.DataFrame, scope: str, qa: float):
    x = data[data.qa_good_field_share_pct >= qa].copy()
    if scope == "W2_W4_only":
        x = x[x.window != "W1_early_april"].copy()

    all_needed = ["q5_minus_q1", "year", "window", "median_field_ndvi"]
    for h in HORIZONS:
        all_needed += [f"precip_{h}d_mm", f"tmean_{h}d_c"]
    x = x.dropna(subset=all_needed).copy()
    levels = sorted(x.window.astype(str).unique())
    if len(x) < 10 or len(levels) < 2:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    metric_rows = []
    coef_frames = []
    cv_frames = []
    year_frames = []

    for spec in model_specs():
        model = spec["model"]
        predictors = spec["predictors"]
        coef, r2, adj, k = fit_full(x, predictors, levels)
        cv = loyo(x, predictors, levels)
        rmse, mae = cv_metrics(cv)
        ym = year_metrics(cv)

        metric_rows.append(
            {
                "scope": scope,
                "qa_threshold_pct": qa,
                "model": model,
                "horizon_days": spec["horizon"],
                "comparison_baseline": spec["baseline"],
                "n": len(x),
                "years": x.year.nunique(),
                "windows": len(levels),
                "k": k,
                "r2_in_sample": r2,
                "adj_r2_in_sample": adj,
                "loyo_rmse": rmse,
                "loyo_mae": mae,
            }
        )
        coef.insert(0, "horizon_days", spec["horizon"])
        coef.insert(0, "model", model)
        coef.insert(0, "qa_threshold_pct", qa)
        coef.insert(0, "scope", scope)
        coef_frames.append(coef)

        if not cv.empty:
            cv.insert(0, "horizon_days", spec["horizon"])
            cv.insert(0, "model", model)
            cv.insert(0, "qa_threshold_pct", qa)
            cv.insert(0, "scope", scope)
            cv_frames.append(cv)
        if not ym.empty:
            ym.insert(0, "comparison_baseline", spec["baseline"])
            ym.insert(0, "horizon_days", spec["horizon"])
            ym.insert(0, "model", model)
            ym.insert(0, "qa_threshold_pct", qa)
            ym.insert(0, "scope", scope)
            year_frames.append(ym)

    metrics = pd.DataFrame(metric_rows)
    lookup = metrics.set_index("model")
    improvements = []
    for r in metrics.itertuples(index=False):
        b = lookup.loc[r.comparison_baseline]
        improvements.append(
            {
                "delta_loyo_rmse_vs_baseline": float(r.loyo_rmse - b.loyo_rmse),
                "loyo_rmse_improvement_vs_baseline_pct": (
                    100.0 * float(b.loyo_rmse - r.loyo_rmse) / float(b.loyo_rmse)
                    if pd.notna(b.loyo_rmse) and float(b.loyo_rmse) > 0
                    else np.nan
                ),
            }
        )
    imp = pd.DataFrame(improvements)
    metrics = pd.concat([metrics.reset_index(drop=True), imp], axis=1)

    coefs = pd.concat(coef_frames, ignore_index=True)
    cvs = pd.concat(cv_frames, ignore_index=True) if cv_frames else pd.DataFrame()
    years = pd.concat(year_frames, ignore_index=True) if year_frames else pd.DataFrame()

    # Per-year comparison uses matching held-out windows from model and baseline.
    comparisons = []
    if not years.empty:
        for r in years.itertuples(index=False):
            b = years[
                (years.model == r.comparison_baseline)
                & (years.heldout_year == r.heldout_year)
            ]
            if b.empty:
                continue
            brmse = float(b.iloc[0].rmse)
            comparisons.append(
                {
                    "scope": scope,
                    "qa_threshold_pct": qa,
                    "model": r.model,
                    "horizon_days": int(r.horizon_days),
                    "comparison_baseline": r.comparison_baseline,
                    "heldout_year": int(r.heldout_year),
                    "n_test": int(r.n_test),
                    "model_rmse": float(r.rmse),
                    "baseline_rmse": brmse,
                    "delta_rmse": float(r.rmse - brmse),
                    "improved": bool(float(r.rmse) < brmse),
                    "model_mae": float(r.mae),
                }
            )
    cmp = pd.DataFrame(comparisons)
    return metrics, coefs, cvs, cmp


def fmt(x, n=4):
    return "nan" if pd.isna(x) else f"{float(x):.{n}f}"


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
    data = load_data(outdir, args.year_start, args.year_end)

    print("=" * 132)
    print("ÅkerSync · Satellite V1a · STEP 29 WEATHER-WINDOW ROBUSTNESS")
    print("=" * 132)
    print(f"Input year×window: {len(data)} | år {args.year_start}–{args.year_end}")
    print("Ingen satellithämtning. Testar väderfönster 14/30/45 dagar, P vs T vs P+T och LOYO år för år.")
    print("QA thresholds:", ", ".join(f"{q:g}%" for q in thresholds))

    mets, coefs, cvs, cmps = [], [], [], []
    for qa in thresholds:
        for scope in ("all_windows", "W2_W4_only"):
            m, c, cv, cmp = evaluate_scope(data, scope, qa)
            if m.empty:
                print(f"VARNING: {scope} QA>={qa:g}% har för få observationer")
                continue
            mets.append(m)
            coefs.append(c)
            if not cv.empty:
                cvs.append(cv)
            if not cmp.empty:
                cmps.append(cmp)

    metrics = pd.concat(mets, ignore_index=True) if mets else pd.DataFrame()
    coef_df = pd.concat(coefs, ignore_index=True) if coefs else pd.DataFrame()
    cv_df = pd.concat(cvs, ignore_index=True) if cvs else pd.DataFrame()
    cmp_df = pd.concat(cmps, ignore_index=True) if cmps else pd.DataFrame()
    if metrics.empty:
        raise RuntimeError("Step 29 producerade inga modeller")

    if not cmp_df.empty:
        count_rows = []
        for keys, g in cmp_df.groupby(
            ["scope", "qa_threshold_pct", "model", "horizon_days", "comparison_baseline"],
            sort=True,
        ):
            scope, qa, model, horizon, baseline = keys
            count_rows.append(
                {
                    "scope": scope,
                    "qa_threshold_pct": qa,
                    "model": model,
                    "horizon_days": horizon,
                    "comparison_baseline": baseline,
                    "years_compared": int(g.heldout_year.nunique()),
                    "years_improved": int(g.improved.sum()),
                    "fraction_years_improved": float(g.improved.mean()),
                    "median_year_delta_rmse": float(g.delta_rmse.median()),
                    "mean_year_delta_rmse": float(g.delta_rmse.mean()),
                }
            )
        counts = pd.DataFrame(count_rows)
        metrics = metrics.merge(
            counts,
            on=["scope", "qa_threshold_pct", "model", "horizon_days", "comparison_baseline"],
            how="left",
        )
    else:
        counts = pd.DataFrame()

    stem = f"lomma_weather_window_robustness_{args.year_start}_{args.year_end}"
    analysis_csv = outdir / f"{stem}_analysis_table.csv"
    metrics_csv = outdir / f"{stem}_metrics.csv"
    coef_csv = outdir / f"{stem}_coefficients.csv"
    cv_csv = outdir / f"{stem}_loyo_predictions.csv"
    year_csv = outdir / f"{stem}_yearwise_comparison.csv"
    summary_txt = outdir / f"{stem}_summary.txt"

    data.to_csv(analysis_csv, index=False, encoding="utf-8-sig")
    metrics.to_csv(metrics_csv, index=False, encoding="utf-8-sig")
    coef_df.to_csv(coef_csv, index=False, encoding="utf-8-sig")
    cv_df.to_csv(cv_csv, index=False, encoding="utf-8-sig")
    cmp_df.to_csv(year_csv, index=False, encoding="utf-8-sig")

    primary = metrics[
        (metrics.scope == "W2_W4_only")
        & (metrics.qa_threshold_pct == float(args.primary_qa))
    ].copy()
    primary = primary.sort_values("loyo_rmse")

    lines = [
        "ÅkerSync Satellite V1a — Step 29 weather-window robustness",
        f"Years: {args.year_start}–{args.year_end}",
        "Regression unit: accepted year × seasonal window",
        "Validation: leave-one-year-out",
        "",
        f"PRIMARY: W2-W4, QA >= {args.primary_qa:g}%",
    ]
    for r in primary.itertuples(index=False):
        yrs = "" if pd.isna(getattr(r, "years_improved", np.nan)) else f" | years improved {int(r.years_improved)}/{int(r.years_compared)}"
        lines.append(
            f"  {r.model:15s} | n={int(r.n):2d} | LOYO RMSE {r.loyo_rmse:.4f} | MAE {r.loyo_mae:.4f} | "
            f"vs {r.comparison_baseline} {r.loyo_rmse_improvement_vs_baseline_pct:+.1f}%{yrs}"
        )

    lines += ["", "QA SENSITIVITY — best PT horizon without vegetation:"]
    for qa in thresholds:
        z = metrics[
            (metrics.scope == "W2_W4_only")
            & (metrics.qa_threshold_pct == qa)
            & (metrics.model.isin([f"PT{h}" for h in HORIZONS]))
        ].sort_values("loyo_rmse")
        if not z.empty:
            r = z.iloc[0]
            lines.append(
                f"  QA>={qa:g}%: {r.model} RMSE={r.loyo_rmse:.4f}, improvement={r.loyo_rmse_improvement_vs_baseline_pct:+.1f}%"
            )

    lines += [
        "",
        "GUARDRAILS:",
        "  Best horizon is exploratory model selection on a small number of year×window observations.",
        "  Prefer a signal that is directionally stable across 14/30/45 d and QA thresholds over one isolated optimum.",
        "  Yearwise LOYO reveals whether improvement is broad or dominated by unusual years.",
        "  Weather associations are not proof of drainage or causal water limitation.",
    ]
    summary_txt.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n" + "=" * 132)
    print("STEP 29 WEATHER-WINDOW ROBUSTNESS KLAR")
    print("=" * 132)
    print(f"\nPRIMARY · W2-W4 · QA >= {args.primary_qa:g}%")
    for r in primary.itertuples(index=False):
        yrs = ""
        if pd.notna(getattr(r, "years_improved", np.nan)):
            yrs = f" | år bättre {int(r.years_improved)}/{int(r.years_compared)}"
        print(
            f"  {r.model:15s} | n={int(r.n):2d} | R2 {r.r2_in_sample:.3f} | "
            f"LOYO RMSE {r.loyo_rmse:.4f} | vs {r.comparison_baseline} {r.loyo_rmse_improvement_vs_baseline_pct:+5.1f}%{yrs}"
        )

    print("\nP/T/PT per väderfönster · W2-W4 primary:")
    for h in HORIZONS:
        for model in (f"P{h}", f"T{h}", f"PT{h}", f"VPT{h}"):
            z = primary[primary.model == model]
            if z.empty:
                continue
            r = z.iloc[0]
            yrs = "" if pd.isna(r.get("years_improved", np.nan)) else f" | år bättre {int(r.years_improved)}/{int(r.years_compared)}"
            print(
                f"  {model:5s} | RMSE {r.loyo_rmse:.4f} | improvement {r.loyo_rmse_improvement_vs_baseline_pct:+5.1f}%{yrs}"
            )

    print("\nQA sensitivity · bästa PT-horisont, W2-W4:")
    for qa in thresholds:
        z = metrics[
            (metrics.scope == "W2_W4_only")
            & (metrics.qa_threshold_pct == qa)
            & (metrics.model.isin([f"PT{h}" for h in HORIZONS]))
        ].sort_values("loyo_rmse")
        if z.empty:
            continue
        r = z.iloc[0]
        print(
            f"  QA>={qa:4.0f}% | {r.model:4s} | RMSE {r.loyo_rmse:.4f} | improvement {r.loyo_rmse_improvement_vs_baseline_pct:+5.1f}%"
        )

    print("\nYear-by-year · bästa primary PT-modell vs window:")
    best_pt = primary[primary.model.isin([f"PT{h}" for h in HORIZONS])].sort_values("loyo_rmse")
    if not best_pt.empty and not cmp_df.empty:
        bm = str(best_pt.iloc[0].model)
        z = cmp_df[
            (cmp_df.scope == "W2_W4_only")
            & (cmp_df.qa_threshold_pct == float(args.primary_qa))
            & (cmp_df.model == bm)
        ].sort_values("heldout_year")
        for r in z.itertuples(index=False):
            mark = "BETTER" if r.improved else "worse"
            print(
                f"  {int(r.heldout_year)} | {bm} {r.model_rmse:.4f} vs baseline {r.baseline_rmse:.4f} | "
                f"delta {r.delta_rmse:+.4f} | {mark} | n={int(r.n_test)}"
            )

    print("\nOutput:")
    for p in (analysis_csv, metrics_csv, coef_csv, cv_csv, year_csv, summary_txt):
        print(" ", p)
    print("\nSTEP 29: OK")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
