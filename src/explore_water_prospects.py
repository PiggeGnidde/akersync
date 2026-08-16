#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Exploratory Skåne ranking: drainage challenge and irrigation sensitivity.

This is deliberately a transparent heuristic, not an agronomic diagnosis.
It combines modelled DSMS2025 soil texture at skifte level with the already
computed 10 m topographic wetness index (TWI).

Robust eligible set (default):
- area >= 1 ha
- soil coverage >= 90 %
- >= 10 soil pixels
- >= 25 valid 10 m TWI cells

Scores use percentile ranks within the eligible Skåne population so clay/sand
percent and TWI contribute on comparable scales:
  drainage_score = 100 * sqrt(clay_percentile * wetness_percentile)
  irrigation_score = 100 * sqrt(sand_percentile * dryness_percentile)
where dryness_percentile = percentile rank of -TWI mean.

The output also contains raw clay_mean * twi_mean for inspection, but ranking
is by the normalized score to avoid arbitrary unit scaling.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import geometry_mask
from rasterio.windows import Window, from_bounds

from common import load_config


def skifte_key(blockid, skifte):
    return str(blockid), str(skifte)


def twi_stats(ds, geom):
    if geom is None or geom.is_empty or geom.area <= 0:
        return (np.nan, np.nan, np.nan, 0, 0)
    w = from_bounds(*geom.bounds, transform=ds.transform)
    c0 = max(0, int(math.floor(w.col_off)))
    r0 = max(0, int(math.floor(w.row_off)))
    c1 = min(ds.width, int(math.ceil(w.col_off + w.width)))
    r1 = min(ds.height, int(math.ceil(w.row_off + w.height)))
    if c1 <= c0 or r1 <= r0:
        return (np.nan, np.nan, np.nan, 0, 0)
    win = Window(c0, r0, c1-c0, r1-r0)
    arr = ds.read(1, window=win, masked=False)
    tr = rasterio.windows.transform(win, ds.transform)
    inside = geometry_mask(
        [geom.__geo_interface__],
        out_shape=arr.shape,
        transform=tr,
        invert=True,
        all_touched=False,
    )
    valid = inside & np.isfinite(arr)
    if ds.nodata is not None:
        valid &= arr != ds.nodata
    vals = arr[valid].astype(np.float64)
    n_inside = int(inside.sum())
    n_valid = int(valid.sum())
    if vals.size == 0:
        return (np.nan, np.nan, np.nan, n_inside, n_valid)
    p50, p90 = np.percentile(vals, [50, 90])
    return (float(vals.mean()), float(p50), float(p90), n_inside, n_valid)


def build_twi_skiften(cfg, cache_path: Path, recompute: bool):
    if cache_path.exists() and not recompute:
        print(f"Återanvänder skifte-TWI: {cache_path}")
        return pd.read_csv(cache_path, dtype={"blockid": str, "skiftesbeteckning": str})

    skiften = gpd.read_file(cfg["skiften"])
    if skiften.crs is None:
        raise RuntimeError("Skiftefilen saknar CRS")
    skiften = skiften.to_crs(3006)
    skiften["blockid"] = skiften["blockid"].astype(str)
    skiften["skiftesbeteckning"] = skiften["skiftesbeteckning"].astype(str)

    work = Path(cfg["whitebox_work_dir"])
    twi_path = work / "twi_10m.tif"
    if not twi_path.exists():
        raise RuntimeError(f"TWI saknas: {twi_path}")

    print(f"Beräknar TWI per skifte från {twi_path.name}: {len(skiften):,} skiften")
    rows = []
    with rasterio.open(twi_path) as ds:
        for j, r in enumerate(skiften.itertuples(index=False), 1):
            geom = r.geometry
            mean, p50, p90, n_inside, n_valid = twi_stats(ds, geom)
            rows.append({
                "blockid": str(r.blockid),
                "skiftesbeteckning": str(r.skiftesbeteckning),
                "twi_mean": mean,
                "twi_p50": p50,
                "twi_p90": p90,
                "twi_inside_cells": n_inside,
                "twi_n_cells": n_valid,
            })
            if j == 1 or j % 1000 == 0 or j == len(skiften):
                print(f"\rSkifte-TWI {j:,}/{len(skiften):,}", end="", flush=True)
    print()

    out = pd.DataFrame(rows)
    out.to_csv(cache_path, index=False, encoding="utf-8-sig")
    print(f"Skifte-TWI sparad: {cache_path}")
    return out


