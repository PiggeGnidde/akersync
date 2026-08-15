#!/usr/bin/env python3
"""Plan DEM coverage for the Skåne MVP without running expensive terrain jobs.

The validated engines use Lantmäteriet 2.5 km MHM tiles.  This script reads the
Jordbruksverket block geometry and reports three useful tile scopes:

  core       tiles touched by Skåne farmland (+170 m topography context)
  one_ring   core plus one neighbouring 2.5 km tile in every direction
  rectangle  a contiguous rectangular tile grid around the one-ring extent

The contiguous rectangle is useful for hydrology because missing inland DEM
patches become artificial flow boundaries.  Ocean NoData is still legitimate.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import geopandas as gpd
import pandas as pd

from common import load_config, MUN_CODES

TILE=2500
TOPO_BUFFER=170.0


def snap_floor(v):
    return int(math.floor(v/TILE)*TILE)


def tiles_for_bounds(bounds):
    minx,miny,maxx,maxy=bounds
    x0=snap_floor(minx); y0=snap_floor(miny)
    # tiny epsilon keeps exact upper tile boundaries from adding an extra tile
    x1=snap_floor(maxx-1e-9); y1=snap_floor(maxy-1e-9)
    return {(x,y) for x in range(x0,x1+TILE,TILE) for y in range(y0,y1+TILE,TILE)}


def filename(x,y):
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

    core=set()
    for geom in blocks.geometry:
        if geom is None or geom.is_empty:continue
        core |= tiles_for_bounds(geom.buffer(TOPO_BUFFER).bounds)

    one=set(core)
    for x,y in list(core):
        for dx in (-TILE,0,TILE):
            for dy in (-TILE,0,TILE):
                one.add((x+dx,y+dy))

    minx=min(x for x,_ in one);maxx=max(x for x,_ in one)
    miny=min(y for _,y in one);maxy=max(y for _,y in one)
    rectangle={(x,y) for x in range(minx,maxx+TILE,TILE) for y in range(miny,maxy+TILE,TILE)}

    dem_dir=Path(cfg["dem_dir"])
    existing_names={p.name.lower() for p in dem_dir.glob("*.tif")}
    rows=[]
    for x,y in sorted(rectangle,key=lambda p:(p[1],p[0])):
        fn=filename(x,y)
        rows.append({
            "filename":fn,
            "lower_left_x":x,
            "lower_left_y":y,
            "core_farmland":(x,y) in core,
            "one_ring":(x,y) in one,
            "contiguous_rectangle":True,
            "already_downloaded":fn.lower() in existing_names,
        })
    df=pd.DataFrame(rows)
    csv=outdir/"dem_plan_skane.csv";df.to_csv(csv,index=False,encoding="utf-8-sig")

    # Convenience outputs for the next acquisition step.  The missing list is
    # intentionally just one exact legacy filename per line so it can be used
    # for manual checking or by a later downloader without parsing CSV.
    missing=df.loc[~df.already_downloaded].copy()
    existing=df.loc[df.already_downloaded].copy()
    missing_csv=outdir/"dem_plan_skane_missing.csv"
    missing.to_csv(missing_csv,index=False,encoding="utf-8-sig")
    missing_txt=outdir/"dem_missing_skane_2p5km.txt"
    missing_txt.write_text("\n".join(missing.filename.astype(str))+"\n",encoding="utf-8")
    existing_txt=outdir/"dem_existing_skane_2p5km.txt"
    existing_txt.write_text("\n".join(existing.filename.astype(str))+"\n",encoding="utf-8")

    bbox=outdir/"dem_plan_skane_bbox.txt"
    bbox.write_text(
        "Skåne DEM plan · SWEREF 99 TM (EPSG:3006)\n"
        f"left={minx}\nbottom={miny}\nright={maxx+TILE}\ntop={maxy+TILE}\n"
        f"tile_size_m={TILE}\n",
        encoding="utf-8")

    print("="*72)
    print("ÅkerSync · Skåne DEM-plan")
    print("="*72)
    print(f"Skåne-block: {len(blocks):,}")
    print(f"Core farmland tiles (+{TOPO_BUFFER:g} m): {len(core):,}")
    print(f"Core + one 2.5 km ring: {len(one):,}")
    print(f"Contiguous rectangle: {len(rectangle):,}")
    print(f"DEM-filer redan i {dem_dir}: {len(existing_names):,}")
    print(f"Matchar rectangle-namn: {int(df.already_downloaded.sum()):,}")
    print(f"Saknas i rectangle: {len(missing):,}")
    print(f"BBox EPSG:3006: {minx}, {miny}, {maxx+TILE}, {maxy+TILE}")
    print("\nOBS: hydrologi behöver sammanhängande terrängkontext; enbart fältrutor")
    print("kan skapa konstgjorda NoData-kanter. Rectangle är därför den säkra")
    print("första Skåne-MVP-planen; havsrutor kan naturligt saknas.")
    print("\nPlan:",csv)
    print("Missing CSV:",missing_csv)
    print("Missing filenames:",missing_txt)
    print("BBox:",bbox)


if __name__=="__main__":main()
