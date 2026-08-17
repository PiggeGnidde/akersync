#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerSync Satellite V1a — Step 30: thermal-time/date confounding stress test.

Question
--------
Step 29 showed that recent weather (especially T30/T45, and PT30/PT45)
improves leave-one-year-out prediction of the within-field TWI response Q5-Q1.
This step asks whether that gain survives a stronger phenology control:

  * cumulative GDD5 from March 1 to the day before the accepted Sentinel date,
  * exact day offset within the seasonal window.

No new satellite or weather download is performed. Existing local outputs from
steps 25/27 are reused.

Primary models
--------------
B0   : window
BG   : window + GDD5 + date_offset
BT45 : window + T45
BGT  : window + GDD5 + date_offset + T45
BGPT : window + GDD5 + date_offset + P45 + T45

The decisive comparison is BGPT versus BG (and BGT versus BG): does recent
weather still improve prediction after the model already knows cumulative
thermal time and exact calendar position within the window?

Validation
----------
Leave-one-year-out (LOYO). Continuous predictors are standardized using only
training years in each fold. Regression unit is one accepted YEAR × WINDOW.
Both all windows and W2-W4 are evaluated at QA thresholds 50/60/75/80%.

Guardrails
----------
GDD5 is a generic thermal-time proxy, not crop-specific phenological truth.
The analysis is observational/descriptive and does not prove drainage or water
stress causality. Regional station weather is a proxy for field conditions.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from common import load_config

ROOT = Path(__file__).resolve().parents[1]

WINDOW_START = {
    "W1_early_april": "04-01",
    "W2_late_may": "05-15",
    "W3_late_june": "06-15",
    "W4_early_july": "07-01",
}

SPECS = [
    {"model": "B0_window", "predictors": [], "baseline": "B0_window"},
    {"model": "BG_window_gdd_offset", "predictors": ["gdd5_mar01", "date_offset_days"], "baseline": "B0_window"},
    {"model": "BT45_window_t45", "predictors": ["tmean_45d_c"], "baseline": "B0_window"},
    {"model": "BGT_window_gdd_offset_t45", "predictors": ["gdd5_mar01", "date_offset_days", "tmean_45d_c"], "baseline": "BG_window_gdd_offset"},
    {"model": "BGPT_window_gdd_offset_p45_t45", "predictors": ["gdd5_mar01", "date_offset_days", "precip_45d_mm", "tmean_45d_c"], "baseline": "BG_window_gdd_offset"},
]


def parse_thresholds(text: str) -> list[float]:
    vals = []
    for p in str(text).split(","):
        p = p.strip()
        if not p:
            continue
        x = float(p)
        if not 0 <= x <= 100:
            raise ValueError("QA thresholds måste ligga mellan 0 och 100")
        vals.append(x)
    if not vals:
        raise ValueError("Minst en QA threshold krävs")
    return sorted(set(vals))