def add_locations(cfg, keys):
    skiften = gpd.read_file(cfg["skiften"])
    if skiften.crs is None:
        raise RuntimeError("Skiftefilen saknar CRS")
    skiften = skiften.to_crs(3006)
    skiften["blockid"] = skiften["blockid"].astype(str)
    skiften["skiftesbeteckning"] = skiften["skiftesbeteckning"].astype(str)
    skiften["_key"] = list(zip(skiften.blockid, skiften.skiftesbeteckning))
    wanted = set(keys)
    x = skiften[skiften._key.isin(wanted)].copy()
    # representative_point is guaranteed inside the polygon and is safer than centroid for odd shapes.
    pts = gpd.GeoSeries(x.geometry.representative_point(), crs=x.crs).to_crs(4326)
    x["lon"] = pts.x.values
    x["lat"] = pts.y.values
    return x[["blockid", "skiftesbeteckning", "lat", "lon"]]


def print_top(title, df, score_col, n=10):
    print("\n" + title)
    print("-" * 122)
    for i, r in enumerate(df.head(n).itertuples(index=False), 1):
        print(
            f"{i:2d}. {str(r.kommun):14s} block={str(r.blockid):11s} "
            f"skifte={str(r.skiftesbeteckning):8s} area={r.area_ha:7.2f} ha  "
            f"score={getattr(r, score_col):6.2f}  lera={r.clay_mean:5.2f}%  "
            f"sand={r.sand_mean:5.2f}%  TWImean={r.twi_mean:6.2f}  "
            f"TWIp90={r.twi_p90:6.2f}  lat,lon={r.lat:.6f},{r.lon:.6f}"
        )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/local_paths.json")
    ap.add_argument("--recompute-twi", action="store_true",
                    help="Räkna om TWI per skifte även om cache finns")
    ap.add_argument("--min-area-ha", type=float, default=1.0)
    ap.add_argument("--min-soil-coverage", type=float, default=90.0)
    ap.add_argument("--min-soil-pixels", type=int, default=10)
    ap.add_argument("--min-twi-cells", type=int, default=25)
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    cfg = load_config(root / args.config)
    d = root / cfg.get("build_dir", "data/derived")
    d.mkdir(parents=True, exist_ok=True)

    soil_path = d / "soil_features_skiften.csv"
    if not soil_path.exists():
        raise RuntimeError(f"Saknas: {soil_path}")
    soil = pd.read_csv(
        soil_path,
        dtype={"blockid": str, "skiftesbeteckning": str, "kommun": str},
    )

    twi = build_twi_skiften(cfg, d / "hydrology_features_skiften.csv", args.recompute_twi)
    x = soil.merge(twi, on=["blockid", "skiftesbeteckning"], how="left", validate="one_to_one")

    # Keep the rules explicit. Soil texture is modelled DSMS2025 data; TWI is topographic propensity.
    eligible = (
        (pd.to_numeric(x["area_ha"], errors="coerce") >= args.min_area_ha)
        & (pd.to_numeric(x["clay_coverage_pct"], errors="coerce") >= args.min_soil_coverage)
        & (pd.to_numeric(x["sand_coverage_pct"], errors="coerce") >= args.min_soil_coverage)
        & (pd.to_numeric(x["clay_n_pix"], errors="coerce") >= args.min_soil_pixels)
        & (pd.to_numeric(x["sand_n_pix"], errors="coerce") >= args.min_soil_pixels)
        & (pd.to_numeric(x["twi_n_cells"], errors="coerce") >= args.min_twi_cells)
        & pd.to_numeric(x["clay_mean"], errors="coerce").notna()
        & pd.to_numeric(x["sand_mean"], errors="coerce").notna()
        & pd.to_numeric(x["twi_mean"], errors="coerce").notna()
    )
    z = x[eligible].copy()
    if z.empty:
        raise RuntimeError("Inga skiften klarade robusthetsfiltret")

    # Percentile ranks on the same eligible Skåne population: 0..1.
    z["clay_pctile"] = z["clay_mean"].rank(method="average", pct=True)
    z["sand_pctile"] = z["sand_mean"].rank(method="average", pct=True)
    z["wetness_pctile"] = z["twi_mean"].rank(method="average", pct=True)
    z["dryness_pctile"] = (-z["twi_mean"]).rank(method="average", pct=True)

    z["clay_x_twi_raw"] = z["clay_mean"] * z["twi_mean"]
    z["drainage_challenge_score"] = 100.0 * np.sqrt(z["clay_pctile"] * z["wetness_pctile"])
    z["irrigation_sensitivity_score"] = 100.0 * np.sqrt(z["sand_pctile"] * z["dryness_pctile"])

    drain = z.sort_values(
        ["drainage_challenge_score", "clay_mean", "twi_mean"], ascending=False
    ).head(100).copy()
    irrig = z.sort_values(
        ["irrigation_sensitivity_score", "sand_mean", "twi_mean"], ascending=[False, False, True]
    ).head(100).copy()

    wanted = list(zip(drain.blockid, drain.skiftesbeteckning)) + list(zip(irrig.blockid, irrig.skiftesbeteckning))
    loc = add_locations(cfg, wanted)
    drain = drain.merge(loc, on=["blockid", "skiftesbeteckning"], how="left", validate="one_to_one")
    irrig = irrig.merge(loc, on=["blockid", "skiftesbeteckning"], how="left", validate="one_to_one")

    all_path = d / "water_prospect_features_skiften.csv"
    drain_path = d / "drainage_challenge_top100_skiften.csv"
    irrig_path = d / "irrigation_sensitivity_top100_skiften.csv"
    z.to_csv(all_path, index=False, encoding="utf-8-sig")
    drain.to_csv(drain_path, index=False, encoding="utf-8-sig")
    irrig.to_csv(irrig_path, index=False, encoding="utf-8-sig")

    method = d / "water_prospect_method.txt"
    method.write_text(
        "ÅkerSync exploratory water prospect ranking\n"
        "==========================================\n"
        "NOT agronomic diagnosis or observed drainage/irrigation need.\n"
        "Soil = modelled DSMS2025 texture. TWI = topographic wetness propensity.\n\n"
        f"Eligible: area >= {args.min_area_ha:g} ha; soil coverage >= {args.min_soil_coverage:g}%; "
        f"soil pixels >= {args.min_soil_pixels}; TWI cells >= {args.min_twi_cells}.\n"
        "Drainage score = 100*sqrt(percentile(clay_mean)*percentile(twi_mean)).\n"
        "Irrigation score = 100*sqrt(percentile(sand_mean)*percentile(-twi_mean)).\n"
        "Area is reported but intentionally NOT included in the challenge score.\n"
        "A separate commercial-lead score could later add field size, access, crop and observed drainage data.\n",
        encoding="utf-8",
    )

    print("=" * 122)
    print("ÅkerSync · #Nyfiken · vattenprospektering")
    print("=" * 122)
    print(f"Skiften totalt:          {len(x):,}")
    print(f"Robust eligible set:     {len(z):,}")
    print("OBS: heuristik, inte observerat dränerings- eller bevattningsbehov.")
    print_top("Dräneringsutmaning — topp 10 (hög lera + hög topografisk våthetsbenägenhet)", drain,
              "drainage_challenge_score")
    print_top("Bevattningskänslighet — topp 10 (hög sand + låg topografisk våthetsbenägenhet)", irrig,
              "irrigation_sensitivity_score")
    print("\nTop 100 CSV:")
    print(" ", drain_path)
    print(" ", irrig_path)
    print("Alla robusta skiften + features:")
    print(" ", all_path)
    print("Metod:")
    print(" ", method)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
