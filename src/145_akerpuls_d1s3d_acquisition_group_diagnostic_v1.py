#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerPuls D1-S3d: zero-PU diagnosis of D1-S3c holdout failures.

Reuses only cached Process references, cached normalized STAC scene lists and
already-downloaded CDSE S3 assets. No network access is needed or allowed by
this stage. It tests whether direct-S3 parity failures come from mixing multiple
same-day acquisitions versus granule precedence within one acquisition.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config" / "akerpuls_d1s3d_acquisition_group_diagnostic_v1.json"
PARENT_SCRIPT = ROOT / "src" / "142_akerpuls_d1s3_parity_v1.py"
DIAG_SCRIPT = ROOT / "src" / "143_akerpuls_d1s3b_diagnostic_v1.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def log(msg: str) -> None:
    print(msg, flush=True)


def acquisition_key(scene: dict[str, Any], pattern: str) -> str:
    item_id = str(scene.get("item_id") or "")
    m = re.match(pattern, item_id)
    if m:
        return m.group(1)
    dt = str(scene.get("datetime") or "")
    if len(dt) >= 19:
        return dt[:19].replace("-", "").replace(":", "").replace("T", "T")
    raise RuntimeError(f"Cannot derive acquisition key for {item_id}")


def grouped_scene_indices(scenes: list[dict[str, Any]], pattern: str) -> dict[str, list[int]]:
    groups: dict[str, list[int]] = {}
    for i, scene in enumerate(scenes):
        groups.setdefault(acquisition_key(scene, pattern), []).append(i)
    return groups


def select_variant(scenes: list[dict[str, Any]], variant: str, pattern: str) -> tuple[list[dict[str, Any]], str, str]:
    groups = grouped_scene_indices(scenes, pattern)
    keys = sorted(groups)
    if not keys:
        raise RuntimeError("No acquisition groups")
    if variant == "ALL_PARENT":
        return scenes, "PARENT", "ALL"
    if variant == "ALL_REVERSED":
        return scenes, "REVERSED", "ALL"
    if variant.startswith("LATEST_ACQUISITION_"):
        key = keys[-1]
    elif variant.startswith("EARLIEST_ACQUISITION_"):
        key = keys[0]
    else:
        raise RuntimeError(f"Unknown D1-S3d variant: {variant}")
    order = "REVERSED" if variant.endswith("_REVERSED") else "PARENT"
    subset = [scenes[i] for i in groups[key]]
    return subset, order, key


