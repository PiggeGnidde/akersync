#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerSync Satellite V1a — Step 31: precipitation isolation + orthogonalized temperature.

Purpose
-------
Step 30 showed that much of the apparent recent-temperature signal is absorbed
by cumulative GDD5 + exact date position, while adding P45+T45 still improved
leave-one-year-out prediction. This step isolates what remains.

Questions
---------
1) Does precipitation alone improve prediction beyond window + GDD5 + date offset?
2) Which lookback (14/30/45 d) is most useful?
3) Does recent temperature add anything once thermal time/date are controlled?
4) Is the gain broad across held-out years and robust to stricter SCL QA?

Models, for h in {14,30,45}
---------------------------
BG      : window + GDD5 + date_offset
BGP_h   : BG + precipitation_h
BGT_h   : BG + temperature_h
BGPT_h  : BG + precipitation_h + temperature_h
BGTR_h  : BG + temperature_h_residual
BGPTR_h : BG + precipitation_h + temperature_h_residual

The residualized temperature is obtained from
    T_h ~ window + GDD5 + date_offset
and therefore represents the component of recent temperature not linearly
explained by the phenology/calendar controls already present in BG. In LOYO,
the residualizer is fitted on training years only and then applied to the held-
out year, avoiding leakage.

Note: BGTR and BGT span the same linear predictor space in-sample; the value of
orthogonalization is interpretability/conditioning, not creating new signal.

Validation
----------
Regression unit = one accepted YEAR × WINDOW observation. Leave-one-year-out
(LOYO), with predictor standardization learned on training years only. Both all
windows and W2-W4 are evaluated at QA thresholds 50/60/75/80%.

Guardrails
----------
This remains observational/descriptive. Regional precipitation is a station
proxy, not field water balance. GDD5 is a generic thermal-time proxy, not crop-
specific phenology. No drainage causality is inferred.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from common import load_config

ROOT = Path(__file__).resolve().parents[1]
HORIZONS = (14, 30, 45)
WINDOW_START = {
    "W1_early_april": "04-01",
    "W2_late_may": "05-15",
    "W3_late_june": "06-15",
    "W4_early_july": "07-01",
}


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
    required = {"year", "window", "date", "q5_minus_q1", "qa_good_field_share_pct"}
    for h in HORIZONS:
        required.update({f"precip_{h}d_mm", f"tmean_{h}d_c"})
    missing = sorted(required - set(x.columns))
    if missing:
        raise RuntimeError(f"year_window_curve saknar kolumner: {missing}")
    if not {"date", "tmean_c"}.issubset(w.columns):
        raise RuntimeError("weather daily saknar date/tmean_c")

    x["year"] = pd.to_numeric(x.year, errors="coerce")
    x["date"] = pd.to_datetime(x.date, errors="coerce")
    x = x[x.year.notna() & x.date.notna()].copy()
    x["year"] = x.year.astype(int)
    x["window"] = x.window.astype(str)
    w["date"] = pd.to_datetime(w.date, errors="coerce")
    w["tmean_c"] = pd.to_numeric(w.tmean_c, errors="coerce")

    rows = []
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
            arr = ww.tmean_c.to_numpy(float)
            arr = arr[np.isfinite(arr)]
            gdd = float(np.maximum(arr - 5.0, 0.0).sum())
        else:
            gdd = np.nan
        md = WINDOW_START.get(str(r.window))
        offset = float((d - pd.Timestamp(f"{y}-{md}")).days) if md else np.nan
        rows.append({
            "year": y,
            "window": str(r.window),
            "date": d,
            "gdd5_mar01": gdd,
            "gdd_temp_coverage_pct": cov,
            "date_offset_days": offset,
            "day_of_year": int(d.dayofyear),
        })
    g = pd.DataFrame(rows)
    return x.merge(g, on=["year", "window", "date"], how="left", validate="one_to_one").sort_values(["year", "date"]).reset_index(drop=True)


