#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Find the clayiest and sandiest 2025 skiften in the current ÅkerSync build.

This is an exploration/QA helper. Soil texture comes from the 20 m DSMS2025
model layers used by ÅkerSync; values are modelled raster estimates, not field
soil samples.
"""
from __future__ import annotations

from pathlib import Path
import argparse

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import Transformer

from common import load_config


def fmt_row(r: pd.Series) -> str:
    return (
        f"{r['kommun']:<14s} block={r['blockid']}  skifte={str(r['skiftesbeteckning']):<8s} "
        f"area={r['area_ha']:7.2f} ha  "
        f"lera={r['clay_mean']:6.2f}%  sand={r['sand_mean']:6.2f}%  silt={r['silt_mean']:6.2f}%  "
        f"coverage={r['texture_coverage_pct']:6.2f}%  n={int(r['texture_n_pix']):4d}  "
        f"lat,lon={r['lat']:.6f},{r['lon']:.6f}"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/local_paths.json")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--min-area-ha", type=float, default=1.0,
                    help="Robust ranking: minimum field area")
    ap.add_argument("--min-coverage", type=float, default=90.0,
                    help="Robust ranking: minimum texture raster coverage")
    ap.add_argument("--min-pixels", type=int, default=10,
                    help="Robust ranking: minimum number of 20 m texture pixels")
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    cfg = load_config(root / args.config)
    d = root / cfg.get("build_dir", "data/derived")
    soil_path = d / "soil_features_skiften.csv"
    if not soil_path.exists():
        raise SystemExit(f"Saknas: {soil_path}")

    x = pd.read_csv(soil_path, dtype={"blockid": str, "skiftesbeteckning": str})
    needed = ["clay_mean", "sand_mean", "silt_mean", "clay_coverage_pct",
              "sand_coverage_pct", "silt_coverage_pct", "clay_n_pix",
              "sand_n_pix", "silt_n_pix", "area_ha"]
    for c in needed:
        x[c] = pd.to_numeric(x[c], errors="coerce")

    x["texture_coverage_pct"] = x[["clay_coverage_pct", "sand_coverage_pct", "silt_coverage_pct"]].min(axis=1)
    x["texture_n_pix"] = x[["clay_n_pix", "sand_n_pix", "silt_n_pix"]].min(axis=1)
    x = x[x[["clay_mean", "sand_mean", "silt_mean"]].notna().all(axis=1)].copy()

    # Attach a representative coordinate from the actual 2025 skifte geometry.
    g = gpd.read_file(cfg["skiften"])
    if g.crs is None:
        raise SystemExit("Skiftesfilen saknar CRS")
    g = g.to_crs(3006)
    g["blockid"] = g["blockid"].astype(str)
    g["skiftesbeteckning"] = g["skiftesbeteckning"].astype(str)
    # representative_point is guaranteed to lie inside the polygon, unlike centroid.
    pts = g.geometry.representative_point()
    tf = Transformer.from_crs(3006, 4326, always_xy=True)
    ll = [tf.transform(p.x, p.y) for p in pts]
    gg = pd.DataFrame({
        "blockid": g["blockid"],
        "skiftesbeteckning": g["skiftesbeteckning"],
        "lon": [p[0] for p in ll],
        "lat": [p[1] for p in ll],
    })
    x = x.merge(gg, on=["blockid", "skiftesbeteckning"], how="left", validate="one_to_one")

    practical = x[
        (x.area_ha >= args.min_area_ha) &
        (x.texture_coverage_pct >= args.min_coverage) &
        (x.texture_n_pix >= args.min_pixels)
    ].copy()

    print("=" * 112)
    print("ÅkerSync · Skånes lerigaste och sandigaste skiften · DSMS2025")
    print("=" * 112)
    print(f"Skiften med komplett texturdata: {len(x):,}")
    print(
        f"Robust urval: area >= {args.min_area_ha:g} ha, coverage >= {args.min_coverage:g}%, "
        f"minst {args.min_pixels} st 20 m-pixlar -> {len(practical):,} skiften"
    )
    print("OBS: ler/sand/silt är modellerade DSMS2025-värden på 20 m grid, inte jordprov.\n")

    for label, frame in (("BOKSTAVLIGT ALLA SKIFTEN", x), ("ROBUST/PRAKTISKT URVAL", practical)):
        print("-" * 112)
        print(label)
        print("-" * 112)
        for metric, title in (("clay_mean", "Mest lera"), ("sand_mean", "Mest sand")):
            print(f"\n{title} — topp {args.top}")
            z = frame.sort_values(metric, ascending=False).head(args.top)
            for i, (_, r) in enumerate(z.iterrows(), 1):
                print(f"{i:2d}. {fmt_row(r)}")

    # Persist a compact ranking for later map/QA use.
    out = []
    for selection, frame in (("all", x), ("robust", practical)):
        for metric in ("clay_mean", "sand_mean"):
            z = frame.sort_values(metric, ascending=False).head(max(args.top, 25)).copy()
            z.insert(0, "rank", np.arange(1, len(z) + 1))
            z.insert(0, "metric", metric)
            z.insert(0, "selection", selection)
            out.append(z[["selection", "metric", "rank", "kommun", "blockid", "skiftesbeteckning",
                          "area_ha", "clay_mean", "sand_mean", "silt_mean",
                          "texture_coverage_pct", "texture_n_pix", "lat", "lon"]])
    out_path = d / "soil_extremes_skiften.csv"
    pd.concat(out, ignore_index=True).to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\nRanking CSV: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
