#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import box

from common import load_config, MUN_CODES

TILE = 2500.0
TOPO_BUFFER = 170.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/local_paths.json")
    ap.add_argument("--missing", default="data/derived/dem_still_missing_skane.csv")
    a = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    cfg = load_config(root / a.config)
    missing_path = root / a.missing if not Path(a.missing).is_absolute() else Path(a.missing)
    if not missing_path.exists():
        raise SystemExit(f"Missing-lista saknas: {missing_path}")

    gaps = pd.read_csv(missing_path)
    core = gaps[gaps["core_farmland"].astype(str).str.lower().isin(["true", "1"])]
    if core.empty:
        print("Inga saknade core-rutor.")
        return

    blocks = gpd.read_file(cfg["blocks"]).to_crs(3006)
    codes = tuple(MUN_CODES.values())
    blocks = blocks[blocks.region_kod.astype(str).str.startswith(codes)].copy()
    blocks = blocks[blocks.geometry.notna() & ~blocks.geometry.is_empty].copy()

    print("=" * 72)
    print("ÅkerSync · inspektion av saknade DEM core-rutor")
    print("=" * 72)

    for _, r in core.iterrows():
        x = float(r["lower_left_x"])
        y = float(r["lower_left_y"])
        tile = box(x, y, x + TILE, y + TILE)

        # Fast candidate reduction, then exact geometry tests.
        cand = blocks.cx[x - TOPO_BUFFER:x + TILE + TOPO_BUFFER,
                         y - TOPO_BUFFER:y + TILE + TOPO_BUFFER].copy()

        actual = cand[cand.geometry.intersects(tile)].copy()
        actual_area = 0.0
        if not actual.empty:
            actual_area = float(actual.geometry.intersection(tile).area.sum())

        buffered_geoms = cand.geometry.buffer(TOPO_BUFFER)
        buf_mask = buffered_geoms.intersects(tile)
        buf_area = 0.0
        if buf_mask.any():
            buf_area = float(buffered_geoms[buf_mask].intersection(tile).area.sum())

        min_dist = float(cand.geometry.distance(tile).min()) if not cand.empty else float("nan")

        mun_codes = sorted(set(actual.region_kod.astype(str))) if not actual.empty else []
        if not mun_codes and not cand.empty:
            near = cand[cand.geometry.distance(tile) <= TOPO_BUFFER + 1e-9]
            mun_codes = sorted(set(near.region_kod.astype(str)))

        print(f"\n{r['filename']}")
        print(f"  Tile EPSG:3006: x={int(x)}..{int(x+TILE)}, y={int(y)}..{int(y+TILE)}")
        print(f"  Block som faktiskt skar tile: {len(actual):,}")
        print(f"  Faktisk jordbruksareal i tile: {actual_area/10000.0:.6f} ha")
        print(f"  +{int(TOPO_BUFFER)} m buffertarea i tile: {buf_area/10000.0:.6f} ha")
        print(f"  Minsta avstånd från block till tile: {min_dist:.3f} m")
        print(f"  region_kod nära/i tile: {', '.join(mun_codes) if mun_codes else '-'}")

        if actual_area <= 1e-6:
            print("  BEDÖMNING: ingen faktisk åkeryta ligger i den saknade DEM-rutan.")
            if min_dist <= TOPO_BUFFER + 1e-9:
                print("  Core-flaggan kommer från 170 m kontext/bounding-box, inte från åkeryta i rutan.")
        else:
            print("  BEDÖMNING: faktisk åkeryta ligger i saknad DEM-ruta — måste lösas före BUILD_ALL.")


if __name__ == "__main__":
    main()
