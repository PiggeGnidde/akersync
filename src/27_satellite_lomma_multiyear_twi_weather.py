#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerSync Satellite V1a — all-year TWI↔NDVI weather experiment, 2018..2026.

This is the scale-up after the controlled 2018/2023/2025 experiment.

Main differences from step 26
-----------------------------
1) All years 2018..2026 are analysed.
2) Catalogue cloud is only a ranking proxy. For each seasonal window the script
   tries up to N candidate Sentinel dates in catalogue-cloud order and accepts
   the first date where enough Lomma fields have good pixel-level SCL coverage.
3) Weather is attached to the *actual accepted satellite date*: precipitation
   totals and mean temperature over the preceding 14/30/45 days.
4) A small descriptive weather-response model is fitted to year×window Q5-Q1
   using 30-day weather plus seasonal-window fixed effects. This is exploratory,
   not causal inference.

Historical caveat
-----------------
2025 skifte polygons are fixed physical sampling footprints for all years. That
keeps spatial sampling comparable, but historical field/crop boundaries may
have differed. Do not interpret this as historical administrative truth.
"""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from common import load_config

ROOT = Path(__file__).resolve().parents[1]
MUN_CODE = "1262"
WINDOWS = [
    ("W1_early_april", "04-01", "04-15"),
    ("W2_late_may", "05-15", "05-31"),
    ("W3_late_june", "06-15", "06-30"),
    ("W4_early_july", "07-01", "07-15"),
]
ROLE_MAP = {
    "dry_hot_relative": "dry_hot",
    "middle_relative": "middle",
    "wet_cool_relative": "wet_cool",
}


def load_module(filename: str, name: str):
    path = ROOT / "src" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Kunde inte ladda {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def build_lomma(cfg: dict) -> gpd.GeoDataFrame:
    blocks = gpd.read_file(cfg["blocks"]).to_crs(3006)
    skiften = gpd.read_file(cfg["skiften"]).to_crs(3006)
    lb = blocks[blocks.region_kod.astype(str).str.startswith(MUN_CODE)].copy()
    ls = skiften[skiften.blockid.astype(str).isin(lb.blockid.astype(str))].copy()
    if ls.empty:
        raise RuntimeError("Hittade inga Lomma-skiften")
    return ls


def collapse_daily(obs: pd.DataFrame) -> pd.DataFrame:
    return (
        obs.groupby("date", as_index=False)
        .agg(
            item_count=("item_id", "count"),
            min_cloud_pct=("cloud_cover_pct", "min"),
            mean_cloud_pct=("cloud_cover_pct", "mean"),
            max_cloud_pct=("cloud_cover_pct", "max"),
        )
        .sort_values("date")
        .reset_index(drop=True)
    )


def candidates_for_window(daily: pd.DataFrame, year: int, md0: str, md1: str) -> pd.DataFrame:
    a = pd.Timestamp(f"{year}-{md0}")
    b = pd.Timestamp(f"{year}-{md1}")
    x = daily[(daily.date >= a) & (daily.date <= b)].copy()
    if x.empty:
        return x
    x["rank_max"] = x.max_cloud_pct.fillna(999.0)
    x["rank_mean"] = x.mean_cloud_pct.fillna(999.0)
    x["rank_min"] = x.min_cloud_pct.fillna(999.0)
    return x.sort_values(["rank_max", "rank_mean", "rank_min", "date"]).reset_index(drop=True)


def field_coverage_qa(ts20, tif: Path, lomma_skiften: gpd.GeoDataFrame,
                      min_field_coverage: float, min_pixels: int):
    df = ts20.stats_for_date(tif, lomma_skiften, tif.stem[-8:])
    if df.empty:
        return 0, 0.0, np.nan
    good = (
        (pd.to_numeric(df.valid_pixels, errors="coerce") >= min_pixels)
        & (pd.to_numeric(df.coverage_pct, errors="coerce") >= min_field_coverage)
        & pd.to_numeric(df.ndvi_mean, errors="coerce").notna()
    )
    n = int(good.sum())
    share = 100.0 * n / max(1, len(lomma_skiften))
    med_cov = float(pd.to_numeric(df.loc[good, "coverage_pct"], errors="coerce").median()) if n else np.nan
    return n, share, med_cov


def weather_features(daily: pd.DataFrame, date: pd.Timestamp) -> dict:
    d = pd.Timestamp(date).normalize()
    out = {}
    for days in (14, 30, 45):
        a = d - pd.Timedelta(days=days)
        b = d - pd.Timedelta(days=1)
        x = daily[(daily.date >= a) & (daily.date <= b)].copy()
        expected = days
        pcov = 100.0 * x.precip_mm.notna().sum() / expected if expected else np.nan
        tcov = 100.0 * x.tmean_c.notna().sum() / expected if expected else np.nan
        p = x.precip_mm.sum(min_count=max(1, int(np.ceil(0.8 * expected))))
        t = x.tmean_c.mean() if tcov >= 80.0 else np.nan
        if pcov < 80.0:
            p = np.nan
        out[f"precip_{days}d_mm"] = float(p) if pd.notna(p) else np.nan
        out[f"tmean_{days}d_c"] = float(t) if pd.notna(t) else np.nan
        out[f"precip_{days}d_coverage_pct"] = float(pcov)
        out[f"temp_{days}d_coverage_pct"] = float(tcov)
    out["day_of_year"] = int(d.dayofyear)
    return out


def add_weather_to_plan(plan: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for r in plan.itertuples(index=False):
        rec = r._asdict()
        rec.update(weather_features(daily, pd.Timestamp(r.selected_date)))
        rows.append(rec)
    return pd.DataFrame(rows)


def fit_fixed_effect_model(df: pd.DataFrame, model_name: str, late_only: bool = False):
    x = df.copy()
    if late_only:
        x = x[x.window != "W1_early_april"].copy()
    needed = ["q5_minus_q1", "precip_30d_mm", "tmean_30d_c", "window", "year"]
    x = x.dropna(subset=needed).copy()
    if len(x) < 10:
        return pd.DataFrame(), {"model": model_name, "n": len(x), "r2": np.nan, "loyo_rmse": np.nan, "loyo_mae": np.nan}

    p_mean, p_sd = x.precip_30d_mm.mean(), x.precip_30d_mm.std(ddof=0)
    t_mean, t_sd = x.tmean_30d_c.mean(), x.tmean_30d_c.std(ddof=0)
    if p_sd <= 1e-12 or t_sd <= 1e-12:
        return pd.DataFrame(), {"model": model_name, "n": len(x), "r2": np.nan, "loyo_rmse": np.nan, "loyo_mae": np.nan}

    windows = [w for w in sorted(x.window.unique()) if w != "W1_early_april"]

    def design(frame: pd.DataFrame, pm=p_mean, ps=p_sd, tm=t_mean, ts=t_sd):
        cols = [np.ones(len(frame)), (frame.precip_30d_mm.to_numpy(float) - pm) / ps,
                (frame.tmean_30d_c.to_numpy(float) - tm) / ts]
        names = ["intercept", "precip30_z", "tmean30_z"]
        for w in windows:
            cols.append((frame.window.astype(str).to_numpy() == w).astype(float))
            names.append(f"window_{w}")
        return np.column_stack(cols), names

    X, names = design(x)
    y = x.q5_minus_q1.to_numpy(float)
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    pred = X @ beta
    sse = float(np.sum((y - pred) ** 2))
    sst = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - sse / sst if sst > 0 else np.nan

    # Leave-one-year-out prediction: weather standardization and coefficients are
    # re-estimated on each training fold; window dummy structure is kept fixed.
    errs = []
    for yr in sorted(x.year.unique()):
        train = x[x.year != yr].copy()
        test = x[x.year == yr].copy()
        if len(train) < 8 or test.empty:
            continue
        pm, ps = train.precip_30d_mm.mean(), train.precip_30d_mm.std(ddof=0)
        tm, ts = train.tmean_30d_c.mean(), train.tmean_30d_c.std(ddof=0)
        if ps <= 1e-12 or ts <= 1e-12:
            continue
        Xtr, _ = design(train, pm, ps, tm, ts)
        Xte, _ = design(test, pm, ps, tm, ts)
        b, *_ = np.linalg.lstsq(Xtr, train.q5_minus_q1.to_numpy(float), rcond=None)
        errs.extend((test.q5_minus_q1.to_numpy(float) - Xte @ b).tolist())
    errs = np.asarray(errs, dtype=float)
    loyo_rmse = float(np.sqrt(np.mean(errs ** 2))) if errs.size else np.nan
    loyo_mae = float(np.mean(np.abs(errs))) if errs.size else np.nan

    coef = pd.DataFrame({
        "model": model_name,
        "term": names,
        "coefficient": beta,
        "n_observations": len(x),
        "r2_in_sample": r2,
        "loyo_rmse": loyo_rmse,
        "loyo_mae": loyo_mae,
        "precip30_mean_mm": p_mean,
        "precip30_sd_mm": p_sd,
        "tmean30_mean_c": t_mean,
        "tmean30_sd_c": t_sd,
    })
    summary = {"model": model_name, "n": len(x), "r2": r2, "loyo_rmse": loyo_rmse, "loyo_mae": loyo_mae}
    return coef, summary


def window_centered_spearman(df: pd.DataFrame):
    x = df.dropna(subset=["q5_minus_q1", "precip_30d_mm", "tmean_30d_c", "window"]).copy()
    if len(x) < 8:
        return np.nan, np.nan, len(x)
    for c in ["q5_minus_q1", "precip_30d_mm", "tmean_30d_c"]:
        x[c + "_wc"] = x[c] - x.groupby("window")[c].transform("mean")
    rp = spearmanr(x.q5_minus_q1_wc, x.precip_30d_mm_wc, nan_policy="omit").statistic
    rt = spearmanr(x.q5_minus_q1_wc, x.tmean_30d_c_wc, nan_policy="omit").statistic
    return float(rp), float(rt), len(x)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/local_paths.json")
    ap.add_argument("--year-start", type=int, default=2018)
    ap.add_argument("--year-end", type=int, default=2026)
    ap.add_argument("--max-candidates", type=int, default=5)
    ap.add_argument("--min-usable-field-share", type=float, default=50.0,
                    help="Hard date QA: percent of all Lomma skiften with >= min-field-coverage after SCL mask")
    ap.add_argument("--min-field-coverage", type=float, default=70.0)
    ap.add_argument("--edge-buffer-m", type=float, default=10.0)
    ap.add_argument("--min-pixels", type=int, default=25)
    ap.add_argument("--min-zone-pixels", type=int, default=3)
    ap.add_argument("--bootstrap", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=270817)
    args = ap.parse_args()

    cfg = load_config(ROOT / args.config)
    outdir = ROOT / cfg.get("build_dir", "data/derived") / "satellite_poc"
    outdir.mkdir(parents=True, exist_ok=True)

    ts20 = load_module("20_satellite_lomma_timeseries.py", "akersync_ts20_all27")
    s22 = load_module("22_satellite_lomma_twi_ndvi.py", "akersync_twi22_all27")
    s23 = load_module("23_satellite_lomma_twi_response_curve.py", "akersync_twi23_all27")
    s26 = load_module("26_satellite_lomma_historical_twi_experiment.py", "akersync_hist26_all27")

    lomma = build_lomma(cfg)
    spatial = s26.make_spatial(lomma)
    twi_path = s22.find_twi(cfg, outdir)

    weather_year_path = outdir / f"lomma_weather_{args.year_start}_{args.year_end}_year_classification.csv"
    weather_daily_path = outdir / f"lomma_weather_{args.year_start}_{args.year_end}_daily.csv"
    if not weather_year_path.exists() or not weather_daily_path.exists():
        raise FileNotFoundError("Saknar SMHI-väderoutput. Kör SATELLITE_LOMMA_WEATHER_CLASSIFICATION.bat först.")
    wy = pd.read_csv(weather_year_path)
    wd = pd.read_csv(weather_daily_path)
    wd["date"] = pd.to_datetime(wd.date, errors="coerce")
    wy["year"] = wy.year.astype(int)

    print("=" * 132)
    print("ÅkerSync · Satellite V1a · ALL-YEAR TWI × WEATHER EXPERIMENT")
    print("=" * 132)
    print(f"År: {args.year_start}–{args.year_end} | Lomma-skiften: {len(lomma):,}")
    print(f"SCL hard QA: minst {args.min_usable_field_share:.0f}% av skiftena ska ha >= {args.min_field_coverage:.0f}% pixelcoverage")
    print(f"Max kandidatdatum per år×fönster: {args.max_candidates}")
    print("Befintliga NDVI-TIFF:ar återanvänds; bara saknade kandidatdatum blir openEO-jobb.")
    print("TWI:", twi_path)

    import openeo
    con = openeo.connect(ts20.BACKEND).authenticate_oidc()
    print("Authenticated/openEO: OK")

    candidate_audit = []
    selected_rows = []
    tif_paths = {}

    for year in range(args.year_start, args.year_end + 1):
        print(f"\n[{year}] STAC 04-01 — 07-15")
        obs = ts20.catalogue_dates(spatial["west"], spatial["south"], spatial["east"], spatial["north"],
                                   f"{year}-04-01", f"{year}-07-15")
        daily = collapse_daily(obs)
        wx = wy[wy.year.eq(year)]
        weather_class = str(wx.weather_class.iloc[0]) if (not wx.empty and "weather_class" in wx) else ""
        role = ROLE_MAP.get(weather_class, weather_class or "year")
        hydro = float(wx.hydroclimate_score.iloc[0]) if (not wx.empty and "hydroclimate_score" in wx and pd.notna(wx.hydroclimate_score.iloc[0])) else np.nan
        pjun = float(wx.precip_jun01_jul15_mm.iloc[0]) if (not wx.empty and "precip_jun01_jul15_mm" in wx and pd.notna(wx.precip_jun01_jul15_mm.iloc[0])) else np.nan
        tjun = float(wx.tmean_jun01_jul15_c.iloc[0]) if (not wx.empty and "tmean_jun01_jul15_c" in wx and pd.notna(wx.tmean_jun01_jul15_c.iloc[0])) else np.nan

        for window, md0, md1 in WINDOWS:
            cand = candidates_for_window(daily, year, md0, md1)
            print(f"  {window}: {len(cand)} katalogdatum")
            accepted = None
            best_attempt = None
            for rank, cr in enumerate(cand.head(args.max_candidates).itertuples(index=False), 1):
                d = pd.Timestamp(cr.date)
                date0 = d.strftime("%Y-%m-%d")
                tif = outdir / f"lomma_ndvi_{d.strftime('%Y%m%d')}.tif"
                print(f"    kandidat {rank}: {date0} | max-moln {float(cr.max_cloud_pct):5.1f}%", end="")
                err = ""
                try:
                    ts20.download_ndvi(con, spatial, date0, tif)
                    if not tif.exists() or tif.stat().st_size < 10_000:
                        raise RuntimeError("TIFF saknas/för liten")
                    n_good, share, med_cov = field_coverage_qa(ts20, tif, lomma, args.min_field_coverage, args.min_pixels)
                    passed = bool(share >= args.min_usable_field_share)
                    print(f" -> SCL field-QA {n_good}/{len(lomma)} = {share:.1f}% | {'PASS' if passed else 'reject'}")
                except Exception as e:
                    n_good, share, med_cov, passed = 0, 0.0, np.nan, False
                    err = f"{type(e).__name__}: {e}"
                    print(f" -> FEL: {err[:180]}")

                audit = {
                    "year": year, "weather_role": role, "window": window,
                    "candidate_rank": rank, "candidate_date": date0,
                    "item_count": int(cr.item_count),
                    "min_cloud_pct": float(cr.min_cloud_pct),
                    "mean_cloud_pct": float(cr.mean_cloud_pct),
                    "max_cloud_pct": float(cr.max_cloud_pct),
                    "qa_good_fields": n_good, "qa_good_field_share_pct": share,
                    "qa_median_coverage_pct": med_cov, "qa_pass": passed,
                    "error": err,
                }
                candidate_audit.append(audit)
                if best_attempt is None or share > best_attempt[0]:
                    best_attempt = (share, audit, tif)
                if passed:
                    accepted = (audit, tif, cr)
                    break

            if accepted is None:
                besttxt = "inga kandidater" if best_attempt is None else f"bäst {best_attempt[0]:.1f}%"
                print(f"    VARNING: {year} {window} saknar datum som klarar hard QA ({besttxt}); fönstret exkluderas.")
                continue

            audit, tif, cr = accepted
            d = pd.Timestamp(audit["candidate_date"])
            selected_rows.append({
                "year": year,
                "weather_role": role,
                "weather_class": weather_class,
                "hydroclimate_score": hydro,
                "precip_jun01_jul15_mm": pjun,
                "tmean_jun01_jul15_c": tjun,
                "window": window,
                "selected_date": d,
                "item_count": audit["item_count"],
                "min_cloud_pct": audit["min_cloud_pct"],
                "mean_cloud_pct": audit["mean_cloud_pct"],
                "max_cloud_pct": audit["max_cloud_pct"],
                "good_catalog_cloud": bool(audit["max_cloud_pct"] <= 40.0),
                "candidate_rank_used": audit["candidate_rank"],
                "qa_good_fields": audit["qa_good_fields"],
                "qa_good_field_share_pct": audit["qa_good_field_share_pct"],
                "qa_median_coverage_pct": audit["qa_median_coverage_pct"],
            })
            tif_paths[(year, window, d.strftime("%Y-%m-%d"))] = tif

    audit_df = pd.DataFrame(candidate_audit)
    plan = pd.DataFrame(selected_rows)
    if plan.empty:
        raise RuntimeError("Inga år×fönster klarade SCL hard QA")
    plan = plan.sort_values(["year", "selected_date"]).reset_index(drop=True)
    plan = add_weather_to_plan(plan, wd)

    print("\nAccepted plan:")
    for r in plan.itertuples(index=False):
        print(f"  {int(r.year)} {r.weather_role:8s} | {r.window:15s} | {pd.Timestamp(r.selected_date).date()} | "
              f"rank {int(r.candidate_rank_used)} | QA {r.qa_good_field_share_pct:5.1f}% | P30 {r.precip_30d_mm:6.1f} | T30 {r.tmean_30d_c:5.2f}")

    field_date = s26.analyse(
        plan, tif_paths, lomma, twi_path, s22,
        args.edge_buffer_m, args.min_pixels, args.min_zone_pixels, args.min_field_coverage,
    )
    by_window, field_year, by_year = s26.aggregate_results(field_date, s23, args.bootstrap, args.seed)

    weather_cols = [c for c in plan.columns if c.startswith("precip_") or c.startswith("tmean_") or c.endswith("coverage_pct") or c == "day_of_year"]
    plan_join = plan[["year", "window", "selected_date"] + weather_cols + ["candidate_rank_used", "qa_good_field_share_pct"]].copy()
    plan_join["date"] = plan_join.selected_date.dt.strftime("%Y-%m-%d")
    by_window["date"] = by_window.date.astype(str)
    by_window = by_window.merge(plan_join.drop(columns="selected_date"), on=["year", "window", "date"], how="left")

    coef1, ms1 = fit_fixed_effect_model(by_window, "all_windows", late_only=False)
    coef2, ms2 = fit_fixed_effect_model(by_window, "W2_W4_only", late_only=True)
    model_df = pd.concat([coef1, coef2], ignore_index=True) if (not coef1.empty or not coef2.empty) else pd.DataFrame()
    rho_p, rho_t, rho_n = window_centered_spearman(by_window)

    stem = f"lomma_multiyear_twi_weather_{args.year_start}_{args.year_end}"
    audit_csv = outdir / f"{stem}_candidate_audit.csv"
    plan_csv = outdir / f"{stem}_selected_plan.csv"
    fd_csv = outdir / f"{stem}_field_date_quintiles.csv"
    fy_csv = outdir / f"{stem}_field_year.csv"
    yw_csv = outdir / f"{stem}_year_window_curve.csv"
    yy_csv = outdir / f"{stem}_year_curve.csv"
    model_csv = outdir / f"{stem}_weather_model.csv"
    summary_txt = outdir / f"{stem}_summary.txt"

    audit_df.to_csv(audit_csv, index=False, encoding="utf-8-sig")
    plan.to_csv(plan_csv, index=False, encoding="utf-8-sig", date_format="%Y-%m-%d")
    field_date.to_csv(fd_csv, index=False, encoding="utf-8-sig")
    field_year.to_csv(fy_csv, index=False, encoding="utf-8-sig")
    by_window.to_csv(yw_csv, index=False, encoding="utf-8-sig")
    by_year.to_csv(yy_csv, index=False, encoding="utf-8-sig")
    model_df.to_csv(model_csv, index=False, encoding="utf-8-sig")

    lines = [
        "ÅkerSync Satellite V1a — all-year TWI × weather experiment",
        f"Years: {args.year_start}–{args.year_end}",
        f"Accepted year-window observations: {len(plan)} / {(args.year_end-args.year_start+1)*4}",
        f"SCL hard QA: >= {args.min_usable_field_share:.1f}% fields with >= {args.min_field_coverage:.1f}% coverage",
        "",
        "YEAR × WINDOW:",
    ]
    for r in by_window.sort_values(["year", "date"]).itertuples(index=False):
        lines.append(
            f"  {int(r.year)} {r.window:15s} {r.date} | n={int(r.fields):3d} | Q5-Q1 {r.q5_minus_q1:+.4f} | "
            f"slope {r.linear_slope_per_quintile:+.4f} | P30 {r.precip_30d_mm:6.1f} mm | T30 {r.tmean_30d_c:5.2f} C | "
            f"QA {r.qa_good_field_share_pct:5.1f}%"
        )
    lines += ["", "DESCRIPTIVE WEATHER RESPONSE:"]
    for ms in (ms1, ms2):
        lines.append(f"  {ms['model']}: n={ms['n']} | R2={ms['r2']:.3f} | LOYO RMSE={ms['loyo_rmse']:.4f} | LOYO MAE={ms['loyo_mae']:.4f}")
    lines.append(f"  Window-centered Spearman: Q5-Q1 vs P30 rho={rho_p:+.3f}; vs T30 rho={rho_t:+.3f}; n={rho_n}")
    lines += [
        "",
        "GUARDRAILS:",
        "  Weather model is descriptive/exploratory, not causal inference.",
        "  SCL pixel QA, not catalogue cloud percentage, decides whether a date is accepted.",
        "  Compare same seasonal windows first; phenology/crop composition can differ across years.",
        "  2025 skifte footprints are fixed geographic sampling areas, not historical boundary truth.",
    ]
    summary_txt.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n" + "=" * 132)
    print("ALL-YEAR TWI × WEATHER EXPERIMENT KLAR")
    print("=" * 132)
    print(f"Accepted windows: {len(plan)} / {(args.year_end-args.year_start+1)*4}")
    print("\nÅr × fönster:")
    for r in by_window.sort_values(["year", "date"]).itertuples(index=False):
        print(f"  {int(r.year)} {r.window:15s} | {r.date} | n={int(r.fields):3d} | Q5-Q1 {r.q5_minus_q1:+.4f} | "
              f"P30 {r.precip_30d_mm:6.1f} | T30 {r.tmean_30d_c:5.2f} | QA {r.qa_good_field_share_pct:5.1f}%")
    print("\nDeskriptiv vädermodell:")
    for ms in (ms1, ms2):
        print(f"  {ms['model']:12s} | n={ms['n']:2d} | R2 {ms['r2']:.3f} | LOYO RMSE {ms['loyo_rmse']:.4f} | MAE {ms['loyo_mae']:.4f}")
    print(f"  window-centered Spearman: P30 rho {rho_p:+.3f} | T30 rho {rho_t:+.3f} | n={rho_n}")
    if not model_df.empty:
        for model in model_df.model.unique():
            m = model_df[model_df.model.eq(model)]
            bp = m.loc[m.term.eq("precip30_z"), "coefficient"]
            bt = m.loc[m.term.eq("tmean30_z"), "coefficient"]
            if len(bp) and len(bt):
                print(f"  {model}: beta(P30_z) {float(bp.iloc[0]):+.4f} | beta(T30_z) {float(bt.iloc[0]):+.4f}")

    print("\nOutput:")
    for p in (audit_csv, plan_csv, fd_csv, fy_csv, yw_csv, yy_csv, model_csv, summary_txt):
        print(" ", p)
    print("\nOBS: hard SCL-QA + kontinuerligt väder är huvudpoängen; ingen dräneringskausalitet antas.")
    print("SATELLITE LOMMA MULTIYEAR TWI WEATHER: OK")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
