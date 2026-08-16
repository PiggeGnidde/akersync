#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerSync Geometry V1a — transparent raw field-shape descriptors.

Primary object: Jordbruksverket 2025 skifte polygon.

Deliberately NO composite machineability score in V1a.  The purpose is to
measure interpretable geometry first, inspect distributions/extremes and only
then decide what deserves calibration against experienced machine operators.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Polygon, MultiPolygon

from common import load_config, MUN_CODES


def polygon_parts(geom):
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom]
    if isinstance(geom, MultiPolygon):
        return [g for g in geom.geoms if g is not None and not g.is_empty]
    # Defensive fallback for any unexpected collection-like geometry.
    try:
        return [g for g in geom.geoms if isinstance(g, Polygon) and not g.is_empty]
    except Exception:
        return []


def mrr_metrics(geom):
    """Return minimum-rotated-rectangle dimensions and long-axis bearing.

    Bearing is degrees clockwise from north, modulo 180:
      0 = N-S, 90 = E-W.
    """
    r = geom.minimum_rotated_rectangle
    if r is None or r.is_empty or r.area <= 0:
        return (np.nan,) * 5
    coords = list(r.exterior.coords)
    if len(coords) < 5:
        return (float(r.area), np.nan, np.nan, np.nan, np.nan)

    edges = []
    for a, b in zip(coords[:-1], coords[1:]):
        dx = float(b[0] - a[0])
        dy = float(b[1] - a[1])
        length = math.hypot(dx, dy)
        edges.append((length, dx, dy))
    edges.sort(key=lambda t: t[0], reverse=True)
    long_m, dx, dy = edges[0]
    short_m = min(e[0] for e in edges if e[0] > 0) if any(e[0] > 0 for e in edges) else np.nan
    aspect = long_m / short_m if short_m and np.isfinite(short_m) else np.nan
    # atan2(Easting component, Northing component) = clockwise bearing from north.
    bearing = math.degrees(math.atan2(dx, dy)) % 180.0 if long_m > 0 else np.nan
    return float(r.area), float(long_m), float(short_m), float(aspect), float(bearing)


def one_geometry(geom):
    parts = polygon_parts(geom)
    if not parts:
        return {
            "geometry_valid": False,
            "area_ha": np.nan,
            "component_count": 0,
            "hole_count": 0,
        }

    area = float(geom.area)
    if not np.isfinite(area) or area <= 0:
        return {
            "geometry_valid": bool(getattr(geom, "is_valid", False)),
            "area_ha": np.nan,
            "component_count": len(parts),
            "hole_count": sum(len(p.interiors) for p in parts),
        }

    exterior_perim = float(sum(p.exterior.length for p in parts))
    hole_perim = float(sum(ring.length for p in parts for ring in p.interiors))
    perimeter_total = exterior_perim + hole_perim
    hole_area = float(sum(Polygon(ring).area for p in parts for ring in p.interiors))
    largest_share = 100.0 * max(p.area for p in parts) / area

    hull = geom.convex_hull
    hull_area = float(hull.area) if hull is not None and not hull.is_empty else np.nan
    convexity = area / hull_area if np.isfinite(hull_area) and hull_area > 0 else np.nan

    mrr_area, long_m, short_m, aspect, bearing = mrr_metrics(geom)
    rectangularity = area / mrr_area if np.isfinite(mrr_area) and mrr_area > 0 else np.nan

    # Simple physical proxy: if driving parallel to the MRR long axis, area/width
    # is the mean equivalent run length. It is intentionally NOT a track simulation.
    erl_proxy = area / short_m if np.isfinite(short_m) and short_m > 0 else np.nan

    compactness = (
        4.0 * math.pi * area / (perimeter_total * perimeter_total)
        if perimeter_total > 0 else np.nan
    )

    return {
        "geometry_valid": bool(geom.is_valid),
        "area_ha": area / 10000.0,
        "perimeter_total_m": perimeter_total,
        "exterior_perimeter_m": exterior_perim,
        "hole_perimeter_m": hole_perim,
        "perimeter_per_ha_m": perimeter_total / (area / 10000.0),
        "component_count": int(len(parts)),
        "largest_component_share_pct": largest_share,
        "hole_count": int(sum(len(p.interiors) for p in parts)),
        "hole_area_ha": hole_area / 10000.0,
        "convex_hull_area_ha": hull_area / 10000.0 if np.isfinite(hull_area) else np.nan,
        "convexity": convexity,
        "mbr_area_ha": mrr_area / 10000.0 if np.isfinite(mrr_area) else np.nan,
        "mbr_long_m": long_m,
        "mbr_short_m": short_m,
        "mbr_aspect_ratio": aspect,
        "mbr_long_axis_deg_from_north": bearing,
        "orientation_stable": bool(np.isfinite(aspect) and aspect >= 1.05),
        "rectangularity": rectangularity,
        "erl_proxy_m": erl_proxy,
        "compactness_4piA_P2": compactness,
    }


def block_to_municipality(blocks: gpd.GeoDataFrame):
    out = {}
    region = blocks["region_kod"].astype(str)
    ids = blocks["blockid"].astype(str)
    for name, code in MUN_CODES.items():
        mask = region.str.startswith(str(code))
        for bid in ids[mask]:
            out[str(bid)] = name
    return out


