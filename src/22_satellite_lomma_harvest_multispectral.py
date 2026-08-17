#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerSync Satellite V1a — multispectral late-season harvest diagnostics for Lomma.

Why this step exists
--------------------
The NDVI-only change-point model produced a large cluster of apparent breaks well
before the first visually observed combine. That means NDVI alone is not harvest-
specific enough: it also reacts strongly to normal senescence.

This script therefore does NOT tune the NDVI threshold. Instead it reuses the
selected dense July-August acquisition dates and downloads cloud-masked Sentinel-2
surface reflectance bands needed for several independent late-season signals:

  NDVI = (B08-B04)/(B08+B04)         green canopy
  NDMI = (B08-B11)/(B08+B11)         vegetation/water content proxy
  NDTI = (B11-B12)/(B11+B12)         residue/tillage-sensitive SWIR contrast
  BSI  = ((B11+B04)-(B08+B02)) / ((B11+B04)+(B08+B02))  bare-soil contrast

The 20 m SWIR bands and SCL are explicitly resampled to a common 10 m UTM33 grid
before export. The output is descriptive: per-field values and consecutive-date
changes. The visual first-combine date is only annotated in the summary; it is not
used for fitting, thresholding or date selection.
"""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from shapely.geometry import box

from common import load_config

ROOT = Path(__file__).resolve().parents[1]
MUN_CODE = "1262"
BANDS = ["B02", "B04", "B08", "B11", "B12"]


def load_ts20():
    p = ROOT / "src" / "20_satellite_lomma_timeseries.py"
    spec = importlib.util.spec_from_file_location("akersync_ts20", p)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Kunde inte ladda {p}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def bool_col(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip().str.lower().isin({"true", "1", "yes", "ja"})


def safe_ratio(num: np.ndarray, den: np.ndarray) -> np.ndarray:
    out = np.full(num.shape, np.nan, dtype=np.float32)
    ok = np.isfinite(num) & np.isfinite(den) & (np.abs(den) > 1e-9)
    out[ok] = (num[ok] / den[ok]).astype(np.float32)
    out[(out < -1.2) | (out > 1.2)] = np.nan
    return out


def download_stack(con, ts20, spatial: dict, date0: str, tif: Path) -> None:
    if tif.exists() and tif.stat().st_size >= 50_000:
        print("  återanvänder", tif.name)
        return

    date1 = (pd.Timestamp(date0) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")

    s2 = con.load_collection(
        ts20.OPENEO_COLLECTION,
        temporal_extent=[date0, date1],
        spatial_extent=spatial,
        bands=BANDS,
    ).resample_spatial(resolution=10.0, projection=32633, method="bilinear")

    scl = con.load_collection(
        ts20.OPENEO_COLLECTION,
        temporal_extent=[date0, date1],
        spatial_extent=spatial,
        bands=["SCL"],
    )
    cloud_mask = scl.process(
        "to_scl_dilation_mask",
        data=scl,
        kernel1_size=17,
        kernel2_size=77,
        mask1_values=[2, 4, 5, 6, 7],
        mask2_values=[3, 8, 9, 10, 11],
        erosion_kernel_size=3,
    ).resample_cube_spatial(s2, method="near")

    cube = s2.mask(cloud_mask).reduce_temporal("median")
    cube.execute_batch(
        outputfile=str(tif),
        title=f"AkerSync Lomma multispectral {date0}",
        out_format="GTiff",
    )


def read_indices(tif: Path):
    with rasterio.open(tif) as ds:
        if ds.count != len(BANDS):
            raise RuntimeError(f"{tif.name}: väntade {len(BANDS)} band, fick {ds.count}")
        data = ds.read().astype(np.float32)
        nodata = ds.nodata
        if nodata is not None and np.isfinite(nodata):
            data[data == nodata] = np.nan
        desc = [str(x) if x else "" for x in ds.descriptions]
        if set(BANDS).issubset(set(desc)):
            ix = {b: desc.index(b) for b in BANDS}
        else:
            ix = {b: i for i, b in enumerate(BANDS)}

        blue = data[ix["B02"]]
        red = data[ix["B04"]]
        nir = data[ix["B08"]]
        swir1 = data[ix["B11"]]
        swir2 = data[ix["B12"]]

        ndvi = safe_ratio(nir - red, nir + red)
        ndmi = safe_ratio(nir - swir1, nir + swir1)
        ndti = safe_ratio(swir1 - swir2, swir1 + swir2)
        bsi_num = (swir1 + red) - (nir + blue)
        bsi_den = (swir1 + red) + (nir + blue)
        bsi = safe_ratio(bsi_num, bsi_den)

        return {
            "ndvi": ndvi,
            "ndmi": ndmi,
            "ndti": ndti,
            "bsi": bsi,
        }, ds.transform, ds.crs


def stat_index(ts20, geom, arr, transform, prefix: str):
    s = ts20.zonal_stats(geom, arr, transform, np.nan)
    if s is None:
        return None
    return {
        f"{prefix}_valid_pixels": s["valid_pixels"],
        f"{prefix}_coverage_pct": s["coverage_pct"],
        f"{prefix}_mean": s["ndvi_mean"],
        f"{prefix}_median": s["ndvi_median"],
        f"{prefix}_sd": s["ndvi_sd"],
        f"{prefix}_p10": s["ndvi_p10"],
        f"{prefix}_p90": s["ndvi_p90"],
    }


def stats_for_date(ts20, tif: Path, fields3006: gpd.GeoDataFrame, date0: str) -> pd.DataFrame:
    idxs, transform, crs = read_indices(tif)
    fields = fields3006.to_crs(crs)
    rows = []
    for pos, (_, r) in enumerate(fields.iterrows()):
        src = fields3006.iloc[pos]
        rec = {
            "date": date0,
            "blockid": str(src.blockid),
            "skiftesbeteckning": str(src.skiftesbeteckning),
            "crop_code_2025": getattr(src, "grdkod_mar", None),
            "area_ha": round(float(r.geometry.area / 10000.0), 4),
        }
        ok = True
        for name, arr in idxs.items():
            s = stat_index(ts20, r.geometry, arr, transform, name)
            if s is None:
                ok = False
                break
            rec.update(s)
        if ok:
            rows.append(rec)
    return pd.DataFrame(rows)


def make_transitions(long: pd.DataFrame, min_coverage: float) -> pd.DataFrame:
    rows = []
    keys = ["blockid", "skiftesbeteckning"]
    metrics = ["ndvi", "ndmi", "ndti", "bsi"]
    for (blockid, skifte), g in long.groupby(keys, sort=False):
        g = g.sort_values("date").reset_index(drop=True)
        for i in range(1, len(g)):
            a = g.iloc[i - 1]
            b = g.iloc[i]
            cover_ok = all(
                float(a[f"{m}_coverage_pct"]) >= min_coverage
                and float(b[f"{m}_coverage_pct"]) >= min_coverage
                for m in metrics
            )
            if not cover_ok:
                continue
            da = pd.Timestamp(a.date)
            db = pd.Timestamp(b.date)
            days = int((db - da).days)
            if days <= 0:
                continue
            rec = {
                "blockid": str(blockid),
                "skiftesbeteckning": str(skifte),
                "crop_code_2025": a.get("crop_code_2025"),
                "area_ha": a.get("area_ha"),
                "date_before": da.strftime("%Y-%m-%d"),
                "date_after": db.strftime("%Y-%m-%d"),
                "midpoint": (da + (db - da) / 2).strftime("%Y-%m-%d"),
                "gap_days": days,
            }
            for m in metrics:
                va = float(a[f"{m}_median"])
                vb = float(b[f"{m}_median"])
                rec[f"{m}_before"] = round(va, 4)
                rec[f"{m}_after"] = round(vb, 4)
                rec[f"delta_{m}"] = round(vb - va, 4)
                rec[f"delta_{m}_per_day"] = round((vb - va) / days, 5)
            rows.append(rec)
    return pd.DataFrame(rows)


def transition_summary(trans: pd.DataFrame, visual_date: pd.Timestamp) -> pd.DataFrame:
    if trans.empty:
        return pd.DataFrame()
    x = trans.copy()
    x["date_before_dt"] = pd.to_datetime(x.date_before)
    x["date_after_dt"] = pd.to_datetime(x.date_after)
    x["qa_relation"] = np.where(
        x.date_after_dt < visual_date,
        "before_visual_onset",
        np.where(x.date_before_dt < visual_date, "straddles_visual_onset", "after_visual_onset"),
    )
    rows = []
    for (a, b, rel), g in x.groupby(["date_before", "date_after", "qa_relation"], sort=True):
        row = {
            "date_before": a,
            "date_after": b,
            "qa_relation": rel,
            "n_fields": len(g),
            "median_gap_days": float(g.gap_days.median()),
        }
        for m in ["ndvi", "ndmi", "ndti", "bsi"]:
            d = pd.to_numeric(g[f"delta_{m}"], errors="coerce").dropna()
            row[f"delta_{m}_p10"] = float(d.quantile(.10)) if len(d) else np.nan
            row[f"delta_{m}_median"] = float(d.median()) if len(d) else np.nan
            row[f"delta_{m}_p90"] = float(d.quantile(.90)) if len(d) else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/local_paths.json")
    ap.add_argument("--start", default="2026-07-09")
    ap.add_argument("--end", default="2026-08-16")
    ap.add_argument("--min-coverage", type=float, default=70.0)
    ap.add_argument("--visual-first-combine", default="2026-07-28")
    args = ap.parse_args()

    start = pd.Timestamp(args.start).normalize()
    end = pd.Timestamp(args.end).normalize()
    visual = pd.Timestamp(args.visual_first_combine).normalize()

    ts20 = load_ts20()
    cfg = load_config(ROOT / args.config)
    outdir = ROOT / cfg.get("build_dir", "data/derived") / "satellite_poc"
    plan_path = outdir / "lomma_harvest_window_20260701_20260816_dates.csv"
    if not plan_path.exists():
        raise FileNotFoundError(f"Saknar {plan_path}. Kör SATELLITE_LOMMA_HARVEST_WINDOW.bat först.")

    plan = pd.read_csv(plan_path, encoding="utf-8-sig")
    plan["date"] = pd.to_datetime(plan.date)
    selected = plan[
        bool_col(plan.selected)
        & (plan.date >= start)
        & (plan.date <= end)
    ].sort_values("date").copy()
    if len(selected) < 3:
        raise RuntimeError("För få valda datum i multispektrala fönstret")

    blocks = gpd.read_file(cfg["blocks"]).to_crs(3006)
    skiften = gpd.read_file(cfg["skiften"]).to_crs(3006)
    lomma_blocks = blocks[blocks.region_kod.astype(str).str.startswith(MUN_CODE)].copy()
    fields = skiften[skiften.blockid.astype(str).isin(lomma_blocks.blockid.astype(str))].copy()
    minx, miny, maxx, maxy = fields.total_bounds
    bbox3006 = gpd.GeoSeries([box(minx - 100, miny - 100, maxx + 100, maxy + 100)], crs=3006)
    west, south, east, north = [float(v) for v in bbox3006.to_crs(4326).total_bounds]
    spatial = {"west": west, "south": south, "east": east, "north": north, "crs": "EPSG:4326"}

    print("=" * 118)
    print("ÅkerSync · Satellite V1a · Lomma multispectral harvest diagnostics")
    print("=" * 118)
    print(f"Skiften: {len(fields):,} | datum: {len(selected)} | {start.date()} — {end.date()}")
    print(f"Extern visuell QA: första observerade tröskan {visual.date()} (endast annotation, ingen fit)")
    print("Index: NDVI + NDMI + NDTI + BSI")

    import openeo
    con = openeo.connect(ts20.BACKEND).authenticate_oidc()
    print("openEO auth: OK")

    all_stats = []
    for i, r in enumerate(selected.itertuples(index=False), 1):
        date0 = pd.Timestamp(r.date).strftime("%Y-%m-%d")
        stamp = pd.Timestamp(r.date).strftime("%Y%m%d")
        tif = outdir / f"lomma_s2_multispectral_{stamp}.tif"
        print(f"\n[{i}/{len(selected)}] {date0}")
        download_stack(con, ts20, spatial, date0, tif)
        st = stats_for_date(ts20, tif, fields, date0)
        all_stats.append(st)
        n70 = int((st.ndvi_coverage_pct >= args.min_coverage).sum())
        print(
            f"  >=70% täckning {n70}/{len(fields)} | median "
            f"NDVI {st.ndvi_median.median():.4f} | NDMI {st.ndmi_median.median():.4f} | "
            f"NDTI {st.ndti_median.median():.4f} | BSI {st.bsi_median.median():.4f}"
        )

    long = pd.concat(all_stats, ignore_index=True)
    long["date"] = pd.to_datetime(long.date)
    trans = make_transitions(long, args.min_coverage)
    summary = transition_summary(trans, visual)

    stem = f"lomma_harvest_multispectral_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}"
    long_csv = outdir / f"{stem}_long.csv"
    trans_csv = outdir / f"{stem}_transitions.csv"
    sum_csv = outdir / f"{stem}_transition_summary.csv"
    txt = outdir / f"{stem}_summary.txt"
    long.to_csv(long_csv, index=False, encoding="utf-8-sig", date_format="%Y-%m-%d")
    trans.to_csv(trans_csv, index=False, encoding="utf-8-sig")
    summary.to_csv(sum_csv, index=False, encoding="utf-8-sig")

    lines = [
        "ÅkerSync Satellite V1a — Lomma multispectral harvest diagnostics",
        f"Window: {args.start} — {args.end}",
        f"Selected dates: {len(selected)}",
        f"Fields: {len(fields)}",
        f"External first combine: {args.visual_first_combine} (annotation only)",
        "",
        "Transition medians (after - before):",
    ]
    print("\n" + "=" * 118)
    print("MULTISPEKTRAL ÖVERGÅNGSANALYS")
    print("=" * 118)
    for r in summary.itertuples(index=False):
        line = (
            f"{r.date_before} -> {r.date_after} | {r.qa_relation:22s} | n={int(r.n_fields):3d} | "
            f"dNDVI {r.delta_ndvi_median:+.4f} | dNDMI {r.delta_ndmi_median:+.4f} | "
            f"dNDTI {r.delta_ndti_median:+.4f} | dBSI {r.delta_bsi_median:+.4f}"
        )
        print("  " + line)
        lines.append("  " + line)

    lines += [
        "",
        "Interpretation: descriptive multispectral transitions only. No harvest classifier has been fitted.",
        "The purpose is to see which spectral dimensions distinguish normal senescence from the late-July/August field transition.",
    ]
    txt.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\nOutput:")
    print(" ", long_csv)
    print(" ", trans_csv)
    print(" ", sum_csv)
    print(" ", txt)
    print("\nSATELLITE LOMMA HARVEST MULTISPECTRAL: OK")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
