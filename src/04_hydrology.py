#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ÅkerSync v0.9c – Hydrologi / TWI

Input:
  - DEM-mapp med de nedladdade MHM .tif-filerna (ca 231 st i vår MVP)
  - arslager_block.gpkg

Pipeline:
  1. Mosaik/resampling: 1 m -> 10 m (average), EPSG:3006 horisontellt
  2. Whitebox FillDepressions + fix flats
  3. Whitebox Slope (degrees)
  4. Whitebox DInfFlowAccumulation, Specific Contributing Area, EJ loggad
  5. Whitebox WetnessIndex
  6. Zonal statistik per Jordbruksverket-block
  7. Enkel kant-QA: avstånd till mosaikens rektangulära ytterkant

OBS:
  - TWI är en topografisk våthetsbenägenhetsproxy, inte faktisk dräneringsstatus.
  - Dikning, jordart, grundvatten och nederbörd ingår inte här.
  - Första MVP:n använder FillDepressions. BreachDepressionsLeastCost blir
    metodkänslighet i nästa steg om resultatet ser lovande ut.
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import time
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd
import rasterio
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.merge import merge
from rasterio.windows import from_bounds

MUN_CODES = {
    "Lomma": "1262",
    "Kavlinge": "1261",
    "Eslov": "1285",
}

WORK_RES_DEFAULT = 10.0
NODATA = -9999.0


def choose_paths():
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception:
        return None, None, None

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)

    dem = filedialog.askdirectory(
        title="Välj DEM-mappen med de 231 Markhöjdmodell .tif-filerna"
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
        title="Välj output-mapp (Avbryt = hydrology_output bredvid scriptet)"
    )
    root.destroy()

    if not out:
        out = str(Path(__file__).resolve().parent / "hydrology_output")
    return dem, blocks, out


def get_whitebox():
    try:
        import whitebox
    except ImportError as e:
        raise RuntimeError(
            "Python-paketet 'whitebox' saknas. Kör STARTA_HYDROLOGI.bat "
            "så installeras det automatiskt."
        ) from e

    try:
        wbt = whitebox.WhiteboxTools()
        # Trigger a harmless backend check.
        ver = wbt.version()
        print(f"WhiteboxTools: {ver}")
        wbt.verbose = True
        return wbt
    except Exception as e:
        raise RuntimeError(
            "Whitebox Python-paketet finns men WhiteboxTools-backenden kunde "
            "inte startas. Skicka hela feltexten till ChatGPT."
        ) from e


def check_sources(paths):
    epsgs = set()
    px = []
    py = []
    bounds = []
    valid_paths = []
    for p in paths:
        try:
            with rasterio.open(p) as ds:
                e = ds.crs.to_epsg() if ds.crs else None
                if e not in (3006, 5845):
                    raise RuntimeError(f"{p.name}: oväntat CRS {ds.crs}")
                epsgs.add(e)
                px.append(abs(ds.transform.a))
                py.append(abs(ds.transform.e))
                bounds.append(ds.bounds)
                valid_paths.append(p)
        except rasterio.errors.RasterioIOError:
            pass

    if not valid_paths:
        raise RuntimeError("Inga läsbara DEM .tif hittades.")

    print(f"DEM-filer: {len(valid_paths)}")
    print(f"DEM EPSG: {sorted(epsgs)}")
    print(f"Median källpixel: {np.median(px):.3f} × {np.median(py):.3f} m")
    return valid_paths, bounds


def aligned_bounds(bounds, res):
    left = min(b.left for b in bounds)
    bottom = min(b.bottom for b in bounds)
    right = max(b.right for b in bounds)
    top = max(b.top for b in bounds)
    return (
        math.floor(left / res) * res,
        math.floor(bottom / res) * res,
        math.ceil(right / res) * res,
        math.ceil(top / res) * res,
    )