def load_data(outdir: Path, year_start: int, year_end: int, min_gdd_coverage: float) -> pd.DataFrame:
    stem = f"lomma_multiyear_twi_weather_{year_start}_{year_end}"
    yw_path = outdir / f"{stem}_year_window_curve.csv"
    weather_path = outdir / f"lomma_weather_{year_start}_{year_end}_daily.csv"
    for p in (yw_path, weather_path):
        if not p.exists():
            raise FileNotFoundError(f"Saknar {p}")

    x = pd.read_csv(yw_path)
    w = pd.read_csv(weather_path)
    need = {"year", "window", "date", "q5_minus_q1", "qa_good_field_share_pct", "precip_45d_mm", "tmean_45d_c"}
    miss = sorted(need - set(x.columns))
    if miss:
        raise RuntimeError(f"year_window_curve saknar kolumner: {miss}")
    if not {"date", "tmean_c"}.issubset(w.columns):
        raise RuntimeError("weather daily saknar date/tmean_c")

    x["year"] = pd.to_numeric(x.year, errors="coerce")
    x["date"] = pd.to_datetime(x.date, errors="coerce")
    x = x[x.year.notna() & x.date.notna()].copy()
    x["year"] = x.year.astype(int)
    x["window"] = x.window.astype(str)
    w["date"] = pd.to_datetime(w.date, errors="coerce")
    w["tmean_c"] = pd.to_numeric(w.tmean_c, errors="coerce")

    gdd_rows = []
    for r in x.itertuples(index=False):
        y = int(r.year)
        d = pd.Timestamp(r.date).normalize()
        start = pd.Timestamp(f"{y}-03-01")
        end = d - pd.Timedelta(days=1)
        ww = w[(w.date >= start) & (w.date <= end)].copy()
        expected = max(0, (end - start).days + 1)
        ntemp = int(ww.tmean_c.notna().sum())
        cov = 100.0 * ntemp / expected if expected else np.nan
        if expected and cov >= min_gdd_coverage:
            gdd = float(np.maximum(ww.tmean_c.to_numpy(float) - 5.0, 0.0)[np.isfinite(ww.tmean_c.to_numpy(float))].sum())
        else:
            gdd = np.nan

        ws = WINDOW_START.get(str(r.window))
        offset = np.nan
        if ws:
            offset = float((d - pd.Timestamp(f"{y}-{ws}")).days)
        gdd_rows.append({
            "year": y,
            "window": str(r.window),
            "date": d,
            "gdd5_mar01": gdd,
            "gdd_temp_coverage_pct": cov,
            "gdd_days_expected": expected,
            "gdd_days_observed": ntemp,
            "date_offset_days": offset,
            "day_of_year": int(d.dayofyear),
        })

    g = pd.DataFrame(gdd_rows)
    data = x.merge(g, on=["year", "window", "date"], how="left", validate="one_to_one")
    return data.sort_values(["year", "date"]).reset_index(drop=True)


def make_design(frame: pd.DataFrame, predictors: list[str], levels: list[str], means: dict, sds: dict):
    cols = [np.ones(len(frame), dtype=float)]
    names = ["intercept"]
    arrw = frame.window.astype(str).to_numpy()
    for lev in levels[1:]:
        cols.append((arrw == lev).astype(float))
        names.append(f"window_{lev}")
    for c in predictors:
        sd = float(sds[c])
        if not np.isfinite(sd) or sd <= 1e-12:
            raise RuntimeError(f"Prediktor {c} har noll/ogiltig variation")
        cols.append((frame[c].to_numpy(float) - float(means[c])) / sd)
        names.append(c + "_z")
    return np.column_stack(cols), names


def fit_full(frame: pd.DataFrame, predictors: list[str], levels: list[str]):
    means = {c: float(frame[c].mean()) for c in predictors}
    sds = {c: float(frame[c].std(ddof=0)) for c in predictors}
    X, names = make_design(frame, predictors, levels, means, sds)
    y = frame.q5_minus_q1.to_numpy(float)
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    pred = X @ beta
    sse = float(np.sum((y - pred) ** 2))
    sst = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - sse / sst if sst > 0 else np.nan
    n, k = len(y), X.shape[1]
    adj = 1.0 - (1.0-r2)*(n-1)/(n-k) if np.isfinite(r2) and n > k else np.nan
    # Condition number on standardized design: useful collinearity diagnostic.
    cond = float(np.linalg.cond(X)) if X.size else np.nan
    coef = pd.DataFrame({"term": names, "coefficient": beta})
    return coef, r2, adj, k, cond


def loyo(frame: pd.DataFrame, predictors: list[str], levels: list[str]) -> pd.DataFrame:
    rows = []
    for yr in sorted(frame.year.unique()):
        tr = frame[frame.year != yr].copy()
        te = frame[frame.year == yr].copy()
        if te.empty or len(tr) < 8:
            continue
        train_levels = set(tr.window.astype(str))
        te = te[te.window.astype(str).isin(train_levels)].copy()
        if te.empty:
            continue
        means = {c: float(tr[c].mean()) for c in predictors}
        sds = {c: float(tr[c].std(ddof=0)) for c in predictors}
        if any((not np.isfinite(sds[c]) or sds[c] <= 1e-12) for c in predictors):
            continue
        Xtr, _ = make_design(tr, predictors, levels, means, sds)
        Xte, _ = make_design(te, predictors, levels, means, sds)
        b, *_ = np.linalg.lstsq(Xtr, tr.q5_minus_q1.to_numpy(float), rcond=None)
        pred = Xte @ b
        obs = te.q5_minus_q1.to_numpy(float)
        for i, rr in enumerate(te.itertuples(index=False)):
            rows.append({
                "heldout_year": int(yr), "window": str(rr.window),
                "observed": float(obs[i]), "predicted": float(pred[i]),
                "error": float(obs[i]-pred[i]),
            })
    return pd.DataFrame(rows)