def main() -> int:
    import pandas as pd
    import rasterio

    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(CFG))
    ap.add_argument("--output-dir")
    args = ap.parse_args()

    cfg = read_json(Path(args.config))
    if cfg.get("schema_version") != "akerpuls-d1s3d-acquisition-group-diagnostic-v1":
        raise RuntimeError("Unexpected D1-S3d config schema")
    if any(bool(v) for v in cfg["guards"].values()):
        raise RuntimeError("D1-S3d forbidden-scope guard unexpectedly enabled")

    parent = load_module(PARENT_SCRIPT, "akerpuls_d1s3_parent")
    diag = load_module(DIAG_SCRIPT, "akerpuls_d1s3_diag")
    parent_cfg = read_json(ROOT / cfg["parent_parity_config"])
    if parent_cfg["expected_final_execution_contract_sha256"] != cfg["expected_final_execution_contract_sha256"]:
        raise RuntimeError("Execution contract binding changed")

    holdout_dir = Path(cfg["parent_holdout_output_dir"])
    manifest = read_json(holdout_dir / "d1s3c_manifest.json")
    if manifest.get("status") != "HOLDOUT_COMPLETE":
        raise RuntimeError("D1-S3c holdout is not complete")
    if int(manifest.get("process_api_calls", -1)) != 0 or float(manifest.get("sentinel_hub_pu_used", -1)) != 0.0:
        raise RuntimeError("Parent holdout is not zero-PU")

    selected_path = holdout_dir / "d1s3c_selected_holdout_requests.csv"
    parity_path = holdout_dir / "d1s3c_holdout_parity.csv"
    if not selected_path.is_file() or not parity_path.is_file():
        raise FileNotFoundError("D1-S3c selected/parity artifacts missing")
    selected = pd.read_csv(selected_path, encoding="utf-8-sig")
    observed = pd.read_csv(parity_path, encoding="utf-8-sig")
    if len(selected) != len(observed):
        raise RuntimeError("D1-S3c artifact row count mismatch")

    out = Path(args.output_dir or cfg["output_dir"])
    out.mkdir(parents=True, exist_ok=True)
    cache_root = Path(cfg["s3_cache_root"])
    pattern = cfg["acquisition_grouping"]["regex"]
    variants = list(cfg["diagnostic_variants"])
    clear_codes = set(map(int, cfg["clear_scl_codes"]))
    radius = int(cfg["interior_radius_pixels"])

    rows: list[dict[str, Any]] = []
    scene_inventory: list[dict[str, Any]] = []
    log("D1S3D_PROGRESS=REUSE_D1S3C_HOLDOUT_AND_LOCAL_CACHE")
    for idx, row in selected.iterrows():
        day = str(row.date)
        tile = str(row.tile_id)
        stac_cache = holdout_dir / "stac_scene_cache" / f"{day}_{tile}.json"
        if not stac_cache.is_file():
            raise FileNotFoundError(f"Cached normalized STAC scene list missing: {stac_cache}")
        scenes = read_json(stac_cache)
        groups = grouped_scene_indices(scenes, pattern)
        keys = sorted(groups)
        log(f"D1S3D_GROUPS {idx+1}/{len(selected)} date={day} tile={tile} scenes={len(scenes)} groups={len(keys)} keys={'|'.join(keys)}")
        for rank, scene in enumerate(scenes):
            scene_inventory.append({
                "date": day, "tile_id": tile, "parent_rank": rank,
                "acquisition_key": acquisition_key(scene, pattern),
                "item_id": scene.get("item_id"), "datetime": scene.get("datetime"),
            })

        process_path = Path(str(row.process_path))
        parent.verify_selected_process_tile(row)
        with rasterio.open(process_path) as ds:
            reference = ds.read().astype(np.float32)
            shape, transform, crs = (ds.height, ds.width), ds.transform, ds.crs

        for variant in variants:
            subset, order, group_key = select_variant(scenes, variant, pattern)
            scene_data = [diag.reproject_scene(scene, cache_root, shape, transform, crs, parent) for scene in subset]
            candidate, owner = diag.mosaic(scene_data, order, "SCL_NONZERO", "SCALE_OFFSET")
            m = diag.metrics(reference, candidate, owner, clear_codes, radius)
            rows.append({
                "date": day, "tile_id": tile, "variant": variant,
                "scene_order": order, "selected_acquisition": group_key,
                "all_acquisition_count": len(keys), "selected_scene_count": len(subset),
                **m,
            })

    frame = pd.DataFrame(rows)
    frame.to_csv(out / "d1s3d_variant_metrics.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(scene_inventory).to_csv(out / "d1s3d_scene_inventory.csv", index=False, encoding="utf-8-sig")

    best_rows = []
    wins = Counter()
    for (day, tile), part in frame.groupby(["date", "tile_id"], sort=True):
        ranked = part.sort_values(
            ["valid_mask_agreement", "interior_ndvi_p99", "interior_lswi_p99", "scl_agreement_common_data"],
            ascending=[False, True, True, False], kind="mergesort",
        )
        best = ranked.iloc[0].to_dict()
        wins[str(best["variant"])] += 1
        best_rows.append(best)
        current = part[part["variant"] == "ALL_REVERSED"].iloc[0]
        log(
            f"D1S3D_BEST date={day} tile={tile} variant={best['variant']} groups={int(best['all_acquisition_count'])} "
            f"validmask={best['valid_mask_agreement']:.6f} scl={best['scl_agreement_common_data']:.6f} "
            f"ndvi_p99={best['valid_ndvi_p99']:.8g} lswi_p99={best['valid_lswi_p99']:.8g} "
            f"current_ndvi_p99={current['valid_ndvi_p99']:.8g} current_lswi_p99={current['valid_lswi_p99']:.8g}"
        )
    best_frame = pd.DataFrame(best_rows)
    best_frame.to_csv(out / "d1s3d_best_by_request.csv", index=False, encoding="utf-8-sig")

    summary = {
        "schema_version": "akerpuls-d1s3d-acquisition-group-diagnostic-result-v1",
        "status": "DIAGNOSTIC_COMPLETE",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "requests": int(len(selected)),
        "variants_per_request": len(variants),
        "variant_wins": dict(sorted(wins.items())),
        "multi_acquisition_requests": int(sum(grouped_scene_indices(read_json(holdout_dir / "stac_scene_cache" / f"{r.date}_{r.tile_id}.json"), pattern).__len__() > 1 for _, r in selected.iterrows())),
        "s3_downloads": 0,
        "stac_queries": 0,
        "process_api_calls": 0,
        "sentinel_hub_pu_used": 0,
        "thresholds_changed": False,
        "product_rule_authorized": False,
        "full_skane_s3_authorized": False,
        "automatic_geometry_replacement": False,
        "next_step": "Use this post-holdout diagnosis only to formulate one new predeclared acquisition/granule rule, then test that rule on a fresh cached-Process holdout before any full-Skane S3 authorization."
    }
    (out / "d1s3d_manifest.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    log("AKERPULS D1-S3D ACQUISITION-GROUP DIAGNOSTIC")
    log("STATUS=DIAGNOSTIC_COMPLETE")
    log(f"REQUESTS={summary['requests']} VARIANTS_PER_REQUEST={summary['variants_per_request']}")
    log(f"MULTI_ACQUISITION_REQUESTS={summary['multi_acquisition_requests']}")
    log("VARIANT_WINS=" + ";".join(f"{k}:{v}" for k, v in summary["variant_wins"].items()))
    log("S3_DOWNLOADS=0")
    log("STAC_QUERIES=0")
    log("PROCESS_API_CALLS=0")
    log("SENTINEL_HUB_PU_USED=0")
    log("THRESHOLDS_CHANGED=FALSE")
    log("FULL_SKANE_S3_AUTHORIZED=FALSE")
    log("D1S3D_STATUS=DIAGNOSTIC_COMPLETE")
    log(f"OUTPUT={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
