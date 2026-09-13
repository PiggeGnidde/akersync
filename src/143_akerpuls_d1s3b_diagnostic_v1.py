#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerPuls D1-S3b: zero-PU diagnosis of the D1-S3 REVIEW mismatch.

This is deliberately diagnostic, not a new parity gate. It reuses the exact
cached Process references and the exact S3 assets downloaded by D1-S3 v1,
tries only a small declared set of backend-semantic variants, and reports
where differences live (coverage/mask, scene ownership, radiometry, or scene
seams). It never calls Sentinel Hub Process API and never downloads S3 data.
No model/threshold/geometry decision is changed here.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config" / "akerpuls_d1s3b_diagnostic_v1.json"
PARENT_SCRIPT = ROOT / "src" / "142_akerpuls_d1s3_parity_v1.py"
REFLECTANCE = ["B02", "B03", "B04", "B08", "B11"]
BAND_INDEX = {"B02": 0, "B03": 1, "B04": 2, "B08": 3, "B11": 4, "SCL": 5, "CLD": 6, "dataMask": 7}


def log(msg: str) -> None:
    print(msg, flush=True)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_parent():
    spec = importlib.util.spec_from_file_location("akerpuls_d1s3_parent", PARENT_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def q(values: np.ndarray, p: float) -> float:
    values = np.asarray(values, dtype=np.float64)
    values = values[np.isfinite(values)]
    return float(np.quantile(values, p)) if values.size else math.nan


def ratio(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    den = a + b
    return np.divide(a - b, den, out=np.zeros_like(a, dtype=np.float32), where=np.abs(den) > 1e-8)


def scene_interior(mask: np.ndarray, owner: np.ndarray, radius: int) -> np.ndarray:
    """Pixels at least radius cells from data edges and scene-owner seams."""
    current = mask.astype(bool).copy()
    own = owner.astype(np.int16)
    h, w = current.shape
    for _ in range(max(0, int(radius))):
        padded_m = np.pad(current, 1, constant_values=False)
        padded_o = np.pad(own, 1, constant_values=-32768)
        keep = current.copy()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dy == 0 and dx == 0:
                    continue
                neigh_m = padded_m[1 + dy:1 + dy + h, 1 + dx:1 + dx + w]
                neigh_o = padded_o[1 + dy:1 + dy + h, 1 + dx:1 + dx + w]
                keep &= neigh_m & (neigh_o == own)
        current = keep
    return current


def reproject_scene(scene: dict[str, Any], cache_root: Path, shape: tuple[int, int], transform: Any, crs: Any, parent: Any) -> dict[str, Any]:
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.warp import reproject

    arrays: dict[str, np.ndarray] = {}
    for band in [*REFLECTANCE, "SCL", "CLD"]:
        path = parent.local_asset_path(cache_root, scene, band)
        if not path.is_file():
            raise FileNotFoundError(f"D1-S3b requires the existing parity cache; missing {path}")
        asset = scene["assets"][band]
        dtype = "float32" if band in REFLECTANCE else "int16"
        dest = np.zeros(shape, dtype=dtype)
        with rasterio.open(path) as src:
            reproject(
                rasterio.band(src, 1), dest,
                src_transform=src.transform,
                src_crs=src.crs,
                src_nodata=asset.get("nodata", 0),
                dst_transform=transform,
                dst_crs=crs,
                dst_nodata=0,
                resampling=Resampling.nearest,
                init_dest_nodata=True,
            )
        if band in REFLECTANCE:
            dest = dest.astype(np.float32) * np.float32(asset.get("scale", 0.0001)) + np.float32(asset.get("offset", 0.0))
        arrays[band] = dest

    scl_path = parent.local_asset_path(cache_root, scene, "SCL")
    with rasterio.open(scl_path) as src:
        source_mask = src.read_masks(1)
        dataset_mask = np.zeros(shape, dtype=np.uint8)
        reproject(
            source_mask,
            dataset_mask,
            src_transform=src.transform,
            src_crs=src.crs,
            src_nodata=0,
            dst_transform=transform,
            dst_crs=crs,
            dst_nodata=0,
            resampling=Resampling.nearest,
            init_dest_nodata=True,
        )
    return {
        "item_id": scene["item_id"],
        "arrays": arrays,
        "coverage_scl": arrays["SCL"] != 0,
        "coverage_dataset": dataset_mask > 0,
    }


def mosaic(scene_data: list[dict[str, Any]], order_name: str, coverage_name: str, reflectance_name: str) -> tuple[np.ndarray, np.ndarray]:
    order = list(range(len(scene_data)))
    if order_name == "REVERSED":
        order = list(reversed(order))
    if order_name not in {"PARENT", "REVERSED"}:
        raise RuntimeError(order_name)
    h, w = scene_data[0]["arrays"]["SCL"].shape
    out = np.zeros((8, h, w), dtype=np.float32)
    owner = np.full((h, w), -1, dtype=np.int16)
    for idx in order:
        scene = scene_data[idx]
        if coverage_name == "SCL_NONZERO":
            coverage = scene["coverage_scl"]
        elif coverage_name == "SCL_DATASET_MASK":
            coverage = scene["coverage_dataset"]
        else:
            raise RuntimeError(coverage_name)
        use = (owner < 0) & coverage
        if not np.any(use):
            continue
        for band in REFLECTANCE:
            values = scene["arrays"][band]
            if reflectance_name == "SCALE_OFFSET_CLIP0":
                values = np.maximum(values, 0.0)
            elif reflectance_name != "SCALE_OFFSET":
                raise RuntimeError(reflectance_name)
            out[BAND_INDEX[band], use] = values[use]
        out[5, use] = scene["arrays"]["SCL"][use]
        out[6, use] = scene["arrays"]["CLD"][use]
        out[7, use] = 1.0
        owner[use] = idx
    return out, owner


def metrics(reference: np.ndarray, candidate: np.ndarray, owner: np.ndarray, clear_codes: set[int], radius: int) -> dict[str, Any]:
    refmask = reference[7] > 0.5
    canmask = candidate[7] > 0.5
    refscl = np.rint(reference[5]).astype(np.int16)
    canscl = np.rint(candidate[5]).astype(np.int16)
    refvalid = refmask & np.isin(refscl, list(clear_codes))
    canvalid = canmask & np.isin(canscl, list(clear_codes))
    common_data = refmask & canmask
    common_valid = refvalid & canvalid
    interior = scene_interior(common_valid, owner, radius)

    ndvi_ref = ratio(reference[3], reference[2])
    ndvi_can = ratio(candidate[3], candidate[2])
    lswi_ref = ratio(reference[3], reference[4])
    lswi_can = ratio(candidate[3], candidate[4])

    row: dict[str, Any] = {
        "pixels_total": int(refmask.size),
        "process_data_pixels": int(refmask.sum()),
        "candidate_data_pixels": int(canmask.sum()),
        "common_data_pixels": int(common_data.sum()),
        "process_valid_pixels": int(refvalid.sum()),
        "candidate_valid_pixels": int(canvalid.sum()),
        "common_valid_pixels": int(common_valid.sum()),
        "interior_valid_pixels": int(interior.sum()),
        "datamask_agreement": float(np.mean(refmask == canmask)),
        "valid_mask_agreement": float(np.mean(refvalid == canvalid)),
        "scl_agreement_common_data": float(np.mean(refscl[common_data] == canscl[common_data])) if common_data.any() else math.nan,
    }

    for scope_name, scope in (("valid", common_valid), ("interior", interior)):
        if not np.any(scope):
            for name in ("ndvi_p50", "ndvi_p95", "ndvi_p99", "lswi_p50", "lswi_p95", "lswi_p99", "reflectance_maxband_p99", "cld_p99"):
                row[f"{scope_name}_{name}"] = math.nan
            continue
        nd = np.abs(ndvi_ref[scope] - ndvi_can[scope])
        lw = np.abs(lswi_ref[scope] - lswi_can[scope])
        row[f"{scope_name}_ndvi_p50"] = q(nd, 0.50)
        row[f"{scope_name}_ndvi_p95"] = q(nd, 0.95)
        row[f"{scope_name}_ndvi_p99"] = q(nd, 0.99)
        row[f"{scope_name}_lswi_p50"] = q(lw, 0.50)
        row[f"{scope_name}_lswi_p95"] = q(lw, 0.95)
        row[f"{scope_name}_lswi_p99"] = q(lw, 0.99)
        p99s = []
        for bi in range(5):
            p99s.append(q(np.abs(reference[bi][scope] - candidate[bi][scope]), 0.99))
        row[f"{scope_name}_reflectance_maxband_p99"] = float(np.nanmax(p99s))
        row[f"{scope_name}_cld_p99"] = q(np.abs(reference[6][scope] - candidate[6][scope]), 0.99)
    return row


def main() -> int:
    import pandas as pd
    import rasterio

    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(CFG))
    ap.add_argument("--output-dir")
    args = ap.parse_args()
    cfg = read_json(Path(args.config))
    if cfg.get("schema_version") != "akerpuls-d1s3b-mismatch-diagnostic-v1":
        raise RuntimeError("Unexpected D1-S3b config schema")
    if any(bool(v) for v in cfg["guards"].values()):
        raise RuntimeError("D1-S3b forbidden-scope guard unexpectedly enabled")

    parent = load_parent()
    parent_cfg = read_json(ROOT / cfg["parent_parity_config"])
    if parent_cfg["expected_final_execution_contract_sha256"] != cfg["expected_final_execution_contract_sha256"]:
        raise RuntimeError("Parent/final execution contract binding changed")
    parent_manifest_path = Path(cfg["parent_output_dir"]) / "d1s3_manifest.json"
    if not parent_manifest_path.is_file():
        raise FileNotFoundError(parent_manifest_path)
    parent_manifest = read_json(parent_manifest_path)
    if parent_manifest.get("status") != "REVIEW":
        raise RuntimeError(f"D1-S3b is only for the observed parent REVIEW; got {parent_manifest.get('status')}")
    if int(parent_manifest.get("process_api_calls", -1)) != 0 or float(parent_manifest.get("sentinel_hub_pu_used", -1)) != 0.0:
        raise RuntimeError("Parent parity manifest is not zero-PU")

    out = Path(args.output_dir or cfg["output_dir"])
    out.mkdir(parents=True, exist_ok=True)
    cache_root = Path(cfg["s3_cache_root"])
    requests = pd.read_csv(parent_cfg["d0_request_plan"], encoding="utf-8-sig")
    selected = parent.choose_cached_reference_rows(requests, Path(parent_cfg["process_raw_root"]), parent_cfg)
    log("D1S3B_PROGRESS=REUSE_PARENT_SELECTION_AND_CACHE")
    log("D1S3B_SELECTED_TILE=" + str(selected.iloc[0].tile_id))
    log("D1S3B_SELECTED_DATES=" + ",".join(selected["date"].astype(str)))

    clear_codes = set(map(int, cfg["clear_scl_codes"]))
    rows: list[dict[str, Any]] = []
    scene_rows: list[dict[str, Any]] = []
    for _, r in selected.iterrows():
        process_path = parent.verify_selected_process_tile(r)
        with rasterio.open(process_path) as ds:
            reference = ds.read().astype(np.float32)
            transform = ds.transform
            crs = ds.crs
            shape = (ds.height, ds.width)
        scenes = parent.query_stac_for_request(r, parent_cfg, out)
        scene_data = [reproject_scene(scene, cache_root, shape, transform, crs, parent) for scene in scenes]
        for rank, scene in enumerate(scenes):
            scene_rows.append({
                "date": str(r.date), "tile_id": str(r.tile_id), "parent_rank": rank,
                "item_id": scene["item_id"], "datetime": scene.get("datetime"),
                "cloud_cover": scene.get("cloud_cover"),
            })
        for order in cfg["diagnostic_variants"]["scene_order"]:
            for coverage in cfg["diagnostic_variants"]["coverage"]:
                for reflectance in cfg["diagnostic_variants"]["reflectance"]:
                    candidate, owner = mosaic(scene_data, order, coverage, reflectance)
                    row = metrics(reference, candidate, owner, clear_codes, int(cfg["interior_radius_pixels"]))
                    row.update({
                        "date": str(r.date), "tile_id": str(r.tile_id),
                        "scene_order": order, "coverage": coverage, "reflectance": reflectance,
                    })
                    rows.append(row)

    frame = pd.DataFrame(rows)
    frame.to_csv(out / "d1s3b_variant_metrics.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(scene_rows).to_csv(out / "d1s3b_scene_inventory.csv", index=False, encoding="utf-8-sig")

    best_rows = []
    for day, part in frame.groupby("date", sort=True):
        ranked = part.sort_values(
            ["valid_mask_agreement", "interior_ndvi_p99", "interior_lswi_p99", "datamask_agreement"],
            ascending=[False, True, True, False], kind="mergesort",
        )
        best = ranked.iloc[0].to_dict()
        best_rows.append(best)
        log(
            "D1S3B_BEST "
            f"date={day} order={best['scene_order']} coverage={best['coverage']} reflectance={best['reflectance']} "
            f"mask={best['datamask_agreement']:.6f} validmask={best['valid_mask_agreement']:.6f} "
            f"common_valid={int(best['common_valid_pixels'])} interior={int(best['interior_valid_pixels'])} "
            f"ndvi_p99_valid={best['valid_ndvi_p99']:.8g} ndvi_p99_interior={best['interior_ndvi_p99']:.8g} "
            f"lswi_p99_valid={best['valid_lswi_p99']:.8g} lswi_p99_interior={best['interior_lswi_p99']:.8g}"
        )
    pd.DataFrame(best_rows).to_csv(out / "d1s3b_best_by_date.csv", index=False, encoding="utf-8-sig")

    baseline = frame[
        (frame["scene_order"] == "PARENT") &
        (frame["coverage"] == "SCL_NONZERO") &
        (frame["reflectance"] == "SCALE_OFFSET")
    ].copy()
    if len(baseline) != len(selected):
        raise RuntimeError("D1-S3b baseline variant count mismatch")

    manifest = {
        "schema_version": "akerpuls-d1s3b-mismatch-diagnostic-result-v1",
        "status": "DIAGNOSTIC_COMPLETE",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "parent_status": parent_manifest.get("status"),
        "final_execution_contract_sha256": cfg["expected_final_execution_contract_sha256"],
        "selected_tile": str(selected.iloc[0].tile_id),
        "selected_dates": selected["date"].astype(str).tolist(),
        "variants_per_date": int(len(frame) / len(selected)),
        "s3_downloads": 0,
        "process_api_calls": 0,
        "sentinel_hub_pu_used": 0,
        "thresholds_changed": False,
        "product_rule_authorized": False,
        "automatic_geometry_replacement": False,
        "next_step": "Use diagnostic evidence to define a separate predeclared backend-equivalence validation; do not authorize full-Skane S3 from D1-S3b alone.",
    }
    (out / "d1s3b_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    log("AKERPULS D1-S3B MISMATCH DIAGNOSTIC")
    log("STATUS=DIAGNOSTIC_COMPLETE")
    log(f"SELECTED_TILE={manifest['selected_tile']}")
    log("SELECTED_DATES=" + ",".join(manifest["selected_dates"]))
    log(f"VARIANTS_PER_DATE={manifest['variants_per_date']}")
    log("S3_DOWNLOADS=0")
    log("PROCESS_API_CALLS=0")
    log("SENTINEL_HUB_PU_USED=0")
    log("THRESHOLDS_CHANGED=FALSE")
    log("PRODUCT_RULE_AUTHORIZED=FALSE")
    log("D1S3B_STATUS=DIAGNOSTIC_COMPLETE")
    log("OUTPUT=" + str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
