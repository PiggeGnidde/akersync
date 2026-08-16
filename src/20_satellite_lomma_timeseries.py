#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerSync Satellite V1a — Sentinel-2 NDVI seasonal time series over Lomma.

Purpose
-------
Build the first real seasonal satellite time series before scaling to Skåne.
The script:
  1) queries Copernicus STAC for Sentinel-2 L2A observations over Lomma,
  2) selects one relatively clear acquisition per cadence window,
  3) always includes an optional anchor date (default: the validated 2026-07-09 PoC),
  4) downloads/reuses cloud-masked 10 m NDVI GeoTIFFs through Copernicus openEO,
  5) computes per-skifte NDVI distribution statistics for the 2025 skifte geometry,
  6) writes long and wide time-series tables plus a date-selection audit table.

2025 crop code is carried only as reference metadata. It is NOT treated as 2026 truth.
"""
from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import geometry_mask
from rasterio.windows import Window, from_bounds
from shapely.geometry import box

from common import load_config

ROOT = Path(__file__).resolve().parents[1]
BACKEND = "https://openeo.dataspace.copernicus.eu"
OPENEO_COLLECTION = "SENTINEL2_L2A"
STAC_SEARCH = "https://stac.dataspace.copernicus.eu/v1/search"
STAC_COLLECTION = "sentinel-2-l2a"
MUN_CODE = "1262"


def http_post_json(url: str, payload: dict, timeout: int = 90) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/geo+json, application/json",
            "User-Agent": "AkerSync-Satellite-Timeseries/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        txt = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"STAC HTTP {e.code}: {txt[:1000]}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Kunde inte nå Copernicus STAC: {e}") from e


def geom_window(bounds, transform, width, height):
    w = from_bounds(*bounds, transform=transform)
    c0 = max(0, int(np.floor(w.col_off)))
    r0 = max(0, int(np.floor(w.row_off)))
    c1 = min(width, int(np.ceil(w.col_off + w.width)))
    r1 = min(height, int(np.ceil(w.row_off + w.height)))
    if c1 <= c0 or r1 <= r0:
        return None
    return Window(c0, r0, c1 - c0, r1 - r0)


def zonal_stats(geom, arr, tr, nodata):
    if geom is None or geom.is_empty or geom.area <= 0:
        return None
    w = geom_window(geom.bounds, tr, arr.shape[1], arr.shape[0])
    if w is None:
        return None
    r0, c0, h, ww = int(w.row_off), int(w.col_off), int(w.height), int(w.width)
    sub = arr[r0:r0 + h, c0:c0 + ww]
    subtr = rasterio.windows.transform(w, tr)
    inside = geometry_mask(
        [geom.__geo_interface__],
        out_shape=sub.shape,
        transform=subtr,
        invert=True,
        all_touched=False,
    )
    ok = inside & np.isfinite(sub)
    if nodata is not None and np.isfinite(nodata):
        ok &= sub != nodata
    ok &= (sub >= -1.05) & (sub <= 1.05)
    vals = sub[ok].astype(float)
    if vals.size == 0:
        return {
            "valid_pixels": 0,
            "coverage_pct": 0.0,
            "ndvi_mean": np.nan,
            "ndvi_median": np.nan,
            "ndvi_sd": np.nan,
            "ndvi_p10": np.nan,
            "ndvi_p90": np.nan,
        }
    pixarea = abs(tr.a * tr.e)
    cov = min(100.0, vals.size * pixarea / geom.area * 100.0)
    q10, q50, q90 = np.percentile(vals, [10, 50, 90])
    return {
        "valid_pixels": int(vals.size),
        "coverage_pct": round(float(cov), 2),
        "ndvi_mean": round(float(vals.mean()), 4),
        "ndvi_median": round(float(q50), 4),
        "ndvi_sd": round(float(vals.std()), 4),
        "ndvi_p10": round(float(q10), 4),
        "ndvi_p90": round(float(q90), 4),
    }


def catalogue_dates(west: float, south: float, east: float, north: float, start: str, end: str) -> pd.DataFrame:
    query = {
        "collections": [STAC_COLLECTION],
        "bbox": [west, south, east, north],
        "datetime": f"{start}T00:00:00Z/{end}T23:59:59Z",
        "limit": 1000,
        "fields": {
            "include": ["id", "bbox", "properties.datetime", "properties.eo:cloud_cover", "properties.platform"]
        },
        "sortby": [{"field": "properties.datetime", "direction": "asc"}],
    }
    result = http_post_json(STAC_SEARCH, query)
    items = result.get("features", [])
    if not items:
        raise RuntimeError("Inga Sentinel-2 L2A-observationer hittades för Lomma och intervallet")
    if len(items) >= 1000:
        raise RuntimeError("STAC-resultatet nådde limit=1000; minska intervallet eller implementera paginering")

    rows = []
    for item in items:
        p = item.get("properties", {}) or {}
        dt = str(p.get("datetime") or "")
        cc = p.get("eo:cloud_cover")
        try:
            cc = float(cc)
        except (TypeError, ValueError):
            cc = np.nan
        rows.append({
            "date": dt[:10],
            "datetime": dt,
            "cloud_cover_pct": cc,
            "platform": p.get("platform", ""),
            "item_id": item.get("id", ""),
        })
    obs = pd.DataFrame(rows)
    obs["date"] = pd.to_datetime(obs["date"], errors="coerce")
    obs = obs[obs.date.notna()].copy()
    if obs.empty:
        raise RuntimeError("STAC-items saknade användbara datum")
    return obs


def select_dates(obs: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, cadence_days: int, anchor: str | None) -> pd.DataFrame:
    # Collapse multiple products on the same acquisition date. Rank conservatively by
    # the worst scene cloud first, then mean cloud. SCL does the real pixel-level mask later.
    daily = (
        obs.groupby("date", as_index=False)
        .agg(
            item_count=("item_id", "count"),
            mean_cloud_pct=("cloud_cover_pct", "mean"),
            max_cloud_pct=("cloud_cover_pct", "max"),
            min_cloud_pct=("cloud_cover_pct", "min"),
        )
        .sort_values("date")
    )

    picked = []
    b0 = start.normalize()
    while b0 <= end:
        b1 = min(end.normalize(), b0 + pd.Timedelta(days=cadence_days - 1))
        x = daily[(daily.date >= b0) & (daily.date <= b1)].copy()
        if not x.empty:
            x["rank_max"] = x.max_cloud_pct.fillna(999.0)
            x["rank_mean"] = x.mean_cloud_pct.fillna(999.0)
            best = x.sort_values(["rank_max", "rank_mean", "date"]).iloc[0].copy()
            best["window_start"] = b0
            best["window_end"] = b1
            best["selection_reason"] = f"best_in_{cadence_days}d_window"
            picked.append(best)
        b0 = b0 + pd.Timedelta(days=cadence_days)

    selected = pd.DataFrame(picked)
    if selected.empty:
        raise RuntimeError("Kunde inte välja något observationsdatum")

    if anchor:
        a = pd.Timestamp(anchor).normalize()
        hit = daily[daily.date == a]
        if not hit.empty and not (selected.date == a).any():
            row = hit.iloc[0].copy()
            row["window_start"] = a
            row["window_end"] = a
            row["selection_reason"] = "forced_anchor"
            selected = pd.concat([selected, pd.DataFrame([row])], ignore_index=True)

    selected = selected.sort_values("date").drop_duplicates("date", keep="first").reset_index(drop=True)
    return selected[[
        "date", "window_start", "window_end", "selection_reason", "item_count",
        "min_cloud_pct", "mean_cloud_pct", "max_cloud_pct"
    ]]


def download_ndvi(con, spatial: dict, date0: str, tif: Path) -> None:
    if tif.exists() and tif.stat().st_size >= 10_000:
        print("  återanvänder", tif.name)
        return

    date1 = (pd.Timestamp(date0) + pd.Timedelta("1 day")).strftime("%Y-%m-%d")
    scl = con.load_collection(
        OPENEO_COLLECTION,
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
    )
    s2 = con.load_collection(
        OPENEO_COLLECTION,
        temporal_extent=[date0, date1],
        spatial_extent=spatial,
        bands=["B04", "B08"],
    )
    ndvi = s2.mask(cloud_mask).ndvi(red="B04", nir="B08").reduce_temporal("median")
    ndvi.execute_batch(
        outputfile=str(tif),
        title=f"AkerSync Lomma NDVI {date0}",
        out_format="GTiff",
    )


def stats_for_date(tif: Path, lomma_skiften: gpd.GeoDataFrame, date0: str) -> pd.DataFrame:
    with rasterio.open(tif) as ds:
        arr = ds.read(1).astype(np.float32)
        nodata = ds.nodata
        fields = lomma_skiften.to_crs(ds.crs).copy()
        rows = []
        for idx, r in fields.iterrows():
            st = zonal_stats(r.geometry, arr, ds.transform, nodata)
            if st is None:
                continue
            src = lomma_skiften.loc[idx]
            rows.append({
                "date": date0,
                "blockid": str(src.blockid),
                "skiftesbeteckning": str(src.skiftesbeteckning),
                "crop_code_2025": getattr(src, "grdkod_mar", None),
                "area_ha": round(float(r.geometry.area / 10000.0), 4),
                **st,
            })
    return pd.DataFrame(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/local_paths.json")
    ap.add_argument("--start", default="2026-04-01")
    ap.add_argument("--end", default="2026-08-16")
    ap.add_argument("--cadence-days", type=int, default=14)
    ap.add_argument("--anchor-date", default="2026-07-09")
    args = ap.parse_args()

    start = pd.Timestamp(args.start).normalize()
    end = pd.Timestamp(args.end).normalize()
    if end < start:
        raise SystemExit("--end måste vara >= --start")
    if args.cadence_days < 3:
        raise SystemExit("--cadence-days måste vara minst 3")

    cfg = load_config(ROOT / args.config)
    outdir = ROOT / cfg.get("build_dir", "data/derived") / "satellite_poc"
    outdir.mkdir(parents=True, exist_ok=True)

    blocks = gpd.read_file(cfg["blocks"]).to_crs(3006)
    skiften = gpd.read_file(cfg["skiften"]).to_crs(3006)
    lomma_blocks = blocks[blocks.region_kod.astype(str).str.startswith(MUN_CODE)].copy()
    lomma_skiften = skiften[skiften.blockid.astype(str).isin(lomma_blocks.blockid.astype(str))].copy()
    if lomma_blocks.empty or lomma_skiften.empty:
        raise RuntimeError("Hittade inte Lomma-block/skiften")

    minx, miny, maxx, maxy = lomma_skiften.total_bounds
    bbox3006 = gpd.GeoSeries([box(minx - 100, miny - 100, maxx + 100, maxy + 100)], crs=3006)
    west, south, east, north = [float(x) for x in bbox3006.to_crs(4326).total_bounds]
    spatial = {"west": west, "south": south, "east": east, "north": north, "crs": "EPSG:4326"}

    print("=" * 104)
    print("ÅkerSync · Satellite V1a · Lomma NDVI seasonal time series")
    print("=" * 104)
    print(f"Skiften: {len(lomma_skiften):,}")
    print(f"Intervall: {start.date()} — {end.date()} | cadence {args.cadence_days} dagar")
    print(f"BBox WGS84: {west:.6f}, {south:.6f}, {east:.6f}, {north:.6f}")
    print("Frågar STAC efter observationsdatum …")

    obs = catalogue_dates(west, south, east, north, args.start, args.end)
    selected = select_dates(obs, start, end, args.cadence_days, args.anchor_date or None)

    stem = f"lomma_ndvi_timeseries_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}"
    dates_csv = outdir / f"{stem}_dates.csv"
    long_csv = outdir / f"{stem}_long.csv"
    wide_csv = outdir / f"{stem}_mean_wide.csv"
    summary_txt = outdir / f"{stem}_summary.txt"
    selected.to_csv(dates_csv, index=False, encoding="utf-8-sig", date_format="%Y-%m-%d")

    print(f"Valda datum: {len(selected)}")
    for r in selected.itertuples(index=False):
        print(
            f"  {pd.Timestamp(r.date).date()} | items {int(r.item_count):2d} | "
            f"moln min/mean/max {r.min_cloud_pct:5.1f}/{r.mean_cloud_pct:5.1f}/{r.max_cloud_pct:5.1f}% | {r.selection_reason}"
        )

    import openeo
    con = openeo.connect(BACKEND).authenticate_oidc()
    print("openEO auth: OK")

    all_stats = []
    for i, r in enumerate(selected.itertuples(index=False), 1):
        date0 = pd.Timestamp(r.date).strftime("%Y-%m-%d")
        stamp = pd.Timestamp(r.date).strftime("%Y%m%d")
        tif = outdir / f"lomma_ndvi_{stamp}.tif"
        print(f"\n[{i}/{len(selected)}] {date0}")
        download_ndvi(con, spatial, date0, tif)
        df = stats_for_date(tif, lomma_skiften, date0)
        if df.empty:
            print("  VARNING: ingen skiftesstatistik")
            continue
        usable = df[(df.valid_pixels > 0) & df.ndvi_mean.notna()]
        print(
            f"  skiften med NDVI {len(usable):,}/{len(df):,} | "
            f">=90% täckning {(df.coverage_pct >= 90).sum():,} | "
            f"median skiftes-NDVI {usable.ndvi_mean.median():.4f}" if len(usable) else
            f"  skiften med NDVI 0/{len(df):,}"
        )
        all_stats.append(df)

    if not all_stats:
        raise RuntimeError("Ingen tidsseriestatistik producerades")

    ts = pd.concat(all_stats, ignore_index=True)
    ts["date"] = pd.to_datetime(ts.date)
    ts = ts.sort_values(["blockid", "skiftesbeteckning", "date"]).reset_index(drop=True)
    ts["delta_ndvi_mean"] = ts.groupby(["blockid", "skiftesbeteckning"])["ndvi_mean"].diff().round(4)
    ts["days_since_prev"] = ts.groupby(["blockid", "skiftesbeteckning"])["date"].diff().dt.days
    ts.to_csv(long_csv, index=False, encoding="utf-8-sig", date_format="%Y-%m-%d")

    wide = ts.pivot_table(
        index=["blockid", "skiftesbeteckning", "crop_code_2025", "area_ha"],
        columns="date",
        values="ndvi_mean",
        aggfunc="first",
    ).reset_index()
    wide.columns = [
        c.strftime("ndvi_%Y%m%d") if isinstance(c, pd.Timestamp) else str(c)
        for c in wide.columns
    ]
    wide.to_csv(wide_csv, index=False, encoding="utf-8-sig")

    date_summary = (
        ts.groupby("date", as_index=False)
        .agg(
            fields=("blockid", "count"),
            usable_fields=("ndvi_mean", "count"),
            median_field_ndvi=("ndvi_mean", "median"),
            median_coverage_pct=("coverage_pct", "median"),
            p10_field_ndvi=("ndvi_mean", lambda x: x.quantile(0.10)),
            p90_field_ndvi=("ndvi_mean", lambda x: x.quantile(0.90)),
        )
    )

    lines = [
        "ÅkerSync Satellite V1a — Lomma NDVI seasonal time series",
        f"Interval: {args.start} — {args.end}",
        f"Cadence target: {args.cadence_days} days",
        f"Selected dates: {len(selected)}",
        f"Fields: {len(lomma_skiften)}",
        "",
        "Date summary:",
    ]
    for r in date_summary.itertuples(index=False):
        lines.append(
            f"  {pd.Timestamp(r.date).date()}: usable={int(r.usable_fields)}/{int(r.fields)}, "
            f"median NDVI={r.median_field_ndvi:.4f}, median coverage={r.median_coverage_pct:.1f}%, "
            f"field P10-P90={r.p10_field_ndvi:.4f}-{r.p90_field_ndvi:.4f}"
        )
    lines += [
        "",
        "Interpretation guardrails:",
        "  NDVI is vegetation greenness/vigour, not yield.",
        "  SCL masks clouds/cloud shadow at pixel level; catalogue cloud % is only used for date selection.",
        "  2025 crop code is reference metadata only and is not assumed to be the 2026 crop.",
        "  A sharp NDVI drop can be consistent with harvest/senescence, but timing must be validated before labeling it as harvest.",
    ]
    summary_txt.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n" + "=" * 104)
    print("TIMESERIE KLAR")
    print("=" * 104)
    for r in date_summary.itertuples(index=False):
        print(
            f"  {pd.Timestamp(r.date).date()} | median NDVI {r.median_field_ndvi:.4f} | "
            f"P10-P90 {r.p10_field_ndvi:.4f}-{r.p90_field_ndvi:.4f} | "
            f"median täckning {r.median_coverage_pct:.1f}%"
        )
    print("\nOutput:")
    print(" ", dates_csv)
    print(" ", long_csv)
    print(" ", wide_csv)
    print(" ", summary_txt)
    print("\nSATELLITE LOMMA TIMESERIES: OK")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