def build_mosaic(paths, bounds, out_tif, res=10.0):
    """
    Merge all source tiles directly to a coarser working grid.
    We deliberately write horizontal CRS as EPSG:3006; z-values remain RH2000.
    """
    # Caller controls reuse. If this function is called, overwrite any
    # previous mosaic (including v0.9b's incompatible PREDICTOR=3 file).
    if out_tif.exists():
        print(f"Tar bort gammal 10 m mosaik: {out_tif.name}")
        out_tif.unlink()

    datasets = [rasterio.open(p) for p in paths]
    try:
        ab = aligned_bounds(bounds, res)
        width = int(round((ab[2] - ab[0]) / res))
        height = int(round((ab[3] - ab[1]) / res))
        n = width * height
        print(f"10 m mosaik: {width:,} × {height:,} = {n/1e6:.1f} Mpix")
        print("Resamplar 1 m -> 10 m med average...")

        arr, transform = merge(
            datasets,
            bounds=ab,
            res=(res, res),
            nodata=NODATA,
            dtype="float32",
            resampling=Resampling.average,
            method="first",
        )

        a = arr[0]
        # Normalize NaN/inf to explicit nodata.
        bad = ~np.isfinite(a)
        a[bad] = NODATA

        # IMPORTANT FOR WHITEBOXTOOLS:
        # Do not use TIFF floating-point predictor PREDICTOR=3.
        # WhiteboxTools v2.4's GeoTIFF reader does not support it.
        # At 10 m this mosaic is only ~100 MB raw, so a plain Float32
        # GeoTIFF is preferable to clever compression for this MVP.
        profile = {
            "driver": "GTiff",
            "height": a.shape[0],
            "width": a.shape[1],
            "count": 1,
            "dtype": "float32",
            "crs": "EPSG:3006",
            "transform": transform,
            "nodata": NODATA,
        }
        with rasterio.open(out_tif, "w", **profile) as dst:
            dst.write(a, 1)
    finally:
        for ds in datasets:
            ds.close()


def verify_raster(path: Path, label: str):
    if not path.exists():
        raise RuntimeError(
            f"{label} skapades inte: {path}\n"
            "Whitebox-steget ovan misslyckades. Körningen stoppas här."
        )
    try:
        with rasterio.open(path) as ds:
            if ds.width <= 0 or ds.height <= 0:
                raise RuntimeError(f"{label} har ogiltig storlek.")
            _ = ds.read(
                1,
                window=rasterio.windows.Window(
                    0, 0, min(32, ds.width), min(32, ds.height)
                )
            )
    except Exception as e:
        raise RuntimeError(
            f"{label} finns men kan inte läsas: {path}\n{e}"
        ) from e


def run_wbt_checked(wbt, work_dir: Path, tool: str, args, expected_output: str):
    print()
    print("=" * 70)
    print(tool)
    print("=" * 70)
    print("Whitebox working dir:", work_dir)
    try:
        wbt.run_tool(tool, args)
    except Exception as e:
        raise RuntimeError(f"WhiteboxTools {tool} kastade ett fel: {e}") from e
    out = work_dir / expected_output
    verify_raster(out, tool)
    print(f"{tool}: OK -> {out.name}")
    return out


def raster_valid_values(path, max_samples=2_000_000, seed=1234):
    """
    Sample valid raster values uniformly by blocks, capped for global thresholds.
    """
    rng = np.random.default_rng(seed)
    chunks = []
    n_total = 0
    with rasterio.open(path) as ds:
        for _, window in ds.block_windows(1):
            a = ds.read(1, window=window, masked=True)
            vals = np.asarray(a.compressed(), dtype=np.float64)
            vals = vals[np.isfinite(vals)]
            if vals.size == 0:
                continue
            # Keep a moderate random subsample per block.
            if vals.size > 5000:
                idx = rng.choice(vals.size, 5000, replace=False)
                vals = vals[idx]
            chunks.append(vals)
            n_total += vals.size

    if not chunks:
        return np.array([], dtype=np.float64)
    x = np.concatenate(chunks)
    if x.size > max_samples:
        idx = rng.choice(x.size, max_samples, replace=False)
        x = x[idx]
    return x


def geom_window(geom, ds):
    try:
        w = from_bounds(*geom.bounds, transform=ds.transform)
    except Exception:
        return None
    c0 = max(0, int(math.floor(w.col_off)))
    r0 = max(0, int(math.floor(w.row_off)))
    c1 = min(ds.width, int(math.ceil(w.col_off + w.width)))
    r1 = min(ds.height, int(math.ceil(w.row_off + w.height)))
    if c1 <= c0 or r1 <= r0:
        return None
    return rasterio.windows.Window(c0, r0, c1-c0, r1-r0)


