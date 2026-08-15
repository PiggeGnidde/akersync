#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ÅkerSync v0.8c – Topografi från Lantmäteriets Markhöjdmodell.

Input:
  - mapp med de nedladdade 1 m GeoTIFF-filerna
  - Jordbruksverkets arslager_block.gpkg

Output:
  - topography_features_blocks.csv
  - topography_features_blocks.gpkg
  - qa_summary.txt
  - hydrology_missing_neighbor_tiles.csv

Metod:
  - källdata: 1 m DEM
  - arbetsgrid: 5 m med medel-resampling (default)
  - höjdstatistik per block
  - lutning från 5 m DEM
  - lokala terrängpositioner (50 m / 150 m) som säkra proxies
  - INTE full flow accumulation/TWI ännu; det kräver sammanhängande
    uppströms DEM-kontext utanför de exakt åkertäckande tilesen.
"""

from __future__ import annotations

import argparse
import math
import re
import sys
import time
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import geopandas as gpd
import rasterio
from rasterio.features import geometry_mask
from rasterio.merge import merge
from rasterio.enums import Resampling
from scipy.ndimage import uniform_filter

MUN_CODES = {
    "Lomma": "1262",
    "Kavlinge": "1261",
    "Eslov": "1285",
}

TILE_RE = re.compile(r"^(?P<y100>\d+)_(?P<x100>\d+)_25\.tif$", re.I)


def choose_paths():
    """Use simple Windows file dialogs when paths are not given."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception:
        return None, None, None

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)

    dem = filedialog.askdirectory(
        title="Välj mappen med de 150 Markhöjdmodell .tif-filerna"
    )
    if not dem:
        root.destroy()
        return None, None, None

    blocks = filedialog.askopenfilename(
        title="Välj arslager_block.gpkg",
        filetypes=[("GeoPackage", "*.gpkg"), ("Alla filer", "*.*")]
    )
    if not blocks:
        root.destroy()
        return None, None, None

    out = filedialog.askdirectory(
        title="Välj output-mapp (Avbryt = skapa topography_output bredvid scriptet)"
    )
    root.destroy()

    if not out:
        out = str(Path(__file__).resolve().parent / "topography_output")
    return dem, blocks, out


def finite_percentile(vals, q):
    vals = np.asarray(vals)
    vals = vals[np.isfinite(vals)]
    if vals.size == 0:
        return np.nan
    return float(np.percentile(vals, q))


def pct(mask):
    if mask.size == 0:
        return np.nan
    return float(100.0 * np.mean(mask))


def nan_uniform(a: np.ndarray, size: int):
    """
    NaN-aware square moving mean plus fraction of the full neighbourhood
    represented by valid data.
    """
    valid = np.isfinite(a).astype(np.float32)
    data = np.where(np.isfinite(a), a, 0.0).astype(np.float32)
    # uniform_filter returns mean, so ratio of filtered valid mask is directly coverage.
    den = uniform_filter(valid, size=size, mode="constant", cval=0.0)
    num = uniform_filter(data, size=size, mode="constant", cval=0.0)
    out = np.full(a.shape, np.nan, dtype=np.float32)
    ok = den > 1e-6
    out[ok] = num[ok] / den[ok]
    return out, den


def aligned_bounds(bounds, res):
    minx, miny, maxx, maxy = bounds
    return (
        math.floor(minx / res) * res,
        math.floor(miny / res) * res,
        math.ceil(maxx / res) * res,
        math.ceil(maxy / res) * res,
    )


