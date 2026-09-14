#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D1-S3j: execute the frozen full-Skane direct-S3 acquisition contract.

This stage never queries STAC and never calls Sentinel Hub Process API. It reads
only the exact D1-S3i frozen scene catalog/tile-scene map, downloads any missing
listed S3 assets into the validated source cache, derives all 593 daily 8-band
FLOAT32 tiles, derives all 568 frozen snapshot 11-band tiles, and builds four
VRT mosaics. The stage is resumable through SHA256-bound sidecars.

No model/fusion computation and no geometry mutation occur here.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config" / "akerpuls_d1s3j_full_skane_s3_acquisition_v1.json"
PARENT_CFG = ROOT / "config" / "akerpuls_d1s3_parity_v1.json"
PARENT = ROOT / "src" / "142_akerpuls_d1s3_parity_v1.py"
DIAG = ROOT / "src" / "143_akerpuls_d1s3b_diagnostic_v1.py"
B1 = ROOT / "src" / "112_akerpuls_prelim_fields_2026_b1_rasters.py"


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


def sha256_obj(obj: Any) -> str:
    return hashlib.sha256(stable_json_bytes(obj)).hexdigest()


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    names = fieldnames or (list(rows[0].keys()) if rows else [])
    if not names:
        raise RuntimeError(f"Cannot write empty CSV without columns: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
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


def canonical_dates(values: Any) -> list[str]:
    return sorted(str(x) for x in values)


def snapshot_order(contract: dict[str, Any]) -> list[str]:
    snaps = contract["frozen_snapshots"]
    return sorted(snaps, key=lambda s: min(str(d) for d in snaps[s]))


def meta_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".json")


def validate_raster(path: Path, count: int, width: int, height: int, transform: Any, crs: Any) -> None:
    import rasterio
    with rasterio.open(path) as ds:
        if ds.count != count or ds.width != width or ds.height != height:
            raise RuntimeError(f"Raster shape/count mismatch: {path}")
        if ds.transform != transform or ds.crs != crs:
            raise RuntimeError(f"Raster grid/CRS mismatch: {path}")
        if str(ds.dtypes[0]).lower() != "float32":
            raise RuntimeError(f"Raster dtype mismatch: {path}")


def cached_output(path: Path, key: str, count: int, width: int, height: int,
                  transform: Any, crs: Any) -> tuple[bool, str, int]:
    mp = meta_path(path)
    if not path.is_file() or not mp.is_file():
        return False, "", 0
    try:
        meta = read_json(mp)
    except Exception:
        return False, "", 0
    if meta.get("output_key_sha256") != key:
        return False, "", 0
    expected_sha = str(meta.get("file_sha256") or "")
    if not expected_sha or sha256_file(path) != expected_sha:
        return False, "", 0
    validate_raster(path, count, width, height, transform, crs)
    return True, expected_sha, int(path.stat().st_size)


def write_float32_raster_atomic(path: Path, arr: np.ndarray, transform: Any, crs: Any,
                                descriptions: list[str]) -> tuple[str, int]:
    import rasterio
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".partial")
    tmp.unlink(missing_ok=True)
    profile = {
        "driver": "GTiff", "width": arr.shape[2], "height": arr.shape[1],
        "count": arr.shape[0], "dtype": "float32", "crs": crs, "transform": transform,
        "compress": "DEFLATE", "predictor": 3, "tiled": True,
        "blockxsize": 256, "blockysize": 256,
    }
    with rasterio.open(tmp, "w", **profile) as ds:
        ds.write(arr.astype(np.float32, copy=False))
        for i, name in enumerate(descriptions, 1):
            ds.set_band_description(i, name)
    tmp.replace(path)
    return sha256_file(path), int(path.stat().st_size)