def vals_for_geom(ds, geom):
    w = geom_window(geom, ds)
    if w is None:
        return np.array([], dtype=np.float64), 0.0
    h, ww = int(w.height), int(w.width)
    tr = rasterio.windows.transform(w, ds.transform)
    inside = geometry_mask(
        [geom.__geo_interface__],
        out_shape=(h, ww),
        transform=tr,
        invert=True,
        all_touched=False,
    )
    a = ds.read(1, window=w, masked=False)
    valid = inside & np.isfinite(a)
    if ds.nodata is not None:
        valid &= (a != ds.nodata)
    vals = a[valid].astype(np.float64)
    coverage = 100.0 * valid.sum() / max(1, inside.sum())
    return vals, coverage


def percentiles(vals):
    if vals.size == 0:
        return [np.nan] * 5
    return [float(x) for x in np.percentile(vals, [10, 50, 90, 95, 99])]


def distance_to_bbox_edge(geom, bounds):
    minx, miny, maxx, maxy = bounds
    gx0, gy0, gx1, gy1 = geom.bounds
    return max(
        0.0,
        min(gx0-minx, miny if False else gy0-miny, maxx-gx1, maxy-gy1)
    )


def extract_features(blocks_path, twi_path, sca_path, slope_path, mosaic_path, out_csv):
    blocks = gpd.read_file(blocks_path)
    if blocks.crs is None:
        raise RuntimeError("Blockfilen saknar CRS.")
    blocks = blocks.to_crs(3006)

    codes = tuple(MUN_CODES.values())
    blocks = blocks[blocks["region_kod"].astype(str).str.startswith(codes)].copy()
    blocks["municipality"] = ""
    for name, code in MUN_CODES.items():
        blocks.loc[
            blocks["region_kod"].astype(str).str.startswith(code),
            "municipality"
        ] = name

    # Global, study-area-relative high-TWI thresholds.
    sample = raster_valid_values(twi_path)
    if sample.size == 0:
        raise RuntimeError("TWI-rastret saknar giltiga värden.")
    twi_global_p90 = float(np.percentile(sample, 90))
    twi_global_p95 = float(np.percentile(sample, 95))
    print(f"Global TWI P90≈{twi_global_p90:.3f}, P95≈{twi_global_p95:.3f}")

    rows = []
    with rasterio.open(twi_path) as twi_ds, \
         rasterio.open(sca_path) as sca_ds, \
         rasterio.open(slope_path) as slope_ds, \
         rasterio.open(mosaic_path) as dem_ds:

        bbox = (dem_ds.bounds.left, dem_ds.bounds.bottom,
                dem_ds.bounds.right, dem_ds.bounds.top)

        t0 = time.time()
        for j, (_, r) in enumerate(blocks.iterrows(), 1):
            g = r.geometry
            tv, tcov = vals_for_geom(twi_ds, g)
            av, acov = vals_for_geom(sca_ds, g)
            sv, scov = vals_for_geom(slope_ds, g)

            tp10,tp50,tp90,tp95,tp99 = percentiles(tv)
            ap10,ap50,ap90,ap95,ap99 = percentiles(av)
            sp10,sp50,sp90,sp95,sp99 = percentiles(sv)

            ln_a = np.log(np.maximum(av, 1e-9)) if av.size else np.array([])
            lp10,lp50,lp90,lp95,lp99 = percentiles(ln_a)

            rows.append({
                "blockid": str(r.get("blockid","")),
                "municipality": r["municipality"],
                "region_kod": str(r.get("region_kod","")),
                "block_area_ha": float(g.area / 10000.0),

                "twi_coverage_pct": tcov,
                "twi_mean": float(np.mean(tv)) if tv.size else np.nan,
                "twi_sd": float(np.std(tv)) if tv.size else np.nan,
                "twi_p10": tp10, "twi_p50": tp50, "twi_p90": tp90,
                "twi_p95": tp95, "twi_p99": tp99,
                "twi_global_p90_threshold": twi_global_p90,
                "twi_global_p95_threshold": twi_global_p95,
                "twi_ge_global_p90_pct": (
                    100.0 * np.mean(tv >= twi_global_p90) if tv.size else np.nan
                ),
                "twi_ge_global_p95_pct": (
                    100.0 * np.mean(tv >= twi_global_p95) if tv.size else np.nan
                ),

                "sca_coverage_pct": acov,
                "sca_mean_m": float(np.mean(av)) if av.size else np.nan,
                "sca_p10_m": ap10, "sca_p50_m": ap50, "sca_p90_m": ap90,
                "sca_p95_m": ap95, "sca_p99_m": ap99,
                "ln_sca_mean": float(np.mean(ln_a)) if ln_a.size else np.nan,
                "ln_sca_p50": lp50, "ln_sca_p90": lp90, "ln_sca_p95": lp95,

                "hydro_slope_coverage_pct": scov,
                "hydro_slope_mean_deg": float(np.mean(sv)) if sv.size else np.nan,
                "hydro_slope_p50_deg": sp50,
                "hydro_slope_p90_deg": sp90,
                "hydro_slope_p95_deg": sp95,

                "distance_to_mosaic_bbox_edge_m": distance_to_bbox_edge(g, bbox),
            })

            if j == 1 or j % 100 == 0 or j == len(blocks):
                elapsed = time.time() - t0
                rate = j / elapsed if elapsed > 0 else 0
                remain = (len(blocks)-j)/rate if rate > 0 else 0
                print(
                    f"\rZonal stats {j:,}/{len(blocks):,}  "
                    f"{rate:.1f} block/s  ca {remain/60:.1f} min kvar",
                    end="", flush=True
                )
        print()

    out = pd.DataFrame(rows)
    out.to_csv(out_csv, index=False, encoding="utf-8-sig")
    return out, twi_global_p90, twi_global_p95


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dem", help="Mapp med MHM .tif")
    ap.add_argument("--blocks", help="arslager_block.gpkg")
    ap.add_argument("--out", help="Output-mapp")
    ap.add_argument("--res", type=float, default=WORK_RES_DEFAULT)
    ap.add_argument("--reuse", action="store_true",
                    help="Återanvänd befintliga mellanraster om de finns")
    ap.add_argument("--work-dir", help="Whitebox lokal arbetsmapp")
    args = ap.parse_args()

    dem_dir, blocks_path, out_dir = args.dem, args.blocks, args.out
    if not dem_dir or not blocks_path:
        d,b,o = choose_paths()
        dem_dir = dem_dir or d
        blocks_path = blocks_path or b
        out_dir = out_dir or o

    if not dem_dir or not blocks_path:
        print("Avbrutet.")
        return 2

    out = Path(out_dir or (Path(__file__).resolve().parent / "hydrology_output"))
    out.mkdir(parents=True, exist_ok=True)

    print("="*72)
    print("ÅkerSync v0.9c – Hydrologi / TWI")
    print("="*72)
    print("DEM:", dem_dir)
    print("Block:", blocks_path)
    print("Output:", out)
    print(f"Hydrologiskt arbetsgrid: {args.res:g} m")
    print("GeoTIFF compatibility: plain Float32, no PREDICTOR=3")
    print("Whitebox raster compression: OFF")
    print()

    paths = sorted(Path(dem_dir).glob("*.tif"))
    paths, source_bounds = check_sources(paths)
    if len(paths) < 220:
        print(
            f"VARNING: bara {len(paths)} DEM-rutor hittades. "
            "Vi väntade oss ca 231 efter hydrologibufferten."
        )

    local_base = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir()))
    work_dir = Path(args.work_dir) if args.work_dir else (local_base / "AkerSyncHydroWork_v09b")
    work_dir.mkdir(parents=True, exist_ok=True)
    print("Whitebox local working directory:", work_dir)

    dem10 = work_dir / f"dem_{int(args.res)}m.tif"
    filled = work_dir / f"dem_{int(args.res)}m_filled.tif"
    slope = work_dir / f"slope_{int(args.res)}m_deg.tif"
    sca = work_dir / f"dinf_sca_{int(args.res)}m.tif"
    twi = work_dir / f"twi_{int(args.res)}m.tif"

    if (not dem10.exists()) or (not args.reuse):
        build_mosaic(paths, source_bounds, dem10, args.res)
    verify_raster(dem10, "DEM mosaic")

    wbt = get_whitebox()
    wbt.set_compress_rasters(False)
    wbt.set_working_dir(str(work_dir))

    def need(p):
        return (not p.exists()) or (not args.reuse)

    if need(filled):
        run_wbt_checked(wbt, work_dir, "FillDepressions", [
            f"--dem={dem10.name}",
            f"--output={filled.name}",
            "--fix_flats"
        ], filled.name)
    else:
        verify_raster(filled, "FillDepressions")

    if need(slope):
        run_wbt_checked(wbt, work_dir, "Slope", [
            f"--dem={filled.name}",
            f"--output={slope.name}",
            "--units=degrees"
        ], slope.name)
    else:
        verify_raster(slope, "Slope")

    if need(sca):
        run_wbt_checked(wbt, work_dir, "DInfFlowAccumulation", [
            f"--input={filled.name}",
            f"--output={sca.name}",
            "--out_type=sca"
        ], sca.name)
    else:
        verify_raster(sca, "DInfFlowAccumulation")

    if need(twi):
        run_wbt_checked(wbt, work_dir, "WetnessIndex", [
            f"--sca={sca.name}",
            f"--slope={slope.name}",
            f"--output={twi.name}"
        ], twi.name)
    else:
        verify_raster(twi, "WetnessIndex")

    features_csv = out / "hydrology_features_blocks.csv"
    feat, q90, q95 = extract_features(
        blocks_path, twi, sca, slope, dem10, features_csv
    )

    # QA summary.
    valid = feat["twi_mean"].notna()
    qa = []
    qa.append("ÅkerSync v0.9c – Hydrology QA")
    qa.append("="*60)
    qa.append(f"DEM tiles found: {len(paths)}")
    qa.append(f"Hydrology work resolution: {args.res:g} m")
    qa.append("Conditioning baseline: Whitebox FillDepressions + fix_flats")
    qa.append("Flow accumulation: D-infinity, Specific Contributing Area")
    qa.append("TWI: Whitebox WetnessIndex = ln(SCA / tan(slope))")
    qa.append("")
    qa.append(f"Blocks total: {len(feat)}")
    qa.append(f"Blocks with TWI: {int(valid.sum())}")
    qa.append(f"Blocks without TWI: {int((~valid).sum())}")
    if valid.any():
        x = feat.loc[valid]
        qa.append(f"Median TWI coverage: {x.twi_coverage_pct.median():.2f}%")
        qa.append(f"Median TWI mean/block: {x.twi_mean.median():.3f}")
        qa.append(f"Median TWI P90/block: {x.twi_p90.median():.3f}")
        qa.append(f"Global sampled TWI P90: {q90:.3f}")
        qa.append(f"Global sampled TWI P95: {q95:.3f}")
        qa.append(
            f"Median block share >= global P90: "
            f"{x.twi_ge_global_p90_pct.median():.2f}%"
        )
        qa.append(
            f"Median distance to mosaic bbox edge: "
            f"{x.distance_to_mosaic_bbox_edge_m.median():.0f} m"
        )
        qa.append(
            f"Blocks within 2500 m of rectangular mosaic edge: "
            f"{int((x.distance_to_mosaic_bbox_edge_m < 2500).sum())}"
        )
    qa.append("")
    qa.append("INTERPRETATION:")
    qa.append("- TWI is topographic wetness propensity, not observed wetness.")
    qa.append("- Drainage pipes, ditches, groundwater and soil are not included.")
    qa.append("- Coastal NoData/ocean is a legitimate outlet.")
    qa.append("- First-pass conditioning uses depression filling.")
    qa.append("- If useful signal is found, compare with least-cost breaching.")
    qa.append("- Edge sensitivity still needs review for upstream catchments.")

    qa_path = out / "hydrology_qa_summary.txt"
    qa.append("")
    qa.append(f"Whitebox local work dir: {work_dir}")
    qa.append("Intermediate rasters:")
    for p in (dem10, filled, slope, sca, twi):
        qa.append(f"- {p.name}: {p.stat().st_size/1024/1024:.1f} MB")
    qa_path.write_text("\n".join(qa), encoding="utf-8")

    diag_path = out / "hydrology_intermediate_files.txt"
    diag_path.write_text(
        "\n".join(str(p) for p in (dem10, filled, slope, sca, twi)),
        encoding="utf-8"
    )

    print()
    print("="*72)
    print("KLART")
    print("="*72)
    print(features_csv)
    print(qa_path)
    print()
    print("Ladda upp hydrology_features_blocks.csv + hydrology_qa_summary.txt")
    print("till ChatGPT. Du behöver inte ladda upp de stora hydrologirastren.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