def design(frame: pd.DataFrame, predictors: list[str], levels: list[str], means: dict, sds: dict):
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
    X, names = design(frame, predictors, levels, means, sds)
    y = frame.q5_minus_q1.to_numpy(float)
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    pred = X @ b
    sse = float(np.sum((y - pred) ** 2))
    sst = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - sse / sst if sst > 0 else np.nan
    n, k = len(y), X.shape[1]
    adj = 1.0 - (1.0-r2)*(n-1)/(n-k) if np.isfinite(r2) and n > k else np.nan
    cond = float(np.linalg.cond(X)) if X.size else np.nan
    coef = pd.DataFrame({"term": names, "coefficient": b})
    return coef, r2, adj, k, cond


def temp_residualizer_fit(train: pd.DataFrame, temp_col: str, levels: list[str]):
    # Unstandardized auxiliary model T ~ window + GDD + date offset.
    cols = [np.ones(len(train), dtype=float)]
    arrw = train.window.astype(str).to_numpy()
    for lev in levels[1:]:
        cols.append((arrw == lev).astype(float))
    cols.append(train.gdd5_mar01.to_numpy(float))
    cols.append(train.date_offset_days.to_numpy(float))
    X = np.column_stack(cols)
    y = train[temp_col].to_numpy(float)
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    return b


def temp_residualizer_apply(frame: pd.DataFrame, temp_col: str, levels: list[str], b: np.ndarray):
    cols = [np.ones(len(frame), dtype=float)]
    arrw = frame.window.astype(str).to_numpy()
    for lev in levels[1:]:
        cols.append((arrw == lev).astype(float))
    cols.append(frame.gdd5_mar01.to_numpy(float))
    cols.append(frame.date_offset_days.to_numpy(float))
    X = np.column_stack(cols)
    return frame[temp_col].to_numpy(float) - X @ b


def ordinary_specs():
    specs = [{"model": "BG", "horizon": 0, "predictors": ["gdd5_mar01", "date_offset_days"], "baseline": "BG"}]
    for h in HORIZONS:
        p, t = f"precip_{h}d_mm", f"tmean_{h}d_c"
        specs.extend([
            {"model": f"BGP{h}", "horizon": h, "predictors": ["gdd5_mar01", "date_offset_days", p], "baseline": "BG"},
            {"model": f"BGT{h}", "horizon": h, "predictors": ["gdd5_mar01", "date_offset_days", t], "baseline": "BG"},
            {"model": f"BGPT{h}", "horizon": h, "predictors": ["gdd5_mar01", "date_offset_days", p, t], "baseline": "BG"},
        ])
    return specs


def loyo_ordinary(frame: pd.DataFrame, predictors: list[str], levels: list[str]) -> pd.DataFrame:
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
        Xtr, _ = design(tr, predictors, levels, means, sds)
        Xte, _ = design(te, predictors, levels, means, sds)
        b, *_ = np.linalg.lstsq(Xtr, tr.q5_minus_q1.to_numpy(float), rcond=None)
        pred = Xte @ b
        obs = te.q5_minus_q1.to_numpy(float)
        for i, rr in enumerate(te.itertuples(index=False)):
            rows.append({"heldout_year": int(yr), "window": str(rr.window), "observed": float(obs[i]), "predicted": float(pred[i]), "error": float(obs[i]-pred[i])})
    return pd.DataFrame(rows)


def fit_orthogonalized_full(frame: pd.DataFrame, h: int, include_precip: bool, levels: list[str]):
    tcol = f"tmean_{h}d_c"
    pcol = f"precip_{h}d_mm"
    rb = temp_residualizer_fit(frame, tcol, levels)
    z = frame.copy()
    z[f"tresid_{h}d_c"] = temp_residualizer_apply(frame, tcol, levels, rb)
    predictors = ["gdd5_mar01", "date_offset_days"]
    if include_precip:
        predictors.append(pcol)
    predictors.append(f"tresid_{h}d_c")
    coef, r2, adj, k, cond = fit_full(z, predictors, levels)
    corr_gdd = float(np.corrcoef(z[f"tresid_{h}d_c"], z.gdd5_mar01)[0,1])
    corr_off = float(np.corrcoef(z[f"tresid_{h}d_c"], z.date_offset_days)[0,1])
    return coef, r2, adj, k, cond, corr_gdd, corr_off