def cv_metrics(cv: pd.DataFrame):
    if cv.empty:
        return np.nan, np.nan
    e = cv.error.to_numpy(float)
    return float(np.sqrt(np.mean(e*e))), float(np.mean(np.abs(e)))


def year_metrics(cv: pd.DataFrame) -> pd.DataFrame:
    rows = []
    if cv.empty:
        return pd.DataFrame()
    for yr, g in cv.groupby("heldout_year", sort=True):
        e = g.error.to_numpy(float)
        rows.append({"heldout_year": int(yr), "n_test": len(g),
                     "rmse": float(np.sqrt(np.mean(e*e))), "mae": float(np.mean(np.abs(e)))})
    return pd.DataFrame(rows)


def evaluate(data: pd.DataFrame, scope: str, qa: float):
    x = data[data.qa_good_field_share_pct >= qa].copy()
    if scope == "W2_W4_only":
        x = x[x.window != "W1_early_april"].copy()
    needed = ["q5_minus_q1", "year", "window", "gdd5_mar01", "date_offset_days", "precip_45d_mm", "tmean_45d_c"]
    x = x.dropna(subset=needed).copy()
    levels = sorted(x.window.astype(str).unique())
    if len(x) < 10 or len(levels) < 2:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    metrics, coefs, cvs, years = [], [], [], []
    for spec in SPECS:
        model, preds, baseline = spec["model"], spec["predictors"], spec["baseline"]
        coef, r2, adj, k, cond = fit_full(x, preds, levels)
        cv = loyo(x, preds, levels)
        rmse, mae = cv_metrics(cv)
        ym = year_metrics(cv)
        metrics.append({"scope": scope, "qa_threshold_pct": qa, "model": model,
                        "comparison_baseline": baseline, "n": len(x), "years": x.year.nunique(),
                        "windows": len(levels), "k": k, "r2_in_sample": r2, "adj_r2_in_sample": adj,
                        "loyo_rmse": rmse, "loyo_mae": mae, "design_condition_number": cond})
        coef.insert(0, "model", model); coef.insert(0, "qa_threshold_pct", qa); coef.insert(0, "scope", scope)
        coefs.append(coef)
        if not cv.empty:
            cv.insert(0, "model", model); cv.insert(0, "qa_threshold_pct", qa); cv.insert(0, "scope", scope)
            cvs.append(cv)
        if not ym.empty:
            ym.insert(0, "model", model); ym.insert(0, "qa_threshold_pct", qa); ym.insert(0, "scope", scope)
            years.append(ym)

    met = pd.DataFrame(metrics)
    lookup = met.set_index("model")
    met["delta_loyo_rmse_vs_baseline"] = np.nan
    met["loyo_improvement_vs_baseline_pct"] = np.nan
    for i, r in met.iterrows():
        b = lookup.loc[r.comparison_baseline]
        if pd.notna(r.loyo_rmse) and pd.notna(b.loyo_rmse) and float(b.loyo_rmse) > 0:
            met.loc[i, "delta_loyo_rmse_vs_baseline"] = float(r.loyo_rmse - b.loyo_rmse)
            met.loc[i, "loyo_improvement_vs_baseline_pct"] = 100.0 * float(b.loyo_rmse - r.loyo_rmse) / float(b.loyo_rmse)

    coefdf = pd.concat(coefs, ignore_index=True)
    cvdf = pd.concat(cvs, ignore_index=True) if cvs else pd.DataFrame()
    ydf = pd.concat(years, ignore_index=True) if years else pd.DataFrame()

    cmp_rows = []
    if not ydf.empty:
        for model in ("BGT_window_gdd_offset_t45", "BGPT_window_gdd_offset_p45_t45"):
            a = ydf[ydf.model.eq(model)]
            b = ydf[ydf.model.eq("BG_window_gdd_offset")]
            m = a.merge(b, on=["heldout_year", "qa_threshold_pct", "scope"], suffixes=("_model", "_bg"))
            for rr in m.itertuples(index=False):
                cmp_rows.append({"scope": scope, "qa_threshold_pct": qa, "model": model,
                                 "heldout_year": int(rr.heldout_year), "n_test": int(rr.n_test_model),
                                 "model_rmse": float(rr.rmse_model), "bg_rmse": float(rr.rmse_bg),
                                 "delta_rmse": float(rr.rmse_model-rr.rmse_bg),
                                 "improved": bool(rr.rmse_model < rr.rmse_bg)})
    return met, coefdf, cvdf, pd.DataFrame(cmp_rows)


