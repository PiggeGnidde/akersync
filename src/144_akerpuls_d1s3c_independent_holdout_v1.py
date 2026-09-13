#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerPuls D1-S3c: independent cached-Process holdout for direct CDSE S3 backend.

Uses no Sentinel Hub Process API calls. The candidate backend semantics were
frozen after D1-S3b diagnosis and before these holdout outcomes:
REVERSED scene order, SCL_NONZERO coverage, SCALE_OFFSET reflectance, NEAREST.
This stage is diagnostic/validation only and cannot authorize product changes.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config" / "akerpuls_d1s3c_independent_holdout_v1.json"
PARENT_SCRIPT = ROOT / "src" / "142_akerpuls_d1s3_parity_v1.py"
DIAG_SCRIPT = ROOT / "src" / "143_akerpuls_d1s3b_diagnostic_v1.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def log(msg: str) -> None:
    print(msg, flush=True)


def deterministic_spread(part: Any, n: int) -> Any:
    """Centroid-nearest seed, then deterministic farthest-point sampling."""
    p = part.copy().reset_index(drop=True)
    p["cx"] = (p["minx"].astype(float) + p["maxx"].astype(float)) / 2.0
    p["cy"] = (p["miny"].astype(float) + p["maxy"].astype(float)) / 2.0
    mx, my = float(p["cx"].mean()), float(p["cy"].mean())
    p["centroid_d2"] = (p["cx"] - mx) ** 2 + (p["cy"] - my) ** 2
    first = p.sort_values(["centroid_d2", "tile_id"], kind="mergesort").index[0]
    chosen = [int(first)]
    while len(chosen) < min(n, len(p)):
        best = None
        for idx, row in p.iterrows():
            if int(idx) in chosen:
                continue
            d2 = min((float(row.cx) - float(p.loc[j, "cx"])) ** 2 + (float(row.cy) - float(p.loc[j, "cy"])) ** 2 for j in chosen)
            candidate = (-d2, str(row.tile_id), int(idx))
            if best is None or candidate < best:
                best = candidate
        assert best is not None
        chosen.append(best[2])
    return p.loc[chosen].drop(columns=["cx", "cy", "centroid_d2"]).reset_index(drop=True)


def select_holdout_rows(requests: Any, process_root: Path, excluded_tile: str, cfg: dict[str, Any]) -> Any:
    import pandas as pd

    rows = requests.copy()
    rows["process_path"] = [str(process_root / Path(str(rel).replace("/", os.sep))) for rel in rows["daily_output_relative"]]
    rows["cached"] = [Path(p).is_file() and Path(p + ".json").is_file() for p in rows["process_path"]]
    cached = rows[rows["cached"]].copy()
    cached = cached[cached["tile_id"].astype(str) != str(excluded_tile)].copy()
    per_date = cached.groupby("date").size().sort_index()
    need = int(cfg["selection"]["requests_per_date"])
    dates = [str(d) for d, count in per_date.items() if int(count) >= need]
    dates = dates[: int(cfg["selection"]["maximum_dates"])]
    if len(dates) < int(cfg["selection"]["minimum_dates"]):
        raise RuntimeError(f"Only {len(dates)} cached dates have >= {need} independent requests")
    parts = []
    for day in dates:
        part = cached[cached["date"].astype(str) == day].copy()
        parts.append(deterministic_spread(part, need))
    selected = pd.concat(parts, ignore_index=True)
    if selected["tile_id"].astype(str).eq(str(excluded_tile)).any():
        raise RuntimeError("Parent diagnostic tile leaked into D1-S3c holdout")
    return selected.sort_values(["date", "tile_id"], kind="mergesort").reset_index(drop=True)


