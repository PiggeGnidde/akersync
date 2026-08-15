#!/usr/bin/env python3
"""Plan DEM coverage for the Skåne MVP without running expensive terrain jobs.

ÅkerSync v0.92 was validated with Lantmäteriet's legacy 2.5 x 2.5 km MHM
GeoTIFF tiles.  From June 2026 Lantmäteriet's current Markhöjdmodell
Nedladdning is delivered as 10 x 10 km COG files through the STAC height API.

For Skåne we therefore use the current 10 km product.  The old 2.5 km geometry
is still calculated here because it is useful for comparing the validated MVP
coverage with the new regional extent.

Hydrology needs a contiguous terrain context.  We first build the legacy
farmland scope (+170 m topography context), add one legacy 2.5 km ring, then
snap that safe extent outwards to the current 10 km grid.  Ocean NoData is a
legitimate outlet and does not require synthetic elevation data.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import geopandas as gpd
import pandas as pd
from pyproj import Transformer

from common import load_config, MUN_CODES

LEGACY_TILE=2500
CURRENT_TILE=10000
TOPO_BUFFER=170.0


def snap_floor(v,tile):
    return int(math.floor(v/tile)*tile)


def snap_ceil(v,tile):
    return int(math.ceil(v/tile)*tile)


def tiles_for_bounds(bounds,tile):
    minx,miny,maxx,maxy=bounds
    x0=snap_floor(minx,tile); y0=snap_floor(miny,tile)
    x1=snap_floor(maxx-1e-9,tile); y1=snap_floor(maxy-1e-9,tile)
    return {(x,y) for x in range(x0,x1+tile,tile) for y in range(y0,y1+tile,tile)}


def legacy_filename(x,y):
    return f"{int(round(y/100))}_{int(round(x/100))}_25.tif"


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--config",default="config/local_paths.json")
    a=ap.parse_args()
    root=Path(__file__).resolve().parents[1]
    cfg=load_config(root/a.config)
    outdir=root/cfg.get("build_dir","data/derived");outdir.mkdir(parents=True,exist_ok=True)

    blocks=gpd.read_file(cfg["blocks"]).to_crs(3006)
    codes=tuple(MUN_CODES.values())
    blocks=blocks[blocks.region_kod.astype(str).str.startswith(codes)].copy()
    if len(blocks)==0:
        raise SystemExit("Inga Skåne-block hittades.")

    # Validated legacy 2.5 km planning geometry.
    core=set()
    for geom in blocks.geometry:
        if geom is None or geom.is_empty:continue
        core |= tiles_for_bounds(geom.buffer(TOPO_BUFFER).bounds,LEGACY_TILE)

    one=set(core)
    for x,y in list(core):
        for dx in (-LEGACY_TILE,0,LEGACY_TILE):
            for dy in (-LEGACY_TILE,0,LEGACY_TILE):
                one.add((x+dx,y+dy))

    legacy_minx=min(x for x,_ in one);legacy_maxx=max(x for x,_ in one)+LEGACY_TILE
    legacy_miny=min(y for _,y in one);legacy_maxy=max(y for _,y in one)+LEGACY_TILE
    legacy_rectangle={(x,y)
        for x in range(legacy_minx,legacy_maxx,LEGACY_TILE)
        for y in range(legacy_miny,legacy_maxy,LEGACY_TILE)}

    # Current Lantmäteriet 10 x 10 km COG extent, snapped OUTSIDE the safe
    # legacy one-ring rectangle.
    minx=snap_floor(legacy_minx,CURRENT_TILE)
    miny=snap_floor(legacy_miny,CURRENT_TILE)
    maxx=snap_ceil(legacy_maxx,CURRENT_TILE)
    maxy=snap_ceil(legacy_maxy,CURRENT_TILE)
    current={(x,y)
        for x in range(minx,maxx,CURRENT_TILE)
        for y in range(miny,maxy,CURRENT_TILE)}

    # The current STAC item/file names are discovered from the API rather than
    # manufactured from the old legacy filename convention.  These grid rows
    # are therefore coordinates / expected coverage cells, not download names.
    rows=[]
    for x,y in sorted(current,key=lambda p:(p[1],p[0])):
        rows.append({
            "lower_left_x":x,
            "lower_left_y":y,
            "right_x":x+CURRENT_TILE,
            "top_y":y+CURRENT_TILE,
            "grid_size_m":CURRENT_TILE,
        })
    pd.DataFrame(rows).to_csv(outdir/"dem_plan_skane.csv",index=False,encoding="utf-8-sig")

    # Keep legacy plan as a diagnostic only.
    dem_dir=Path(cfg["dem_dir"])
    existing_names={p.name.lower() for p in dem_dir.glob("*.tif")}
    legacy_rows=[]
    for x,y in sorted(legacy_rectangle,key=lambda p:(p[1],p[0])):
        fn=legacy_filename(x,y)
        legacy_rows.append({
            "filename":fn,
            "lower_left_x":x,
            "lower_left_y":y,
            "core_farmland":(x,y) in core,
            "one_ring":(x,y) in one,
            "already_downloaded":fn.lower() in existing_names,
        })
    ldf=pd.DataFrame(legacy_rows)
    ldf.to_csv(outdir/"dem_plan_skane_legacy_2p5km.csv",index=False,encoding="utf-8-sig")

    # STAC search uses WGS84 bbox by default.  Save both coordinate systems.
    tf=Transformer.from_crs(3006,4326,always_xy=True)
    west,south=tf.transform(minx,miny)
    east,north=tf.transform(maxx,maxy)

    bbox=outdir/"dem_plan_skane_bbox.txt"
    bbox.write_text(
        "Skåne DEM plan · CURRENT Markhöjdmodell 10 x 10 km COG\n"
        "SWEREF 99 TM (EPSG:3006)\n"
        f"left={minx}\nbottom={miny}\nright={maxx}\ntop={maxy}\n"
        f"tile_size_m={CURRENT_TILE}\n"
        "\nWGS84 / STAC bbox (west,south,east,north)\n"
        f"{west:.8f},{south:.8f},{east:.8f},{north:.8f}\n",
        encoding="utf-8")

    print("="*72)
    print("ÅkerSync · Skåne DEM-plan")
    print("="*72)
    print(f"Skåne-block: {len(blocks):,}")
    print("\nValiderad legacy-plan (2.5 km):")
    print(f"  Core farmland tiles (+{TOPO_BUFFER:g} m): {len(core):,}")
    print(f"  Core + one 2.5 km ring: {len(one):,}")
    print(f"  Contiguous rectangle: {len(legacy_rectangle):,}")
    print(f"  Befintliga legacy DEM-filer: {len(existing_names):,}")
    print(f"  Matchar legacy rectangle: {int(ldf.already_downloaded.sum()):,}")
    print("\nREKOMMENDERAD Skåne-MVP (nuvarande Lantmäteriet-produkt):")
    print(f"  Current 10 x 10 km grid cells: {len(current):,}")
    print(f"  BBox EPSG:3006: {minx}, {miny}, {maxx}, {maxy}")
    print(f"  STAC bbox WGS84: {west:.8f},{south:.8f},{east:.8f},{north:.8f}")
    print("\nOBS: ladda de nya 10 km COG-filerna till en SEPARAT dem_skane-mapp.")
    print("Blanda inte legacy 2.5 km och nya 10 km filer i samma DEM-mapp.")
    print("\nPlan:",outdir/"dem_plan_skane.csv")
    print("BBox:",bbox)


if __name__=="__main__":main()