def loyo_orthogonalized(frame: pd.DataFrame, h: int, include_precip: bool, levels: list[str]) -> pd.DataFrame:
    rows = []
    tcol = f"tmean_{h}d_c"
    pcol = f"precip_{h}d_mm"
    rcol = f"tresid_{h}d_c"
    for yr in sorted(frame.year.unique()):
        tr = frame[frame.year != yr].copy()
        te = frame[frame.year == yr].copy()
        if te.empty or len(tr) < 8:
            continue
        train_levels = set(tr.window.astype(str))
        te = te[te.window.astype(str).isin(train_levels)].copy()
        if te.empty:
            continue
        rb = temp_residualizer_fit(tr, tcol, levels)
        tr[rcol] = temp_residualizer_apply(tr, tcol, levels, rb)
        te[rcol] = temp_residualizer_apply(te, tcol, levels, rb)
        predictors = ["gdd5_mar01", "date_offset_days"]
        if include_precip:
            predictors.append(pcol)
        predictors.append(rcol)
        means = {c: float(tr[c].mean()) for c in predictors}
        sds = {c: float(tr[c].std(ddof=0)) for c in predictors}
        if any((not np.isfinite(sds[c]) or sds[c] <= 1e-12) for c in predictors):
            continue
        Xtr, _ = design(tr, predictors, levels, means, sds)
        Xte, _ = design(te, predictors, levels, means, sds)
        b, *_ = np.linalg.lstsq(Xtr, tr.q5_minus_q1.to_numpy(float), rcond=None)
        pred = Xte @ b
        obs = te.q5_minus_q1.to_numpy(float)
        for i, rr in enumerate(te.itertuples(index=False)):
            rows.append({"heldout_year": int(yr), "window": str(rr.window), "observed": float(obs[i]), "predicted": float(pred[i]), "error": float(obs[i]-pred[i])})
    return pd.DataFrame(rows)


def cv_metrics(cv: pd.DataFrame):
    if cv.empty:
        return np.nan, np.nan
    e = cv.error.to_numpy(float)
    return float(np.sqrt(np.mean(e*e))), float(np.mean(np.abs(e)))


def year_metrics(cv: pd.DataFrame):
    rows = []
    if cv.empty:
        return pd.DataFrame()
    for yr, g in cv.groupby("heldout_year", sort=True):
        e = g.error.to_numpy(float)
        rows.append({"heldout_year": int(yr), "n_test": len(g), "rmse": float(np.sqrt(np.mean(e*e))), "mae": float(np.mean(np.abs(e)))})
    return pd.DataFrame(rows)


