#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerSync Satellite V1a — visual QA map for the first Lomma NDVI PoC.

Reuses the already downloaded GeoTIFF and per-skifte CSV. No Copernicus request
is made here. Produces one self-contained municipality HTML (apart from Leaflet
and basemap tiles) with Sentinel-2 NDVI over aerial imagery and clickable 2025
skifte boundaries for visual sanity checking.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from PIL import Image
from rasterio.warp import transform_bounds

from common import load_config

ROOT = Path(__file__).resolve().parents[1]
MUN_CODE = "1262"


def colorize_ndvi(arr: np.ndarray, nodata) -> np.ndarray:
    valid = np.isfinite(arr) & (arr >= -1.05) & (arr <= 1.05)
    if nodata is not None and np.isfinite(nodata):
        valid &= arr != nodata

    # Deliberately simple fixed NDVI palette for QA, not a scientific class map.
    stops = np.array([-0.2, 0.0, 0.2, 0.4, 0.6, 0.8, 1.0], dtype=float)
    colors = np.array([
        [110, 75, 45],
        [165, 120, 55],
        [220, 190, 90],
        [180, 210, 95],
        [105, 175, 75],
        [45, 125, 55],
        [15, 75, 35],
    ], dtype=float)
    x = np.clip(arr.astype(float), stops[0], stops[-1])
    rgba = np.zeros(arr.shape + (4,), dtype=np.uint8)
    for c in range(3):
        rgba[..., c] = np.interp(x, stops, colors[:, c]).astype(np.uint8)
    rgba[..., 3] = np.where(valid, 205, 0).astype(np.uint8)
    return rgba


