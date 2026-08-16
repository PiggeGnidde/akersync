#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerSync Satellite V1a — dense late-season NDVI series + harvest-event candidates.

This is deliberately NOT a crop/harvest classifier yet.

Goal
----
Resolve the July-August transition more densely than the 14-day seasonal series,
and estimate a *late-season structural break* per skifte while separating it from
smooth senescence as far as possible with a simple transparent model.

For every field with enough valid observations we compare:

    M0: NDVI(t) = a + b*t

against piecewise step models

    M1(tau): NDVI(t) = a + b*t + c*I(t >= tau)

where c < 0 is an abrupt negative level shift after accounting for a smooth
linear late-season trend.  tau is searched over admissible observation breaks.
The result is a candidate interval, not proof of harvest.

The optional visual first-combine date is used ONLY for external QA reporting;
it never enters model fitting or candidate selection.

Implementation reuses the already validated Sentinel-2/openEO, SCL masking and
per-skifte zonal-statistics functions from 20_satellite_lomma_timeseries.py.
"""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box

from common import load_config

ROOT = Path(__file__).resolve().parents[1]
MUN_CODE = "1262"


def load_ts_module():
    path = ROOT / "src" / "20_satellite_lomma_timeseries.py"
    spec = importlib.util.spec_from_file_location("akersync_sat_ts20", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Kunde inte ladda {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def collapse_daily(obs: pd.DataFrame) -> pd.DataFrame:
    daily = (
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
    return daily


def choose_dense_dates(
    daily: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
    max_mean_cloud: float,
    max_min_cloud: float,
    forced_dates: set[pd.Timestamp],
) -> pd.DataFrame:
    x = daily[(daily.date >= start) & (daily.date <= end)].copy()
    x["selected"] = (
        ((x.mean_cloud_pct <= max_mean_cloud) & (x.min_cloud_pct <= max_min_cloud))
        | x.date.isin(forced_dates)
    )
    x["selection_reason"] = np.where(
        x.date.isin(forced_dates),
        "forced_anchor",
        np.where(x.selected, "catalog_cloud_gate", "rejected_catalog_cloud"),
    )
    return x


def fit_linear(t: np.ndarray, y: np.ndarray):
    X = np.column_stack([np.ones_like(t), t])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    return beta, float(np.sum(resid * resid))


def fit_step_model(t: np.ndarray, y: np.ndarray, j: int):
    # Break is between j-1 and j; indicator turns on at observation j.
    step = (np.arange(len(t)) >= j).astype(float)
    X = np.column_stack([np.ones_like(t), t, step])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    return beta, float(np.sum(resid * resid))


def candidate_for_field(
    g: pd.DataFrame,
    min_coverage: float,
    candidate_after: pd.Timestamp,
    min_obs: int,
    max_gap_days: int,
):
    q = g.copy()
    q["date"] = pd.to_datetime(q.date)
    q = q[
        (pd.to_numeric(q.coverage_pct, errors="coerce") >= min_coverage)
        & pd.to_numeric(q.ndvi_median, errors="coerce").notna()
    ].sort_values("date")

    if len(q) < min_obs:
        return None

    dates = q.date.to_numpy(dtype="datetime64[D]")
    t = (dates - dates[0]).astype("timedelta64[D]").astype(float)
    y = q.ndvi_median.astype(float).to_numpy()

    _, sse0 = fit_linear(t, y)
    if not np.isfinite(sse0):
        return None

    best = None
    # Need >=2 observations on each side.  Search only breaks whose right-hand
    # observation is on/after candidate_after, so spring/early senescence cannot win.
    for j in range(2, len(q) - 1):
        right_date = pd.Timestamp(q.iloc[j].date)
        left_date = pd.Timestamp(q.iloc[j - 1].date)
        if right_date < candidate_after:
            continue
        gap_days = int((right_date - left_date).days)
        if gap_days <= 0 or gap_days > max_gap_days:
            continue

        beta, sse1 = fit_step_model(t, y, j)
        step_ndvi = float(beta[2])
        if not np.isfinite(step_ndvi) or step_ndvi >= 0:
            continue

        improvement = max(0.0, sse0 - sse1)
        improvement_frac = improvement / sse0 if sse0 > 1e-12 else 0.0
        pair_delta = float(y[j] - y[j - 1])
        pair_rate = pair_delta / gap_days
        midpoint = left_date + (right_date - left_date) / 2

        rec = {
            "candidate_interval_start": left_date.strftime("%Y-%m-%d"),
            "candidate_interval_end": right_date.strftime("%Y-%m-%d"),
            "candidate_midpoint": midpoint.strftime("%Y-%m-%d"),
            "gap_days": gap_days,
            "ndvi_before": round(float(y[j - 1]), 4),
            "ndvi_after": round(float(y[j]), 4),
            "pair_delta_ndvi": round(pair_delta, 4),
            "pair_delta_per_day": round(pair_rate, 5),
            "step_ndvi_adjusted": round(step_ndvi, 4),
            "linear_slope_per_day": round(float(beta[1]), 5),
            "sse_linear": round(sse0, 6),
            "sse_step": round(sse1, 6),
            "sse_improvement_frac": round(improvement_frac, 4),
            "n_valid_obs": int(len(q)),
            "median_coverage_pct": round(float(q.coverage_pct.median()), 1),
        }
        # Transparent ranking: prefer a real negative adjusted step; SSE improvement
        # is the primary discriminator, step magnitude breaks near-ties.
        rank_key = (improvement_frac, -step_ndvi)
        if best is None or rank_key > best[0]:
            best = (rank_key, rec)

    return None if best is None else best[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/local_paths.json")
    ap.add_argument("--start", default="2026-07-01")
    ap.add_argument("--end", default="2026-08-16")
    ap.add_argument("--candidate-after", default="2026-07-20")
    ap.add_argument("--max-mean-cloud", type=float, default=55.0,
                    help="Daily mean catalogue cloud gate; SCL still does pixel masking")
    ap.add_argument("--max-min-cloud", type=float, default=35.0,
                    help="At least one overlapping product must be below this catalogue cloud level")
    ap.add_argument("--min-coverage", type=float, default=70.0,
                    help="Minimum valid pixel coverage for a date to enter field event fitting")
    ap.add_argument("--min-obs", type=int, default=5)
    ap.add_argument("--max-gap-days", type=int, default=12)
    ap.add_argument("--visual-first-combine", default="2026-07-28",
                    help="External QA annotation only; NEVER used by the fit")
    ap.add_argument("--force-date", action="append", default=["2026-07-09", "2026-08-03"],
                    help="Force an acquisition date if present in catalogue; repeatable")
    args = ap.parse_args()

    start = pd.Timestamp(args.start).normalize()
    end = pd.Timestamp(args.end).normalize()
    candidate_after = pd.Timestamp(args.candidate_after).normalize()
    if end < start:
        raise SystemExit("--end måste vara >= --start")

    ts20 = load_ts_module()
    cfg = load_config(ROOT / args.config)
    outdir = ROOT / cfg.get("build_dir", "data/derived") / "satellite_poc"
    outdir.mkdir(parents=True, exist_ok=True)

    blocks = gpd.read_file(cfg["blocks"]).to_crs(3006)
    skiften = gpd.read_file(cfg["skiften"]).to_crs(3006)
    lomma_blocks = blocks[blocks.region_kod.astype(str).str.startswith(MUN_CODE)].copy()
    lomma_skiften = skiften[skiften.blockid.astype(str).isin(lomma_blocks.blockid.astype(str))].copy()
    if lomma_skiften.empty:
        raise RuntimeError("Hittade inga Lomma-skiften")

    minx, miny, maxx, maxy = lomma_skiften.total_bounds
    bbox3006 = gpd.GeoSeries([box(minx - 100, miny - 100, maxx + 100, maxy + 100)], crs=3006)
    west, south, east, north = [float(x) for x in bbox3006.to_crs(4326).total_bounds]
    spatial = {"west": west, "south": south, "east": east, "north": north, "crs": "EPSG:4326"}

    print("=" * 112)
    print("ÅkerSync · Satellite V1a · Lomma dense harvest-window NDVI + change-point candidates")
    print("=" * 112)
    print(f"Skiften: {len(lomma_skiften):,}")
    print(f"Dense intervall: {start.date()} — {end.date()}")
    print(f"Candidate breaks tidigast: {candidate_after.date()}")
    print(f"Extern visuell QA: första observerade tröskan {args.visual_first_combine} (används INTE i fitten)")
    print("Frågar STAC efter alla observationsdatum …")

    obs = ts20.catalogue_dates(west, south, east, north, args.start, args.end)
    daily = collapse_daily(obs)
    forced = {pd.Timestamp(x).normalize() for x in args.force_date}
    plan = choose_dense_dates(
        daily, start, end, args.max_mean_cloud, args.max_min_cloud, forced
    )
    selected = plan[plan.selected].copy().reset_index(drop=True)

    stem = f"lomma_harvest_window_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}"
    plan_csv = outdir / f"{stem}_dates.csv"
    long_csv = outdir / f"{stem}_long.csv"
    candidates_csv = outdir / f"{stem}_candidates.csv"
    summary_txt = outdir / f"{stem}_summary.txt"
    plan.to_csv(plan_csv, index=False, encoding="utf-8-sig", date_format="%Y-%m-%d")

    print(f"Katalogdatum: {len(plan)} | valda för pixelkörning: {len(selected)}")
    for r in plan.itertuples(index=False):
        mark = "KÖR" if r.selected else "skip"
        print(
            f"  {pd.Timestamp(r.date).date()} | {mark:4s} | items {int(r.item_count):2d} | "
            f"moln min/mean/max {r.min_cloud_pct:5.1f}/{r.mean_cloud_pct:5.1f}/{r.max_cloud_pct:5.1f}% | {r.selection_reason}"
        )
    if len(selected) < args.min_obs:
        raise RuntimeError("För få valda datum för change-point-fit; lätta på molntrösklarna")

    import openeo
    con = openeo.connect(ts20.BACKEND).authenticate_oidc()
    print("openEO auth: OK")

    all_stats = []
    for k, r in enumerate(selected.itertuples(index=False), 1):
        date0 = pd.Timestamp(r.date).strftime("%Y-%m-%d")
        stamp = pd.Timestamp(r.date).strftime("%Y%m%d")
        tif = outdir / f"lomma_ndvi_{stamp}.tif"
        print(f"\n[{k}/{len(selected)}] {date0}")
        ts20.download_ndvi(con, spatial, date0, tif)
        st = ts20.stats_for_date(tif, lomma_skiften, date0)
        all_stats.append(st)
        n = int(st.ndvi_median.notna().sum())
        n90 = int((st.coverage_pct >= 90).sum())
        med = float(st.ndvi_median.median()) if n else np.nan
        medcov = float(st.coverage_pct.median()) if len(st) else np.nan
        print(f"  skiften med NDVI {n}/{len(lomma_skiften)} | >=90% täckning {n90} | median NDVI {med:.4f} | med täckning {medcov:.1f}%")

    long = pd.concat(all_stats, ignore_index=True)
    long["date"] = pd.to_datetime(long.date)
    long.to_csv(long_csv, index=False, encoding="utf-8-sig", date_format="%Y-%m-%d")

    cand_rows = []
    keys = ["blockid", "skiftesbeteckning"]
    for (blockid, skifte), g in long.groupby(keys, sort=False):
        rec = candidate_for_field(
            g,
            min_coverage=args.min_coverage,
            candidate_after=candidate_after,
            min_obs=args.min_obs,
            max_gap_days=args.max_gap_days,
        )
        if rec is None:
            continue
        first = g.iloc[0]
        rec = {
            "blockid": str(blockid),
            "skiftesbeteckning": str(skifte),
            "crop_code_2025": first.get("crop_code_2025"),
            "area_ha": first.get("area_ha"),
            **rec,
        }
        cand_rows.append(rec)

    candidates = pd.DataFrame(cand_rows)
    if not candidates.empty:
        candidates["candidate_midpoint"] = pd.to_datetime(candidates.candidate_midpoint)
        candidates = candidates.sort_values(
            ["sse_improvement_frac", "step_ndvi_adjusted"],
            ascending=[False, True],
        ).reset_index(drop=True)
        candidates.to_csv(candidates_csv, index=False, encoding="utf-8-sig", date_format="%Y-%m-%d")
    else:
        pd.DataFrame().to_csv(candidates_csv, index=False, encoding="utf-8-sig")

    lines = [
        "ÅkerSync Satellite V1a — Lomma dense harvest-window analysis",
        f"Interval: {args.start} — {args.end}",
        f"Selected dates: {len(selected)} / {len(plan)} catalogue dates",
        f"Fields: {len(lomma_skiften)}",
        f"Candidate fields: {len(candidates)}",
        f"Min valid coverage in fitting: {args.min_coverage:.1f}%",
        f"Candidate break not before: {args.candidate_after}",
        f"External visual first combine seen: {args.visual_first_combine} (QA only, not fit)",
        "",
        "Model: NDVI=a+b*t versus NDVI=a+b*t+c*I(t>=tau), choose negative step with largest SSE improvement.",
        "Interpretation: candidate structural break, NOT yet a validated harvest date.",
        "",
    ]

    if not candidates.empty:
        mids = pd.to_datetime(candidates.candidate_midpoint)
        lines += [
            f"Candidate midpoint median: {mids.median().date()}",
            f"Candidate midpoint P10/P90: {mids.quantile(.10).date()} / {mids.quantile(.90).date()}",
            f"Median adjusted step: {candidates.step_ndvi_adjusted.median():.4f}",
            f"Median SSE improvement fraction: {candidates.sse_improvement_frac.median():.4f}",
            "",
            "Candidate midpoint counts:",
        ]
        counts = mids.dt.strftime("%Y-%m-%d").value_counts().sort_index()
        for d, n in counts.items():
            lines.append(f"  {d}: {n}")

    summary_txt.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n" + "=" * 112)
    print("HARVEST-WINDOW ANALYS KLAR")
    print("=" * 112)
    print(f"Candidate fields: {len(candidates)} / {len(lomma_skiften)}")
    if not candidates.empty:
        mids = pd.to_datetime(candidates.candidate_midpoint)
        print(f"Median candidate midpoint: {mids.median().date()}")
        print(f"P10-P90 candidate midpoint: {mids.quantile(.10).date()} — {mids.quantile(.90).date()}")
        print(f"Median adjusted NDVI-step: {candidates.step_ndvi_adjusted.median():.4f}")
        print("\nCandidate midpoint counts:")
        for d, n in mids.dt.strftime("%Y-%m-%d").value_counts().sort_index().items():
            print(f"  {d}: {n}")
    print("\nOutput:")
    print(" ", plan_csv)
    print(" ", long_csv)
    print(" ", candidates_csv)
    print(" ", summary_txt)
    print("\nOBS: candidate = satellitbaserat strukturbrott; inte ännu validerad skördehändelse.")
    print("SATELLITE LOMMA HARVEST WINDOW: OK")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
