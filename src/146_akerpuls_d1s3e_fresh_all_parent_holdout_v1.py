#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerPuls D1-S3e: fresh predeclared ALL_PARENT direct-S3 holdout.

This stage follows the post-holdout D1-S3d diagnostic, where ALL_PARENT won
11/12 requests. It excludes every tile ID used by the earlier D1-S3 parity and
D1-S3c holdout, freezes one backend semantics before these outcomes, and tests
it on fresh cached Process references. It never calls Sentinel Hub Process API.
A PASS authorizes only a later end-to-end pipeline parity test, not full-Skåne.

A first D1-S3e attempt stopped during STAC discovery, before any parity outcome,
because one cached Process request had no intersecting public-STAC scene. The
source-eligibility rule is therefore now frozen before outcomes: zero-scene rows
are replaced within the same date by a deterministic geographically spread
cached Process row. Replacement uses source availability and geometry only,
never parity metrics.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config" / "akerpuls_d1s3e_fresh_all_parent_holdout_v1.json"
PARENT_SCRIPT = ROOT / "src" / "142_akerpuls_d1s3_parity_v1.py"
DIAG_SCRIPT = ROOT / "src" / "143_akerpuls_d1s3b_diagnostic_v1.py"
HOLDOUT_SCRIPT = ROOT / "src" / "144_akerpuls_d1s3c_independent_holdout_v1.py"


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


def collect_prior_tile_ids(cfg: dict[str, Any], parent_cfg: dict[str, Any]) -> set[str]:
    prior: set[str] = set()
    parent_manifest = Path(parent_cfg["output_dir"]) / "d1s3_manifest.json"
    if not parent_manifest.is_file():
        raise FileNotFoundError(parent_manifest)
    pm = read_json(parent_manifest)
    prior.add(str(pm["selected_tile"]))

    cdir = Path(cfg["parent_holdout_output_dir"])
    selected_c = cdir / "d1s3c_selected_holdout_requests.csv"
    if not selected_c.is_file():
        raise FileNotFoundError(selected_c)
    import pandas as pd
    c = pd.read_csv(selected_c, encoding="utf-8-sig")
    prior.update(c["tile_id"].astype(str).tolist())
    return prior


def prepare_fresh_cached_rows(requests: Any, process_root: Path, prior_tiles: set[str]) -> Any:
    rows = requests.copy()
    rows["process_path"] = [str(process_root / Path(str(rel).replace("/", os.sep))) for rel in rows["daily_output_relative"]]
    rows["cached"] = [Path(p).is_file() and Path(p + ".json").is_file() for p in rows["process_path"]]
    cached = rows[rows["cached"]].copy()
    cached = cached[~cached["tile_id"].astype(str).isin(prior_tiles)].copy()
    return cached.reset_index(drop=True)


def select_fresh_rows(requests: Any, process_root: Path, prior_tiles: set[str], cfg: dict[str, Any], spread_fn: Any) -> Any:
    import pandas as pd

    cached = prepare_fresh_cached_rows(requests, process_root, prior_tiles)
    sel_cfg = cfg["selection"]
    need = int(sel_cfg["requests_per_date"])
    max_dates = int(sel_cfg["maximum_dates"])
    min_dates = int(sel_cfg["minimum_dates"])
    used_tiles: set[str] = set()
    parts = []

    for day in sorted(cached["date"].astype(str).unique()):
        part = cached[cached["date"].astype(str) == day].copy()
        if bool(sel_cfg["require_unique_tile_ids_across_dates"]):
            part = part[~part["tile_id"].astype(str).isin(used_tiles)].copy()
        if len(part) < need:
            continue
        chosen = spread_fn(part, need)
        if len(chosen) != need:
            raise RuntimeError(f"Fresh holdout spread selection returned {len(chosen)} rows for {day}, expected {need}")
        parts.append(chosen)
        used_tiles.update(chosen["tile_id"].astype(str).tolist())
        if len(parts) >= max_dates:
            break

    if len(parts) < min_dates:
        raise RuntimeError(f"Only {len(parts)} fresh dates support {need} unique prior-excluded cached requests")
    selected = pd.concat(parts, ignore_index=True)
    if selected["tile_id"].astype(str).isin(prior_tiles).any():
        raise RuntimeError("Prior tile leaked into D1-S3e fresh holdout")
    if bool(sel_cfg["require_unique_tile_ids_across_dates"]) and selected["tile_id"].astype(str).duplicated().any():
        raise RuntimeError("D1-S3e global tile uniqueness violated")
    return selected.sort_values(["date", "tile_id"], kind="mergesort").reset_index(drop=True)