def fmt(x, n=4):
    return "nan" if pd.isna(x) else f"{float(x):.{n}f}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/local_paths.json")
    ap.add_argument("--year-start", type=int, default=2018)
    ap.add_argument("--year-end", type=int, default=2026)
    ap.add_argument("--qa-thresholds", default="50,60,75,80")
    ap.add_argument("--primary-qa", type=float, default=50.0)
    ap.add_argument("--min-gdd-coverage", type=float, default=85.0)
    args = ap.parse_args()

    thresholds = parse_thresholds(args.qa_thresholds)
    if args.primary_qa not in thresholds:
        thresholds = sorted(set(thresholds + [args.primary_qa]))

    cfg = load_config(ROOT / args.config)
    outdir = ROOT / cfg.get("build_dir", "data/derived") / "satellite_poc"
    outdir.mkdir(parents=True, exist_ok=True)
    data = load_data(outdir, args.year_start, args.year_end, args.min_gdd_coverage)

    print("="*132)
    print("ÅkerSync · Satellite V1a · STEP 30 THERMAL-TIME / DATE CONFOUNDING")
    print("="*132)
    print(f"Input year×window: {len(data)} | years {args.year_start}-{args.year_end}")
    print("Ingen nättrafik: endast lokala Step 25/27-filer.")
    print("Phenology proxy: GDD5 från 1 mars till dagen före Sentinel + exakt day-offset inom window.")
    print("Decisive: BGPT/BGT vs BG under LOYO. QA:", ", ".join(f"{q:g}%" for q in thresholds))

    mets=[]; coefs=[]; cvs=[]; cmps=[]
    for qa in thresholds:
        for scope in ("all_windows", "W2_W4_only"):
            m,c,v,cp = evaluate(data, scope, qa)
            if not m.empty: mets.append(m)
            if not c.empty: coefs.append(c)
            if not v.empty: cvs.append(v)
            if not cp.empty: cmps.append(cp)

    metrics = pd.concat(mets, ignore_index=True)
    coefficients = pd.concat(coefs, ignore_index=True)
    predictions = pd.concat(cvs, ignore_index=True)
    comparisons = pd.concat(cmps, ignore_index=True) if cmps else pd.DataFrame()

    stem = f"lomma_thermal_time_confounding_{args.year_start}_{args.year_end}"
    analysis_csv = outdir / f"{stem}_analysis_table.csv"
    metrics_csv = outdir / f"{stem}_metrics.csv"
    coef_csv = outdir / f"{stem}_coefficients.csv"
    pred_csv = outdir / f"{stem}_loyo_predictions.csv"
    cmp_csv = outdir / f"{stem}_yearwise_comparison.csv"
    summary_txt = outdir / f"{stem}_summary.txt"
    data.to_csv(analysis_csv, index=False, encoding="utf-8-sig", date_format="%Y-%m-%d")
    metrics.to_csv(metrics_csv, index=False, encoding="utf-8-sig")
    coefficients.to_csv(coef_csv, index=False, encoding="utf-8-sig")
    predictions.to_csv(pred_csv, index=False, encoding="utf-8-sig")
    comparisons.to_csv(cmp_csv, index=False, encoding="utf-8-sig")

    primary = metrics[(metrics.scope.eq("W2_W4_only")) & (metrics.qa_threshold_pct.eq(args.primary_qa))].copy()
    order = [s["model"] for s in SPECS]
    primary["ord"] = primary.model.map({m:i for i,m in enumerate(order)})
    primary = primary.sort_values("ord")

    lines = ["ÅkerSync Step 30 — thermal-time/date confounding", "", f"PRIMARY W2-W4 QA>={args.primary_qa:g}%:"]
    for r in primary.itertuples(index=False):
        lines.append(f"  {r.model:34s} n={int(r.n):2d} R2={r.r2_in_sample:.3f} LOYO={r.loyo_rmse:.4f} baseline={r.comparison_baseline} improvement={r.loyo_improvement_vs_baseline_pct:+.1f}% cond={r.design_condition_number:.1f}")

    print("\n" + "="*132)
    print("STEP 30 THERMAL-TIME CONFOUNDING KLAR")
    print("="*132)
    print(f"\nPRIMARY · W2-W4 · QA >= {args.primary_qa:g}%")
    for r in primary.itertuples(index=False):
        print(f"  {r.model:34s} | n={int(r.n):2d} | R2 {r.r2_in_sample:.3f} | LOYO RMSE {r.loyo_rmse:.4f} | vs {r.comparison_baseline} {r.loyo_improvement_vs_baseline_pct:+5.1f}% | cond {r.design_condition_number:.1f}")

    print("\nQA sensitivity · incremental recent weather beyond GDD+date (W2-W4):")
    for qa in thresholds:
        z = metrics[(metrics.scope.eq("W2_W4_only")) & (metrics.qa_threshold_pct.eq(qa))]
        bg = z[z.model.eq("BG_window_gdd_offset")]
        bgt = z[z.model.eq("BGT_window_gdd_offset_t45")]
        bgpt = z[z.model.eq("BGPT_window_gdd_offset_p45_t45")]
        if bg.empty or bgt.empty or bgpt.empty:
            continue
        print(f"  QA>={qa:4.0f}% | BG {bg.iloc[0].loyo_rmse:.4f} | +T45 {bgt.iloc[0].loyo_rmse:.4f} ({bgt.iloc[0].loyo_improvement_vs_baseline_pct:+5.1f}%) | +P45+T45 {bgpt.iloc[0].loyo_rmse:.4f} ({bgpt.iloc[0].loyo_improvement_vs_baseline_pct:+5.1f}%)")
        lines.append(f"QA {qa:g}: BG {bg.iloc[0].loyo_rmse:.4f}; BGT {bgt.iloc[0].loyo_rmse:.4f}; BGPT {bgpt.iloc[0].loyo_rmse:.4f}")

    if not comparisons.empty:
        print("\nYear-by-year · BGPT vs BG · primary W2-W4:")
        cp = comparisons[(comparisons.scope.eq("W2_W4_only")) & (comparisons.qa_threshold_pct.eq(args.primary_qa)) & comparisons.model.eq("BGPT_window_gdd_offset_p45_t45")].sort_values("heldout_year")
        for r in cp.itertuples(index=False):
            tag = "BETTER" if r.improved else "worse"
            print(f"  {int(r.heldout_year)} | BGPT {r.model_rmse:.4f} vs BG {r.bg_rmse:.4f} | delta {r.delta_rmse:+.4f} | {tag} | n={int(r.n_test)}")
        if len(cp):
            print(f"  => bättre i {int(cp.improved.sum())}/{len(cp)} år")
            lines += ["", f"BGPT vs BG yearwise: improved {int(cp.improved.sum())}/{len(cp)} years"]

    # Simple predictor correlation diagnostics in the primary sample.
    xx = data[(data.qa_good_field_share_pct >= args.primary_qa) & (data.window != "W1_early_april")].dropna(subset=["gdd5_mar01","date_offset_days","precip_45d_mm","tmean_45d_c"])
    print("\nPrimary predictor correlations (Pearson):")
    corr = xx[["gdd5_mar01","date_offset_days","precip_45d_mm","tmean_45d_c"]].corr()
    for a,b in [("gdd5_mar01","tmean_45d_c"),("gdd5_mar01","date_offset_days"),("tmean_45d_c","date_offset_days"),("precip_45d_mm","tmean_45d_c")]:
        print(f"  {a:18s} vs {b:18s}: r={corr.loc[a,b]:+.3f}")

    lines += ["", "Guardrail: GDD/date controls reduce phenology confounding but do not establish water-stress or drainage causality."]
    summary_txt.write_text("\n".join(lines)+"\n", encoding="utf-8")

    print("\nOutput:")
    for p in (analysis_csv, metrics_csv, coef_csv, pred_csv, cmp_csv, summary_txt):
        print(" ", p)
    print("\nSTEP 30: OK")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
