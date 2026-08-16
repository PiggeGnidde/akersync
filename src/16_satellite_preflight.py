#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerSync Satellite V1a — Sentinel-2 catalogue preflight for Skåne.

Purpose of this first satellite step:
  * query the public Copernicus Data Space STAC catalogue (no pixel download),
  * discover which Sentinel-2 L2A MGRS tiles actually intersect Skåne farmland,
  * inventory observation dates/cloud metadata for a requested time interval,
  * verify that the expected red/NIR/SCL assets are advertised,
  * write deterministic CSV/JSON/TXT planning outputs for the next step.

No NDVI is calculated here and no satellite pixels are downloaded.  This is the
satellite equivalent of the DEM preflight/planning stage: understand footprint,
volume and catalogue metadata before building the data pipeline.
"""
from __future__ import annotations

import argparse
import json
import re
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import shape

from common import load_config

ROOT = Path(__file__).resolve().parents[1]
STAC_SEARCH = "https://stac.dataspace.copernicus.eu/v1/search"
COLLECTION = "sentinel-2-l2a"
TILE_RE = re.compile(r"_T([0-9]{2}[A-Z]{3})_")


def http_post_json(url: str, payload: dict, timeout: int = 90) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/geo+json, application/json",
            "User-Agent": "AkerSync-Satellite-Preflight/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        txt = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"STAC HTTP {e.code}: {txt[:1000]}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Kunde inte nå Copernicus STAC: {e}") from e


def mgrs_tile(item: dict) -> str:
    item_id = str(item.get("id", ""))
    m = TILE_RE.search(item_id)
    if m:
        return m.group(1)
    p = item.get("properties", {}) or {}
    for k in ("mgrs:tile", "s2:mgrs_tile", "grid:code"):
        v = p.get(k)
        if v:
            s = str(v).upper()
            if s.startswith("MGRS-"):
                s = s[5:]
            if s.startswith("T") and re.fullmatch(r"T[0-9]{2}[A-Z]{3}", s):
                s = s[1:]
            if re.fullmatch(r"[0-9]{2}[A-Z]{3}", s):
                return s
    return "UNKNOWN"


def iso_day(item: dict) -> str:
    p = item.get("properties", {}) or {}
    dt = str(p.get("datetime") or p.get("start_datetime") or "")
    return dt[:10]


def cloud(item: dict) -> float:
    v = (item.get("properties", {}) or {}).get("eo:cloud_cover")
    try:
        return float(v)
    except (TypeError, ValueError):
        return np.nan


def asset_present(keys: list[str], stem: str) -> bool:
    s = stem.upper()
    return any(str(k).upper() == s or str(k).upper().startswith(s + "_") for k in keys)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/local_paths.json")
    ap.add_argument("--start", default="2026-07-01", help="YYYY-MM-DD")
    ap.add_argument("--end", default="2026-07-31", help="YYYY-MM-DD")
    ap.add_argument("--limit", type=int, default=1000, help="STAC max items for preflight interval")
    args = ap.parse_args()

    root = ROOT
    cfg = load_config(root / args.config)
    outdir = root / cfg.get("build_dir", "data/derived")
    outdir.mkdir(parents=True, exist_ok=True)

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    if end < start:
        raise SystemExit("--end måste vara >= --start")

    print("=" * 108)
    print("ÅkerSync · Satellite V1a · Sentinel-2 L2A STAC preflight")
    print("=" * 108)
    print(f"Intervall: {args.start} — {args.end}")
    print("Steg 1 laddar ENDAST katalogmetadata; inga satellitpixlar hämtas.")

    blocks = gpd.read_file(cfg["blocks"])
    if blocks.crs is None:
        raise RuntimeError("Blocklagret saknar CRS")
    blocks = blocks.to_crs(3006)
    blocks = blocks[blocks.geometry.notna() & ~blocks.geometry.is_empty].copy()
    if len(blocks) == 0:
        raise RuntimeError("Inga blockgeometrier")

    blocks4326 = blocks.to_crs(4326)
    west, south, east, north = [float(x) for x in blocks4326.total_bounds]
    print(f"Skåne-block: {len(blocks):,}")
    print(f"BBox WGS84: {west:.6f}, {south:.6f}, {east:.6f}, {north:.6f}")

    query = {
        "collections": [COLLECTION],
        "bbox": [west, south, east, north],
        "datetime": f"{args.start}T00:00:00Z/{args.end}T23:59:59Z",
        "limit": args.limit,
        "fields": {
            "include": [
                "id", "bbox", "geometry", "properties.datetime", "properties.eo:cloud_cover",
                "properties.platform", "properties.sat:relative_orbit", "assets"
            ]
        },
        "sortby": [{"field": "properties.datetime", "direction": "asc"}],
    }
    print("Frågar Copernicus STAC …")
    result = http_post_json(STAC_SEARCH, query)
    items = result.get("features", [])
    if not isinstance(items, list):
        raise RuntimeError("Oväntat STAC-svar: features är inte en lista")
    if len(items) >= args.limit:
        print(f"VARNING: fick {len(items)} items = limit {args.limit}; intervallet kan vara trunkerat.")
    print(f"STAC-items i Skåne-bbox: {len(items):,}")
    if not items:
        raise RuntimeError("Inga Sentinel-2 L2A-items hittades för intervallet")

    # Determine which returned MGRS tile footprints truly touch at least one agricultural block.
    # This avoids counting bbox-corner tiles that contain no Skåne farmland.
    sindex = blocks.sindex
    tile_example: dict[str, dict] = {}
    for item in items:
        tile_example.setdefault(mgrs_tile(item), item)

    tile_block_count: dict[str, int] = {}
    for tile, item in tile_example.items():
        geom_json = item.get("geometry")
        if not geom_json:
            tile_block_count[tile] = 0
            continue
        g4326 = gpd.GeoSeries([shape(geom_json)], crs=4326)
        g3006 = g4326.to_crs(3006).iloc[0]
        hits = sindex.query(g3006, predicate="intersects")
        tile_block_count[tile] = int(len(hits))

    farmland_tiles = sorted(t for t, n in tile_block_count.items() if n > 0)
    bbox_only_tiles = sorted(t for t, n in tile_block_count.items() if n == 0)

    rows = []
    for item in items:
        tile = mgrs_tile(item)
        if tile not in farmland_tiles:
            continue
        p = item.get("properties", {}) or {}
        asset_keys = sorted((item.get("assets", {}) or {}).keys())
        rows.append({
            "tile": tile,
            "date": iso_day(item),
            "datetime": p.get("datetime"),
            "cloud_cover_pct": cloud(item),
            "platform": p.get("platform", ""),
            "relative_orbit": p.get("sat:relative_orbit", ""),
            "item_id": item.get("id", ""),
            "has_B04": asset_present(asset_keys, "B04"),
            "has_B08": asset_present(asset_keys, "B08"),
            "has_SCL": asset_present(asset_keys, "SCL"),
            "asset_key_count": len(asset_keys),
            "asset_keys": ",".join(asset_keys),
        })
    obs = pd.DataFrame(rows)
    if obs.empty:
        raise RuntimeError("STAC gav items men inget tile-footprint träffade jordbruksblock")

    summary_rows = []
    for tile in farmland_tiles:
        x = obs[obs.tile == tile].copy()
        cc = pd.to_numeric(x.cloud_cover_pct, errors="coerce")
        best_idx = cc.idxmin() if cc.notna().any() else None
        best = x.loc[best_idx] if best_idx is not None else None
        summary_rows.append({
            "tile": tile,
            "blocks_intersecting_tile": tile_block_count.get(tile, 0),
            "items": len(x),
            "unique_dates": x.date.nunique(),
            "cloud_le_10": int((cc <= 10).sum()),
            "cloud_le_20": int((cc <= 20).sum()),
            "cloud_le_40": int((cc <= 40).sum()),
            "median_cloud_pct": float(cc.median()) if cc.notna().any() else np.nan,
            "best_cloud_pct": float(cc.min()) if cc.notna().any() else np.nan,
            "best_date": str(best["date"]) if best is not None else "",
            "B04_all_items": bool(x.has_B04.all()),
            "B08_all_items": bool(x.has_B08.all()),
            "SCL_all_items": bool(x.has_SCL.all()),
        })
    tile_summary = pd.DataFrame(summary_rows).sort_values("tile")

    stem = f"sentinel2_preflight_{args.start.replace('-', '')}_{args.end.replace('-', '')}"
    obs_csv = outdir / f"{stem}_items.csv"
    tiles_csv = outdir / f"{stem}_tiles.csv"
    raw_json = outdir / f"{stem}_stac.json"
    txt = outdir / f"{stem}_summary.txt"
    obs.to_csv(obs_csv, index=False, encoding="utf-8-sig")
    tile_summary.to_csv(tiles_csv, index=False, encoding="utf-8-sig")
    raw_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "ÅkerSync Satellite V1a — Sentinel-2 L2A STAC preflight",
        f"Interval: {args.start} — {args.end}",
        f"Blocks: {len(blocks)}",
        f"BBox WGS84: {west:.6f},{south:.6f},{east:.6f},{north:.6f}",
        f"STAC bbox items: {len(items)}",
        f"Farmland MGRS tiles: {len(farmland_tiles)} — {', '.join(farmland_tiles)}",
        f"BBox-only tiles excluded: {len(bbox_only_tiles)} — {', '.join(bbox_only_tiles) if bbox_only_tiles else '-'}",
        "",
        "Per tile:",
    ]
    for r in tile_summary.itertuples(index=False):
        lines.append(
            f"  {r.tile}: blocks={r.blocks_intersecting_tile:,}, items={r.items}, dates={r.unique_dates}, "
            f"cloud<=20%={r.cloud_le_20}, best={r.best_cloud_pct:.1f}% ({r.best_date}), "
            f"B04/B08/SCL={r.B04_all_items}/{r.B08_all_items}/{r.SCL_all_items}"
        )
    lines += [
        "",
        "OBS: eo:cloud_cover är produkt/tile-metadata, inte molnandel över just jordbruksmarken.",
        "Nästa steg efter godkänd preflight är en liten pixel-PoC för några fält, inte hela Skåne direkt.",
    ]
    txt.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\nSentinel-2 tiles som faktiskt träffar minst ett Skåne-block:")
    for r in tile_summary.itertuples(index=False):
        print(
            f"  {r.tile}: block {r.blocks_intersecting_tile:6,d} | items {r.items:3d} | datum {r.unique_dates:2d} | "
            f"<=20% moln {r.cloud_le_20:2d} | bäst {r.best_cloud_pct:5.1f}% {r.best_date}"
        )
    if bbox_only_tiles:
        print("BBox-only tiles (ingen jordbruksmark):", ", ".join(bbox_only_tiles))

    print("\nAsset sanity:")
    print("  B04 alla items:", bool(obs.has_B04.all()))
    print("  B08 alla items:", bool(obs.has_B08.all()))
    print("  SCL alla items:", bool(obs.has_SCL.all()))
    print("\nOutput:")
    print(" ", tiles_csv)
    print(" ", obs_csv)
    print(" ", txt)
    print(" ", raw_json)
    print("\nSATELLITE PREFLIGHT: OK")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