def finalize_sidecar(path: Path, payload: dict[str, Any], file_sha: str, file_bytes: int) -> None:
    mp = meta_path(path); tmp = mp.with_suffix(mp.suffix + ".partial")
    tmp.unlink(missing_ok=True)
    doc = {**payload, "file_sha256": file_sha, "file_bytes": int(file_bytes),
           "completed_utc": datetime.now(timezone.utc).isoformat()}
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(mp)


def source_asset_audit(scenes: list[dict[str, Any]], cache_root: Path, parent: Any) -> dict[str, Any]:
    total = missing = corrupt = verified = 0
    total_bytes = missing_bytes = 0
    for scene in scenes:
        for band in scene["assets"]:
            asset = scene["assets"][band]
            size = int(asset.get("bytes") or 0); total += 1; total_bytes += size
            p = parent.local_asset_path(cache_root, scene, band)
            if not p.is_file():
                missing += 1; missing_bytes += size; continue
            if size and p.stat().st_size != size:
                corrupt += 1; missing_bytes += size; continue
            if not parent._multihash_ok(p, asset.get("checksum")):
                corrupt += 1; missing_bytes += size; continue
            verified += 1
    return {"assets": total, "total_bytes": total_bytes, "verified": verified,
            "missing": missing, "corrupt": corrupt, "missing_bytes": missing_bytes}


def build_vrt(vrt_path: Path, tile_rows: pd.DataFrame, snapshot_paths: dict[str, Path],
              band_names: list[str], epsg: int, resolution: float) -> tuple[str, int, int, int]:
    from rasterio.crs import CRS
    import rasterio

    minx = float(tile_rows.minx.min()); miny = float(tile_rows.miny.min())
    maxx = float(tile_rows.maxx.max()); maxy = float(tile_rows.maxy.max())
    width = int(round((maxx - minx) / resolution)); height = int(round((maxy - miny) / resolution))
    if width <= 0 or height <= 0:
        raise RuntimeError("Invalid VRT dimensions")
    wkt = escape(CRS.from_epsg(epsg).to_wkt())
    lines = [f'<VRTDataset rasterXSize="{width}" rasterYSize="{height}">',
             f"  <SRS>{wkt}</SRS>",
             f"  <GeoTransform>{minx:.15g}, {resolution:.15g}, 0, {maxy:.15g}, 0, {-resolution:.15g}</GeoTransform>"]
    ordered = tile_rows.sort_values("tile_id")
    for bi, band_name in enumerate(band_names, 1):
        lines.append(f'  <VRTRasterBand dataType="Float32" band="{bi}">')
        lines.append(f"    <Description>{escape(band_name)}</Description>")
        for r in ordered.itertuples(index=False):
            tid = str(r.tile_id); src = snapshot_paths[tid]
            xoff = int(round((float(r.minx) - minx) / resolution))
            yoff = int(round((maxy - float(r.maxy)) / resolution))
            tw = int(round((float(r.maxx) - float(r.minx)) / resolution))
            th = int(round((float(r.maxy) - float(r.miny)) / resolution))
            lines += [
                "    <SimpleSource>",
                f'      <SourceFilename relativeToVRT="0">{escape(str(src))}</SourceFilename>',
                f"      <SourceBand>{bi}</SourceBand>",
                f'      <SourceProperties RasterXSize="{tw}" RasterYSize="{th}" DataType="Float32" BlockXSize="256" BlockYSize="256"/>',
                f'      <SrcRect xOff="0" yOff="0" xSize="{tw}" ySize="{th}"/>',
                f'      <DstRect xOff="{xoff}" yOff="{yoff}" xSize="{tw}" ySize="{th}"/>',
                "    </SimpleSource>",
            ]
        lines.append("  </VRTRasterBand>")
    lines.append("</VRTDataset>")
    vrt_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = vrt_path.with_suffix(vrt_path.suffix + ".partial")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(vrt_path)
    with rasterio.open(vrt_path) as ds:
        if ds.count != len(band_names) or ds.width != width or ds.height != height or ds.crs != CRS.from_epsg(epsg):
            raise RuntimeError(f"VRT verification failed: {vrt_path}")
    return sha256_file(vrt_path), int(vrt_path.stat().st_size), width, height