def main() -> int:
    import pandas as pd
    import rasterio

    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(CFG))
    ap.add_argument("--output-dir")
    args = ap.parse_args()

    cfg = read_json(Path(args.config))
    if cfg.get("schema_version") != "akerpuls-d1s3c-independent-backend-holdout-v1":
        raise RuntimeError("Unexpected D1-S3c config schema")
    if any(bool(v) for v in cfg["guards"].values()):
        raise RuntimeError("D1-S3c forbidden-scope guard unexpectedly enabled")
    sem = cfg["candidate_backend_semantics"]
    if (sem["scene_order"], sem["coverage"], sem["reflectance"], sem["resampling"]) != ("REVERSED", "SCL_NONZERO", "SCALE_OFFSET", "NEAREST"):
        raise RuntimeError("D1-S3c frozen backend semantics changed")

    parent = load_module(PARENT_SCRIPT, "akerpuls_d1s3_parent")
    diag = load_module(DIAG_SCRIPT, "akerpuls_d1s3_diag")
    parent_cfg = read_json(ROOT / cfg["parent_parity_config"])
    diag_manifest = read_json(Path(cfg["parent_diagnostic_output_dir"]) / "d1s3b_manifest.json")
    excluded_tile = str(diag_manifest["selected_tile"])
    if parent_cfg["expected_final_execution_contract_sha256"] != cfg["expected_final_execution_contract_sha256"]:
        raise RuntimeError("Execution contract binding changed")

    out = Path(args.output_dir or cfg["output_dir"])
    out.mkdir(parents=True, exist_ok=True)
    cache_root = Path(cfg["s3_cache_root"])
    requests = pd.read_csv(parent_cfg["d0_request_plan"], encoding="utf-8-sig")
    process_root = Path(parent_cfg["process_raw_root"])

    log("D1S3C_PROGRESS=SELECT_INDEPENDENT_CACHED_HOLDOUT")
    selected = select_holdout_rows(requests, process_root, excluded_tile, cfg)
    selected.to_csv(out / "d1s3c_selected_holdout_requests.csv", index=False, encoding="utf-8-sig")
    dates = sorted(selected["date"].astype(str).unique())
    log(f"D1S3C_EXCLUDED_PARENT_TILE={excluded_tile}")
    log(f"D1S3C_SELECTED_DATES={','.join(dates)}")
    log(f"D1S3C_REQUESTS={len(selected)}")

    scene_sets = []
    process_paths = []
    scene_rows = []
    log("D1S3C_PROGRESS=VERIFY_CACHE_AND_QUERY_STAC")
    for _, row in selected.iterrows():
        process_path = parent.verify_selected_process_tile(row)
        process_paths.append(process_path)
        scenes = parent.query_stac_for_request(row, parent_cfg, out)
        scene_sets.append(scenes)
        for rank, scene in enumerate(scenes):
            scene_rows.append({"date": row.date, "tile_id": row.tile_id, "parent_rank": rank, "item_id": scene["item_id"], "datetime": scene["datetime"]})
    pd.DataFrame(scene_rows).to_csv(out / "d1s3c_scene_inventory.csv", index=False, encoding="utf-8-sig")

    unique, projected_bytes = parent.estimate_unique_assets(scene_sets)
    projected_gib = projected_bytes / (1024 ** 3)
    free_gib = shutil.disk_usage(cache_root).free / (1024 ** 3)
    guards = cfg["resource_guards"]
    if len(unique) > int(guards["maximum_unique_scene_assets"]):
        raise RuntimeError("D1-S3c unique scene-asset guard exceeded")
    if projected_gib > float(guards["maximum_projected_download_gib"]):
        raise RuntimeError("D1-S3c projected download guard exceeded")
    if free_gib - projected_gib < float(guards["minimum_free_gib_after_projected_download"]):
        raise RuntimeError("D1-S3c free-disk guard failed")
    log(f"D1S3C_UNIQUE_SCENE_ASSETS={len(unique)}")
    log(f"D1S3C_PROJECTED_ARCHIVE_GIB={projected_gib:.3f}")
    log(f"D1S3C_FREE_DISK_GIB={free_gib:.3f}")

    log("D1S3C_PROGRESS=DOWNLOAD_DIRECT_S3_ASSETS")
    downloads, cache_hits, downloaded_bytes = parent.download_assets(scene_sets, cache_root, {**parent_cfg, "resource_guards": {**parent_cfg["resource_guards"], "maximum_unique_scene_assets": int(guards["maximum_unique_scene_assets"]), "maximum_download_gib": float(guards["maximum_projected_download_gib"]), "minimum_free_gib_after_projected_download": float(guards["minimum_free_gib_after_projected_download"])}})

    clear_codes = set(map(int, sem["clear_scl_codes"]))
    radius = int(sem["interior_radius_pixels"])
    result_rows = []
    log("D1S3C_PROGRESS=REPROJECT_FIXED_BACKEND_AND_COMPARE")
    for i, ((_, row), process_path, scenes) in enumerate(zip(selected.iterrows(), process_paths, scene_sets), 1):
        with rasterio.open(process_path) as ds:
            reference = ds.read().astype(np.float32)
            shape, transform, crs = (ds.height, ds.width), ds.transform, ds.crs
        scene_data = [diag.reproject_scene(scene, cache_root, shape, transform, crs, parent) for scene in scenes]
        candidate, owner = diag.mosaic(scene_data, sem["scene_order"], sem["coverage"], sem["reflectance"])
        m = diag.metrics(reference, candidate, owner, clear_codes, radius)
        result_rows.append({"date": str(row.date), "tile_id": str(row.tile_id), **m})
        log(
            f"D1S3C_PARITY {i}/{len(selected)} date={row.date} tile={row.tile_id} "
            f"validmask={m['valid_mask_agreement']:.6f} scl={m['scl_agreement_common_data']:.6f} "
            f"ndvi_p99={m['valid_ndvi_p99']:.6g} lswi_p99={m['valid_lswi_p99']:.6g} "
            f"interior_ndvi_p99={m['interior_ndvi_p99']:.6g}"
        )

    frame = pd.DataFrame(result_rows)
    frame.to_csv(out / "d1s3c_holdout_parity.csv", index=False, encoding="utf-8-sig")
    summary = {
        "schema_version": "akerpuls-d1s3c-independent-backend-holdout-result-v1",
        "status": "HOLDOUT_COMPLETE",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "excluded_parent_diagnostic_tile": excluded_tile,
        "dates": dates,
        "requests": int(len(frame)),
        "candidate_backend_semantics": sem,
        "valid_mask_agreement_p10": float(frame["valid_mask_agreement"].quantile(0.10)),
        "valid_mask_agreement_p50": float(frame["valid_mask_agreement"].quantile(0.50)),
        "valid_mask_agreement_min": float(frame["valid_mask_agreement"].min()),
        "ndvi_p99_p50": float(frame["valid_ndvi_p99"].quantile(0.50)),
        "ndvi_p99_p90": float(frame["valid_ndvi_p99"].quantile(0.90)),
        "ndvi_p99_max": float(frame["valid_ndvi_p99"].max()),
        "lswi_p99_p50": float(frame["valid_lswi_p99"].quantile(0.50)),
        "lswi_p99_p90": float(frame["valid_lswi_p99"].quantile(0.90)),
        "lswi_p99_max": float(frame["valid_lswi_p99"].max()),
        "s3_asset_downloads": int(downloads),
        "s3_asset_cache_hits": int(cache_hits),
        "s3_downloaded_bytes": int(downloaded_bytes),
        "process_api_calls": 0,
        "sentinel_hub_pu_used": 0,
        "thresholds_changed": False,
        "full_skane_s3_authorized": False,
        "automatic_geometry_replacement": False,
        "next_step": "Review independent holdout distribution. If stable, run an end-to-end pilot/model parity before authorizing full-Skane direct S3 acquisition."
    }
    (out / "d1s3c_manifest.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    log("AKERPULS D1-S3C INDEPENDENT BACKEND HOLDOUT")
    log("STATUS=HOLDOUT_COMPLETE")
    log(f"EXCLUDED_PARENT_DIAGNOSTIC_TILE={excluded_tile}")
    log(f"DATES={','.join(dates)} REQUESTS={len(frame)}")
    log(f"VALID_MASK_AGREEMENT_MIN={summary['valid_mask_agreement_min']:.6f} P10={summary['valid_mask_agreement_p10']:.6f} P50={summary['valid_mask_agreement_p50']:.6f}")
    log(f"NDVI_P99_P50={summary['ndvi_p99_p50']:.8g} P90={summary['ndvi_p99_p90']:.8g} MAX={summary['ndvi_p99_max']:.8g}")
    log(f"LSWI_P99_P50={summary['lswi_p99_p50']:.8g} P90={summary['lswi_p99_p90']:.8g} MAX={summary['lswi_p99_max']:.8g}")
    log(f"S3_ASSET_DOWNLOADS={downloads} S3_ASSET_CACHE_HITS={cache_hits} S3_DOWNLOADED_GIB={downloaded_bytes/(1024**3):.3f}")
    log("PROCESS_API_CALLS=0")
    log("SENTINEL_HUB_PU_USED=0")
    log("THRESHOLDS_CHANGED=FALSE")
    log("FULL_SKANE_S3_AUTHORIZED=FALSE")
    log("D1S3C_STATUS=HOLDOUT_COMPLETE")
    log(f"OUTPUT={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