class DemTiles:
    def __init__(self, folder: Path):
        self.folder = folder
        self.paths = sorted(folder.glob("*.tif"))
        if not self.paths:
            raise RuntimeError(f"Inga .tif-filer hittades i {folder}")

        self.datasets = []
        self.records = []

        print(f"Öppnar/indexerar {len(self.paths)} DEM-filer...")
        for p in self.paths:
            ds = rasterio.open(p)
            if ds.crs is None:
                ds.close()
                raise RuntimeError(f"CRS saknas i {p.name}")
            epsg = ds.crs.to_epsg()
            # Lantmäteriets Markhöjdmodell kan vara taggad som:
            #   EPSG:3006 = SWEREF 99 TM
            #   EPSG:5845 = SWEREF 99 TM + RH2000 height
            # EPSG:5845 har samma horisontella x/y-grid som EPSG:3006.
            if epsg not in (3006, 5845):
                ds.close()
                raise RuntimeError(
                    f"{p.name}: väntade EPSG:3006 eller EPSG:5845, fick {ds.crs}"
                )
            self.datasets.append(ds)
            b = ds.bounds
            self.records.append((b.left, b.bottom, b.right, b.top, ds, p.name))

        # Verify 1 m source scale approximately.
        px = [abs(ds.transform.a) for ds in self.datasets]
        py = [abs(ds.transform.e) for ds in self.datasets]
        self.pixel_x = float(np.median(px))
        self.pixel_y = float(np.median(py))
        epsgs = sorted({ds.crs.to_epsg() for ds in self.datasets})
        print(f"DEM CRS/EPSG: {epsgs}")
        if 5845 in epsgs:
            print("  EPSG:5845 = SWEREF 99 TM + RH2000 height (korrekt)")
        print(f"Median källpixel: {self.pixel_x:.3f} × {self.pixel_y:.3f} m")

    def close(self):
        for ds in self.datasets:
            try:
                ds.close()
            except Exception:
                pass

    def intersecting(self, bounds):
        minx, miny, maxx, maxy = bounds
        out = []
        for l, b, r, t, ds, name in self.records:
            if r > minx and l < maxx and t > miny and b < maxy:
                out.append(ds)
        return out

    def read_mosaic(self, bounds, res=5.0):
        bounds = aligned_bounds(bounds, res)
        srcs = self.intersecting(bounds)
        if not srcs:
            return None, None, 0

        arr, transform = merge(
            srcs,
            bounds=bounds,
            res=(res, res),
            resampling=Resampling.average,
            nodata=np.nan,
            dtype="float32",
            masked=False,
            method="first",
        )
        return arr[0].astype(np.float32), transform, len(srcs)


def block_features(geom, tiles: DemTiles, work_res=5.0, buffer_m=170.0):
    """
    Extract robust topographic features from a 5 m working DEM.
    buffer_m supports 150 m neighbourhood/TPI statistics.
    """
    if geom is None or geom.is_empty:
        return None

    bg = geom.buffer(buffer_m)
    dem, transform, tile_count = tiles.read_mosaic(bg.bounds, work_res)
    if dem is None:
        return None

    valid_dem = np.isfinite(dem)
    if not valid_dem.any():
        return None

    inside = geometry_mask(
        [geom.__geo_interface__],
        out_shape=dem.shape,
        transform=transform,
        invert=True,
        all_touched=False,
    )
    in_valid = inside & valid_dem
    n_inside = int(inside.sum())
    n_valid = int(in_valid.sum())
    if n_valid == 0:
        return None

    z = dem[in_valid].astype(np.float64)

    # Slope on the 5 m averaged grid.
    # np.gradient returns derivatives along rows (north/south) and columns (east/west).
    gy, gx = np.gradient(dem.astype(np.float64), work_res, work_res)
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    slope_valid = inside & np.isfinite(slope)
    sv = slope[slope_valid]

    # Local terrain position: cell elevation minus neighbourhood mean.
    # Window is approximately 2*radius + one cell.
    size50 = int(round((2 * 50) / work_res)) + 1
    size150 = int(round((2 * 150) / work_res)) + 1
    if size50 % 2 == 0: size50 += 1
    if size150 % 2 == 0: size150 += 1

    mean50, ctx50 = nan_uniform(dem, size50)
    mean150, ctx150 = nan_uniform(dem, size150)
    tpi50 = dem - mean50
    tpi150 = dem - mean150

    tpi50v = tpi50[in_valid & np.isfinite(tpi50)]
    tpi150v = tpi150[in_valid & np.isfinite(tpi150)]
    ctx50v = ctx50[inside]
    ctx150v = ctx150[inside]

    out = {
        "work_res_m": work_res,
        "source_pixel_m": tiles.pixel_x,
        "tile_count": tile_count,
        "n_cells_5m": n_valid,
        "dem_coverage_pct": 100.0 * n_valid / max(1, n_inside),

        "elev_mean_m": float(np.mean(z)),
        "elev_sd_m": float(np.std(z)),
        "elev_min_m": float(np.min(z)),
        "elev_p05_m": finite_percentile(z, 5),
        "elev_p50_m": finite_percentile(z, 50),
        "elev_p95_m": finite_percentile(z, 95),
        "elev_max_m": float(np.max(z)),
        "relief_p95_p05_m": finite_percentile(z, 95) - finite_percentile(z, 5),

        "slope_coverage_pct": 100.0 * int(slope_valid.sum()) / max(1, n_inside),
        "slope_mean_deg": float(np.mean(sv)) if sv.size else np.nan,
        "slope_p50_deg": finite_percentile(sv, 50),
        "slope_p90_deg": finite_percentile(sv, 90),
        "slope_p95_deg": finite_percentile(sv, 95),
        "slope_p99_deg": finite_percentile(sv, 99),
        "slope_lt_0p5_pct": pct(sv < 0.5) if sv.size else np.nan,
        "slope_lt_1_pct": pct(sv < 1.0) if sv.size else np.nan,
        "slope_gt_3_pct": pct(sv > 3.0) if sv.size else np.nan,
        "slope_gt_5_pct": pct(sv > 5.0) if sv.size else np.nan,

        # Safe local topographic-low proxies; NOT TWI.
        "tpi50_p10_m": finite_percentile(tpi50v, 10),
        "tpi50_p50_m": finite_percentile(tpi50v, 50),
        "tpi50_p90_m": finite_percentile(tpi50v, 90),
        "local_low50_lt_m0p25_pct": pct(tpi50v < -0.25) if tpi50v.size else np.nan,
        "local_low50_lt_m0p50_pct": pct(tpi50v < -0.50) if tpi50v.size else np.nan,

        "tpi150_p10_m": finite_percentile(tpi150v, 10),
        "tpi150_p50_m": finite_percentile(tpi150v, 50),
        "tpi150_p90_m": finite_percentile(tpi150v, 90),
        "local_low150_lt_m0p50_pct": pct(tpi150v < -0.50) if tpi150v.size else np.nan,

        # Context quality: 100% means full surrounding raster existed for the moving window.
        "context50_mean_pct": float(100.0 * np.mean(ctx50v)) if ctx50v.size else np.nan,
        "context150_mean_pct": float(100.0 * np.mean(ctx150v)) if ctx150v.size else np.nan,
    }
    return out


