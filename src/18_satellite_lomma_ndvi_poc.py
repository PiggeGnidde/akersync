#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerSync Satellite V1a — first real Sentinel-2 pixel PoC over Lomma.

Downloads one cloud-masked NDVI composite for 2026-07-09 via Copernicus openEO,
then computes per-skifte NDVI statistics locally. This is deliberately limited
to Lomma before scaling to all Skåne or long time series.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import geometry_mask
from rasterio.windows import from_bounds, Window
from shapely.geometry import box

from common import load_config

ROOT = Path(__file__).resolve().parents[1]
BACKEND = "https://openeo.dataspace.copernicus.eu"
COLLECTION = "SENTINEL2_L2A"
MUN_CODE = "1262"


def geom_window(bounds, transform, width, height):
    w = from_bounds(*bounds, transform=transform)
    c0 = max(0, int(np.floor(w.col_off))); r0 = max(0, int(np.floor(w.row_off)))
    c1 = min(width, int(np.ceil(w.col_off + w.width))); r1 = min(height, int(np.ceil(w.row_off + w.height)))
    if c1 <= c0 or r1 <= r0:
        return None
    return Window(c0, r0, c1-c0, r1-r0)


def zonal_stats(geom, arr, tr, nodata):
    if geom is None or geom.is_empty or geom.area <= 0:
        return None
    w = geom_window(geom.bounds, tr, arr.shape[1], arr.shape[0])
    if w is None:
        return None
    r0, c0, h, ww = int(w.row_off), int(w.col_off), int(w.height), int(w.width)
    sub = arr[r0:r0+h, c0:c0+ww]
    subtr = rasterio.windows.transform(w, tr)
    inside = geometry_mask([geom.__geo_interface__], out_shape=sub.shape, transform=subtr, invert=True, all_touched=False)
    ok = inside & np.isfinite(sub)
    if nodata is not None and np.isfinite(nodata):
        ok &= sub != nodata
    # NDVI sanity guard; also removes unexpected encoded nodata.
    ok &= (sub >= -1.05) & (sub <= 1.05)
    vals = sub[ok].astype(float)
    if vals.size == 0:
        return {
            "valid_pixels": 0, "coverage_pct": 0.0,
            "ndvi_mean": np.nan, "ndvi_median": np.nan, "ndvi_sd": np.nan,
            "ndvi_p10": np.nan, "ndvi_p90": np.nan,
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/local_paths.json")
    ap.add_argument("--date", default="2026-07-09")
    ap.add_argument("--max-cloud", type=float, default=20.0)
    args = ap.parse_args()

    cfg = load_config(ROOT / args.config)
    outdir = ROOT / cfg.get("build_dir", "data/derived") / "satellite_poc"
    outdir.mkdir(parents=True, exist_ok=True)

    blocks = gpd.read_file(cfg["blocks"]).to_crs(3006)
    skiften = gpd.read_file(cfg["skiften"]).to_crs(3006)
    lomma_blocks = blocks[blocks.region_kod.astype(str).str.startswith(MUN_CODE)].copy()
    lomma_skiften = skiften[skiften.blockid.astype(str).isin(lomma_blocks.blockid.astype(str))].copy()
    if lomma_blocks.empty or lomma_skiften.empty:
        raise RuntimeError("Hittade inte Lomma-block/skiften")

    # Small buffer so edge fields are not clipped by the requested raster extent.
    # Use Shapely box instead of GeoSeries.from_bbox for compatibility with the
    # GeoPandas version used by the validated ÅkerSync environment.
    minx, miny, maxx, maxy = lomma_skiften.total_bounds
    bbox3006 = gpd.GeoSeries([box(minx-100, miny-100, maxx+100, maxy+100)], crs=3006)
    west, south, east, north = [float(x) for x in bbox3006.to_crs(4326).total_bounds]
    spatial = {"west": west, "south": south, "east": east, "north": north, "crs": "EPSG:4326"}

    date0 = args.date
    # openEO temporal extents are half-open enough that using the next day is the safest one-day request.
    day = pd.Timestamp(date0)
    date1 = (day + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    stamp = day.strftime("%Y%m%d")
    tif = outdir / f"lomma_ndvi_{stamp}.tif"
    csv = outdir / f"lomma_ndvi_{stamp}_skiften.csv"
    txt = outdir / f"lomma_ndvi_{stamp}_summary.txt"

    print("=" * 100)
    print("ÅkerSync · Satellite V1a · Lomma NDVI pixel-PoC")
    print("=" * 100)
    print(f"Skiften: {len(lomma_skiften):,} | datum: {date0} | max tile-cloud: {args.max_cloud:.0f}%")
    print(f"BBox WGS84: {west:.6f}, {south:.6f}, {east:.6f}, {north:.6f}")

    if not tif.exists() or tif.stat().st_size < 10_000:
        import openeo
        con = openeo.connect(BACKEND).authenticate_oidc()
        print("openEO auth: OK")
        print("Bygger SCL cloud mask …")
        scl = con.load_collection(
            COLLECTION,
            temporal_extent=[date0, date1],
            spatial_extent=spatial,
            bands=["SCL"],
            max_cloud_cover=args.max_cloud,
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
        print("Laddar B04/B08 och beräknar NDVI …")
        s2 = con.load_collection(
            COLLECTION,
            temporal_extent=[date0, date1],
            spatial_extent=spatial,
            bands=["B04", "B08"],
            max_cloud_cover=args.max_cloud,
        )
        ndvi = s2.mask(cloud_mask).ndvi(red="B04", nir="B08")
        # If overlapping products contribute on the same date, collapse to one pixel value.
        ndvi = ndvi.reduce_temporal("median")
        print("Skickar batchjobb till Copernicus. Det kan ta några minuter …")
        ndvi.execute_batch(
            outputfile=str(tif),
            title=f"AkerSync Lomma NDVI {date0}",
            out_format="GTiff",
        )
        print("GeoTIFF hämtad:", tif)
    else:
        print("Återanvänder befintlig GeoTIFF:", tif)

    with rasterio.open(tif) as ds:
        if ds.count < 1:
            raise RuntimeError("GeoTIFF saknar rasterband")
        arr = ds.read(1).astype(np.float32)
        nodata = ds.nodata
        print(f"Raster: {ds.width}×{ds.height} | CRS {ds.crs} | pixel {abs(ds.transform.a):.2f}×{abs(ds.transform.e):.2f}")
        fields = lomma_skiften.to_crs(ds.crs).copy()
        rows = []
        for idx, r in fields.iterrows():
            st = zonal_stats(r.geometry, arr, ds.transform, nodata)
            if st is None:
                continue
            src = lomma_skiften.loc[idx]
            rows.append({
                "blockid": str(src.blockid),
                "skiftesbeteckning": str(src.skiftesbeteckning),
                "crop_code_2025": getattr(src, "grdkod_mar", None),
                "area_ha": round(float(r.geometry.area / 10000.0), 4),
                **st,
            })

    df = pd.DataFrame(rows)
    if df.empty:
        raise RuntimeError("Ingen skiftesstatistik kunde beräknas")
    df.to_csv(csv, index=False, encoding="utf-8-sig")

    usable = df[(df.valid_pixels > 0) & df.ndvi_mean.notna()]
    good90 = df[df.coverage_pct >= 90]
    lines = [
        "ÅkerSync Satellite V1a — Lomma NDVI pixel-PoC",
        f"Date: {date0}",
        f"Fields total: {len(df)}",
        f"Fields with any valid NDVI: {len(usable)}",
        f"Fields with >=90% valid-pixel coverage: {len(good90)}",
        f"Median field NDVI mean: {usable.ndvi_mean.median():.4f}" if len(usable) else "Median field NDVI mean: n/a",
        f"Median field valid coverage: {usable.coverage_pct.median():.1f}%" if len(usable) else "Median field valid coverage: n/a",
        "",
        "Interpretation: this is cloud-masked Sentinel-2 NDVI, not yield and not crop classification.",
        "crop_code_2025 is included only as current local reference; 2026 crop truth is not assumed here.",
    ]
    txt.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\nResultat:")
    print(f"  Skiften med NDVI: {len(usable):,} / {len(df):,}")
    print(f"  >=90% pixeltäckning: {len(good90):,}")
    if len(usable):
        print(f"  Median skiftes-NDVI: {usable.ndvi_mean.median():.4f}")
        print(f"  Median giltig täckning: {usable.coverage_pct.median():.1f}%")
    print("\nOutput:")
    print(" ", tif)
    print(" ", csv)
    print(" ", txt)
    print("\nSATELLITE LOMMA NDVI POC: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