def is_no_stac_scene_error(exc: Exception) -> bool:
    return isinstance(exc, RuntimeError) and str(exc).startswith("No STAC scenes for ")


def deterministic_same_date_replacement(cached: Any, day: str, current_selected: Any, forbidden_tiles: set[str]) -> Any:
    """Pick a deterministic same-date reserve without using any parity outcome.

    Candidate = row maximizing minimum squared centroid distance to the currently
    selected rows of that same date; ties are broken by tile_id. If there are no
    same-date anchors, choose the lexicographically first tile_id.
    """
    part = cached[cached["date"].astype(str) == str(day)].copy()
    part = part[~part["tile_id"].astype(str).isin(forbidden_tiles)].copy()
    if part.empty:
        raise RuntimeError(f"No same-date reserve candidates remain for {day}")

    part["cx"] = (part["minx"].astype(float) + part["maxx"].astype(float)) / 2.0
    part["cy"] = (part["miny"].astype(float) + part["maxy"].astype(float)) / 2.0
    anchors = current_selected[current_selected["date"].astype(str) == str(day)].copy()
    if anchors.empty:
        return part.sort_values("tile_id", kind="mergesort").iloc[0].drop(labels=["cx", "cy"])

    anchors["cx"] = (anchors["minx"].astype(float) + anchors["maxx"].astype(float)) / 2.0
    anchors["cy"] = (anchors["miny"].astype(float) + anchors["maxy"].astype(float)) / 2.0
    scores = []
    for idx, r in part.iterrows():
        d2 = ((anchors["cx"] - float(r.cx)) ** 2 + (anchors["cy"] - float(r.cy)) ** 2).min()
        scores.append((float(d2), str(r.tile_id), idx))
    scores.sort(key=lambda x: (-x[0], x[1]))
    chosen_idx = scores[0][2]
    return part.loc[chosen_idx].drop(labels=["cx", "cy"])


def evaluate_acceptance(frame: Any, cfg: dict[str, Any]) -> dict[str, Any]:
    a = cfg["acceptance"]
    request_pass = (
        (frame["valid_ndvi_p99"] <= float(a["request_ndvi_p99_max"])) &
        (frame["valid_lswi_p99"] <= float(a["request_lswi_p99_max"]))
    )
    pass_fraction = float(request_pass.mean())
    ndvi_p90 = float(frame["valid_ndvi_p99"].quantile(0.90))
    lswi_p90 = float(frame["valid_lswi_p99"].quantile(0.90))
    ndvi_max = float(frame["valid_ndvi_p99"].max())
    lswi_max = float(frame["valid_lswi_p99"].max())
    validmask_p10 = float(frame["valid_mask_agreement"].quantile(0.10))
    scl_p10 = float(frame["scl_agreement_common_data"].quantile(0.10))
    checks = {
        "request_pass_fraction": pass_fraction >= float(a["minimum_request_pass_fraction"]),
        "ndvi_p90": ndvi_p90 <= float(a["aggregate_ndvi_p99_p90_max"]),
        "lswi_p90": lswi_p90 <= float(a["aggregate_lswi_p99_p90_max"]),
        "ndvi_max": ndvi_max <= float(a["aggregate_ndvi_p99_max_max"]),
        "lswi_max": lswi_max <= float(a["aggregate_lswi_p99_max_max"]),
        "validmask_p10": validmask_p10 >= float(a["valid_mask_agreement_p10_min"]),
        "scl_p10": scl_p10 >= float(a["scl_agreement_common_data_p10_min"]),
    }
    return {
        "request_pass_count": int(request_pass.sum()),
        "request_pass_fraction": pass_fraction,
        "ndvi_p90": ndvi_p90,
        "lswi_p90": lswi_p90,
        "ndvi_max": ndvi_max,
        "lswi_max": lswi_max,
        "validmask_p10": validmask_p10,
        "scl_p10": scl_p10,
        "checks": checks,
        "pass": all(checks.values()),
    }