def expected_legacy_filename(x, y):
    # lower-left SWEREF99TM coordinate -> Lantmäteriet legacy filename
    return f"{int(round(y/100))}_{int(round(x/100))}_25.tif"


def hydrology_neighbour_report(tiles: DemTiles, output_csv: Path):
    """
    One 2.5 km neighbour ring around every downloaded tile.
    This is not guaranteed full upstream catchment coverage, but gives the
    minimum next buffer set for local flow/TWI experiments.
    """
    tile_size = 2500
    existing = {}
    for l,b,r,t,ds,name in tiles.records:
        # Snap lower-left to 2.5 km grid.
        x = int(round(l / tile_size) * tile_size)
        y = int(round(b / tile_size) * tile_size)
        existing[(x,y)] = name

    required = set(existing.keys())
    for x,y in list(existing.keys()):
        for dx in (-tile_size, 0, tile_size):
            for dy in (-tile_size, 0, tile_size):
                required.add((x+dx, y+dy))

    rows = []
    for x,y in sorted(required, key=lambda p:(p[1],p[0])):
        is_existing = (x,y) in existing
        rows.append({
            "filename": existing.get((x,y), expected_legacy_filename(x,y)),
            "lower_left_x": x,
            "lower_left_y": y,
            "already_downloaded": is_existing,
            "needed_for_one_tile_hydrology_buffer": True,
        })

    pd.DataFrame(rows).to_csv(output_csv, index=False, encoding="utf-8-sig")
    return len(existing), len(required), len(required)-len(existing)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dem", help="Mapp med DEM .tif")
    ap.add_argument("--blocks", help="arslager_block.gpkg")
    ap.add_argument("--out", help="Output-mapp")
    ap.add_argument("--res", type=float, default=5.0, help="Arbetsgrid i meter, default 5")
    args = ap.parse_args()

    dem_dir = args.dem
    blocks_path = args.blocks
    out_dir = args.out

    if not dem_dir or not blocks_path:
        d,b,o = choose_paths()
        dem_dir = dem_dir or d
        blocks_path = blocks_path or b
        out_dir = out_dir or o

    if not dem_dir or not blocks_path:
        print("Avbrutet: DEM-mapp eller blockfil saknas.")
        return 2

    out_dir = Path(out_dir or (Path(__file__).resolve().parent / "topography_output"))
    out_dir.mkdir(parents=True, exist_ok=True)

    print("="*72)
    print("ÅkerSync v0.8c – Topografi")
    print("="*72)
    print("DEM:", dem_dir)
    print("Block:", blocks_path)
    print("Output:", out_dir)
    print(f"Arbetsgrid: {args.res:g} m (källa 1 m)")
    print()

    blocks = gpd.read_file(blocks_path)
    if blocks.crs is None:
        raise RuntimeError("Blockfilen saknar CRS.")
    blocks = blocks.to_crs(3006)

    wanted_codes = tuple(MUN_CODES.values())
    blocks = blocks[blocks["region_kod"].astype(str).str.startswith(wanted_codes)].copy()
    blocks["municipality"] = ""
    for name,code in MUN_CODES.items():
        blocks.loc[blocks["region_kod"].astype(str).str.startswith(code), "municipality"] = name

    print(f"Block att bearbeta: {len(blocks):,}")

    tiles = DemTiles(Path(dem_dir))
    try:
        # Report hydrology context first.
        existing_n, ring_n, missing_n = hydrology_neighbour_report(
            tiles, out_dir / "hydrology_missing_neighbor_tiles.csv"
        )
        print()
        print("Hydrologikontext:")
        print(f"  DEM-rutor nu: {existing_n}")
        print(f"  En 2,5-km grannring skulle kräva: {ring_n}")
        print(f"  Extra rutor för denna minsta hydrologibuffer: {missing_n}")
        print()

        features = []
        t0 = time.time()
        for j,(idx,row) in enumerate(blocks.iterrows(),1):
            try:
                f = block_features(row.geometry, tiles, work_res=args.res)
            except Exception as e:
                f = None
                print(f"\nVARNING block {row.get('blockid','?')}: {e}")

            base = {
                "blockid": str(row.get("blockid","")),
                "municipality": row["municipality"],
                "region_kod": str(row.get("region_kod","")),
                "kategori": row.get("kategori", None),
                "agoslag": row.get("agoslag", None),
                "block_area_ha": float(row.geometry.area / 10000.0),
            }
            if f:
                base.update(f)
            features.append(base)

            if j == 1 or j % 100 == 0 or j == len(blocks):
                elapsed = time.time()-t0
                rate = j/elapsed if elapsed>0 else 0
                remain = (len(blocks)-j)/rate if rate>0 else 0
                print(
                    f"\r{j:,}/{len(blocks):,} block  "
                    f"{rate:.1f} block/s  "
                    f"ca {remain/60:.1f} min kvar",
                    end="", flush=True
                )
        print()

    finally:
        tiles.close()

    feat = pd.DataFrame(features)
    csv_path = out_dir / "topography_features_blocks.csv"
    feat.to_csv(csv_path, index=False, encoding="utf-8-sig")

    # Join to geometry for later ÅkerSync mapping.
    out_gdf = blocks.merge(feat, on="blockid", how="left", suffixes=("", "_feat"))
    gpkg_path = out_dir / "topography_features_blocks.gpkg"
    out_gdf.to_file(gpkg_path, layer="topography_blocks", driver="GPKG")

    # QA summary.
    valid = feat["elev_mean_m"].notna() if "elev_mean_m" in feat else pd.Series(False, index=feat.index)
    qa = []
    qa.append("ÅkerSync v0.8c – QA summary")
    qa.append("="*50)
    qa.append(f"Block totalt: {len(feat)}")
    qa.append(f"Block med DEM-features: {int(valid.sum())}")
    qa.append(f"Block utan DEM-features: {int((~valid).sum())}")
    if valid.any():
        x = feat.loc[valid]
        qa.append(f"Median DEM coverage: {x.dem_coverage_pct.median():.2f}%")
        qa.append(f"Median slope coverage: {x.slope_coverage_pct.median():.2f}%")
        qa.append(f"Median elevation: {x.elev_mean_m.median():.2f} m")
        qa.append(f"Median mean slope: {x.slope_mean_deg.median():.3f} deg")
        qa.append(f"Median relief P95-P05: {x.relief_p95_p05_m.median():.2f} m")
        qa.append(f"Median context50: {x.context50_mean_pct.median():.1f}%")
        qa.append(f"Median context150: {x.context150_mean_pct.median():.1f}%")
    qa.append("")
    qa.append(f"Hydrology tiles downloaded: {existing_n}")
    qa.append(f"One-ring hydrology tiles total: {ring_n}")
    qa.append(f"Additional one-ring tiles missing: {missing_n}")
    qa.append("")
    qa.append("OBS: flow accumulation/TWI ingår medvetet INTE i v0.8a.")
    qa.append("De kräver sammanhängande uppströms terräng utanför de exakt")
    qa.append("åkertäckande DEM-rutorna. v0.8a använder i stället lokala")
    qa.append("TPI/lågterräng-proxies och rapporterar kontexttäckning.")

    qa_path = out_dir / "qa_summary.txt"
    qa_path.write_text("\n".join(qa), encoding="utf-8")

    print()
    print("="*72)
    print("KLART")
    print("="*72)
    print(csv_path)
    print(gpkg_path)
    print(qa_path)
    print(out_dir / "hydrology_missing_neighbor_tiles.csv")
    print()
    print("Ladda upp topography_features_blocks.csv + qa_summary.txt till ChatGPT.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
