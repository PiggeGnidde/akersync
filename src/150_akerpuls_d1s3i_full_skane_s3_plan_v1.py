#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D1-S3i: freeze a full-Skane direct-S3 acquisition plan after D1-S3h PASS.

Public STAC only. No S3 object request/download, no Sentinel Hub Process call,
zero PU, no model execution and no geometry mutation.

The stage preserves the frozen D0/D0b 593 daily tile-date domain. It queries the
six frozen dates only once each over the full D0 tile envelope, intersects exact
STAC item geometries with exact D0 tiles, freezes scene ordering/assets, audits
the existing validated S3 asset cache, estimates disk use, and writes an exact
execution contract for a later guarded acquisition stage.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config" / "akerpuls_d1s3i_full_skane_s3_plan_v1.json"
PARENT = ROOT / "src" / "142_akerpuls_d1s3_parity_v1.py"


def log(msg: str) -> None:
    print(msg, flush=True)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def stable_json_bytes(obj: Any) -> bytes:
    return (json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    names = fieldnames or (list(rows[0].keys()) if rows else [])
    if not names:
        raise RuntimeError(f"Cannot infer columns for empty CSV {path}")
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=names)
        w.writeheader(); w.writerows(rows)


def git_guard(cfg: dict[str, Any]) -> tuple[str, str]:
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    if branch != cfg["feature_branch"]:
        raise RuntimeError(f"Expected branch {cfg['feature_branch']}, got {branch}")
    dirty = subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True).strip()
    if dirty:
        raise RuntimeError("Working tree must be clean")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    return branch, head


def flatten_snapshot_dates(contract: dict[str, Any]) -> list[str]:
    return [str(day) for _snap, days in contract["frozen_snapshots"].items() for day in days]


def _query_signature(cfg: dict[str, Any], day: str, bbox4326: list[float]) -> str:
    payload = {
        "url": cfg["direct_s3_backend"]["stac_search_url"],
        "collection": cfg["direct_s3_backend"]["collection"],
        "date": day,
        "bbox": [round(float(x), 9) for x in bbox4326],
    }
    return hashlib.sha256(stable_json_bytes(payload)).hexdigest()


