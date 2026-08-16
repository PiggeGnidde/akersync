#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Explore Geometry V1a without inventing a composite score.

Purpose:
- inspect interpretable extremes,
- create a strict multi-criterion shortlist for visual/expert QA,
- keep all component metrics visible.

The "Königsegg candidate" screen is NOT a score.  It is an intersection of
explicit top-decile criteria among reasonably sized fields.  Defaults:
  area >= 5 ha eligible population,
  no holes,
  top decile in area, rectangularity, convexity and ERL proxy.

A looser 3-of-4 screen is also exported for visual review.  Aspect ratio is
reported but deliberately not rewarded yet because we have not calibrated
whether 2:1, 4:1 or something else is operationally best.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from common import load_config


KEYS = ["blockid", "skiftesbeteckning"]
CRITERIA = ["area_ha", "rectangularity", "convexity", "erl_proxy_m"]


def add_locations(cfg, df):
    if df.empty:
        out = df.copy()
        out["lat"] = np.nan
        out["lon"] = np.nan
        return out
    s = gpd.read_file(cfg["skiften"])
    if s.crs is None:
        raise RuntimeError("Skiftefilen saknar CRS")
    s = s.to_crs(3006)
    s["blockid"] = s["blockid"].astype(str)
    s["skiftesbeteckning"] = s["skiftesbeteckning"].astype(str)
    wanted = set(zip(df.blockid.astype(str), df.skiftesbeteckning.astype(str)))
    s["_key"] = list(zip(s.blockid, s.skiftesbeteckning))
    x = s[s._key.isin(wanted)].copy()
    pts = gpd.GeoSeries(x.geometry.representative_point(), crs=x.crs).to_crs(4326)
    x["lon"] = pts.x.values
    x["lat"] = pts.y.values
    loc = x[KEYS + ["lat", "lon"]]
    return df.merge(loc, on=KEYS, how="left", validate="one_to_one")


