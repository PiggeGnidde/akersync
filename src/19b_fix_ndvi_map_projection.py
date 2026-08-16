#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fix visual NDVI QA overlay by warping the UTM GeoTIFF to Web Mercator.

The NDVI statistics themselves are already computed in the native Sentinel-2
UTM grid and are not changed. This script only fixes the Leaflet image overlay:
L.imageOverlay cannot correctly georeference an unwarped UTM raster by assigning
only transformed WGS84 corner bounds. We therefore warp the raster to EPSG:3857
(the map projection used by Leaflet/Esri/OSM), rebuild the PNG and replace the
imageOverlay block in the already generated HTML.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from PIL import Image
from rasterio.transform import array_bounds
from rasterio.warp import calculate_default_transform, reproject, Resampling, transform_bounds

from common import load_config

ROOT = Path(__file__).resolve().parents[1]


def colorize_ndvi(arr: np.ndarray) -> np.ndarray:
    valid = np.isfinite(arr) & (arr >= -1.05) & (arr <= 1.05)
    stops = np.array([-0.2, 0.0, 0.2, 0.4, 0.6, 0.8, 1.0], dtype=float)
    colors = np.array([
        [110, 75, 45], [165, 120, 55], [220, 190, 90], [180, 210, 95],
        [105, 175, 75], [45, 125, 55], [15, 75, 35],
    ], dtype=float)
    x = np.clip(np.where(valid, arr, 0.0).astype(float), stops[0], stops[-1])
    rgba = np.zeros(arr.shape + (4,), dtype=np.uint8)
    for c in range(3):
        rgba[..., c] = np.interp(x, stops, colors[:, c]).astype(np.uint8)
    rgba[..., 3] = np.where(valid, 205, 0).astype(np.uint8)
    return rgba


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/local_paths.json")
    ap.add_argument("--date", default="2026-07-09")
    args = ap.parse_args()

    cfg = load_config(ROOT / args.config)
    outdir = ROOT / cfg.get("build_dir", "data/derived") / "satellite_poc"
    stamp = pd.Timestamp(args.date).strftime("%Y%m%d")
    tif = outdir / f"lomma_ndvi_{stamp}.tif"
    html_path = outdir / f"lomma_ndvi_{stamp}_map.html"
    if not tif.exists():
        raise FileNotFoundError(tif)
    if not html_path.exists():
        raise FileNotFoundError(f"Saknar {html_path}. Kör SATELLITE_LOMMA_NDVI_MAP.bat först.")

    dst_crs = "EPSG:3857"
    with rasterio.open(tif) as ds:
        src = ds.read(1).astype(np.float32)
        dst_transform, width, height = calculate_default_transform(
            ds.crs, dst_crs, ds.width, ds.height, *ds.bounds
        )
        dst = np.full((height, width), np.nan, dtype=np.float32)
        reproject(
            source=src,
            destination=dst,
            src_transform=ds.transform,
            src_crs=ds.crs,
            src_nodata=ds.nodata,
            dst_transform=dst_transform,
            dst_crs=dst_crs,
            dst_nodata=np.nan,
            resampling=Resampling.nearest,
        )

    left, bottom, right, top = array_bounds(height, width, dst_transform)
    west, south, east, north = transform_bounds(
        dst_crs, "EPSG:4326", left, bottom, right, top, densify_pts=21
    )
    bounds_json = json.dumps([[south, west], [north, east]])

    rgba = colorize_ndvi(dst)
    buf = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, format="PNG", optimize=True)
    ndvi_uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")

    html = html_path.read_text(encoding="utf-8")
    start = html.index("const bounds=")
    end = html.index("\nconst fields=", start)
    replacement = (
        f"const bounds={bounds_json};\n"
        f"const ndvi=L.imageOverlay('{ndvi_uri}',bounds,{{opacity:.70,interactive:false}}).addTo(map);"
    )
    html = html[:start] + replacement + html[end:]
    html = html.replace(
        "10 m · SCL-molnmaskerad · visuell QA.",
        "10 m · SCL-molnmaskerad · visuell QA · raster warpat till Web Mercator.",
        1,
    )
    html_path.write_text(html, encoding="utf-8")

    print("=" * 92)
    print("ÅkerSync · NDVI map projection fix")
    print("=" * 92)
    print(f"Källa: {tif.name} · native CRS bevarad för statistik")
    print(f"Visning: warp -> EPSG:3857 · {width}x{height}")
    print("Uppdaterad karta:", html_path)
    print("NDVI MAP PROJECTION FIX: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