def evaluate(data: pd.DataFrame, scope: str, qa: float):
    x = data[data.qa_good_field_share_pct >= qa].copy()
    if scope == "W2_W4_only":
        x = x[x.window != "W1_early_april"].copy()
    needed = ["q5_minus_q1", "year", "window", "gdd5_mar01", "date_offset_days"]
    for h in HORIZONS:
        needed += [f"precip_{h}d_mm", f"tmean_{h}d_c"]
    x = x.dropna(subset=needed).copy()
    levels = sorted(x.window.astype(str).unique())
    if len(x) < 10 or len(levels) < 2:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    metrics, coefs, cvs, yearframes = [], [], [], []

    for spec in ordinary_specs():
        model = spec["model"]
        coef, r2, adj, k, cond = fit_full(x, spec["predictors"], levels)
        cv = loyo_ordinary(x, spec["predictors"], levels)
        rmse, mae = cv_metrics(cv)
        metrics.append({"scope": scope, "qa_threshold_pct": qa, "model": model, "horizon_days": spec["horizon"], "comparison_baseline": spec["baseline"], "n": len(x), "years": x.year.nunique(), "windows": len(levels), "k": k, "r2_in_sample": r2, "adj_r2_in_sample": adj, "loyo_rmse": rmse, "loyo_mae": mae, "design_condition_number": cond, "tresid_corr_gdd": np.nan, "tresid_corr_offset": np.nan})
        coef.insert(0, "horizon_days", spec["horizon"]); coef.insert(0, "model", model); coef.insert(0, "qa_threshold_pct", qa); coef.insert(0, "scope", scope)
        coefs.append(coef)
        if not cv.empty:
            cv.insert(0, "horizon_days", spec["horizon"]); cv.insert(0, "model", model); cv.insert(0, "qa_threshold_pct", qa); cv.insert(0, "scope", scope)
            cvs.append(cv)
            ym = year_metrics(cv)
            ym.insert(0, "model", model); ym.insert(0, "qa_threshold_pct", qa); ym.insert(0, "scope", scope)
            yearframes.append(ym)

    for h in HORIZONS:
        for include_precip in (False, True):
            model = ("BGPTR" if include_precip else "BGTR") + str(h)
            baseline = "BG" if not include_precip else f"BGP{h}"
            coef, r2, adj, k, cond, cg, co = fit_orthogonalized_full(x, h, include_precip, levels)
            cv = loyo_orthogonalized(x, h, include_precip, levels)
            rmse, mae = cv_metrics(cv)
            metrics.append({"scope": scope, "qa_threshold_pct": qa, "model": model, "horizon_days": h, "comparison_baseline": baseline, "n": len(x), "years": x.year.nunique(), "windows": len(levels), "k": k, "r2_in_sample": r2, "adj_r2_in_sample": adj, "loyo_rmse": rmse, "loyo_mae": mae, "design_condition_number": cond, "tresid_corr_gdd": cg, "tresid_corr_offset": co})
            coef.insert(0, "horizon_days", h); coef.insert(0, "model", model); coef.insert(0, "qa_threshold_pct", qa); coef.insert(0, "scope", scope)
            coefs.append(coef)
            if not cv.empty:
                cv.insert(0, "horizon_days", h); cv.insert(0, "model", model); cv.insert(0, "qa_threshold_pct", qa); cv.insert(0, "scope", scope)
                cvs.append(cv)
                ym = year_metrics(cv)
                ym.insert(0, "model", model); ym.insert(0, "qa_threshold_pct", qa); ym.insert(0, "scope", scope)
                yearframes.append(ym)

    met = pd.DataFrame(metrics)
    lookup = met.set_index("model")
    met["delta_loyo_rmse_vs_baseline"] = np.nan
    met["loyo_improvement_vs_baseline_pct"] = np.nan
    for i, r in met.iterrows():
        if r.comparison_baseline not in lookup.index:
            continue
        b = lookup.loc[r.comparison_baseline]
        if pd.notna(r.loyo_rmse) and pd.notna(b.loyo_rmse) and float(b.loyo_rmse) > 0:
            met.loc[i, "delta_loyo_rmse_vs_baseline"] = float(r.loyo_rmse - b.loyo_rmse)
            met.loc[i, "loyo_improvement_vs_baseline_pct"] = 100.0 * float(b.loyo_rmse-r.loyo_rmse)/float(b.loyo_rmse)

    coefdf = pd.concat(coefs, ignore_index=True)
    cvdf = pd.concat(cvs, ignore_index=True) if cvs else pd.DataFrame()
    ydf = pd.concat(yearframes, ignore_index=True) if yearframes else pd.DataFrame()

    comparisons = []
    if not ydf.empty:
        bg = ydf[ydf.model.eq("BG")]
        for model in [f"BGP{h}" for h in HORIZONS] + [f"BGPT{h}" for h in HORIZONS]:
            mm = ydf[ydf.model.eq(model)]
            j = mm.merge(bg, on=["heldout_year", "qa_threshold_pct", "scope"], suffixes=("_model", "_bg"))
            for rr in j.itertuples(index=False):
                comparisons.append({"scope": scope, "qa_threshold_pct": qa, "model": model, "heldout_year": int(rr.heldout_year), "n_test": int(rr.n_test_model), "model_rmse": float(rr.rmse_model), "bg_rmse": float(rr.rmse_bg), "delta_rmse": float(rr.rmse_model-rr.rmse_bg), "improved": bool(rr.rmse_model < rr.rmse_bg)})
    return met, coefdf, cvdf, pd.DataFrame(comparisons)


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
        thresholds = sorted(set(thresholds + [float(args.primary_qa)]))

    cfg = load_config(ROOT / args.config)
    outdir = ROOT / cfg.get("build_dir", "data/derived") / "satellite_poc"
    outdir.mkdir(parents=True, exist_ok=True)
    data = load_data(outdir, args.year_start, args.year_end, args.min_gdd_coverage)

    print("=" * 132)
    print("ÅkerSync · Satellite V1a · STEP 31 PRECIPITATION ISOLATION + ORTHOGONALIZED TEMPERATURE")
    print("=" * 132)
    print(f"Input year×window: {len(data)} | År {args.year_start}–{args.year_end}")
    print("Ingen satellit- eller väderhämtning: endast befintliga lokala CSV-filer används.")
    print("Bas: BG = window + GDD5 + exakt datumoffset. Test: P/T/PT 14/30/45 d + orthogonalized T.")

    mets, coefs, cvs, cmps = [], [], [], []
    for qa in thresholds:
        for scope in ("all_windows", "W2_W4_only"):
            m, c, v, y = evaluate(data, scope, qa)
            if not m.empty: mets.append(m)
            if not c.empty: coefs.append(c)
            if not v.empty: cvs.append(v)
            if not y.empty: cmps.append(y)

    metrics = pd.concat(mets, ignore_index=True) if mets else pd.DataFrame()
    coefdf = pd.concat(coefs, ignore_index=True) if coefs else pd.DataFrame()
    cvdf = pd.concat(cvs, ignore_index=True) if cvs else pd.DataFrame()
    cmpdf = pd.concat(cmps, ignore_index=True) if cmps else pd.DataFrame()
    if metrics.empty:
        raise RuntimeError("Inga modeller kunde skattas")

    stem = f"lomma_precipitation_isolation_{args.year_start}_{args.year_end}"
    data_csv = outdir / f"{stem}_analysis_table.csv"
    met_csv = outdir / f"{stem}_metrics.csv"
    coef_csv = outdir / f"{stem}_coefficients.csv"
    cv_csv = outdir / f"{stem}_loyo_predictions.csv"
    cmp_csv = outdir / f"{stem}_yearwise_comparison.csv"
    summary_txt = outdir / f"{stem}_summary.txt"
    data.to_csv(data_csv, index=False, encoding="utf-8-sig", date_format="%Y-%m-%d")
    metrics.to_csv(met_csv, index=False, encoding="utf-8-sig")
    coefdf.to_csv(coef_csv, index=False, encoding="utf-8-sig")
    cvdf.to_csv(cv_csv, index=False, encoding="utf-8-sig")
    cmpdf.to_csv(cmp_csv, index=False, encoding="utf-8-sig")

    primary = metrics[(metrics.scope.eq("W2_W4_only")) & (metrics.qa_threshold_pct.eq(args.primary_qa))].copy()
    primary = primary.sort_values("loyo_rmse")

    print("\n" + "=" * 132)
    print("STEP 31 PRECIPITATION ISOLATION KLAR")
    print("=" * 132)
    print(f"\nPRIMARY · W2-W4 · QA >= {args.primary_qa:g}%")
    bg = primary[primary.model.eq("BG")]
    bg_rmse = float(bg.iloc[0].loyo_rmse) if not bg.empty else np.nan
    for r in primary.itertuples(index=False):
        imp_bg = 100.0*(bg_rmse-float(r.loyo_rmse))/bg_rmse if np.isfinite(bg_rmse) and bg_rmse > 0 else np.nan
        print(f"  {r.model:8s} | n={int(r.n):2d} | R2 {r.r2_in_sample:.3f} | LOYO RMSE {r.loyo_rmse:.4f} | vs BG {imp_bg:+5.1f}% | cond {r.design_condition_number:.1f}")

    print("\nP / T / PT per horisont · W2-W4 primary:")
    for h in HORIZONS:
        vals = []
        for name in (f"BGP{h}", f"BGT{h}", f"BGPT{h}"):
            z = primary[primary.model.eq(name)]
            if z.empty:
                continue
            r = z.iloc[0]
            imp = 100.0*(bg_rmse-float(r.loyo_rmse))/bg_rmse if np.isfinite(bg_rmse) and bg_rmse > 0 else np.nan
            vals.append(f"{name} {r.loyo_rmse:.4f} ({imp:+.1f}%)")
        print(f"  {h:2d} d | " + " | ".join(vals))

    print("\nOrthogonalized temperature · incremental beyond BG or BGP:")
    for h in HORIZONS:
        for name in (f"BGTR{h}", f"BGPTR{h}"):
            z = primary[primary.model.eq(name)]
            if z.empty:
                continue
            r = z.iloc[0]
            print(f"  {name:8s} | RMSE {r.loyo_rmse:.4f} | vs {r.comparison_baseline} {r.loyo_improvement_vs_baseline_pct:+.1f}% | corr(resT,GDD) {r.tresid_corr_gdd:+.3f} | corr(resT,offset) {r.tresid_corr_offset:+.3f} | cond {r.design_condition_number:.1f}")

    print("\nQA sensitivity · precipitation alone beyond BG (W2-W4):")
    for qa in thresholds:
        q = metrics[(metrics.scope.eq("W2_W4_only")) & (metrics.qa_threshold_pct.eq(qa)) & (metrics.model.str.startswith("BGP")) & (~metrics.model.str.startswith("BGPT")) & (~metrics.model.str.startswith("BGPTR"))].copy()
        if q.empty:
            continue
        best = q.loc[q.loyo_rmse.idxmin()]
        print(f"  QA>={qa:4.0f}% | {best.model:5s} | RMSE {best.loyo_rmse:.4f} | improvement vs BG {best.loyo_improvement_vs_baseline_pct:+.1f}%")

    pmods = primary[primary.model.isin([f"BGP{h}" for h in HORIZONS])].copy()
    if not pmods.empty:
        bestp = pmods.loc[pmods.loyo_rmse.idxmin()]
        print(f"\nYear-by-year · bästa precipitation-only model {bestp.model} vs BG:")
        y = cmpdf[(cmpdf.scope.eq("W2_W4_only")) & (cmpdf.qa_threshold_pct.eq(args.primary_qa)) & (cmpdf.model.eq(bestp.model))].sort_values("heldout_year")
        better = 0
        for r in y.itertuples(index=False):
            flag = "BETTER" if r.improved else "worse"
            better += int(r.improved)
            print(f"  {int(r.heldout_year)} | {bestp.model} {r.model_rmse:.4f} vs BG {r.bg_rmse:.4f} | delta {r.delta_rmse:+.4f} | {flag} | n={int(r.n_test)}")
        print(f"  => bättre i {better}/{len(y)} år")

    lines = [
        "ÅkerSync Satellite V1a — Step 31 precipitation isolation",
        f"Years: {args.year_start}–{args.year_end}",
        "Baseline BG = window + GDD5(Mar1→date-1) + exact within-window date offset.",
        "LOYO uses whole held-out years and training-only standardization/residualization.",
        "Orthogonalized T is residual from T ~ window + GDD5 + date offset.",
        "Observational/descriptive only; regional precipitation is not field water balance.",
        "",
        "PRIMARY W2-W4 QA>=50:",
    ]
    for r in primary.itertuples(index=False):
        lines.append(f"  {r.model:8s} | n={int(r.n)} | R2={r.r2_in_sample:.4f} | LOYO_RMSE={r.loyo_rmse:.5f} | condition={r.design_condition_number:.2f}")
    summary_txt.write_text("\n".join(lines)+"\n", encoding="utf-8")

    print("\nOutput:")
    for p in (data_csv, met_csv, coef_csv, cv_csv, cmp_csv, summary_txt):
        print(" ", p)
    print("\nSTEP 31: OK")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
