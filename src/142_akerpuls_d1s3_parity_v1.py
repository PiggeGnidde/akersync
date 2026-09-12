#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerPuls D1-S3 parity: reproduce cached Sentinel Hub tiles from CDSE STAC+S3.

This stage spends zero Sentinel Hub processing units and never calls the Process
API. It reuses already cached D1 FLOAT32 Process tiles as the reference, selects
one deterministic tile observed on as many cached dates as possible, downloads
only the required original Sentinel-2 L2A assets from CDSE S3, reprojects them
with NEAREST onto the exact cached Process grid, and compares pixel values.

The purpose is operational/scientific backend parity only. No fusion refit,
threshold tuning, split/merge decision, crop inference, or geometry mutation is
allowed here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import urllib.parse
import urllib.request
from datetime import date, timedelta, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config" / "akerpuls_d1s3_parity_v1.json"
PROCESS_BANDS = ["B02", "B03", "B04", "B08", "B11", "SCL", "CLD", "dataMask"]
REFLECTANCE_BANDS = ["B02", "B03", "B04", "B08", "B11"]


def log(msg: str) -> None:
    print(msg, flush=True)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def scene_sort_key(feature: dict[str, Any]) -> tuple[str, str, str, str]:
    """Approximate Sentinel Hub default mostRecent ordering deterministically."""
    props = feature.get("properties") or {}
    return (
        str(props.get("datetime") or ""),
        str(props.get("created") or ""),
        str(props.get("updated") or ""),
        str(feature.get("id") or ""),
    )


def _next_link(document: dict[str, Any], current_url: str) -> str:
    for link in document.get("links", []):
        if link.get("rel") == "next":
            return urllib.parse.urljoin(current_url, str(link.get("href") or ""))
    return ""


def _normalize_asset(asset: dict[str, Any], band: str) -> dict[str, Any]:
    href = str(asset.get("href") or "")
    if not href.startswith("s3://"):
        raise RuntimeError(f"Asset {band} is not exposed over S3: {href}")
    default_scale = 0.0001 if band in REFLECTANCE_BANDS else 1.0
    return {
        "s3_uri": href,
        "bytes": int(asset.get("file:size") or 0),
        "checksum": asset.get("file:checksum"),
        "scale": float(asset.get("raster:scale", default_scale)),
        "offset": float(asset.get("raster:offset", 0.0)),
        "nodata": asset.get("nodata", 0),
    }


def query_stac_for_request(row: Any, cfg: dict[str, Any], out: Path) -> list[dict[str, Any]]:
    from rasterio.warp import transform_bounds

    day = date.fromisoformat(str(row.date))
    next_day = day + timedelta(days=1)
    bbox4326 = transform_bounds(
        f"EPSG:{cfg['target_crs_epsg']}", "EPSG:4326",
        float(row.minx), float(row.miny), float(row.maxx), float(row.maxy),
        densify_pts=21,
    )
    params = {
        "collections": cfg["collection"],
        "bbox": ",".join(f"{v:.8f}" for v in bbox4326),
        "datetime": f"{day}T00:00:00Z/{next_day}T00:00:00Z",
        "limit": "100",
    }
    current = cfg["stac_search_url"] + "?" + urllib.parse.urlencode(params)
    pages: list[dict[str, Any]] = []
    seen: set[str] = set()
    while current:
        if current in seen:
            raise RuntimeError("STAC pagination loop")
        seen.add(current)
        req = urllib.request.Request(current, headers={"User-Agent": "AkerSync-AkerPuls-D1S3/1.0"})
        with urllib.request.urlopen(req, timeout=120) as response:
            raw = response.read()
        document = json.loads(raw.decode("utf-8"))
        pages.append(document)
        current = _next_link(document, current)
        if len(pages) > 10:
            raise RuntimeError("Unexpectedly many STAC pages for one parity request")

    raw_dir = out / "stac" / f"{row.date}_{row.tile_id}"
    raw_dir.mkdir(parents=True, exist_ok=True)
    for i, document in enumerate(pages, 1):
        (raw_dir / f"page_{i:02d}.json").write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    features: dict[str, dict[str, Any]] = {}
    for document in pages:
        for feature in document.get("features", []):
            features[str(feature["id"])] = feature
    if not features:
        raise RuntimeError(f"No STAC scenes for {row.date} / {row.tile_id}")
    if len(features) > int(cfg["resource_guards"]["maximum_stac_items_per_request"]):
        raise RuntimeError("STAC item guard exceeded")

    required = cfg["assets"]
    scenes = []
    for feature in sorted(features.values(), key=scene_sort_key, reverse=True):
        assets = feature.get("assets") or {}
        missing = [key for key in required.values() if key not in assets]
        if missing:
            available = ",".join(sorted(assets.keys()))
            raise RuntimeError(
                f"STAC item {feature.get('id')} lacks required assets {missing}. AVAILABLE_ASSETS={available}"
            )
        props = feature.get("properties") or {}
        scenes.append({
            "item_id": str(feature["id"]),
            "datetime": str(props.get("datetime") or ""),
            "created": str(props.get("created") or ""),
            "updated": str(props.get("updated") or ""),
            "cloud_cover": float(props.get("eo:cloud_cover") or 0.0),
            "assets": {
                band: _normalize_asset(assets[key], band)
                for band, key in required.items()
            },
        })
    return scenes