def print_rows(title, df, n=10):
    print("\n" + title)
    print("-" * 132)
    if df.empty:
        print("  (inga)")
        return
    for i, r in enumerate(df.head(n).itertuples(index=False), 1):
        lat = getattr(r, "lat", np.nan)
        lon = getattr(r, "lon", np.nan)
        pos = f"{lat:.6f},{lon:.6f}" if np.isfinite(lat) and np.isfinite(lon) else "-"
        print(
            f"{i:2d}. {str(r.kommun):14s} block={str(r.blockid):11s} skifte={str(r.skiftesbeteckning):8s} "
            f"area={r.area_ha:7.2f} ha  rect={r.rectangularity:5.3f}  conv={r.convexity:5.3f}  "
            f"ERL={r.erl_proxy_m:7.1f} m  MBR={r.mbr_long_m:6.0f}×{r.mbr_short_m:5.0f} m "
            f"aspect={r.mbr_aspect_ratio:5.2f} holes={int(r.hole_count):2d}  lat,lon={pos}"
        )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/local_paths.json")
    ap.add_argument("--min-area-ha", type=float, default=5.0,
                    help="Minsta areal för den huvudsakliga maskinbarhets-explorationen")
    ap.add_argument("--quantile", type=float, default=0.90,
                    help="Tröskel för strikt kandidat-screen, default 0.90")
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    cfg = load_config(root / args.config)
    d = root / cfg.get("build_dir", "data/derived")
    src = d / "geometry_v1a_skiften.csv"
    if not src.exists():
        raise RuntimeError(f"Saknas: {src}. Kör RUN_GEOMETRY_V1A.bat först.")

    df = pd.read_csv(src, dtype={"blockid": str, "skiftesbeteckning": str, "kommun": str})
    for c in CRITERIA + [
        "mbr_long_m", "mbr_short_m", "mbr_aspect_ratio", "perimeter_per_ha_m",
        "hole_count", "hole_area_ha", "component_count"
    ]:
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    eligible = df[
        df.geometry_valid.fillna(False).astype(bool)
        & df.area_ha.ge(args.min_area_ha)
        & df[CRITERIA].notna().all(axis=1)
    ].copy()
    if eligible.empty:
        raise RuntimeError("Inga skiften klarade explorationsfiltret")

    q = float(args.quantile)
    thresholds = {c: float(eligible[c].quantile(q)) for c in CRITERIA}
    for c in CRITERIA:
        eligible[f"top_{int(q*100)}_{c}"] = eligible[c].ge(thresholds[c])
    flag_cols = [f"top_{int(q*100)}_{c}" for c in CRITERIA]
    eligible["criteria_met"] = eligible[flag_cols].sum(axis=1).astype(int)
    eligible["hole_free"] = eligible.hole_count.fillna(0).eq(0)

    strict = eligible[eligible.hole_free & eligible.criteria_met.eq(len(CRITERIA))].copy()
    loose = eligible[eligible.hole_free & eligible.criteria_met.ge(len(CRITERIA)-1)].copy()

    # No weighted score. Sorting only makes the console deterministic/readable.
    strict = strict.sort_values(["area_ha", "erl_proxy_m", "rectangularity"], ascending=False)
    loose = loose.sort_values(["criteria_met", "area_ha", "erl_proxy_m"], ascending=False)

    # Selected transparent extremes for expert/visual sanity checking.
    largest = eligible.nlargest(10, "area_ha")
    longest = eligible.nlargest(10, "erl_proxy_m")
    most_rect = eligible.nlargest(10, "rectangularity")
    least_rect = eligible.nsmallest(10, "rectangularity")
    least_convex = eligible.nsmallest(10, "convexity")
    perimeter_heavy = eligible.nlargest(10, "perimeter_per_ha_m")
    most_elongated = eligible.nlargest(10, "mbr_aspect_ratio")

    selected_keys = pd.concat([
        strict[KEYS], loose.head(50)[KEYS], largest[KEYS], longest[KEYS], most_rect[KEYS],
        least_rect[KEYS], least_convex[KEYS], perimeter_heavy[KEYS], most_elongated[KEYS]
    ]).drop_duplicates()
    selected = eligible.merge(selected_keys, on=KEYS, how="inner")
    loc = add_locations(cfg, selected[KEYS])
    loc = loc[KEYS + ["lat", "lon"]]

    def with_loc(x):
        return x.merge(loc, on=KEYS, how="left", validate="one_to_one")

    strict = with_loc(strict)
    loose = with_loc(loose)
    largest = with_loc(largest)
    longest = with_loc(longest)
    most_rect = with_loc(most_rect)
    least_rect = with_loc(least_rect)
    least_convex = with_loc(least_convex)
    perimeter_heavy = with_loc(perimeter_heavy)
    most_elongated = with_loc(most_elongated)

    strict_path = d / "geometry_v1a_koenigsegg_strict_candidates.csv"
    loose_path = d / "geometry_v1a_koenigsegg_loose_candidates.csv"
    eligible_path = d / "geometry_v1a_exploration_eligible.csv"
    thresholds_path = d / "geometry_v1a_candidate_thresholds.txt"
    strict.to_csv(strict_path, index=False, encoding="utf-8-sig")
    loose.to_csv(loose_path, index=False, encoding="utf-8-sig")
    eligible.to_csv(eligible_path, index=False, encoding="utf-8-sig")
    thresholds_path.write_text(
        "ÅkerSync Geometry V1a — score-free candidate screen\n"
        "==================================================\n"
        "NOT a machineability score. Explicit multi-criterion screen only.\n"
        f"Eligible population: valid geometry, area >= {args.min_area_ha:g} ha.\n"
        f"Strict screen: no holes + top {100*(1-q):g}% in all four criteria below.\n"
        f"Loose screen: no holes + at least 3 of 4 criteria.\n\n"
        + "\n".join(f"{c}: >= {thresholds[c]:.6f}" for c in CRITERIA)
        + "\n\nAspect ratio is reported but deliberately not optimized/calibrated yet.\n",
        encoding="utf-8",
    )

    print("=" * 132)
    print("ÅkerSync · Geometry V1a · extremer + score-fri Königsegg-screen")
    print("=" * 132)
    print(f"Skiften totalt:                 {len(df):,}")
    print(f"Explorationspopulation >= {args.min_area_ha:g} ha: {len(eligible):,}")
    print(f"Top-decile tröskel q={q:.2f}:")
    for c in CRITERIA:
        print(f"  {c:18s} >= {thresholds[c]:.4f}")
    print(f"Strikt 4/4 + inga hål:          {len(strict):,}")
    print(f"Lös 3+/4 + inga hål:           {len(loose):,}")

    print_rows("Königsegg-screen · strikt 4/4 (ingen score)", strict, 15)
    print_rows("Störst areal · endast råmått", largest)
    print_rows("Längst ERL-proxy · endast råmått", longest)
    print_rows("Högst rectangularity · endast råmått", most_rect)
    print_rows("Lägst rectangularity · >= min areal", least_rect)
    print_rows("Lägst convexity · >= min areal", least_convex)
    print_rows("Mest kant per hektar · >= min areal", perimeter_heavy)
    print_rows("Mest långsmala MBR · observation, ej värdering", most_elongated)

    print("\nOutput:")
    print(" ", strict_path)
    print(" ", loose_path)
    print(" ", eligible_path)
    print(" ", thresholds_path)
    print("\nNästa steg efter detta är visuell + senior maskinförar-QA, inte en viktad score.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
