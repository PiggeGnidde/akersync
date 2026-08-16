#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Diagnose blocks that received no TWI in the full-Skåne hydrology run.

This is intentionally read-only. It distinguishes three common causes:
1) the polygon contains no 10 m cell centres (sub-pixel/narrow geometry),
2) the DEM exists but a Whitebox derivative is NoData inside the block,
3) the DEM itself is NoData inside the block.
"""
from __future__ import annotations

from pathlib import Path
import argparse
import json
import math

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import geometry_mask
from rasterio.windows import from_bounds, Window

from common import load_config, MUN_CODES


def mun_from_region(code: str) -> str:
    s = str(code)
    for name, prefix in MUN_CODES.items():
        if s.startswith(prefix):
            return name
    return "-"


def pixel_audit(ds, geom):
    # Clip requested window to raster bounds. A one-cell pad makes tiny polygons
    # near pixel boundaries easier to diagnose without changing the actual mask rule.
    try:
        w = from_bounds(*geom.bounds, transform=ds.transform)
        c0 = max(0, int(math.floor(w.col_off)) - 1)
        r0 = max(0, int(math.floor(w.row_off)) - 1)
        c1 = min(ds.width, int(math.ceil(w.col_off + w.width)) + 1)
        r1 = min(ds.height, int(math.ceil(w.row_off + w.height)) + 1)
        if c1 <= c0 or r1 <= r0:
            return {"inside_centres": 0, "valid": 0, "coverage_pct": np.nan}
        ww = Window(c0, r0, c1-c0, r1-r0)
        arr = ds.read(1, window=ww, masked=False)
        tr = rasterio.windows.transform(ww, ds.transform)
        inside = geometry_mask(
            [geom.__geo_interface__],
            out_shape=arr.shape,
            transform=tr,
            invert=True,
            all_touched=False,
        )
        valid = inside & np.isfinite(arr)
        if ds.nodata is not None:
            valid &= (arr != ds.nodata)
        n_inside = int(inside.sum())
        n_valid = int(valid.sum())
        cov = 100.0 * n_valid / n_inside if n_inside else np.nan
        return {"inside_centres": n_inside, "valid": n_valid, "coverage_pct": cov}
    except Exception as e:
        return {"inside_centres": -1, "valid": -1, "coverage_pct": np.nan, "error": str(e)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/local_paths.json")
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    cfg = load_config(root / args.config)
    derived = root / cfg.get("build_dir", "data/derived")
    hyd_path = derived / "hydrology_features_blocks.csv"
    blocks_path = Path(cfg["blocks"])
    work = Path(cfg["whitebox_work_dir"])

    if not hyd_path.exists():
        raise SystemExit(f"Saknas: {hyd_path}")
    if not blocks_path.exists():
        raise SystemExit(f"Saknas: {blocks_path}")

    hyd = pd.read_csv(hyd_path, dtype={"blockid": str, "region_kod": str})
    bad = hyd[pd.to_numeric(hyd["twi_mean"], errors="coerce").isna()].copy()

    print("="*92)
    print("ÅkerSync · diagnos av block utan TWI")
    print("="*92)
    print(f"Hydrologirader totalt: {len(hyd):,}")
    print(f"Block utan TWI:        {len(bad):,}")

    if bad.empty:
        print("\nDIAGNOS: GRÖN — inga block saknar TWI.")
        return 0

    blocks = gpd.read_file(blocks_path)
    if blocks.crs is None:
        raise SystemExit("Blockfilen saknar CRS")
    blocks = blocks.to_crs(3006)
    blocks["blockid"] = blocks["blockid"].astype(str)
    wanted = set(bad.blockid.astype(str))
    g = blocks[blocks.blockid.isin(wanted)].copy()

    rasters = {
        "dem": work / "dem_10m.tif",
        "filled": work / "dem_10m_filled.tif",
        "slope": work / "slope_10m_deg.tif",
        "sca": work / "dinf_sca_10m.tif",
        "twi": work / "twi_10m.tif",
    }
    missing = [str(p) for p in rasters.values() if not p.exists()]
    if missing:
        raise SystemExit("Saknade arbetsraster:\n" + "\n".join(missing))

    dsets = {k: rasterio.open(p) for k, p in rasters.items()}
    rows = []
    try:
        print("\nDetaljer:")
        for _, hr in bad.iterrows():
            bid = str(hr.blockid)
            gg = g[g.blockid == bid]
            if gg.empty:
                print(f"{bid}: blockgeometri saknas")
                continue
            br = gg.iloc[0]
            geom = br.geometry
            area_ha = float(geom.area / 10000.0)
            region = str(br.get("region_kod", hr.get("region_kod", "")))
            mun = mun_from_region(region)
            audits = {name: pixel_audit(ds, geom) for name, ds in dsets.items()}

            if audits["dem"]["inside_centres"] == 0:
                reason = "SUBPIXEL_10M"
            elif audits["dem"]["valid"] == 0:
                reason = "DEM_NODATA"
            elif audits["twi"]["valid"] == 0:
                reason = "DERIVATIVE_NODATA"
            else:
                reason = "UNEXPECTED"

            print("-"*92)
            print(f"blockid={bid}  kommun={mun}  region={region}  area={area_ha:.6f} ha")
            print(f"bbox={tuple(round(x,2) for x in geom.bounds)}  geom={geom.geom_type}")
            print(f"hydrology CSV: twi_cov={hr.get('twi_coverage_pct', np.nan)}  "
                  f"sca_cov={hr.get('sca_coverage_pct', np.nan)}  "
                  f"slope_cov={hr.get('hydro_slope_coverage_pct', np.nan)}  "
                  f"edge_m={hr.get('distance_to_mosaic_bbox_edge_m', np.nan)}")
            for name in ("dem", "filled", "slope", "sca", "twi"):
                a = audits[name]
                cov = a["coverage_pct"]
                covtxt = "-" if not np.isfinite(cov) else f"{cov:.2f}%"
                print(f"  {name:6s}: cellcentra inne={a['inside_centres']:4d}  "
                      f"giltiga={a['valid']:4d}  coverage={covtxt}")
            print(f"DIAGNOS: {reason}")

            row = {
                "blockid": bid,
                "municipality": mun,
                "region_kod": region,
                "area_ha": area_ha,
                "geom_type": geom.geom_type,
                "reason": reason,
                "distance_to_mosaic_bbox_edge_m": hr.get("distance_to_mosaic_bbox_edge_m", np.nan),
            }
            for name, a in audits.items():
                row[f"{name}_inside_centres"] = a["inside_centres"]
                row[f"{name}_valid"] = a["valid"]
                row[f"{name}_coverage_pct"] = a["coverage_pct"]
            rows.append(row)
    finally:
        for ds in dsets.values():
            ds.close()

    out = derived / "hydrology_missing_blocks_audit.csv"
    pd.DataFrame(rows).to_csv(out, index=False, encoding="utf-8-sig")

    reasons = pd.Series([r["reason"] for r in rows]).value_counts().to_dict() if rows else {}
    total_area = sum(r["area_ha"] for r in rows)
    print("\n" + "="*92)
    print("SAMMANFATTNING")
    print("="*92)
    print(f"Block utan TWI: {len(rows)}")
    print(f"Total blockarea: {total_area:.6f} ha")
    for k, v in reasons.items():
        print(f"  {k}: {v}")
    print(f"Audit CSV: {out}")
    print("\nÄndra inte hydrologimatematiken utifrån detta test; använd diagnosen för QA-beslut.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