def main() -> int:
    import rasterio
    from rasterio.crs import CRS
    from rasterio.transform import from_bounds

    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(CFG))
    ap.add_argument("--work-output-dir")
    ap.add_argument("--derived-root")
    args = ap.parse_args()
    cfg = read_json(Path(args.config))
    if cfg.get("schema_version") != "akerpuls-d1s3j-full-skane-s3-acquisition-v1":
        raise RuntimeError("Unexpected D1-S3j config schema")
    if any(bool(v) for v in cfg["guards"].values()):
        raise RuntimeError("D1-S3j forbidden-scope guard unexpectedly enabled")
    if not bool(cfg["execution"]["never_query_stac"]) or not bool(cfg["execution"]["never_call_process_api"]):
        raise RuntimeError("D1-S3j network isolation policy changed")

    branch, head = git_guard(cfg)
    manifest_path = Path(cfg["d1s3i_manifest"])
    contract_path = Path(cfg["full_skane_s3_execution_contract"])
    if not manifest_path.is_file() or not contract_path.is_file():
        raise FileNotFoundError("D1-S3i manifest/contract missing")
    pman = read_json(manifest_path); contract = read_json(contract_path)
    contract_sha = sha256_file(contract_path)
    if pman.get("status") != cfg["required_d1s3i_status"]:
        raise RuntimeError(f"D1-S3i status changed: {pman.get('status')}")
    if contract_sha != cfg["expected_full_skane_s3_execution_contract_sha256"]:
        raise RuntimeError(f"Full-Skane S3 execution contract hash changed: {contract_sha}")
    if pman.get("full_skane_s3_execution_contract_sha256") != contract_sha:
        raise RuntimeError("D1-S3i manifest/contract SHA mismatch")
    policy = contract.get("execution_policy", {})
    required_policy = [
        "consume_exact_scene_catalog_and_tile_scene_map_without_requerying_or_adding_scene_ids",
        "build_all_593_daily_sources_from_direct_s3_scene_assets",
        "never_mix_process_tiles_into_full_skane_s3_sources",
        "unplanned_d0_tile_dates_are_zero",
        "build_568_snapshot_tiles_with_frozen_pair_rule",
    ]
    if not all(bool(policy.get(k)) for k in required_policy):
        raise RuntimeError("Frozen execution policy changed")
    if bool(policy.get("process_api_calls")) or bool(policy.get("sentinel_hub_pu")):
        raise RuntimeError("Frozen execution policy unexpectedly permits Process API/PU")

    exp = cfg["expected"]
    d0 = contract.get("d0_domain", {})
    if int(d0.get("raster_tiles", -1)) != int(exp["raster_tiles"]) or int(d0.get("daily_tile_dates", -1)) != int(exp["daily_tile_dates"]):
        raise RuntimeError("Frozen D0 domain changed")
    if int(d0.get("snapshot_tiles", -1)) != int(exp["snapshot_tiles"]) or int(d0.get("frozen_zero_tile_dates", -1)) != int(exp["frozen_zero_tile_dates"]):
        raise RuntimeError("Frozen snapshot/zero domain changed")
    dates = canonical_dates(d for days in contract["frozen_snapshots"].values() for d in days)
    if dates != canonical_dates(exp["frozen_dates"]):
        raise RuntimeError(f"Frozen dates changed: {dates}")

    paths = {
        "scene_catalog_sha256": Path(cfg["scene_catalog"]),
        "daily_tile_plan_sha256": Path(cfg["daily_tile_plan"]),
        "tile_scene_map_sha256": Path(cfg["tile_scene_map"]),
        "asset_inventory_sha256": Path(cfg["asset_inventory"]),
        "frozen_zero_tile_dates_sha256": Path(cfg["frozen_zero_tile_dates"]),
        "d0_raster_tiles_sha256": Path(cfg["d0_raster_tiles"]),
        "d0_snapshot_tile_plan_sha256": Path(cfg["d0_snapshot_tile_plan"]),
    }
    frozen_hashes = contract["frozen_inputs"]
    for key, path in paths.items():
        if not path.is_file(): raise FileNotFoundError(path)
        got = sha256_file(path)
        if got != frozen_hashes.get(key):
            raise RuntimeError(f"Frozen input hash mismatch {key}: {got}")

    catalog_doc = read_json(Path(cfg["scene_catalog"])); scenes = list(catalog_doc.get("scenes", []))
    if len(scenes) != int(exp["scene_items"]):
        raise RuntimeError(f"Scene catalog count {len(scenes)} != {exp['scene_items']}")
    scene_lookup = {str(s["item_id"]): s for s in scenes}
    if len(scene_lookup) != len(scenes): raise RuntimeError("Duplicate scene item IDs")
    if sum(len(s["assets"]) for s in scenes) != int(exp["scene_assets"]):
        raise RuntimeError("Scene asset count changed")

    daily = pd.read_csv(cfg["daily_tile_plan"], encoding="utf-8-sig", dtype={"tile_id": str, "date": str})
    mapping = pd.read_csv(cfg["tile_scene_map"], encoding="utf-8-sig", dtype={"tile_id": str, "date": str, "item_id": str})
    zeros = pd.read_csv(cfg["frozen_zero_tile_dates"], encoding="utf-8-sig", dtype={"tile_id": str, "date": str})
    tiles = pd.read_csv(cfg["d0_raster_tiles"], encoding="utf-8-sig", dtype={"tile_id": str})
    snap_plan = pd.read_csv(cfg["d0_snapshot_tile_plan"], encoding="utf-8-sig", dtype={"tile_id": str, "snapshot": str})
    if len(daily) != int(exp["daily_tile_dates"]) or len(zeros) != int(exp["frozen_zero_tile_dates"]):
        raise RuntimeError("Daily/zero frozen row count changed")
    if len(tiles) != int(exp["raster_tiles"]) or len(snap_plan) != int(exp["snapshot_tiles"]):
        raise RuntimeError("Raster/snapshot tile count changed")
    if daily[["date", "tile_id"]].duplicated().any() or mapping[["date", "tile_id", "tile_scene_order"]].duplicated().any():
        raise RuntimeError("Duplicate frozen daily/tile-scene mapping rows")
    if set(mapping.item_id.astype(str)) - set(scene_lookup):
        raise RuntimeError("Tile-scene map references item outside frozen catalog")
    map_counts = mapping.groupby(["date", "tile_id"]).size().to_dict()
    for r in daily.itertuples(index=False):
        if int(map_counts.get((str(r.date), str(r.tile_id)), 0)) != int(r.scene_count):
            raise RuntimeError(f"Scene-count mismatch for {r.date}/{r.tile_id}")

    work = Path(args.work_output_dir or cfg["work_output_dir"]); work.mkdir(parents=True, exist_ok=True)
    derived = Path(args.derived_root or cfg["derived_root"]); derived.mkdir(parents=True, exist_ok=True)
    cache_root = Path(cfg["source_asset_cache_root"]); cache_root.mkdir(parents=True, exist_ok=True)
    parent = load_module(PARENT, "d1s3j_parent")
    diag = load_module(DIAG, "d1s3j_diag")
    b1 = load_module(B1, "d1s3j_b1")
    parent_cfg = read_json(PARENT_CFG)

    log("D1S3J_PROGRESS=AUDIT_AND_DOWNLOAD_ONLY_FROZEN_SOURCE_ASSETS")
    before = source_asset_audit(scenes, cache_root, parent)
    rg = cfg["resource_guards"]
    before_total_gib = before["total_bytes"] / (1024 ** 3); before_missing_gib = before["missing_bytes"] / (1024 ** 3)
    if before["assets"] > int(rg["maximum_scene_assets"]): raise RuntimeError("Scene asset guard exceeded")
    if before_total_gib > float(rg["maximum_source_archive_gib"]): raise RuntimeError("Source archive guard exceeded")
    if before_missing_gib > float(rg["maximum_missing_download_gib_at_execution_start"]): raise RuntimeError("Missing-download guard exceeded")
    if before["corrupt"]:
        raise RuntimeError(f"Corrupt frozen source assets present: {before['corrupt']}; preserved for diagnosis")
    free_before = shutil.disk_usage(derived).free / (1024 ** 3)
    if free_before < float(rg["minimum_free_gib_before_execution"]): raise RuntimeError("Free-disk guard failed before execution")
    log(f"D1S3J_SOURCE_AUDIT assets={before['assets']} verified={before['verified']} missing={before['missing']} corrupt={before['corrupt']} total_gib={before_total_gib:.3f} missing_gib={before_missing_gib:.3f}")

    dlcfg = {**parent_cfg, "resource_guards": {**parent_cfg["resource_guards"],
             "maximum_unique_scene_assets": int(rg["maximum_scene_assets"]),
             "maximum_download_gib": float(rg["maximum_source_archive_gib"]),
             "minimum_free_gib_after_projected_download": float(rg["minimum_free_gib_after_execution"])}}
    downloads, source_cache_hits, downloaded_bytes = parent.download_assets([scenes], cache_root, dlcfg)
    after = source_asset_audit(scenes, cache_root, parent)
    if after["missing"] or after["corrupt"] or after["verified"] != int(exp["scene_assets"]):
        raise RuntimeError(f"Frozen source archive not complete after download: {after}")

    crs = CRS.from_epsg(int(exp["target_crs_epsg"])); width = height = int(exp["tile_pixels"])
    daily_desc = list(cfg["backend"]["daily_bands"]); snap_desc = list(cfg["backend"]["snapshot_bands"])
    daily_index: list[dict[str, Any]] = []; daily_sha: dict[tuple[str, str], str] = {}
    daily_built = daily_hits = 0
    log("D1S3J_PROGRESS=BUILD_593_DAILY_DIRECT_S3_TILES")
    sorted_daily = daily.sort_values(["date", "tile_id"]).reset_index(drop=True)
    for n, r in enumerate(sorted_daily.itertuples(index=False), 1):
        day, tid = str(r.date), str(r.tile_id)
        m = mapping[(mapping.date.astype(str) == day) & (mapping.tile_id.astype(str) == tid)].sort_values("tile_scene_order")
        scene_ids = m.item_id.astype(str).tolist()
        transform = from_bounds(float(r.minx), float(r.miny), float(r.maxx), float(r.maxy), width, height)
        rel = cfg["paths"]["daily_template"].format(date=day, tile_id=tid)
        path = derived / Path(rel)
        key_payload = {"schema": "akerpuls-d1s3j-daily-v1", "contract_sha256": contract_sha,
                       "date": day, "tile_id": tid, "scene_ids_parent_order": scene_ids,
                       "bbox": [float(r.minx), float(r.miny), float(r.maxx), float(r.maxy)],
                       "width": width, "height": height, "backend": cfg["backend"]}
        key = sha256_obj(key_payload)
        hit, fsha, fbytes = cached_output(path, key, int(exp["daily_bands"]), width, height, transform, crs)
        if hit:
            daily_hits += 1
        else:
            if scene_ids:
                scene_data = [diag.reproject_scene(scene_lookup[sid], cache_root, (height, width), transform, crs, parent) for sid in scene_ids]
                arr, _owner = diag.mosaic(scene_data, "PARENT", "SCL_NONZERO", "SCALE_OFFSET")
            else:
                arr = np.zeros((int(exp["daily_bands"]), height, width), dtype=np.float32)
            fsha, fbytes = write_float32_raster_atomic(path, arr, transform, crs, daily_desc)
            finalize_sidecar(path, {"schema_version": "akerpuls-d1s3j-daily-sidecar-v1",
                                    "output_key_sha256": key, "contract_sha256": contract_sha,
                                    "date": day, "tile_id": tid, "scene_ids_parent_order": scene_ids}, fsha, fbytes)
            daily_built += 1
        daily_sha[(day, tid)] = fsha
        daily_index.append({"date": day, "tile_id": tid, "scene_count": len(scene_ids), "path": str(path),
                            "sha256": fsha, "bytes": fbytes, "cache_hit": bool(hit)})
        if n % 10 == 0 or n == len(sorted_daily):
            log(f"D1S3J_DAILY_PROGRESS={n}/{len(sorted_daily)} BUILT={daily_built} CACHE_HITS={daily_hits}")
    write_csv(work / "d1s3j_daily_outputs.csv", daily_index)

    tile_lookup = {str(r.tile_id): r for r in tiles.itertuples(index=False)}
    planned = set(daily_sha)
    frozen_snaps = contract["frozen_snapshots"]
    snap_index: list[dict[str, Any]] = []; snapshot_built = snapshot_hits = 0
    snap_valid: dict[str, dict[str, float | int]] = {}
    log("D1S3J_PROGRESS=BUILD_568_FROZEN_SNAPSHOT_TILES")
    total_snap = int(exp["snapshot_tiles"]); done = 0
    for snap in snapshot_order(contract):
        snap_key = str(snap).lower(); days = [str(d) for d in frozen_snaps[snap]]
        valid_sum = 0; pixel_sum = 0; source_date_0 = 0; source_date_1 = 0
        snapshot_paths: dict[str, Path] = {}
        for tid in sorted(tile_lookup):
            tr = tile_lookup[tid]
            transform = from_bounds(float(tr.minx), float(tr.miny), float(tr.maxx), float(tr.maxy), width, height)
            arrays = []; source_tokens = []
            for day in days:
                if (day, tid) in planned:
                    dpath = derived / Path(cfg["paths"]["daily_template"].format(date=day, tile_id=tid))
                    arr, dtr, dcrs = b1.read_source(dpath, width, height)
                    if dtr != transform or dcrs != crs: raise RuntimeError(f"Daily grid mismatch {day}/{tid}")
                    arrays.append(arr); source_tokens.append(daily_sha[(day, tid)])
                else:
                    arrays.append(np.zeros((int(exp["daily_bands"]), height, width), dtype=np.float32)); source_tokens.append("ZERO_BY_FROZEN_D0_DOMAIN")
            out_arr = None
            rel = cfg["paths"]["snapshot_template"].format(snapshot=snap_key, tile_id=tid)
            path = derived / Path(rel); snapshot_paths[tid] = path
            key_payload = {"schema": "akerpuls-d1s3j-snapshot-v1", "contract_sha256": contract_sha,
                           "snapshot": snap, "tile_id": tid, "dates": days, "daily_source_tokens": source_tokens,
                           "backend": cfg["backend"]}
            key = sha256_obj(key_payload)
            hit, fsha, fbytes = cached_output(path, key, int(exp["snapshot_bands"]), width, height, transform, crs)
            if hit:
                snapshot_hits += 1
                with rasterio.open(path) as ds:
                    valid = ds.read(8); source_idx = ds.read(11)
            else:
                out_arr = b1.choose_pair(arrays, set(map(int, cfg["backend"]["clear_scl_codes"])))
                fsha, fbytes = write_float32_raster_atomic(path, out_arr, transform, crs, snap_desc)
                finalize_sidecar(path, {"schema_version": "akerpuls-d1s3j-snapshot-sidecar-v1",
                                        "output_key_sha256": key, "contract_sha256": contract_sha,
                                        "snapshot": snap, "tile_id": tid, "dates": days,
                                        "daily_source_tokens": source_tokens}, fsha, fbytes)
                snapshot_built += 1; valid = out_arr[7]; source_idx = out_arr[10]
            valid_sum += int(np.count_nonzero(valid > 0.5)); pixel_sum += int(valid.size)
            source_date_0 += int(np.count_nonzero(np.rint(source_idx).astype(np.int16) == 0))
            source_date_1 += int(np.count_nonzero(np.rint(source_idx).astype(np.int16) == 1)) if len(days) == 2 else 0
            snap_index.append({"snapshot": snap, "tile_id": tid, "dates": "+".join(days), "path": str(path),
                               "sha256": fsha, "bytes": fbytes, "cache_hit": bool(hit)})
            done += 1
            if done % 10 == 0 or done == total_snap:
                log(f"D1S3J_SNAPSHOT_PROGRESS={done}/{total_snap} BUILT={snapshot_built} CACHE_HITS={snapshot_hits}")
        snap_valid[snap] = {"valid_pixels": valid_sum, "pixels": pixel_sum,
                            "valid_fraction": float(valid_sum / pixel_sum) if pixel_sum else 0.0,
                            "source_date_index_0_pixels": source_date_0,
                            "source_date_index_1_pixels": source_date_1}
    write_csv(work / "d1s3j_snapshot_outputs.csv", snap_index)

    log("D1S3J_PROGRESS=BUILD_AND_VERIFY_4_SNAPSHOT_VRTS")
    vrt_rows = []
    for snap in snapshot_order(contract):
        snap_key = str(snap).lower()
        paths_for_snap = {tid: derived / Path(cfg["paths"]["snapshot_template"].format(snapshot=snap_key, tile_id=tid)) for tid in tile_lookup}
        vrt = derived / Path(cfg["paths"]["snapshot_vrt_template"].format(snapshot=snap_key))
        vsha, vbytes, vw, vh = build_vrt(vrt, tiles, paths_for_snap, snap_desc, int(exp["target_crs_epsg"]), float(exp["resolution_m"]))
        vrt_rows.append({"snapshot": snap, "path": str(vrt), "sha256": vsha, "bytes": vbytes, "width": vw, "height": vh, "bands": len(snap_desc)})
        log(f"D1S3J_VRT snapshot={snap} width={vw} height={vh} sha256={vsha}")
    write_csv(work / "d1s3j_vrt_outputs.csv", vrt_rows)

    free_after = shutil.disk_usage(derived).free / (1024 ** 3)
    checks = {
        "source_archive_complete": after["verified"] == int(exp["scene_assets"]) and after["missing"] == 0 and after["corrupt"] == 0,
        "daily_outputs_complete": len(daily_index) == int(exp["daily_tile_dates"]) and all(Path(r["path"]).is_file() for r in daily_index),
        "snapshot_outputs_complete": len(snap_index) == int(exp["snapshot_tiles"]) and all(Path(r["path"]).is_file() for r in snap_index),
        "vrt_outputs_complete": len(vrt_rows) == int(exp["snapshot_count"]) and all(Path(r["path"]).is_file() for r in vrt_rows),
        "free_disk_guard": free_after >= float(rg["minimum_free_gib_after_execution"]),
        "no_process_or_stac_execution_path": True,
        "model_not_executed": True,
        "automatic_geometry_replacement_false": True,
    }
    status = "PASS_TO_FULL_SKANE_D1_RASTER_QA" if all(checks.values()) else "REVIEW"
    hashes = {
        "daily_outputs_index_sha256": sha256_file(work / "d1s3j_daily_outputs.csv"),
        "snapshot_outputs_index_sha256": sha256_file(work / "d1s3j_snapshot_outputs.csv"),
        "vrt_outputs_index_sha256": sha256_file(work / "d1s3j_vrt_outputs.csv"),
    }
    manifest = {
        "schema_version": "akerpuls-d1s3j-full-skane-s3-acquisition-result-v1", "status": status,
        "generated_utc": datetime.now(timezone.utc).isoformat(), "git": {"branch": branch, "head": head},
        "full_skane_s3_execution_contract_sha256": contract_sha,
        "source_archive": {"scene_items": len(scenes), "assets": after["assets"], "verified_assets": after["verified"],
                           "downloads_this_run": int(downloads), "cache_hits_this_run": int(source_cache_hits),
                           "downloaded_bytes_this_run": int(downloaded_bytes)},
        "derived": {"root": str(derived), "daily_tiles": len(daily_index), "daily_built_this_run": daily_built,
                    "daily_cache_hits_this_run": daily_hits, "snapshot_tiles": len(snap_index),
                    "snapshot_built_this_run": snapshot_built, "snapshot_cache_hits_this_run": snapshot_hits,
                    "vrts": len(vrt_rows), "snapshot_validity_all_tile_pixels": snap_valid},
        "checks": checks, "output_index_hashes": hashes,
        "free_disk_gib_before": free_before, "free_disk_gib_after": free_after,
        "public_stac_http_calls": 0, "s3_object_downloads": int(downloads),
        "process_api_calls": 0, "sentinel_hub_pu_used": 0,
        "full_skane_model_executed": False, "automatic_geometry_replacement": False,
        "next_step": "Zero-network full-Skane D1 raster/field-validity QA before any D2 split/fusion model execution.",
        "interpretation": cfg["interpretation"],
    }
    (work / "d1s3j_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    log("AKERPULS D1-S3J FULL-SKANE DIRECT-S3 ACQUISITION")
    log(f"STATUS={status}")
    log(f"SOURCE_ASSETS={after['assets']} VERIFIED={after['verified']} DOWNLOADS_THIS_RUN={downloads} SOURCE_CACHE_HITS={source_cache_hits} DOWNLOADED_GIB={downloaded_bytes/(1024**3):.3f}")
    log(f"DAILY_TILES={len(daily_index)} BUILT_THIS_RUN={daily_built} CACHE_HITS={daily_hits}")
    log(f"SNAPSHOT_TILES={len(snap_index)} BUILT_THIS_RUN={snapshot_built} CACHE_HITS={snapshot_hits}")
    for snap in snapshot_order(contract):
        s = snap_valid[snap]
        log(f"SNAPSHOT_{snap}_VALID_ALL_TILE_PIXELS={s['valid_fraction']:.6f}")
    log(f"VRTS={len(vrt_rows)}")
    log("CHECKS=" + ";".join(f"{k}:{str(v).upper()}" for k, v in checks.items()))
    log(f"FREE_DISK_GIB_BEFORE={free_before:.3f} AFTER={free_after:.3f}")
    log(f"DAILY_OUTPUT_INDEX_SHA256={hashes['daily_outputs_index_sha256']}")
    log(f"SNAPSHOT_OUTPUT_INDEX_SHA256={hashes['snapshot_outputs_index_sha256']}")
    log(f"VRT_OUTPUT_INDEX_SHA256={hashes['vrt_outputs_index_sha256']}")
    log("PUBLIC_STAC_HTTP_CALLS=0")
    log(f"S3_OBJECT_DOWNLOADS={downloads}")
    log("PROCESS_API_CALLS=0")
    log("SENTINEL_HUB_PU_USED=0")
    log("FULL_SKANE_MODEL_EXECUTED=FALSE")
    log("AUTOMATIC_GEOMETRY_REPLACEMENT=FALSE")
    log(f"D1S3J_STATUS={status}")
    log(f"OUTPUT={work}")
    return 0 if status == "PASS_TO_FULL_SKANE_D1_RASTER_QA" else 2


if __name__ == "__main__":
    raise SystemExit(main())