def q(series, p):
    x = pd.to_numeric(series, errors="coerce").dropna()
    return float(x.quantile(p)) if len(x) else np.nan


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/local_paths.json")
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    cfg = load_config(root / args.config)
    outdir = root / cfg.get("build_dir", "data/derived")
    outdir.mkdir(parents=True, exist_ok=True)

    print("=" * 96)
    print("ÅkerSync · Geometry V1a · råa skiftesmått · INGEN score")
    print("=" * 96)

    blocks = gpd.read_file(cfg["blocks"])
    skiften = gpd.read_file(cfg["skiften"])
    if blocks.crs is None or skiften.crs is None:
        raise RuntimeError("Block/skifte saknar CRS")
    blocks = blocks.to_crs(3006)
    skiften = skiften.to_crs(3006)
    blocks["blockid"] = blocks["blockid"].astype(str)
    skiften["blockid"] = skiften["blockid"].astype(str)
    skiften["skiftesbeteckning"] = skiften["skiftesbeteckning"].astype(str)

    b2m = block_to_municipality(blocks)
    rows = []
    n = len(skiften)
    for i, r in enumerate(skiften.itertuples(index=False), 1):
        d = one_geometry(r.geometry)
        d.update({
            "kommun": b2m.get(str(r.blockid), "-"),
            "blockid": str(r.blockid),
            "skiftesbeteckning": str(r.skiftesbeteckning),
            "crop_code": getattr(r, "grdkod_mar", None),
            "ansokt_areal_ha": getattr(r, "ansokt_areal_ha", np.nan),
            "faststalld_areal_ha": getattr(r, "faststalld_areal_ha", np.nan),
        })
        rows.append(d)
        if i == 1 or i % 2000 == 0 or i == n:
            print(f"\rGeometry V1a {i:,}/{n:,}", end="", flush=True)
    print()

    df = pd.DataFrame(rows)
    # Stable, human-friendly column order.
    front = [
        "kommun", "blockid", "skiftesbeteckning", "crop_code",
        "area_ha", "ansokt_areal_ha", "faststalld_areal_ha", "geometry_valid",
        "component_count", "largest_component_share_pct", "hole_count", "hole_area_ha",
        "perimeter_total_m", "exterior_perimeter_m", "hole_perimeter_m", "perimeter_per_ha_m",
        "mbr_area_ha", "mbr_long_m", "mbr_short_m", "mbr_aspect_ratio",
        "mbr_long_axis_deg_from_north", "orientation_stable", "rectangularity",
        "convex_hull_area_ha", "convexity", "erl_proxy_m", "compactness_4piA_P2",
    ]
    df = df[[c for c in front if c in df.columns] + [c for c in df.columns if c not in front]]

    out_csv = outdir / "geometry_v1a_skiften.csv"
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")

    summary_rows = []
    for mun in MUN_CODES:
        x = df[df.kommun == mun]
        summary_rows.append({
            "kommun": mun,
            "skiften": len(x),
            "invalid_geometry": int((~x.geometry_valid.fillna(False)).sum()),
            "multipart_pct": 100.0 * float((x.component_count > 1).mean()) if len(x) else np.nan,
            "with_holes_pct": 100.0 * float((x.hole_count > 0).mean()) if len(x) else np.nan,
            "median_area_ha": q(x.area_ha, 0.50),
            "p90_area_ha": q(x.area_ha, 0.90),
            "median_rectangularity": q(x.rectangularity, 0.50),
            "p10_rectangularity": q(x.rectangularity, 0.10),
            "median_convexity": q(x.convexity, 0.50),
            "p10_convexity": q(x.convexity, 0.10),
            "median_aspect_ratio": q(x.mbr_aspect_ratio, 0.50),
            "median_mbr_long_m": q(x.mbr_long_m, 0.50),
            "median_mbr_short_m": q(x.mbr_short_m, 0.50),
            "median_erl_proxy_m": q(x.erl_proxy_m, 0.50),
        })
    summary = pd.DataFrame(summary_rows)
    summary_csv = outdir / "geometry_v1a_summary.csv"
    summary.to_csv(summary_csv, index=False, encoding="utf-8-sig")

    good = df[
        df.geometry_valid.fillna(False)
        & pd.to_numeric(df.area_ha, errors="coerce").gt(0)
        & pd.to_numeric(df.rectangularity, errors="coerce").notna()
        & pd.to_numeric(df.convexity, errors="coerce").notna()
    ]
    print(f"Skiften totalt:          {len(df):,}")
    print(f"Geometriskt mätbara:     {len(good):,}")
    print(f"Ogiltig geometri:        {int((~df.geometry_valid.fillna(False)).sum()):,}")
    print(f"Multipart:               {int((df.component_count > 1).sum()):,}")
    print(f"Med hål:                 {int((df.hole_count > 0).sum()):,}")
    print("\nSkånefördelning, råmått:")
    for label, col in [
        ("Areal ha", "area_ha"),
        ("Rectangularity", "rectangularity"),
        ("Convexity", "convexity"),
        ("MBR aspect", "mbr_aspect_ratio"),
        ("MBR lång m", "mbr_long_m"),
        ("MBR kort m", "mbr_short_m"),
        ("ERL-proxy m", "erl_proxy_m"),
    ]:
        s = pd.to_numeric(good[col], errors="coerce").dropna()
        if len(s):
            print(f"  {label:16s} P10={s.quantile(.10):8.3f}  P50={s.quantile(.50):8.3f}  P90={s.quantile(.90):8.3f}")

    print("\nOutput:")
    print(" ", out_csv)
    print(" ", summary_csv)
    print("\nV1a gör ingen sammansatt maskinbarhets-score.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