def _multihash_ok(path: Path, encoded: str | None) -> bool:
    if not encoded:
        return True
    try:
        raw = bytes.fromhex(str(encoded))
    except ValueError:
        return True
    if len(raw) < 3:
        return True
    code, length, expected = raw[0], raw[1], raw[2:]
    algorithms = {0x12: "sha256", 0x16: "sha3_256"}
    if code not in algorithms or length != len(expected):
        return True
    h = hashlib.new(algorithms[code])
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.digest() == expected


def local_asset_path(cache_root: Path, scene: dict[str, Any], band: str) -> Path:
    uri = urllib.parse.urlparse(scene["assets"][band]["s3_uri"])
    return cache_root / "items" / scene["item_id"] / f"{band}_{Path(uri.path).name}"


def estimate_unique_assets(scene_sets: list[list[dict[str, Any]]]) -> tuple[dict[tuple[str, str], tuple[dict[str, Any], str]], int]:
    unique: dict[tuple[str, str], tuple[dict[str, Any], str]] = {}
    for scenes in scene_sets:
        for scene in scenes:
            for band in scene["assets"]:
                unique[(scene["item_id"], band)] = (scene, band)
    total = sum(int(scene["assets"][band]["bytes"]) for scene, band in unique.values())
    return unique, total


def download_assets(
    scene_sets: list[list[dict[str, Any]]], cache_root: Path, cfg: dict[str, Any]
) -> tuple[int, int, int]:
    try:
        import boto3
        from botocore.config import Config
    except ImportError as exc:
        raise RuntimeError("boto3/botocore are required for D1-S3 parity") from exc

    access = os.environ.get("AWS_ACCESS_KEY_ID", "").strip()
    secret = os.environ.get("AWS_SECRET_ACCESS_KEY", "").strip()
    if not access or not secret:
        raise RuntimeError("BLOCKED_S3_CREDENTIALS: AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY are not set")

    unique, projected_bytes = estimate_unique_assets(scene_sets)
    max_assets = int(cfg["resource_guards"]["maximum_unique_scene_assets"])
    if len(unique) > max_assets:
        raise RuntimeError(f"Unique scene-asset guard exceeded: {len(unique)} > {max_assets}")
    projected_gib = projected_bytes / (1024 ** 3)
    max_gib = float(cfg["resource_guards"]["maximum_download_gib"])
    if projected_gib > max_gib:
        raise RuntimeError(f"Projected S3 parity download {projected_gib:.2f} GiB exceeds guard {max_gib:.2f} GiB")

    cache_root.mkdir(parents=True, exist_ok=True)
    free_gib = shutil.disk_usage(cache_root).free / (1024 ** 3)
    minimum_after = float(cfg["resource_guards"]["minimum_free_gib_after_projected_download"])
    if free_gib - projected_gib < minimum_after:
        raise RuntimeError(
            f"Insufficient free disk: free={free_gib:.2f} GiB projected={projected_gib:.2f} GiB "
            f"required_after={minimum_after:.2f} GiB"
        )

    log(f"D1S3_UNIQUE_SCENE_ASSETS={len(unique)}")
    log(f"D1S3_PROJECTED_ARCHIVE_GIB={projected_gib:.3f}")
    log(f"D1S3_FREE_DISK_GIB={free_gib:.3f}")

    client = boto3.client(
        "s3", endpoint_url=cfg["s3_endpoint_url"],
        aws_access_key_id=access, aws_secret_access_key=secret,
        region_name="default",
        config=Config(signature_version="s3v4", retries={"max_attempts": 8, "mode": "adaptive"}),
    )
    downloads = cache_hits = downloaded_bytes = 0
    for n, ((item_id, band), (scene, band_name)) in enumerate(sorted(unique.items()), 1):
        assert band == band_name
        asset = scene["assets"][band]
        target = local_asset_path(cache_root, scene, band)
        good = target.is_file()
        if good and asset["bytes"]:
            good = target.stat().st_size == int(asset["bytes"])
        if good:
            good = _multihash_ok(target, asset.get("checksum"))
        if good:
            cache_hits += 1
        else:
            if target.exists():
                raise RuntimeError(f"Corrupt S3 parity cache preserved for diagnosis: {target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(target.suffix + ".partial")
            tmp.unlink(missing_ok=True)
            parsed = urllib.parse.urlparse(asset["s3_uri"])
            client.download_file(parsed.netloc, parsed.path.lstrip("/"), str(tmp))
            if asset["bytes"] and tmp.stat().st_size != int(asset["bytes"]):
                raise RuntimeError(f"Downloaded size mismatch: {item_id}/{band}")
            if not _multihash_ok(tmp, asset.get("checksum")):
                raise RuntimeError(f"Downloaded checksum mismatch: {item_id}/{band}")
            tmp.replace(target)
            downloads += 1
            downloaded_bytes += target.stat().st_size
        if n % 5 == 0 or n == len(unique):
            log(f"D1S3_S3_PROGRESS={n}/{len(unique)} DOWNLOADS={downloads} CACHE_HITS={cache_hits}")
    return downloads, cache_hits, downloaded_bytes


def choose_cached_reference_rows(requests: Any, process_root: Path, cfg: dict[str, Any]) -> Any:
    import pandas as pd

    rows = requests.copy()
    rows["process_path"] = [
        str(process_root / Path(str(rel).replace("/", os.sep)))
        for rel in rows["daily_output_relative"]
    ]
    rows["cached"] = [Path(p).is_file() and Path(p + ".json").is_file() for p in rows["process_path"]]
    cached = rows[rows["cached"]].copy()
    if cached.empty:
        raise RuntimeError("No cached D1 Process tiles found; D1-S3 parity requires existing reference tiles")

    per_tile = cached.groupby("tile_id")["date"].nunique().sort_values(ascending=False)
    max_dates = int(per_tile.iloc[0])
    minimum = int(cfg["selection"]["minimum_cached_dates"])
    if max_dates < minimum:
        raise RuntimeError(f"Best cached tile covers only {max_dates} dates; need at least {minimum}")
    candidates = set(per_tile[per_tile == max_dates].index.astype(str))

    cx = (cached["minx"].astype(float) + cached["maxx"].astype(float)) / 2.0
    cy = (cached["miny"].astype(float) + cached["maxy"].astype(float)) / 2.0
    medx, medy = float(cx.median()), float(cy.median())
    best: tuple[float, str] | None = None
    for tile in sorted(candidates):
        part = cached[cached["tile_id"].astype(str) == tile].iloc[0]
        x = (float(part.minx) + float(part.maxx)) / 2.0
        y = (float(part.miny) + float(part.maxy)) / 2.0
        value = ((x - medx) ** 2 + (y - medy) ** 2, tile)
        if best is None or value < best:
            best = value
    assert best is not None
    chosen_tile = best[1]
    selected = cached[cached["tile_id"].astype(str) == chosen_tile].copy()
    selected = selected.sort_values("date", kind="mergesort")
    maximum = int(cfg["selection"]["maximum_cached_dates"])
    selected = selected.drop_duplicates("date", keep="first").head(maximum).copy()
    if len(selected) < minimum:
        raise RuntimeError("Deterministic cached parity selection fell below minimum date count")
    return selected.reset_index(drop=True)


def verify_selected_process_tile(row: Any) -> Path:
    process_path = Path(str(row.process_path))
    meta_path = Path(str(process_path) + ".json")
    meta = read_json(meta_path)
    actual = sha256_file(process_path)
    if actual != meta.get("response_sha256"):
        raise RuntimeError(f"Cached Process response hash mismatch: {process_path}")
    return process_path


def _reproject_asset(source_path: Path, shape: tuple[int, int], transform: Any, crs: Any, nodata: Any, dtype: str) -> np.ndarray:
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.warp import reproject

    out = np.zeros(shape, dtype=dtype)
    with rasterio.open(source_path) as src:
        reproject(
            rasterio.band(src, 1), out,
            src_transform=src.transform, src_crs=src.crs, src_nodata=src.nodata if src.nodata is not None else nodata,
            dst_transform=transform, dst_crs=crs, dst_nodata=0,
            resampling=Resampling.nearest, init_dest_nodata=True,
        )
    return out


def build_local_tile(process_path: Path, scenes: list[dict[str, Any]], cache_root: Path) -> np.ndarray:
    import rasterio

    with rasterio.open(process_path) as ref:
        height, width = ref.height, ref.width
        transform, crs = ref.transform, ref.crs
    shape = (height, width)
    owner = np.full(shape, -1, dtype=np.int16)
    scl_mosaic = np.zeros(shape, dtype=np.int16)

    for scene_index, scene in enumerate(scenes):
        asset = scene["assets"]["SCL"]
        values = _reproject_asset(
            local_asset_path(cache_root, scene, "SCL"), shape, transform, crs,
            asset.get("nodata", 0), "int16",
        )
        use = (owner < 0) & (values != 0)
        owner[use] = scene_index
        scl_mosaic[use] = values[use]

    result = np.zeros((8, height, width), dtype=np.float32)
    for out_index, band in enumerate(["B02", "B03", "B04", "B08", "B11", "CLD"]):
        mosaic = np.zeros(shape, dtype=np.float32)
        for scene_index, scene in enumerate(scenes):
            use = owner == scene_index
            if not np.any(use):
                continue
            asset = scene["assets"][band]
            values = _reproject_asset(
                local_asset_path(cache_root, scene, band), shape, transform, crs,
                asset.get("nodata", 0), "float32",
            )
            values = values * float(asset.get("scale", 1.0)) + float(asset.get("offset", 0.0))
            mosaic[use] = values[use]
        if band == "CLD":
            result[6] = mosaic
        else:
            result[out_index] = mosaic
    result[5] = scl_mosaic.astype(np.float32)
    result[7] = (owner >= 0).astype(np.float32)
    return result


def safe_ratio(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    den = a + b
    return np.divide(a - b, den, out=np.zeros_like(den, dtype=np.float32), where=np.abs(den) > 1e-8)


def _quantile(values: np.ndarray, q: float) -> float:
    if values.size == 0:
        return math.inf
    return float(np.quantile(values.astype(np.float64), q))


def compare_arrays(process: np.ndarray, local: np.ndarray, thresholds: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if process.shape != local.shape or process.shape[0] != 8:
        raise RuntimeError(f"Parity array shape mismatch: {process.shape} vs {local.shape}")
    p_mask = process[7] > 0.5
    l_mask = local[7] > 0.5
    both = p_mask & l_mask
    mask_agreement = float(np.mean(p_mask == l_mask))
    compared = int(both.sum())
    scl_agreement = float(np.mean(np.rint(process[5][both]) == np.rint(local[5][both]))) if compared else 0.0

    rows: list[dict[str, Any]] = []
    reflectance_pass = True
    for idx, band in enumerate(REFLECTANCE_BANDS):
        delta = np.abs(process[idx][both] - local[idx][both])
        med = _quantile(delta, 0.5)
        p99 = _quantile(delta, 0.99)
        passed = (
            med <= float(thresholds["maximum_reflectance_median_abs_delta"])
            and p99 <= float(thresholds["maximum_reflectance_p99_abs_delta"])
        )
        reflectance_pass &= passed
        rows.append({"metric": band, "median_abs_delta": med, "p99_abs_delta": p99, "pass": bool(passed)})

    cld_delta = np.abs(process[6][both] - local[6][both])
    cld_p99 = _quantile(cld_delta, 0.99)
    rows.append({"metric": "CLD", "median_abs_delta": _quantile(cld_delta, 0.5), "p99_abs_delta": cld_p99,
                 "pass": cld_p99 <= float(thresholds["maximum_cld_p99_abs_delta"])})

    p_ndvi = safe_ratio(process[3], process[2])
    l_ndvi = safe_ratio(local[3], local[2])
    ndvi_delta = np.abs(p_ndvi[both] - l_ndvi[both])
    ndvi_p99 = _quantile(ndvi_delta, 0.99)
    rows.append({"metric": "NDVI", "median_abs_delta": _quantile(ndvi_delta, 0.5), "p99_abs_delta": ndvi_p99,
                 "pass": ndvi_p99 <= float(thresholds["maximum_ndvi_p99_abs_delta"])})

    p_lswi = safe_ratio(process[3], process[4])
    l_lswi = safe_ratio(local[3], local[4])
    lswi_delta = np.abs(p_lswi[both] - l_lswi[both])
    lswi_p99 = _quantile(lswi_delta, 0.99)
    rows.append({"metric": "LSWI", "median_abs_delta": _quantile(lswi_delta, 0.5), "p99_abs_delta": lswi_p99,
                 "pass": lswi_p99 <= float(thresholds["maximum_lswi_p99_abs_delta"])})

    passed = (
        compared >= int(thresholds["minimum_compared_pixels"])
        and mask_agreement >= float(thresholds["minimum_datamask_agreement"])
        and scl_agreement >= float(thresholds["minimum_scl_agreement"])
        and reflectance_pass
        and cld_p99 <= float(thresholds["maximum_cld_p99_abs_delta"])
        and ndvi_p99 <= float(thresholds["maximum_ndvi_p99_abs_delta"])
        and lswi_p99 <= float(thresholds["maximum_lswi_p99_abs_delta"])
    )
    summary = {
        "status": "PASS" if passed else "REVIEW",
        "compared_pixels": compared,
        "datamask_agreement": mask_agreement,
        "scl_agreement": scl_agreement,
        "cld_p99_abs_delta": cld_p99,
        "ndvi_p99_abs_delta": ndvi_p99,
        "lswi_p99_abs_delta": lswi_p99,
    }
    return rows, summary


def write_local_debug_tiff(path: Path, local: np.ndarray, reference_path: Path) -> None:
    import rasterio

    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(reference_path) as ref:
        profile = ref.profile.copy()
        profile.update(count=8, dtype="float32", compress="DEFLATE", predictor=3)
        with rasterio.open(path, "w", **profile) as dst:
            dst.write(local.astype(np.float32))
            for i, name in enumerate(PROCESS_BANDS, 1):
                dst.set_band_description(i, name)


def validate_config(cfg: dict[str, Any]) -> None:
    if cfg.get("schema_version") != "akerpuls-d1s3-process-s3-parity-v1":
        raise RuntimeError("Unexpected D1-S3 config schema")
    if cfg["preprocessing"]["reflectance_resampling"] != "NEAREST" or cfg["preprocessing"]["quality_resampling"] != "NEAREST":
        raise RuntimeError("D1-S3 preprocessing is not frozen to NEAREST")
    if cfg["preprocessing"]["mosaicking_order"] != "mostRecent":
        raise RuntimeError("D1-S3 must reproduce Sentinel Hub default mostRecent mosaicking")
    guards = cfg.get("guards", {})
    if any(bool(v) for v in guards.values()):
        raise RuntimeError("D1-S3 forbidden-scope guard unexpectedly enabled")


def main() -> int:
    import pandas as pd
    import rasterio

    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(CFG))
    ap.add_argument("--output-dir")
    ap.add_argument("--s3-cache-root")
    args = ap.parse_args()

    cfg = read_json(Path(args.config))
    validate_config(cfg)
    out = Path(args.output_dir or cfg["output_dir"])
    cache_root = Path(args.s3_cache_root or cfg["s3_cache_root"])
    out.mkdir(parents=True, exist_ok=True)

    contract_path = Path(cfg["final_execution_contract"])
    if not contract_path.is_file():
        raise FileNotFoundError(contract_path)
    contract_sha = sha256_file(contract_path)
    if contract_sha != cfg["expected_final_execution_contract_sha256"]:
        raise RuntimeError(f"D1 execution contract SHA mismatch: {contract_sha}")

    request_plan = Path(cfg["d0_request_plan"])
    if not request_plan.is_file():
        raise FileNotFoundError(request_plan)
    requests = pd.read_csv(request_plan, encoding="utf-8-sig")
    process_root = Path(cfg["process_raw_root"])

    log("D1S3_PROGRESS=DISCOVER_CACHED_PROCESS_REFERENCES")
    selected = choose_cached_reference_rows(requests, process_root, cfg)
    selected.to_csv(out / "d1s3_selected_reference_requests.csv", index=False, encoding="utf-8-sig")
    selected_dates = ",".join(selected["date"].astype(str))
    chosen_tile = str(selected.iloc[0].tile_id)
    log(f"D1S3_SELECTED_TILE={chosen_tile}")
    log(f"D1S3_SELECTED_DATES={selected_dates}")
    log(f"D1S3_REFERENCE_REQUESTS={len(selected)}")

    process_paths = []
    scene_sets = []
    scene_rows = []
    log("D1S3_PROGRESS=VERIFY_PROCESS_CACHE_AND_QUERY_STAC")
    for _, row in selected.iterrows():
        process_path = verify_selected_process_tile(row)
        process_paths.append(process_path)
        scenes = query_stac_for_request(row, cfg, out)
        scene_sets.append(scenes)
        for order, scene in enumerate(scenes):
            scene_rows.append({
                "date": row.date, "tile_id": row.tile_id, "mosaic_order": order,
                "item_id": scene["item_id"], "datetime": scene["datetime"],
                "created": scene["created"], "updated": scene["updated"],
                "cloud_cover": scene["cloud_cover"],
            })
        log(f"D1S3_STAC date={row.date} tile={row.tile_id} items={len(scenes)} first={scenes[0]['item_id']}")
    pd.DataFrame(scene_rows).to_csv(out / "d1s3_scene_inventory.csv", index=False, encoding="utf-8-sig")

    log("D1S3_PROGRESS=DOWNLOAD_DIRECT_S3_ASSETS")
    downloads, cache_hits, downloaded_bytes = download_assets(scene_sets, cache_root, cfg)

    threshold = cfg["parity_thresholds"]
    tile_summaries = []
    metric_rows = []
    log("D1S3_PROGRESS=REPROJECT_NEAREST_AND_COMPARE")
    for n, ((_, row), process_path, scenes) in enumerate(zip(selected.iterrows(), process_paths, scene_sets), 1):
        with rasterio.open(process_path) as ds:
            process = ds.read().astype(np.float32)
            if process.shape[0] != 8:
                raise RuntimeError(f"Reference tile has {process.shape[0]} bands, expected 8: {process_path}")
        local = build_local_tile(process_path, scenes, cache_root)
        rows, summary = compare_arrays(process, local, threshold)
        debug = out / "local_tiles" / f"{row.date}_{row.tile_id}_s3_local.tif"
        write_local_debug_tiff(debug, local, process_path)
        for metric in rows:
            metric_rows.append({"date": row.date, "tile_id": row.tile_id, **metric})
        tile_summaries.append({"date": str(row.date), "tile_id": str(row.tile_id), **summary})
        log(
            f"D1S3_PARITY date={row.date} tile={row.tile_id} status={summary['status']} "
            f"pixels={summary['compared_pixels']} mask={summary['datamask_agreement']:.6f} "
            f"scl={summary['scl_agreement']:.6f} ndvi_p99={summary['ndvi_p99_abs_delta']:.6g} "
            f"lswi_p99={summary['lswi_p99_abs_delta']:.6g}"
        )
    pd.DataFrame(metric_rows).to_csv(out / "d1s3_metric_parity.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(tile_summaries).to_csv(out / "d1s3_tile_parity.csv", index=False, encoding="utf-8-sig")

    overall = all(x["status"] == "PASS" for x in tile_summaries)
    status = "PASS" if overall else "REVIEW"
    manifest = {
        "schema_version": "akerpuls-d1s3-process-s3-parity-result-v1",
        "status": status,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "final_execution_contract_sha256": contract_sha,
        "selected_tile": chosen_tile,
        "selected_dates": [str(x) for x in selected["date"]],
        "reference_requests": int(len(selected)),
        "s3_asset_downloads": int(downloads),
        "s3_asset_cache_hits": int(cache_hits),
        "s3_downloaded_bytes": int(downloaded_bytes),
        "tile_summaries": tile_summaries,
        "process_api_calls": 0,
        "sentinel_hub_pu_used": 0,
        "fusion_refit": False,
        "thresholds_tuned": False,
        "automatic_split": False,
        "automatic_merge": False,
        "automatic_geometry_replacement": False,
        "next_step": "If PASS, freeze direct-STAC/S3 acquisition backend for full-Skane D1-S3 run; preserve existing Process cache unchanged.",
    }
    (out / "d1s3_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    log("AKERPULS D1-S3 PROCESS VS DIRECT S3 PARITY")
    log(f"STATUS={status}")
    log(f"FINAL_EXECUTION_CONTRACT_SHA256={contract_sha}")
    log(f"REFERENCE_REQUESTS={len(selected)}")
    log(f"SELECTED_TILE={chosen_tile}")
    log(f"SELECTED_DATES={selected_dates}")
    log(f"S3_ASSET_DOWNLOADS={downloads}")
    log(f"S3_ASSET_CACHE_HITS={cache_hits}")
    log(f"S3_DOWNLOADED_GIB={downloaded_bytes/(1024**3):.3f}")
    log("PROCESS_API_CALLS=0")
    log("SENTINEL_HUB_PU_USED=0")
    log("AUTOMATIC_GEOMETRY_REPLACEMENT=FALSE")
    log(f"D1S3_STATUS={status}")
    log("OUTPUT=" + str(out))
    return 0 if overall else 2


if __name__ == "__main__":
    raise SystemExit(main())
