#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import box

from common import load_config, MUN_CODES

TILE = 2500.0
TOPO_BUFFER = 170.0


def main():
    root = Path(__file__).resolve().parents[1]
    cfg = load_config(root / "config" / "local_paths.json")
    miss_path = root / "data" / "derived" / "dem_still_missing_skane.csv"
    if not miss_path.exists():
        raise SystemExit("Kör CHECK_SKANE_DEM.bat först.")

    gaps = pd.read_csv(miss_path)
    core = gaps[gaps["core_farmland"].astype(str).str.lower().isin(["true", "1"])].copy()
    if core.empty:
        print("Inga saknade core-rutor.")
        return

    blocks = gpd.read_file(cfg["blocks"]).to_crs(3006)
    codes = tuple(MUN_CODES.values())
    blocks = blocks[blocks.region_kod.astype(str).str.startswith(codes)].copy()
    blocks["region_kod_s"] = blocks.region_kod.astype(str)

    rows = []
    print("=" * 88)
    print("ÅkerSync · detaljgranskning av saknade DEM core-rutor")
    print("=" * 88)
    print("Core i DEM-planen betyder åkermark + 170 m topografibuffer.")
    print("Vi skiljer nu verklig åkermark i rutan från buffer-only-träffar.\n")

    for _, r in core.sort_values(["lower_left_y", "lower_left_x"], ascending=[False, True]).iterrows():
        x = float(r.lower_left_x)
        y = float(r.lower_left_y)
        tile = box(x, y, x + TILE, y + TILE)

        # Spatial-index first pass keeps the exact intersections cheap.
        idx = list(blocks.sindex.query(tile, predicate="intersects"))
        cand = blocks.iloc[idx].copy() if idx else blocks.iloc[0:0].copy()

        actual_area_m2 = 0.0
        actual_blocks = []
        municipalities = set()
        if not cand.empty:
            for _, b in cand.iterrows():
                g = b.geometry
                if g is None or g.is_empty:
                    continue
                inter = g.intersection(tile)
                if not inter.is_empty:
                    a = float(inter.area)
                    if a > 0:
                        actual_area_m2 += a
                        actual_blocks.append(str(b.get("blockid", "")))
                        code = str(b.region_kod_s)[:4]
                        for name, c in MUN_CODES.items():
                            if c == code:
                                municipalities.add(name)
                                break

        # If no actual farmland intersects the tile, measure distance to nearest block.
        nearest_m = 0.0 if actual_area_m2 > 0 else float(blocks.geometry.distance(tile).min())

        # Quantify why the tile was classified as core in the planner: intersection
        # of the 170 m buffered farmland with the tile. This is diagnostic only.
        search = tile.buffer(TOPO_BUFFER)
        idxb = list(blocks.sindex.query(search, predicate="intersects"))
        bcand = blocks.iloc[idxb].copy() if idxb else blocks.iloc[0:0].copy()
        buffered_area_m2 = 0.0
        if not bcand.empty:
            # Union avoids double-counting overlapping buffers.
            buffered = bcand.geometry.buffer(TOPO_BUFFER).union_all()
            buffered_area_m2 = float(buffered.intersection(tile).area)

        cls = "ACTUAL_FARMLAND" if actual_area_m2 > 0 else "BUFFER_ONLY"
        ha = actual_area_m2 / 10000.0
        bha = buffered_area_m2 / 10000.0
        muni_txt = ",".join(sorted(municipalities)) if municipalities else "-"
        print(
            f"{r.filename:<22} {cls:<15} "
            f"åkermark={ha:8.3f} ha  buffer={bha:8.3f} ha  "
            f"närmsta block={nearest_m:7.1f} m  kommun={muni_txt}"
        )

        rows.append({
            "filename": str(r.filename),
            "lower_left_x": int(x),
            "lower_left_y": int(y),
            "classification": cls,
            "actual_farmland_ha": ha,
            "buffered_farmland_170m_ha": bha,
            "nearest_block_m": nearest_m,
            "intersecting_block_count": len(set(actual_blocks)),
            "municipalities": muni_txt,
        })

    out = root / "data" / "derived" / "dem_missing_core_audit.csv"
    pd.DataFrame(rows).to_csv(out, index=False, encoding="utf-8-sig")

    n_actual = sum(r["classification"] == "ACTUAL_FARMLAND" for r in rows)
    actual_ha = sum(r["actual_farmland_ha"] for r in rows)
    n_buffer = len(rows) - n_actual
    print("\n" + "-" * 88)
    print(f"Saknade core-rutor:          {len(rows)}")
    print(f"  buffer-only:               {n_buffer}")
    print(f"  med faktisk åkermark:      {n_actual}")
    print(f"Faktisk åkermark utan DEM:   {actual_ha:.3f} ha")
    print("Audit CSV:", out)

    if n_actual == 0:
        print("\nCORE AUDIT: GRÖN — alla C-rutor är endast 170 m bufferträffar, ingen faktisk åkermark saknar DEM.")
    else:
        print("\nCORE AUDIT: GRANSKA — minst en saknad ruta innehåller faktisk åkermark.")
        print("Sätt inte DATA FREEZE innan dessa rutor har bedömts.")


if __name__ == "__main__":
    main()