def main() -> int:
    import pandas as pd
    import rasterio

    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(CFG))
    ap.add_argument("--output-dir")
    args = ap.parse_args()

    cfg = read_json(Path(args.config))
    if cfg.get("schema_version") != "akerpuls-d1s3e-fresh-all-parent-holdout-v1":
        raise RuntimeError("Unexpected D1-S3e config schema")
    if any(bool(v) for v in cfg["guards"].values()):
        raise RuntimeError("D1-S3e forbidden-scope guard unexpectedly enabled")
    sem = cfg["candidate_backend_semantics"]
    expected_sem = ("ALL_ACQUISITIONS_RETURNED_BY_FROZEN_STAC_QUERY", "PARENT", "SCL_NONZERO", "SCALE_OFFSET", "NEAREST")
    actual_sem = (sem["scene_scope"], sem["scene_order"], sem["coverage"], sem["reflectance"], sem["resampling"])
    if actual_sem != expected_sem or not bool(sem["frozen_after_d1s3d_before_d1s3e_outcomes"]):
        raise RuntimeError("D1-S3e frozen backend semantics changed")
    if not bool(cfg["acceptance"]["frozen_before_holdout_outcomes"]):
        raise RuntimeError("D1-S3e acceptance was not frozen before outcomes")
    src_elig = cfg.get("source_eligibility", {})
    if not bool(src_elig.get("frozen_after_zero_scene_block_before_any_d1s3e_parity_outcomes", False)):
        raise RuntimeError("D1-S3e source-eligibility replacement rule is not frozen")
    if bool(src_elig.get("replacement_may_use_parity_metrics", True)):
        raise RuntimeError("D1-S3e replacement must never use parity metrics")

    parent = load_module(PARENT_SCRIPT, "akerpuls_d1s3_parent")
    diag = load_module(DIAG_SCRIPT, "akerpuls_d1s3_diag")
    prev = load_module(HOLDOUT_SCRIPT, "akerpuls_d1s3c_prev")
    parent_cfg = read_json(ROOT / cfg["parent_parity_config"])
    if parent_cfg["expected_final_execution_contract_sha256"] != cfg["expected_final_execution_contract_sha256"]:
        raise RuntimeError("Execution contract binding changed")

    dmanifest_path = Path(cfg["parent_group_diagnostic_output_dir"]) / "d1s3d_manifest.json"
    if not dmanifest_path.is_file():
        raise FileNotFoundError(dmanifest_path)
    dm = read_json(dmanifest_path)
    if dm.get("status") != "DIAGNOSTIC_COMPLETE" or int(dm.get("variant_wins", {}).get("ALL_PARENT", 0)) != 11:
        raise RuntimeError("D1-S3e expects the observed D1-S3d ALL_PARENT:11 diagnostic result")

    out = Path(args.output_dir or cfg["output_dir"])
    out.mkdir(parents=True, exist_ok=True)
    cache_root = Path(cfg["s3_cache_root"])
    requests = pd.read_csv(parent_cfg["d0_request_plan"], encoding="utf-8-sig")
    process_root = Path(parent_cfg["process_raw_root"])
    prior_tiles = collect_prior_tile_ids(cfg, parent_cfg)
    cached_fresh = prepare_fresh_cached_rows(requests, process_root, prior_tiles)

    log("D1S3E_PROGRESS=SELECT_FRESH_PRIOR_EXCLUDED_HOLDOUT")
    selected = select_fresh_rows(requests, process_root, prior_tiles, cfg, prev.deterministic_spread)
    selected.to_csv(out / "d1s3e_initial_selected_holdout_requests.csv", index=False, encoding="utf-8-sig")
    dates = sorted(selected["date"].astype(str).unique())
    log(f"D1S3E_PRIOR_TILE_IDS_EXCLUDED={len(prior_tiles)}")
    log(f"D1S3E_SELECTED_DATES={','.join(dates)}")
    log(f"D1S3E_REQUESTS={len(selected)} UNIQUE_TILES={selected['tile_id'].astype(str).nunique()}")

    scene_sets: list[list[dict[str, Any]]] = []
    process_paths: list[Path] = []
    scene_rows: list[dict[str, Any]] = []
    replacement_rows: list[dict[str, Any]] = []
    selected = selected.copy().reset_index(drop=True)
    reserved_tiles = set(selected["tile_id"].astype(str).tolist())
    rejected_tiles: set[str] = set()

    log("D1S3E_PROGRESS=VERIFY_CACHE_QUERY_STAC_AND_REPLACE_ZERO_SCENE")
    i = 0
    while i < len(selected):
        row = selected.iloc[i]
        process_path = parent.verify_selected_process_tile(row)
        log(f"D1S3E_STAC_PROGRESS={i+1}/{len(selected)} date={row.date} tile={row.tile_id}")
        try:
            scenes = prev.query_stac_resilient(parent, row, parent_cfg, out, cfg)
        except Exception as exc:
            if not is_no_stac_scene_error(exc):
                raise
            old_tile = str(row.tile_id)
            day = str(row.date)
            reserved_tiles.discard(old_tile)
            rejected_tiles.add(old_tile)
            current_without = selected.drop(index=i).reset_index(drop=True)
            forbidden = set(prior_tiles) | set(reserved_tiles) | set(rejected_tiles)
            repl = deterministic_same_date_replacement(cached_fresh, day, current_without, forbidden)
            new_tile = str(repl.tile_id)
            if new_tile in forbidden:
                raise RuntimeError("D1-S3e replacement selected a forbidden tile")
            replacement_rows.append({
                "date": day,
                "rejected_tile_id": old_tile,
                "reason": "ZERO_STAC_SCENES",
                "replacement_tile_id": new_tile,
                "selection_rule": src_elig["on_zero_stac_scenes"],
            })
            for col in selected.columns:
                selected.at[i, col] = repl[col]
            reserved_tiles.add(new_tile)
            log(f"D1S3E_SOURCE_REPLACEMENT date={day} rejected={old_tile} replacement={new_tile} reason=ZERO_STAC_SCENES")
            continue

        if len(scenes) < int(src_elig.get("minimum_stac_scenes", 1)):
            raise RuntimeError(f"Source-eligibility invariant failed for {row.date}/{row.tile_id}")
        process_paths.append(process_path)
        scene_sets.append(scenes)
        for rank, scene in enumerate(scenes):
            scene_rows.append({
                "date": str(row.date), "tile_id": str(row.tile_id), "parent_rank": rank,
                "item_id": scene["item_id"], "datetime": scene["datetime"],
            })
        i += 1

    if len(scene_sets) != len(selected) or len(process_paths) != len(selected):
        raise RuntimeError("D1-S3e source-eligible selection did not produce one scene set per request")
    if selected["tile_id"].astype(str).duplicated().any():
        raise RuntimeError("D1-S3e final global tile uniqueness violated after replacement")
    per_date = selected.groupby(selected["date"].astype(str)).size().to_dict()
    if any(int(per_date.get(day, 0)) != int(cfg["selection"]["requests_per_date"]) for day in dates):
        raise RuntimeError("D1-S3e replacement changed per-date holdout size")

    selected.to_csv(out / "d1s3e_selected_holdout_requests.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(replacement_rows, columns=["date","rejected_tile_id","reason","replacement_tile_id","selection_rule"]).to_csv(
        out / "d1s3e_source_unavailable_replacements.csv", index=False, encoding="utf-8-sig"
    )
    pd.DataFrame(scene_rows).to_csv(out / "d1s3e_scene_inventory.csv", index=False, encoding="utf-8-sig")
    log(f"D1S3E_SOURCE_REPLACEMENTS={len(replacement_rows)}")

    unique, projected_bytes = parent.estimate_unique_assets(scene_sets)
    projected_gib = projected_bytes / (1024 ** 3)
    free_gib = shutil.disk_usage(cache_root).free / (1024 ** 3)
    guards = cfg["resource_guards"]
    if len(unique) > int(guards["maximum_unique_scene_assets"]):
        raise RuntimeError("D1-S3e unique scene-asset guard exceeded")
    if projected_gib > float(guards["maximum_projected_download_gib"]):
        raise RuntimeError("D1-S3e projected download guard exceeded")
    if free_gib - projected_gib < float(guards["minimum_free_gib_after_projected_download"]):
        raise RuntimeError("D1-S3e free-disk guard failed")
    log(f"D1S3E_UNIQUE_SCENE_ASSETS={len(unique)}")
    log(f"D1S3E_PROJECTED_ARCHIVE_GIB={projected_gib:.3f}")
    log(f"D1S3E_FREE_DISK_GIB={free_gib:.3f}")

    log("D1S3E_PROGRESS=DOWNLOAD_DIRECT_S3_ASSETS")
    dl_cfg = {**parent_cfg, "resource_guards": {**parent_cfg["resource_guards"],
        "maximum_unique_scene_assets": int(guards["maximum_unique_scene_assets"]),
        "maximum_download_gib": float(guards["maximum_projected_download_gib"]),
        "minimum_free_gib_after_projected_download": float(guards["minimum_free_gib_after_projected_download"])}}
    downloads, cache_hits, downloaded_bytes = parent.download_assets(scene_sets, cache_root, dl_cfg)

    clear_codes = set(map(int, sem["clear_scl_codes"]))
    radius = int(sem["interior_radius_pixels"])
    rows = []
    log("D1S3E_PROGRESS=REPROJECT_FROZEN_ALL_PARENT_AND_COMPARE")
    for j, ((_, row), process_path, scenes) in enumerate(zip(selected.iterrows(), process_paths, scene_sets), 1):
        with rasterio.open(process_path) as ds:
            reference = ds.read().astype(np.float32)
            shape, transform, crs = (ds.height, ds.width), ds.transform, ds.crs
        scene_data = [diag.reproject_scene(scene, cache_root, shape, transform, crs, parent) for scene in scenes]
        candidate, owner = diag.mosaic(scene_data, "PARENT", "SCL_NONZERO", "SCALE_OFFSET")
        m = diag.metrics(reference, candidate, owner, clear_codes, radius)
        req_pass = m["valid_ndvi_p99"] <= float(cfg["acceptance"]["request_ndvi_p99_max"]) and m["valid_lswi_p99"] <= float(cfg["acceptance"]["request_lswi_p99_max"])
        rows.append({"date": str(row.date), "tile_id": str(row.tile_id), "request_pass": bool(req_pass), **m})
        log(
            f"D1S3E_PARITY {j}/{len(selected)} date={row.date} tile={row.tile_id} pass={str(req_pass).upper()} "
            f"validmask={m['valid_mask_agreement']:.6f} scl={m['scl_agreement_common_data']:.6f} "
            f"ndvi_p99={m['valid_ndvi_p99']:.8g} lswi_p99={m['valid_lswi_p99']:.8g}"
        )

    frame = pd.DataFrame(rows)
    frame.to_csv(out / "d1s3e_holdout_parity.csv", index=False, encoding="utf-8-sig")
    acc = evaluate_acceptance(frame, cfg)
    status = "PASS_TO_END_TO_END_PARITY" if acc["pass"] else "REVIEW"
    summary = {
        "schema_version": "akerpuls-d1s3e-fresh-all-parent-holdout-result-v1",
        "status": status,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "dates": dates,
        "requests": int(len(frame)),
        "unique_tiles": int(selected["tile_id"].astype(str).nunique()),
        "prior_tile_ids_excluded": sorted(prior_tiles),
        "source_eligibility_contract": src_elig,
        "source_replacements": replacement_rows,
        "candidate_backend_semantics": sem,
        "acceptance_contract": cfg["acceptance"],
        "acceptance_result": acc,
        "s3_asset_downloads": int(downloads),
        "s3_asset_cache_hits": int(cache_hits),
        "s3_downloaded_bytes": int(downloaded_bytes),
        "process_api_calls": 0,
        "sentinel_hub_pu_used": 0,
        "thresholds_changed": False,
        "full_skane_s3_authorized": False,
        "automatic_geometry_replacement": False,
        "next_step": "PASS permits only a separate end-to-end pilot/model parity using frozen backend semantics. REVIEW means no retuning on this holdout and no full-Skåne S3 authorization."
    }
    (out / "d1s3e_manifest.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    log("AKERPULS D1-S3E FRESH ALL_PARENT BACKEND HOLDOUT")
    log(f"STATUS={status}")
    log(f"DATES={','.join(dates)} REQUESTS={len(frame)} UNIQUE_TILES={summary['unique_tiles']}")
    log(f"SOURCE_REPLACEMENTS={len(replacement_rows)}")
    log(f"REQUEST_PASS={acc['request_pass_count']}/{len(frame)} FRACTION={acc['request_pass_fraction']:.4f}")
    log(f"VALID_MASK_P10={acc['validmask_p10']:.6f} SCL_P10={acc['scl_p10']:.6f}")
    log(f"NDVI_P99_P90={acc['ndvi_p90']:.8g} MAX={acc['ndvi_max']:.8g}")
    log(f"LSWI_P99_P90={acc['lswi_p90']:.8g} MAX={acc['lswi_max']:.8g}")
    log("ACCEPTANCE_CHECKS=" + ";".join(f"{k}:{str(v).upper()}" for k, v in acc["checks"].items()))
    log(f"S3_ASSET_DOWNLOADS={downloads} S3_ASSET_CACHE_HITS={cache_hits} S3_DOWNLOADED_GIB={downloaded_bytes/(1024**3):.3f}")
    log("PROCESS_API_CALLS=0")
    log("SENTINEL_HUB_PU_USED=0")
    log("THRESHOLDS_CHANGED=FALSE")
    log("FULL_SKANE_S3_AUTHORIZED=FALSE")
    log(f"D1S3E_STATUS={status}")
    log(f"OUTPUT={out}")
    return 0 if acc["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