def fmt(v, n=3):
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "–"
    try:
        return f"{float(v):.{n}f}".replace(".", ",")
    except Exception:
        return str(v)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/local_paths.json")
    ap.add_argument("--date", default="2026-07-09")
    args = ap.parse_args()

    cfg = load_config(ROOT / args.config)
    outdir = ROOT / cfg.get("build_dir", "data/derived") / "satellite_poc"
    stamp = pd.Timestamp(args.date).strftime("%Y%m%d")
    tif = outdir / f"lomma_ndvi_{stamp}.tif"
    csv = outdir / f"lomma_ndvi_{stamp}_skiften.csv"
    html_out = outdir / f"lomma_ndvi_{stamp}_map.html"

    if not tif.exists():
        raise FileNotFoundError(f"Saknar {tif}. Kör SATELLITE_LOMMA_NDVI_POC.bat först.")
    if not csv.exists():
        raise FileNotFoundError(f"Saknar {csv}. Kör SATELLITE_LOMMA_NDVI_POC.bat först.")

    with rasterio.open(tif) as ds:
        arr = ds.read(1).astype(np.float32)
        rgba = colorize_ndvi(arr, ds.nodata)
        west, south, east, north = transform_bounds(ds.crs, "EPSG:4326", *ds.bounds, densify_pts=21)

    buf = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, format="PNG", optimize=True)
    ndvi_uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")

    stats = pd.read_csv(csv, dtype={"blockid": str, "skiftesbeteckning": str, "crop_code_2025": str})
    blocks = gpd.read_file(cfg["blocks"]).to_crs(3006)
    skiften = gpd.read_file(cfg["skiften"]).to_crs(3006)
    lomma_blocks = blocks[blocks.region_kod.astype(str).str.startswith(MUN_CODE)].copy()
    fields = skiften[skiften.blockid.astype(str).isin(lomma_blocks.blockid.astype(str))].copy()
    fields["blockid"] = fields.blockid.astype(str)
    fields["skiftesbeteckning"] = fields.skiftesbeteckning.astype(str)
    fields = fields.merge(stats, on=["blockid", "skiftesbeteckning"], how="left", suffixes=("", "_sat"))
    fields = fields.to_crs(4326)

    # Keep popup payload explicit and small.
    keep = ["blockid", "skiftesbeteckning", "crop_code_2025", "coverage_pct", "ndvi_mean", "ndvi_median", "ndvi_sd", "ndvi_p10", "ndvi_p90", "geometry"]
    gj = json.loads(fields[keep].to_json())
    for f in gj["features"]:
        p = f["properties"]
        p["popup"] = (
            f"<b>Skifte {p.get('skiftesbeteckning','')}</b><br>"
            f"Block {p.get('blockid','')}<br>"
            f"Grödkod 2025: <b>{p.get('crop_code_2025') or '–'}</b><hr>"
            f"NDVI medel: <b>{fmt(p.get('ndvi_mean'))}</b><br>"
            f"Median: {fmt(p.get('ndvi_median'))}<br>"
            f"P10–P90: {fmt(p.get('ndvi_p10'))} – {fmt(p.get('ndvi_p90'))}<br>"
            f"SD: {fmt(p.get('ndvi_sd'))}<br>"
            f"Giltig täckning: {fmt(p.get('coverage_pct'),1)} %<br>"
            f"<span style='font-size:11px;color:#555'>2025 års grödkod är endast referens; NDVI är Sentinel-2 {args.date}.</span>"
        )

    gj_json = json.dumps(gj, ensure_ascii=False, separators=(",", ":"))
    bounds_json = json.dumps([[south, west], [north, east]])

    html = f"""<!doctype html>
<html lang=\"sv\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">
<title>ÅkerSync · Lomma NDVI · {args.date}</title>
<link rel=\"stylesheet\" href=\"https://unpkg.com/leaflet@1.9.4/dist/leaflet.css\">
<style>
html,body,#map{{height:100%;margin:0}} body{{font-family:Arial,sans-serif}}
.panel{{position:absolute;z-index:1000;top:12px;left:12px;background:rgba(255,255,255,.94);padding:10px 12px;border-radius:9px;box-shadow:0 1px 6px #555;max-width:330px}}
.panel b{{font-size:16px}} .small{{font-size:11px;color:#555;margin-top:4px}}
.legend{{position:absolute;z-index:1000;right:12px;bottom:24px;background:rgba(255,255,255,.94);padding:8px 10px;border-radius:8px;box-shadow:0 1px 5px #777;font-size:12px}}
.grad{{width:180px;height:12px;background:linear-gradient(90deg,rgb(110,75,45),rgb(220,190,90),rgb(180,210,95),rgb(105,175,75),rgb(15,75,35));margin:4px 0}}
.leaflet-popup-content{{min-width:220px}}
</style></head><body>
<div id=\"map\"></div>
<div class=\"panel\"><b>ÅkerSync · Sentinel-2 NDVI</b><br>Lomma · {args.date}<div class=\"small\">10 m · SCL-molnmaskerad · visuell QA. Grödkod = Jordbruksverket 2025, inte antagen 2026-sanning.</div></div>
<div class=\"legend\"><b>NDVI</b><div class=\"grad\"></div><span>−0,2</span><span style=\"float:right\">1,0</span></div>
<script src=\"https://unpkg.com/leaflet@1.9.4/dist/leaflet.js\"></script>
<script>
const map=L.map('map');
const esri=L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}',{{maxZoom:19,attribution:'Imagery © Esri'}}).addTo(map);
const osm=L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{maxZoom:19,attribution:'© OpenStreetMap contributors'}});
const bounds={bounds_json};
const ndvi=L.imageOverlay('{ndvi_uri}',bounds,{{opacity:.70,interactive:false}}).addTo(map);
const fields={gj_json};
const skifte=L.geoJSON(fields,{{style:{{color:'#00d8ff',weight:1.5,fill:false}},onEachFeature:(f,l)=>l.bindPopup(f.properties.popup)}}).addTo(map);
L.control.layers({{'Esri flygbild':esri,'OpenStreetMap':osm}},{{'Sentinel-2 NDVI':ndvi,'Skiften 2025':skifte}},{{collapsed:false}}).addTo(map);
map.fitBounds(bounds);
</script></body></html>"""
    html_out.write_text(html, encoding="utf-8")

    print("=" * 92)
    print("ÅkerSync · Satellite V1a · Lomma NDVI visual QA map")
    print("=" * 92)
    print(f"Raster: {tif.name} | skiften: {len(fields):,}")
    print("Output:", html_out)
    print("SATELLITE LOMMA NDVI MAP: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