def _http_json_with_retry(url: str, transport: dict[str, Any], call_counter: list[int]) -> dict[str, Any]:
    attempts = int(transport["max_attempts"])
    retry_codes = set(map(int, transport["retry_status_codes"]))
    base = float(transport["base_backoff_seconds"]); cap = float(transport["max_backoff_seconds"])
    for attempt in range(1, attempts + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AkerSync-AkerPuls-D1S3i/1.0"})
            call_counter[0] += 1
            with urllib.request.urlopen(req, timeout=120) as response:
                raw = response.read()
            time.sleep(float(transport["request_spacing_seconds"]))
            return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code not in retry_codes or attempt == attempts:
                raise
            wait = min(cap, base * (2 ** (attempt - 1)))
            log(f"D1S3I_STAC_RETRY status={exc.code} attempt={attempt}/{attempts} sleep={wait:.1f}s")
            time.sleep(wait)
        except urllib.error.URLError:
            if attempt == attempts:
                raise
            wait = min(cap, base * (2 ** (attempt - 1)))
            log(f"D1S3I_STAC_RETRY network_error attempt={attempt}/{attempts} sleep={wait:.1f}s")
            time.sleep(wait)
    raise RuntimeError("Unreachable STAC retry state")


def query_date(cfg: dict[str, Any], day: str, bbox4326: list[float], out: Path,
               parent: Any, call_counter: list[int]) -> list[dict[str, Any]]:
    """Query one frozen date with resumable local response cache."""
    cache = out / "stac" / day
    cache.mkdir(parents=True, exist_ok=True)
    sig = _query_signature(cfg, day, bbox4326)
    complete = cache / "complete.json"
    pages: list[dict[str, Any]] = []
    if bool(cfg["planning"]["reuse_completed_stac_date_queries_on_retry"]) and complete.is_file():
        meta = read_json(complete)
        if meta.get("query_signature_sha256") == sig:
            page_files = [cache / str(p) for p in meta.get("pages", [])]
            if page_files and all(p.is_file() for p in page_files):
                pages = [read_json(p) for p in page_files]
                log(f"D1S3I_STAC_CACHE date={day} pages={len(pages)}")

    if not pages:
        for p in cache.glob("page_*.json"):
            p.unlink()
        d = date.fromisoformat(day); nxt = d + timedelta(days=1)
        params = {
            "collections": cfg["direct_s3_backend"]["collection"],
            "bbox": ",".join(f"{float(x):.9f}" for x in bbox4326),
            "datetime": f"{d}T00:00:00Z/{nxt}T00:00:00Z",
            "limit": "100",
        }
        current = cfg["direct_s3_backend"]["stac_search_url"] + "?" + urllib.parse.urlencode(params)
        seen: set[str] = set()
        max_pages = int(cfg["stac_transport"]["maximum_pages_per_date"])
        while current:
            if current in seen:
                raise RuntimeError(f"STAC pagination loop on {day}")
            seen.add(current)
            doc = _http_json_with_retry(current, cfg["stac_transport"], call_counter)
            pages.append(doc)
            if len(pages) > max_pages:
                raise RuntimeError(f"STAC page guard exceeded on {day}")
            current = parent._next_link(doc, current)
        page_names = []
        for i, doc in enumerate(pages, 1):
            p = cache / f"page_{i:02d}.json"
            p.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            page_names.append(p.name)
        complete.write_text(json.dumps({
            "query_signature_sha256": sig, "date": day, "pages": page_names,
            "completed_utc": datetime.now(timezone.utc).isoformat(),
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    features: dict[str, dict[str, Any]] = {}
    for doc in pages:
        for feature in doc.get("features", []):
            if feature.get("id"):
                features[str(feature["id"])] = feature
    if not features:
        raise RuntimeError(f"No STAC items over full D0 envelope for frozen date {day}")
    max_items = int(cfg["stac_transport"]["maximum_items_per_date"])
    if len(features) > max_items:
        raise RuntimeError(f"STAC item guard exceeded on {day}: {len(features)} > {max_items}")
    return sorted(features.values(), key=parent.scene_sort_key, reverse=True)


def normalized_scene(feature: dict[str, Any], day: str, rank: int, cfg: dict[str, Any], parent: Any) -> dict[str, Any]:
    assets = feature.get("assets") or {}
    required = cfg["direct_s3_backend"]["assets"]
    missing = [key for key in required.values() if key not in assets]
    if missing:
        raise RuntimeError(f"STAC item {feature.get('id')} lacks required assets {missing}")
    props = feature.get("properties") or {}
    return {
        "date": day,
        "date_scene_rank": int(rank),
        "item_id": str(feature["id"]),
        "datetime": str(props.get("datetime") or ""),
        "created": str(props.get("created") or ""),
        "updated": str(props.get("updated") or ""),
        "cloud_cover": float(props.get("eo:cloud_cover") or 0.0),
        "geometry": feature.get("geometry"),
        "assets": {band: parent._normalize_asset(assets[key], band) for band, key in required.items()},
    }


def validate_parentage(cfg: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], str, str]:
    hpath = Path(cfg["d1s3h_manifest"])
    cpath = Path(cfg["d0b_final_execution_contract"])
    if not hpath.is_file() or not cpath.is_file():
        raise FileNotFoundError("D1-S3h manifest or D0b final execution contract missing")
    h = read_json(hpath); c = read_json(cpath)
    if h.get("status") != cfg["required_d1s3h_status"]:
        raise RuntimeError(f"D1-S3h status is {h.get('status')}, expected {cfg['required_d1s3h_status']}")
    if h.get("c7_frozen_status_preserved") != "REVIEW":
        raise RuntimeError("Historical C7 REVIEW provenance was not preserved by D1-S3h")
    if int(h.get("process_api_calls", -1)) != 0 or float(h.get("sentinel_hub_pu_used", -1)) != 0:
        raise RuntimeError("D1-S3h provenance unexpectedly used Process API/PU")
    ch = sha256_file(cpath)
    if ch != cfg["expected_final_execution_contract_sha256"]:
        raise RuntimeError(f"D0b final execution contract hash changed: {ch}")
    if int(c.get("frozen_geometry", {}).get("fields", -1)) != int(cfg["expected"]["fields"]):
        raise RuntimeError("Frozen field count changed")
    dates = flatten_snapshot_dates(c)
    if dates != list(cfg["expected"]["frozen_dates"]):
        raise RuntimeError(f"Frozen dates changed: {dates}")
    sem = cfg["direct_s3_backend"]
    hsem = h.get("backend_semantics", {})
    for key in ("scene_order", "coverage", "reflectance", "resampling"):
        if hsem.get(key) != sem[key]:
            raise RuntimeError(f"Direct-S3 semantic {key} differs from D1-S3h")
    if h.get("empty_frozen_date_policy") != sem["empty_daily_tile_policy"]:
        raise RuntimeError("Empty-date/tile policy differs from D1-S3h")
    if not bool(sem["frozen_from_d1s3e_and_confirmed_d1s3h"]):
        raise RuntimeError("Direct-S3 backend not marked frozen/confirmed")
    return h, c, sha256_file(hpath), ch


def audit_inputs(cfg: dict[str, Any], contract: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, str]]:
    reqp = Path(cfg["d0_request_plan"]); tilep = Path(cfg["d0_raster_tiles"]); snapp = Path(cfg["d0_snapshot_tile_plan"])
    for p in (reqp, tilep, snapp):
        if not p.is_file(): raise FileNotFoundError(p)
    req = pd.read_csv(reqp, encoding="utf-8-sig", dtype={"tile_id": str, "date": str})
    tiles = pd.read_csv(tilep, encoding="utf-8-sig", dtype={"tile_id": str})
    snaps = pd.read_csv(snapp, encoding="utf-8-sig", dtype={"tile_id": str, "snapshot": str})
    exp = cfg["expected"]
    if len(req) != int(exp["daily_tile_date_rows"]): raise RuntimeError(f"D0 request rows {len(req)} != {exp['daily_tile_date_rows']}")
    if len(tiles) != int(exp["raster_tiles"]): raise RuntimeError(f"D0 raster tiles {len(tiles)} != {exp['raster_tiles']}")
    if len(snaps) != int(exp["snapshot_tiles"]): raise RuntimeError(f"D0 snapshot tiles {len(snaps)} != {exp['snapshot_tiles']}")
    if req[["date", "tile_id"]].duplicated().any(): raise RuntimeError("Duplicate D0 daily tile-date row")
    if set(req.date.astype(str)) != set(map(str, exp["frozen_dates"])): raise RuntimeError("D0 request plan date set changed")
    if set(req.tile_id.astype(str)) - set(tiles.tile_id.astype(str)): raise RuntimeError("D0 request references unknown raster tile")
    if int(contract["request_plan"]["rows"]) != len(req) or contract["request_plan"]["sha256"] != sha256_file(reqp):
        raise RuntimeError("D0 request plan no longer matches D0b final execution contract")
    for col in ("upsampling", "downsampling"):
        if col not in req.columns or set(req[col].astype(str).str.upper()) != {"NEAREST"}:
            raise RuntimeError(f"D0 request {col} is not uniformly NEAREST")
    if "harmonize_values" not in req.columns or not req["harmonize_values"].astype(str).str.lower().isin(["true", "1"]).all():
        raise RuntimeError("D0 request harmonize_values changed")
    hashes = {"d0_request_plan_sha256": sha256_file(reqp), "d0_raster_tiles_sha256": sha256_file(tilep),
              "d0_snapshot_tile_plan_sha256": sha256_file(snapp)}
    return req, tiles, snaps, hashes


def cache_status(cache_root: Path, scene: dict[str, Any], band: str, parent: Any) -> tuple[str, Path]:
    p = parent.local_asset_path(cache_root, scene, band)
    if not p.is_file(): return "MISSING", p
    asset = scene["assets"][band]; expected = int(asset.get("bytes") or 0)
    if expected and p.stat().st_size != expected: return "CORRUPT_SIZE", p
    if not parent._multihash_ok(p, asset.get("checksum")): return "CORRUPT_CHECKSUM", p
    return "HIT_VERIFIED", p


def nearest_existing(path: Path) -> Path:
    p = path
    while not p.exists() and p.parent != p:
        p = p.parent
    if not p.exists():
        raise RuntimeError(f"No existing ancestor for storage path {path}")
    return p


def main() -> int:
    import geopandas as gpd
    from rasterio.warp import transform_bounds
    from shapely.geometry import box, shape

    ap = argparse.ArgumentParser(); ap.add_argument("--config", default=str(CFG)); ap.add_argument("--output-dir")
    args = ap.parse_args()
    cfg = read_json(Path(args.config))
    if cfg.get("schema_version") != "akerpuls-d1s3i-full-skane-s3-plan-v1": raise RuntimeError("Unexpected D1-S3i config schema")
    if any(bool(v) for v in cfg["guards"].values()): raise RuntimeError("D1-S3i forbidden-scope guard unexpectedly enabled")
    if not cfg["planning"]["no_asset_downloads"] or not cfg["planning"]["no_s3_object_calls"] or not cfg["planning"]["no_process_api_calls"]:
        raise RuntimeError("D1-S3i must remain STAC-only planning")
    if cfg["direct_s3_backend"]["process_cache_policy"] != "NEVER_READ_AS_SOURCE_FOR_FULL_SKANE_S3_EXECUTION; PROCESS_CACHE_IS_VALIDATION_EVIDENCE_ONLY":
        raise RuntimeError("Process-cache isolation policy changed")

    branch, head = git_guard(cfg)
    hman, contract, hsha, csha = validate_parentage(cfg)
    req, tiles, snaps, input_hashes = audit_inputs(cfg, contract)
    out = Path(args.output_dir or cfg["output_dir"]); out.mkdir(parents=True, exist_ok=True)
    parent = load_module(PARENT, "d1s3i_parent")

    minx, miny = float(tiles.minx.min()), float(tiles.miny.min())
    maxx, maxy = float(tiles.maxx.max()), float(tiles.maxy.max())
    bbox4326 = list(transform_bounds("EPSG:32633", "EPSG:4326", minx, miny, maxx, maxy, densify_pts=21))
    log(f"D1S3I_D0_TILE_ENVELOPE_32633={minx:.1f},{miny:.1f},{maxx:.1f},{maxy:.1f}")
    log("D1S3I_PROGRESS=QUERY_6_FROZEN_DATES_PUBLIC_STAC_ONLY")

    call_counter = [0]
    queried_features: dict[str, list[dict[str, Any]]] = {}
    scenes_by_date: dict[str, list[dict[str, Any]]] = {}
    for day in cfg["expected"]["frozen_dates"]:
        feats = query_date(cfg, day, bbox4326, out, parent, call_counter)
        queried_features[day] = feats
        scenes = [normalized_scene(f, day, i + 1, cfg, parent) for i, f in enumerate(feats)]
        scenes_by_date[day] = scenes
        log(f"D1S3I_STAC date={day} items={len(scenes)} first={scenes[0]['item_id']}")

    # Transform exact item footprints and map only the already frozen 593 D0 tile-date rows.
    log("D1S3I_PROGRESS=FREEZE_EXACT_TILE_SCENE_MAPPING")
    scene_geom_by_date: dict[str, dict[str, Any]] = {}
    for day, scenes in scenes_by_date.items():
        geoms = []
        ids = []
        for s in scenes:
            if not s.get("geometry"):
                raise RuntimeError(f"STAC item {s['item_id']} has no geometry")
            geom = shape(s["geometry"])
            if geom.is_empty or not geom.is_valid:
                raise RuntimeError(f"STAC item {s['item_id']} has invalid/empty geometry")
            geoms.append(geom); ids.append(s["item_id"])
        gg = gpd.GeoSeries(geoms, index=ids, crs=4326).to_crs(32633)
        scene_geom_by_date[day] = {str(idx): geom for idx, geom in gg.items()}

    scene_lookup = {s["item_id"]: s for ss in scenes_by_date.values() for s in ss}
    tile_lookup = {str(r.tile_id): box(float(r.minx), float(r.miny), float(r.maxx), float(r.maxy)) for r in tiles.itertuples(index=False)}
    daily_rows: list[dict[str, Any]] = []; map_rows: list[dict[str, Any]] = []
    used_items: set[str] = set(); zero_planned_rows = 0
    for r in req.sort_values(["date", "tile_id"]).itertuples(index=False):
        day, tid = str(r.date), str(r.tile_id); tg = tile_lookup[tid]
        matches = [s for s in scenes_by_date[day] if scene_geom_by_date[day][s["item_id"]].intersects(tg)]
        if not matches: zero_planned_rows += 1
        ids = [s["item_id"] for s in matches]; used_items.update(ids)
        daily_rows.append({
            "date": day, "snapshot": str(r.snapshot), "tile_id": tid,
            "minx": float(r.minx), "miny": float(r.miny), "maxx": float(r.maxx), "maxy": float(r.maxy),
            "width": int(r.width), "height": int(r.height), "scene_count": len(matches),
            "scene_ids_parent_order": ";".join(ids), "d0_planned_daily_source": True,
            "empty_daily_tile_policy_if_no_scene": cfg["direct_s3_backend"]["empty_daily_tile_policy"],
            "daily_output_relative": str(r.daily_output_relative),
        })
        for k, s in enumerate(matches, 1):
            map_rows.append({"date": day, "snapshot": str(r.snapshot), "tile_id": tid,
                             "tile_scene_order": k, "date_scene_rank": s["date_scene_rank"], "item_id": s["item_id"]})
    write_csv(out / "d1s3i_daily_tile_plan.csv", daily_rows)
    write_csv(out / "d1s3i_tile_scene_map.csv", map_rows,
              ["date", "snapshot", "tile_id", "tile_scene_order", "date_scene_rank", "item_id"])

    # Explicit frozen zero domain: 142*6 minus the 593 D0 rows. These are not expanded by current STAC.
    planned = {(str(r.date), str(r.tile_id)) for r in req.itertuples(index=False)}
    zero_rows = []
    date_to_snap = {str(day): str(snap) for snap, days in contract["frozen_snapshots"].items() for day in days}
    for day in cfg["expected"]["frozen_dates"]:
        for tid in sorted(tile_lookup):
            if (day, tid) not in planned:
                zero_rows.append({"date": day, "snapshot": date_to_snap[day], "tile_id": tid,
                                  "policy": "ZERO_BY_FROZEN_D0_REQUEST_DOMAIN", "physical_daily_file_required": False})
    write_csv(out / "d1s3i_frozen_zero_tile_dates.csv", zero_rows,
              ["date", "snapshot", "tile_id", "policy", "physical_daily_file_required"])

    scene_inventory = []
    used_scene_catalog = []
    used_tile_counts = pd.Series([r["item_id"] for r in map_rows], dtype=str).value_counts().to_dict() if map_rows else {}
    for day in cfg["expected"]["frozen_dates"]:
        for s in scenes_by_date[day]:
            used = s["item_id"] in used_items
            scene_inventory.append({"date": day, "date_scene_rank": s["date_scene_rank"], "item_id": s["item_id"],
                                    "datetime": s["datetime"], "created": s["created"], "updated": s["updated"],
                                    "cloud_cover": s["cloud_cover"], "used_in_frozen_d0_domain": used,
                                    "mapped_daily_tiles": int(used_tile_counts.get(s["item_id"], 0))})
            if used: used_scene_catalog.append(s)
    write_csv(out / "d1s3i_scene_inventory.csv", scene_inventory)
    catalog_path = out / "d1s3i_scene_catalog.json"
    catalog_path.write_bytes(stable_json_bytes({"schema_version": "akerpuls-d1s3i-scene-catalog-v1", "scenes": used_scene_catalog}))

    log("D1S3I_PROGRESS=AUDIT_EXACT_SOURCE_ASSETS_AND_LOCAL_CACHE")
    cache_root = Path(cfg["direct_s3_backend"]["source_asset_cache_root"])
    asset_rows = []; total_bytes = missing_bytes = cached_bytes = 0; corrupt = 0; zero_size = 0
    for s in used_scene_catalog:
        for band in cfg["direct_s3_backend"]["assets"]:
            a = s["assets"][band]; size = int(a.get("bytes") or 0); total_bytes += size
            if size <= 0: zero_size += 1
            status, lp = cache_status(cache_root, s, band, parent)
            if status == "HIT_VERIFIED": cached_bytes += size
            else:
                missing_bytes += size
                if status.startswith("CORRUPT_"): corrupt += 1
            asset_rows.append({"date": s["date"], "item_id": s["item_id"], "band": band, "s3_uri": a["s3_uri"],
                               "bytes": size, "checksum": a.get("checksum"), "scale": a.get("scale"), "offset": a.get("offset"),
                               "nodata": a.get("nodata"), "local_cache_path": str(lp), "cache_status": status})
    asset_rows.sort(key=lambda x: (x["date"], x["item_id"], x["band"]))
    write_csv(out / "d1s3i_asset_inventory.csv", asset_rows)

    source_gib = total_bytes / (1024 ** 3); missing_gib = missing_bytes / (1024 ** 3); cached_gib = cached_bytes / (1024 ** 3)
    # Upper bound before DEFLATE compression: 8-band daily sources + 11-band snapshot tiles, FLOAT32.
    tile_px = 1024 * 1024
    daily_uncompressed = len(req) * 8 * tile_px * 4
    snapshot_uncompressed = len(snaps) * 11 * tile_px * 4
    derived_uncompressed = daily_uncompressed + snapshot_uncompressed
    derived_gib = derived_uncompressed / (1024 ** 3)
    storage_anchor = nearest_existing(Path(cfg["direct_s3_backend"]["derived_full_skane_root"]))
    free_gib = shutil.disk_usage(storage_anchor).free / (1024 ** 3)
    worst_remaining = free_gib - missing_gib - derived_gib

    hashes = {
        **input_hashes,
        "scene_catalog_sha256": sha256_file(catalog_path),
        "scene_inventory_sha256": sha256_file(out / "d1s3i_scene_inventory.csv"),
        "daily_tile_plan_sha256": sha256_file(out / "d1s3i_daily_tile_plan.csv"),
        "tile_scene_map_sha256": sha256_file(out / "d1s3i_tile_scene_map.csv"),
        "asset_inventory_sha256": sha256_file(out / "d1s3i_asset_inventory.csv"),
        "frozen_zero_tile_dates_sha256": sha256_file(out / "d1s3i_frozen_zero_tile_dates.csv"),
    }
    rg = cfg["resource_guards"]
    checks = {
        "d1s3h_pass_parent": hman.get("status") == cfg["required_d1s3h_status"],
        "d0_daily_domain_exact": len(daily_rows) == int(cfg["expected"]["daily_tile_date_rows"]),
        "d0_snapshot_domain_exact": len(snaps) == int(cfg["expected"]["snapshot_tiles"]),
        "every_planned_daily_tile_has_scene": zero_planned_rows == 0,
        "scene_item_guard": len(used_scene_catalog) <= int(rg["maximum_unique_scene_items"]),
        "scene_asset_guard": len(asset_rows) <= int(rg["maximum_unique_scene_assets"]),
        "source_archive_guard": source_gib <= float(rg["maximum_source_archive_gib"]),
        "derived_uncompressed_guard": derived_gib <= float(rg["maximum_derived_uncompressed_gib"]),
        "disk_guard": worst_remaining >= float(rg["minimum_free_gib_after_missing_source_plus_uncompressed_derived"]),
        "asset_sizes_nonzero": (zero_size == 0) if bool(rg["require_nonzero_stac_file_size_for_all_assets"]) else True,
        "no_corrupt_local_cache_assets": (corrupt == 0) if bool(rg["require_no_corrupt_local_cache_assets"]) else True,
    }
    status = "PASS_TO_FULL_SKANE_S3_ACQUISITION" if all(checks.values()) else "REVIEW"

    execution_contract = {
        "schema_version": "akerpuls-full-skane-direct-s3-execution-contract-v1",
        "source_plan_schema": cfg["schema_version"],
        "parent_d1s3h": {"manifest_sha256": hsha, "required_status": cfg["required_d1s3h_status"], "c7_historical_status": "REVIEW"},
        "parent_d0b_execution_contract_sha256": csha,
        "frozen_geometry": contract["frozen_geometry"],
        "frozen_snapshots": contract["frozen_snapshots"],
        "analysis_partition": contract["analysis_partition"],
        "model_application": contract["model_application"],
        "direct_s3_backend": cfg["direct_s3_backend"],
        "d0_domain": {"raster_tiles": len(tiles), "daily_tile_dates": len(req), "snapshot_tiles": len(snaps), "frozen_zero_tile_dates": len(zero_rows)},
        "frozen_inputs": hashes,
        "source_assets": {"scene_items": len(used_scene_catalog), "assets": len(asset_rows), "total_bytes": total_bytes,
                          "cache_verified_assets_at_plan_time": sum(r["cache_status"] == "HIT_VERIFIED" for r in asset_rows),
                          "missing_or_unusable_assets_at_plan_time": sum(r["cache_status"] != "HIT_VERIFIED" for r in asset_rows)},
        "execution_policy": {
            "consume_exact_scene_catalog_and_tile_scene_map_without_requerying_or_adding_scene_ids": True,
            "build_all_593_daily_sources_from_direct_s3_scene_assets": True,
            "never_mix_process_tiles_into_full_skane_s3_sources": True,
            "use_process_cache_only_as_validation_evidence": True,
            "unplanned_d0_tile_dates_are_zero": True,
            "build_568_snapshot_tiles_with_frozen_pair_rule": True,
            "build_one_vrt_per_snapshot": True,
            "process_api_calls": False,
            "sentinel_hub_pu": False,
            "automatic_geometry_replacement": False,
        },
        "automatic_split": False, "automatic_merge": False, "automatic_geometry_replacement": False,
    }
    contract_path = out / "FULL_SKANE_S3_EXECUTION_CONTRACT.json"
    contract_path.write_bytes(stable_json_bytes(execution_contract))
    execution_sha = sha256_file(contract_path)

    manifest = {
        "schema_version": "akerpuls-d1s3i-full-skane-s3-plan-result-v1", "status": status,
        "generated_utc": datetime.now(timezone.utc).isoformat(), "git": {"branch": branch, "head": head},
        "d1s3h_manifest_sha256": hsha, "d0b_execution_contract_sha256": csha,
        "public_stac_http_calls_this_run": call_counter[0], "s3_object_network_calls": 0,
        "s3_asset_downloads": 0, "process_api_calls": 0, "sentinel_hub_pu_used": 0,
        "queried_items_total": sum(len(v) for v in scenes_by_date.values()), "used_scene_items": len(used_scene_catalog),
        "used_scene_assets": len(asset_rows), "planned_daily_tile_dates": len(req), "frozen_zero_tile_dates": len(zero_rows),
        "snapshot_tiles": len(snaps), "planned_daily_rows_without_scene": zero_planned_rows,
        "source_archive_gib": source_gib, "verified_cache_assets": sum(r["cache_status"] == "HIT_VERIFIED" for r in asset_rows),
        "verified_cache_gib": cached_gib, "missing_or_unusable_assets": sum(r["cache_status"] != "HIT_VERIFIED" for r in asset_rows),
        "missing_or_unusable_gib": missing_gib, "corrupt_cache_assets": corrupt, "zero_size_stac_assets": zero_size,
        "derived_uncompressed_gib_upper": derived_gib, "free_disk_gib": free_gib,
        "worst_case_free_after_missing_assets_plus_uncompressed_derived_gib": worst_remaining,
        "checks": checks, "frozen_file_hashes": hashes,
        "full_skane_s3_execution_contract_sha256": execution_sha,
        "full_skane_s3_executed": False, "full_skane_model_executed": False,
        "automatic_geometry_replacement": False, "interpretation": cfg["interpretation"],
    }
    (out / "d1s3i_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    qa = ["# ÅkerPuls D1-S3i full-Skåne direct-S3 plan", f"- Status: **{status}**",
          f"- Frozen D0 daily tile-date rows: {len(req)}", f"- Frozen zero tile-date rows: {len(zero_rows)}",
          f"- Snapshot tiles: {len(snaps)}", f"- Used scene items: {len(used_scene_catalog)}", f"- Used scene assets: {len(asset_rows)}",
          f"- Source archive: {source_gib:.3f} GiB", f"- Verified cache: {cached_gib:.3f} GiB", f"- Missing/unusable: {missing_gib:.3f} GiB",
          f"- Derived uncompressed upper bound: {derived_gib:.3f} GiB", f"- Free disk now: {free_gib:.3f} GiB",
          f"- Worst-case free after missing source + uncompressed derived: {worst_remaining:.3f} GiB",
          f"- Public STAC HTTP calls this run: {call_counter[0]}", "- S3 object calls/downloads: **0**", "- Sentinel Hub Process calls/PU: **0 / 0**",
          f"- Execution contract SHA256: `{execution_sha}`", "- Full-Skåne execution: **FALSE**", "- Automatic geometry replacement: **FALSE**"]
    (out / "d1s3i_qa.md").write_text("\n".join(qa) + "\n", encoding="utf-8")

    log("AKERPULS D1-S3I FULL-SKANE DIRECT-S3 PLAN - STAC ONLY / ZERO DOWNLOAD / ZERO PU")
    log(f"STATUS={status}")
    log(f"D0_RASTER_TILES={len(tiles)} DAILY_TILE_DATES={len(req)} FROZEN_ZERO_TILE_DATES={len(zero_rows)} SNAPSHOT_TILES={len(snaps)}")
    for day in cfg["expected"]["frozen_dates"]:
        used_day = {r['item_id'] for r in map_rows if r['date'] == day}
        daily_n = sum(1 for r in daily_rows if r['date'] == day)
        log(f"DATE_{day} STAC_ITEMS={len(scenes_by_date[day])} USED_ITEMS={len(used_day)} DAILY_TILES={daily_n}")
    log(f"USED_SCENE_ITEMS={len(used_scene_catalog)} USED_SCENE_ASSETS={len(asset_rows)}")
    log(f"SOURCE_ARCHIVE_GIB={source_gib:.3f} CACHE_VERIFIED_ASSETS={sum(r['cache_status']=='HIT_VERIFIED' for r in asset_rows)} CACHE_GIB={cached_gib:.3f}")
    log(f"MISSING_OR_UNUSABLE_ASSETS={sum(r['cache_status']!='HIT_VERIFIED' for r in asset_rows)} MISSING_OR_UNUSABLE_GIB={missing_gib:.3f} CORRUPT_CACHE_ASSETS={corrupt}")
    log(f"DERIVED_UNCOMPRESSED_GIB_UPPER={derived_gib:.3f} FREE_DISK_GIB={free_gib:.3f} WORST_CASE_FREE_GIB={worst_remaining:.3f}")
    log(f"PLANNED_DAILY_ROWS_WITHOUT_SCENE={zero_planned_rows}")
    log("PLAN_CHECKS=" + ";".join(f"{k}:{str(v).upper()}" for k, v in checks.items()))
    log(f"FULL_SKANE_S3_EXECUTION_CONTRACT_SHA256={execution_sha}")
    log(f"PUBLIC_STAC_HTTP_CALLS_THIS_RUN={call_counter[0]}")
    log("S3_OBJECT_NETWORK_CALLS=0")
    log("S3_ASSET_DOWNLOADS=0")
    log("PROCESS_API_CALLS=0")
    log("SENTINEL_HUB_PU_USED=0")
    log("FULL_SKANE_S3_EXECUTED=FALSE")
    log("FULL_SKANE_MODEL_EXECUTED=FALSE")
    log("AUTOMATIC_GEOMETRY_REPLACEMENT=FALSE")
    log(f"D1S3I_STATUS={status}")
    log(f"OUTPUT={out}")
    return 0 if status.startswith("PASS") else 2


if __name__ == "__main__":
    raise SystemExit(main())
