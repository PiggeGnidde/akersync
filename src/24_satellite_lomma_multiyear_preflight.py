#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerSync Satellite V1a — multiyear Lomma Sentinel-2 metadata preflight.

Purpose
-------
Before downloading many historical pixels, inspect 2018..2026 Sentinel-2 L2A
availability over Lomma and choose one catalogue-best acquisition in each of
four calendar windows that bracket the TWI↔NDVI seasonal response seen in 2026:

  W1 early_april : Apr 01–15
  W2 late_may    : May 15–31
  W3 late_june   : Jun 15–30
  W4 early_july  : Jul 01–15

This is metadata only. No openEO authentication and no satellite pixels are
downloaded. Scene/tile cloud cover is used only for ranking. Pixel-level SCL
masking remains mandatory in the later download stage.

Historical note
---------------
The current 2025 skifte geometry is used only to define the Lomma spatial bbox.
No claim is made here that historical administrative field boundaries were the
same in earlier years.
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
WINDOWS = [
    ("W1_early_april", "04-01", "04-15"),
    ("W2_late_may", "05-15", "05-31"),
    ("W3_late_june", "06-15", "06-30"),
    ("W4_early_july", "07-01", "07-15"),
]


def load_ts20():
    path = ROOT / "src" / "20_satellite_lomma_timeseries.py"
    spec = importlib.util.spec_from_file_location("akersync_sat_ts20_preflight", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Kunde inte ladda {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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


def choose_best(daily: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp):
    x = daily[(daily.date >= start) & (daily.date <= end)].copy()
    if x.empty:
        return None
    x["rank_max"] = x.max_cloud_pct.fillna(999.0)
    x["rank_mean"] = x.mean_cloud_pct.fillna(999.0)
    x["rank_min"] = x.min_cloud_pct.fillna(999.0)
    # Conservative ranking: first minimize the cloudiest overlapping product,
    # then the average and best product. Earlier date only breaks exact ties.
    return x.sort_values(["rank_max", "rank_mean", "rank_min", "date"]).iloc[0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/local_paths.json")
    ap.add_argument("--year-start", type=int, default=2018)
    ap.add_argument("--year-end", type=int, default=2026)
    ap.add_argument("--good-max-cloud", type=float, default=40.0,
                    help="Only a QA flag; does not reject a selected date")
    args = ap.parse_args()

    if args.year_end < args.year_start:
        raise SystemExit("--year-end måste vara >= --year-start")

    ts20 = load_ts20()
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

    print("=" * 118)
    print("ÅkerSync · Satellite V1a · Lomma multiyear Sentinel-2 preflight")
    print("=" * 118)
    print(f"År: {args.year_start}–{args.year_end} | skiften för bbox: {len(lomma_skiften):,}")
    print(f"BBox WGS84: {west:.6f}, {south:.6f}, {east:.6f}, {north:.6f}")
    print("Fönster: " + ", ".join(f"{name} {a}..{b}" for name, a, b in WINDOWS))
    print("Metadata-only: inga satellitpixlar laddas ned.\n")

    rows: list[dict] = []
    for year in range(args.year_start, args.year_end + 1):
        query_start = f"{year}-04-01"
        query_end = f"{year}-07-15"
        print(f"[{year}] STAC {query_start} — {query_end} …")
        obs = ts20.catalogue_dates(west, south, east, north, query_start, query_end)
        daily = collapse_daily(obs)
        print(f"  katalogdatum: {len(daily)}")

        for window_name, md0, md1 in WINDOWS:
            w0 = pd.Timestamp(f"{year}-{md0}")
            w1 = pd.Timestamp(f"{year}-{md1}")
            best = choose_best(daily, w0, w1)
            if best is None:
                rec = {
                    "year": year,
                    "window": window_name,
                    "window_start": w0,
                    "window_end": w1,
                    "selected_date": pd.NaT,
                    "item_count": 0,
                    "min_cloud_pct": np.nan,
                    "mean_cloud_pct": np.nan,
                    "max_cloud_pct": np.nan,
                    "good_catalog_cloud": False,
                }
                print(f"    {window_name:15s}: INGET DATUM")
            else:
                good = bool(np.isfinite(best.max_cloud_pct) and best.max_cloud_pct <= args.good_max_cloud)
                rec = {
                    "year": year,
                    "window": window_name,
                    "window_start": w0,
                    "window_end": w1,
                    "selected_date": pd.Timestamp(best.date),
                    "item_count": int(best.item_count),
                    "min_cloud_pct": float(best.min_cloud_pct),
                    "mean_cloud_pct": float(best.mean_cloud_pct),
                    "max_cloud_pct": float(best.max_cloud_pct),
                    "good_catalog_cloud": good,
                }
                flag = "GOOD" if good else "cloudy"
                print(
                    f"    {window_name:15s}: {pd.Timestamp(best.date).date()} | "
                    f"items {int(best.item_count):2d} | cloud min/mean/max "
                    f"{best.min_cloud_pct:5.1f}/{best.mean_cloud_pct:5.1f}/{best.max_cloud_pct:5.1f}% | {flag}"
                )
            rows.append(rec)

    plan = pd.DataFrame(rows)
    plan["selected_date"] = pd.to_datetime(plan.selected_date)
    stem = f"lomma_multiyear_preflight_{args.year_start}_{args.year_end}"
    plan_csv = outdir / f"{stem}_dates.csv"
    summary_txt = outdir / f"{stem}_summary.txt"
    plan.to_csv(plan_csv, index=False, encoding="utf-8-sig", date_format="%Y-%m-%d")

    year_summary = (
        plan.groupby("year", as_index=False)
        .agg(
            windows=("window", "count"),
            dates_found=("selected_date", lambda x: int(x.notna().sum())),
            good_windows=("good_catalog_cloud", "sum"),
            worst_selected_cloud_pct=("max_cloud_pct", "max"),
        )
    )

    lines = [
        "ÅkerSync Satellite V1a — Lomma multiyear Sentinel-2 metadata preflight",
        f"Years: {args.year_start}–{args.year_end}",
        f"Lomma bbox: {west:.6f}, {south:.6f}, {east:.6f}, {north:.6f}",
        f"Good catalogue-cloud QA threshold: max overlapping product <= {args.good_max_cloud:.1f}%",
        "Important: catalogue cloud is only a ranking/QA proxy; later SCL pixel masking decides usable field coverage.",
        "",
        "YEAR SUMMARY:",
    ]
    for r in year_summary.itertuples(index=False):
        worst = "NA" if not np.isfinite(r.worst_selected_cloud_pct) else f"{r.worst_selected_cloud_pct:.1f}%"
        lines.append(
            f"  {int(r.year)} | dates {int(r.dates_found)}/{int(r.windows)} | "
            f"good windows {int(r.good_windows)}/{int(r.windows)} | worst selected max-cloud {worst}"
        )
    lines += [
        "",
        "NEXT:",
        "  Use this plan to choose a controlled historical pixel download, then run the same within-field TWI quintile response curve by year.",
        "  Weather classification is added separately; do not infer wet/dry years from Sentinel catalogue cloud cover.",
    ]
    summary_txt.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n" + "=" * 118)
    print("MULTIYEAR PREFLIGHT KLAR")
    print("=" * 118)
    for r in year_summary.itertuples(index=False):
        worst = "NA" if not np.isfinite(r.worst_selected_cloud_pct) else f"{r.worst_selected_cloud_pct:.1f}%"
        print(
            f"  {int(r.year)} | datum {int(r.dates_found)}/{int(r.windows)} | "
            f"GOOD {int(r.good_windows)}/{int(r.windows)} | värsta valt max-moln {worst}"
        )
    print("\nOutput:")
    print(" ", plan_csv)
    print(" ", summary_txt)
    print("\nSATELLITE LOMMA MULTIYEAR PREFLIGHT: OK")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
