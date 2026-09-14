#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AkerPuls D1-S3f: C7 end-to-end Process-vs-direct-S3 pipeline parity.

Zero Sentinel Hub Process API calls. Reconstructs the exact C7B grid from direct
CDSE S3 under the D1-S3e-passed ALL_PARENT semantics, rebuilds all four frozen
snapshots, then reruns the frozen C7C split + TRUE-LOO + 3-signal fusion pipeline.
Acceptance was frozen before any S3-C7 model outcome was observed.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config" / "akerpuls_d1s3f_c7_end_to_end_parity_v1.json"
MASTER = ROOT / "config" / "akerpuls_prelim_fields_2026_v0.json"
PARENT = ROOT / "src" / "142_akerpuls_d1s3_parity_v1.py"
DIAG = ROOT / "src" / "143_akerpuls_d1s3b_diagnostic_v1.py"
RESILIENT = ROOT / "src" / "144_akerpuls_d1s3c_independent_holdout_v1.py"
B1 = ROOT / "src" / "112_akerpuls_prelim_fields_2026_b1_rasters.py"
C7C = ROOT / "src" / "135_akerpuls_c7c_frozen_fusion_validation.py"
SNAPS = ["S2_2026_APRIL", "S2_2026_MAY", "S2_2026_JUNE", "S2_2026_JULY"]
SOURCE_BANDS = ["B02", "B03", "B04", "B08", "B11", "SCL", "CLD", "dataMask"]


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def log(s: str) -> None:
    print(s, flush=True)


def finite_q(values: Any, q: float) -> float:
    x = pd.to_numeric(pd.Series(values), errors="coerce").to_numpy(dtype=float)
    x = x[np.isfinite(x)]
    return float(np.quantile(x, q)) if len(x) else math.nan


def finite_max(values: Any) -> float:
    x = pd.to_numeric(pd.Series(values), errors="coerce").to_numpy(dtype=float)
    x = x[np.isfinite(x)]
    return float(np.max(x)) if len(x) else math.nan


def jaccard(a: set[str], b: set[str]) -> float:
    u = a | b
    return 1.0 if not u else len(a & b) / len(u)


def write_source(path: Path, arr: np.ndarray, transform: Any, crs: Any) -> None:
    import rasterio
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".partial")
    profile = {
        "driver": "GTiff", "width": arr.shape[2], "height": arr.shape[1],
        "count": 8, "dtype": "float32", "crs": crs, "transform": transform,
        "compress": "DEFLATE", "predictor": 3, "tiled": True,
        "blockxsize": 256, "blockysize": 256,
    }
    with rasterio.open(tmp, "w", **profile) as ds:
        ds.write(arr.astype(np.float32))
        for i, name in enumerate(SOURCE_BANDS, 1):
            ds.set_band_description(i, name)
    tmp.replace(path)


def build_field_validity(pilot_path: Path, raster_dir: Path, transform: Any, shape: tuple[int, int]) -> list[dict[str, Any]]:
    import geopandas as gpd
    import rasterio
    from rasterio.features import rasterize

    g = gpd.read_file(pilot_path).to_crs(32633).reset_index(drop=True)
    labels = rasterize(
        [(geom, i + 1) for i, geom in enumerate(g.geometry)],
        out_shape=shape, transform=transform, fill=0, dtype="int32", all_touched=False,
    )
    totals = np.bincount(labels.ravel(), minlength=len(g) + 1).astype(float)
    rows = [{"parent_field_id_2025": str(fid), "pixels": int(totals[i])}
            for i, fid in enumerate(g["parent_field_id_2025"].astype(str), 1)]
    summary: list[dict[str, Any]] = []
    for snap in SNAPS:
        p = raster_dir / f"{snap.lower()}.tif"
        with rasterio.open(p) as ds:
            desc = {n: i + 1 for i, n in enumerate(ds.descriptions) if n}
            valid = ds.read(desc["VALID"]).astype(np.float32)
        good = np.bincount(labels.ravel(), weights=valid.ravel(), minlength=len(g) + 1)
        col = f"valid_{snap.lower()}"
        vals = []
        for i, rec in enumerate(rows, 1):
            v = None if totals[i] == 0 else round(float(good[i] / totals[i]), 6)
            rec[col] = v
            if v is not None:
                vals.append(v)
        field_mask = labels > 0
        vf = float(valid[field_mask].mean()) if field_mask.any() else 0.0
        summary.append({
            "snapshot": snap, "pilot_pixel_valid_fraction": round(vf, 6),
            "fields_ge_0p8_valid": int(sum(v >= 0.8 for v in vals)),
            "fields_ge_0p5_valid": int(sum(v >= 0.5 for v in vals)),
            "fields_total": int(len(vals)),
        })
    pd.DataFrame(rows).to_csv(raster_dir / "field_snapshot_validity.csv", index=False)
    return summary


def snapshot_diagnostics(ref_dir: Path, s3_dir: Path, pilot_path: Path) -> pd.DataFrame:
    import geopandas as gpd
    import rasterio
    from rasterio.features import rasterize

    g = gpd.read_file(pilot_path).to_crs(32633)
    rows = []
    for snap in SNAPS:
        rp = ref_dir / f"{snap.lower()}.tif"
        sp = s3_dir / f"{snap.lower()}.tif"
        with rasterio.open(rp) as r, rasterio.open(sp) as s:
            if (r.width, r.height, r.transform, r.crs) != (s.width, s.height, s.transform, s.crs):
                raise RuntimeError(f"Snapshot grid mismatch for {snap}")
            ra = r.read().astype(np.float32); sa = s.read().astype(np.float32)
            labels = rasterize([(geom, 1) for geom in g.geometry], out_shape=(r.height, r.width),
                               transform=r.transform, fill=0, dtype="uint8", all_touched=False) > 0
        rv = ra[7] > 0.5; sv = sa[7] > 0.5
        common = labels & rv & sv
        valid_agree = float(np.mean(rv[labels] == sv[labels])) if labels.any() else math.nan
        if common.any():
            nd = np.abs(ra[8][common] - sa[8][common])
            lw = np.abs(ra[9][common] - sa[9][common])
            nd99 = float(np.quantile(nd, .99)); lw99 = float(np.quantile(lw, .99))
        else:
            nd99 = lw99 = math.nan
        rows.append({"snapshot": snap, "valid_agreement_fields": valid_agree,
                     "ndvi_abs_p99_common_valid": nd99, "lswi_abs_p99_common_valid": lw99,
                     "common_valid_pixels": int(common.sum())})
    return pd.DataFrame(rows)


def compare_pipeline(ref_dir: Path, s3_dir: Path, cfg: dict[str, Any]) -> tuple[dict[str, Any], pd.DataFrame]:
    rf = pd.read_csv(ref_dir / "c7c_field_validation.csv", dtype={"parent_field_id_2025": str})
    sf = pd.read_csv(s3_dir / "c7c_field_validation.csv", dtype={"parent_field_id_2025": str})
    m = rf.merge(sf, on="parent_field_id_2025", suffixes=("_ref", "_s3"), validate="one_to_one")
    if len(m) != int(cfg["expected_c7_fields"]):
        raise RuntimeError(f"C7 field comparison expected {cfg['expected_c7_fields']}, got {len(m)}")

    discovery_agreement = float((m["discovery_type_ref"].astype(str) == m["discovery_type_s3"].astype(str)).mean())
    ur = m["discovery_type_ref"].astype(str).eq("UNCERTAIN")
    us = m["discovery_type_s3"].astype(str).eq("UNCERTAIN")
    uncertain_agreement = float((ur == us).mean())
    ref_cand = set(rf.loc[rf.discovery_type.astype(str).eq("SPLIT_CANDIDATE"), "parent_field_id_2025"].astype(str))
    s3_cand = set(sf.loc[sf.discovery_type.astype(str).eq("SPLIT_CANDIDATE"), "parent_field_id_2025"].astype(str))
    candidate_j = jaccard(ref_cand, s3_cand)
    ref_locked = set(rf.loc[rf.get("locked_split_pass", False).fillna(False).astype(bool), "parent_field_id_2025"].astype(str))
    s3_locked = set(sf.loc[sf.get("locked_split_pass", False).fillna(False).astype(bool), "parent_field_id_2025"].astype(str))
    locked_sym = len(ref_locked ^ s3_locked)

    common_cand = ref_cand & s3_cand
    cm = m[m.parent_field_id_2025.astype(str).isin(common_cand)].copy()
    sep_abs = np.abs(pd.to_numeric(cm["separation_ratio_ref"], errors="coerce") - pd.to_numeric(cm["separation_ratio_s3"], errors="coerce"))

    rt = pd.read_csv(ref_dir / "c7c_true_loo_candidates.csv", dtype={"field_id_normalized": str})
    st = pd.read_csv(s3_dir / "c7c_true_loo_candidates.csv", dtype={"field_id_normalized": str})
    tm = rt[["field_id_normalized", "true_loo_min_child_dice"]].merge(
        st[["field_id_normalized", "true_loo_min_child_dice"]], on="field_id_normalized",
        suffixes=("_ref", "_s3"), how="inner", validate="one_to_one")
    tdiff = np.abs(pd.to_numeric(tm["true_loo_min_child_dice_ref"], errors="coerce") -
                   pd.to_numeric(tm["true_loo_min_child_dice_s3"], errors="coerce"))

    rc = pd.read_csv(ref_dir / "c7c_fusion_candidates.csv", dtype={"parent_field_id_2025": str})
    sc = pd.read_csv(s3_dir / "c7c_fusion_candidates.csv", dtype={"parent_field_id_2025": str})
    fm = rc[["parent_field_id_2025", "fusion_score"]].merge(
        sc[["parent_field_id_2025", "fusion_score"]], on="parent_field_id_2025",
        suffixes=("_ref", "_s3"), how="inner", validate="one_to_one")
    fdiff = np.abs(pd.to_numeric(fm["fusion_score_ref"], errors="coerce") - pd.to_numeric(fm["fusion_score_s3"], errors="coerce"))

    def tier_set(df: pd.DataFrame, col: str) -> set[str]:
        return set(df.loc[df[col].fillna(False).astype(bool), "parent_field_id_2025"].astype(str))
    rp90, sp90 = tier_set(rc, "fusion_ge_dev_p90"), tier_set(sc, "fusion_ge_dev_p90")
    rp95, sp95 = tier_set(rc, "fusion_ge_dev_p95"), tier_set(sc, "fusion_ge_dev_p95")

    result = {
        "fields_compared": int(len(m)),
        "field_discovery_exact_agreement": discovery_agreement,
        "uncertain_flag_exact_agreement": uncertain_agreement,
        "reference_baseline_candidates": len(ref_cand), "s3_baseline_candidates": len(s3_cand),
        "baseline_candidate_jaccard": candidate_j,
        "reference_locked_candidates": len(ref_locked), "s3_locked_candidates": len(s3_locked),
        "locked_candidate_symmetric_difference": int(locked_sym),
        "common_baseline_candidates": int(len(common_cand)),
        "separation_ratio_abs_diff_p95": finite_q(sep_abs, .95),
        "separation_ratio_abs_diff_max": finite_max(sep_abs),
        "common_true_loo_candidates": int(len(tm)),
        "true_loo_min_dice_abs_diff_p95": finite_q(tdiff, .95),
        "true_loo_min_dice_abs_diff_max": finite_max(tdiff),
        "common_fusion_candidates": int(len(fm)),
        "fusion_score_abs_diff_p95": finite_q(fdiff, .95),
        "fusion_score_abs_diff_max": finite_max(fdiff),
        "reference_p90": len(rp90), "s3_p90": len(sp90),
        "fusion_p90_symmetric_difference": len(rp90 ^ sp90),
        "reference_p95": len(rp95), "s3_p95": len(sp95),
        "fusion_p95_symmetric_difference": len(rp95 ^ sp95),
        "reference_p95_falling_below_s3_p90": len(rp95 - sp90),
    }

    a = cfg["acceptance"]
    checks = {
        "field_discovery": result["field_discovery_exact_agreement"] >= float(a["field_discovery_exact_agreement_min"]),
        "uncertain_flag": result["uncertain_flag_exact_agreement"] >= float(a["uncertain_flag_exact_agreement_min"]),
        "baseline_candidate_jaccard": result["baseline_candidate_jaccard"] >= float(a["baseline_candidate_jaccard_min"]),
        "locked_candidate_symdiff": result["locked_candidate_symmetric_difference"] <= int(a["locked_candidate_symmetric_difference_max"]),
        "separation_p95": result["separation_ratio_abs_diff_p95"] <= float(a["separation_ratio_abs_diff_p95_max"]),
        "separation_max": result["separation_ratio_abs_diff_max"] <= float(a["separation_ratio_abs_diff_max"]),
        "true_loo_p95": result["true_loo_min_dice_abs_diff_p95"] <= float(a["true_loo_min_dice_abs_diff_p95_max"]),
        "true_loo_max": result["true_loo_min_dice_abs_diff_max"] <= float(a["true_loo_min_dice_abs_diff_max"]),
        "fusion_score_p95": result["fusion_score_abs_diff_p95"] <= float(a["fusion_score_abs_diff_p95_max"]),
        "fusion_score_max": result["fusion_score_abs_diff_max"] <= float(a["fusion_score_abs_diff_max"]),
        "fusion_p90_symdiff": result["fusion_p90_symmetric_difference"] <= int(a["fusion_p90_symmetric_difference_max"]),
        "fusion_p95_symdiff": result["fusion_p95_symmetric_difference"] <= int(a["fusion_p95_symmetric_difference_max"]),
        "no_p95_collapse": result["reference_p95_falling_below_s3_p90"] <= int(a["reference_p95_falling_below_s3_p90_max"]),
    }
    result["checks"] = checks
    result["pass"] = bool(all(checks.values()))

    detail = m[["parent_field_id_2025", "discovery_type_ref", "discovery_type_s3"]].copy()
    detail["discovery_equal"] = detail.discovery_type_ref.astype(str).eq(detail.discovery_type_s3.astype(str))
    return result, detail


def main() -> int:
    import geopandas as gpd
    import rasterio

    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(CFG))
    ap.add_argument("--output-dir")
    args = ap.parse_args()
    cfg = read_json(Path(args.config))
    if cfg.get("schema_version") != "akerpuls-d1s3f-c7-end-to-end-parity-v1":
        raise RuntimeError("Unexpected D1-S3f config schema")
    if any(bool(v) for v in cfg["guards"].values()):
        raise RuntimeError("D1-S3f forbidden-scope guard unexpectedly enabled")
    if not bool(cfg["acceptance"]["frozen_before_s3_c7_outcomes"]):
        raise RuntimeError("D1-S3f acceptance not frozen")
    sem = cfg["candidate_backend_semantics"]
    expected = ("ALL_ACQUISITIONS_RETURNED_BY_FROZEN_STAC_QUERY", "PARENT", "SCL_NONZERO", "SCALE_OFFSET", "NEAREST")
    got = (sem["scene_scope"], sem["scene_order"], sem["coverage"], sem["reflectance"], sem["resampling"])
    if got != expected or not bool(sem["frozen_from_d1s3e"]):
        raise RuntimeError("D1-S3f backend semantics changed")

    d1e = read_json(Path(cfg["parent_d1s3e_output_dir"]) / "d1s3e_manifest.json")
    if d1e.get("status") != "PASS_TO_END_TO_END_PARITY":
        raise RuntimeError("D1-S3e did not pass to end-to-end parity")
    if int(d1e.get("process_api_calls", -1)) != 0 or float(d1e.get("sentinel_hub_pu_used", -1)) != 0.0:
        raise RuntimeError("D1-S3e is not zero-PU")

    out = Path(args.output_dir or cfg["output_dir"]); out.mkdir(parents=True, exist_ok=True)
    s3_rdir = out / "s3_c7b_rasters"; s3_rdir.mkdir(parents=True, exist_ok=True)
    s3_c7c_out = out / "s3_c7c_fusion_validation"; s3_c7c_out.mkdir(parents=True, exist_ok=True)
    ref_rdir = Path(cfg["c7b_reference_dir"]); ref_c7c = Path(cfg["c7c_reference_dir"])
    for needed in (ref_rdir / "c7b_manifest.json", ref_c7c / "c7c_summary.json"):
        if not needed.is_file(): raise FileNotFoundError(needed)

    parent = load_module(PARENT, "d1s3f_parent")
    diag = load_module(DIAG, "d1s3f_diag")
    resilient = load_module(RESILIENT, "d1s3f_resilient")
    b1 = load_module(B1, "d1s3f_b1")
    c7c = load_module(C7C, "d1s3f_c7c")
    parent_cfg = read_json(ROOT / cfg["parent_parity_config"])
    master = read_json(MASTER)
    if parent_cfg["expected_final_execution_contract_sha256"] != cfg["expected_final_execution_contract_sha256"]:
        raise RuntimeError("Execution contract binding changed")

    ref_manifest = read_json(ref_rdir / "c7b_manifest.json")
    if ref_manifest.get("status") != "PASS" or int(ref_manifest.get("pilot_fields", 0)) != int(cfg["expected_c7_fields"]):
        raise RuntimeError("Reference C7B manifest mismatch")
    if ref_manifest.get("fusion_freeze_sha256") != cfg["expected_fusion_freeze_sha256"]:
        raise RuntimeError("Reference C7B fusion freeze changed")
    grid = ref_manifest["grid"]; bbox = list(map(float, grid["bbox_32633"]))
    width, height = int(grid["width"]), int(grid["height"])
    with rasterio.open(ref_rdir / "s2_2026_april.tif") as rr:
        transform, crs = rr.transform, rr.crs
        if rr.width != width or rr.height != height:
            raise RuntimeError("Reference C7B grid manifest/raster mismatch")

    log("D1S3F_PROGRESS=QUERY_FROZEN_DATES_FOR_EXACT_C7_GRID")
    scene_sets: dict[str, list[dict[str, Any]]] = {}
    all_sets = []
    for snap, days in master["snapshots"].items():
        for day in days:
            row = SimpleNamespace(date=day, tile_id="C7_FULL", minx=bbox[0], miny=bbox[1], maxx=bbox[2], maxy=bbox[3])
            scenes = resilient.query_stac_resilient(parent, row, parent_cfg, out, cfg)
            scene_sets[day] = scenes; all_sets.append(scenes)
            log(f"D1S3F_STAC date={day} scenes={len(scenes)}")

    unique, projected_bytes = parent.estimate_unique_assets(all_sets)
    projected_gib = projected_bytes / (1024 ** 3)
    free_gib = shutil.disk_usage(Path(cfg["s3_cache_root"])).free / (1024 ** 3)
    rg = cfg["resource_guards"]
    if len(unique) > int(rg["maximum_unique_scene_assets"]): raise RuntimeError("D1-S3f asset guard exceeded")
    if projected_gib > float(rg["maximum_projected_download_gib"]): raise RuntimeError("D1-S3f download guard exceeded")
    if free_gib - projected_gib < float(rg["minimum_free_gib_after_projected_download"]): raise RuntimeError("D1-S3f disk guard failed")
    log(f"D1S3F_UNIQUE_SCENE_ASSETS={len(unique)} PROJECTED_GIB={projected_gib:.3f} FREE_GIB={free_gib:.3f}")

    dlcfg = {**parent_cfg, "resource_guards": {**parent_cfg["resource_guards"],
             "maximum_unique_scene_assets": int(rg["maximum_unique_scene_assets"]),
             "maximum_download_gib": float(rg["maximum_projected_download_gib"]),
             "minimum_free_gib_after_projected_download": float(rg["minimum_free_gib_after_projected_download"])}}
    downloads, cache_hits, downloaded_bytes = parent.download_assets(all_sets, Path(cfg["s3_cache_root"]), dlcfg)

    log("D1S3F_PROGRESS=REPROJECT_ALL_PARENT_DAILY_AND_BUILD_FROZEN_SNAPSHOTS")
    daily_arrays: dict[str, np.ndarray] = {}
    for day in sorted(scene_sets):
        scene_data = [diag.reproject_scene(sc, Path(cfg["s3_cache_root"]), (height, width), transform, crs, parent)
                      for sc in scene_sets[day]]
        arr, _owner = diag.mosaic(scene_data, "PARENT", "SCL_NONZERO", "SCALE_OFFSET")
        daily_arrays[day] = arr
        write_source(s3_rdir / "source_daily" / f"s2_{day}.tif", arr, transform, crs)
        log(f"D1S3F_DAILY date={day} scenes={len(scene_data)} data_fraction={float((arr[7] > .5).mean()):.6f}")

    for snap, days in master["snapshots"].items():
        snap_arr = b1.choose_pair([daily_arrays[d] for d in days], set(map(int, sem["clear_scl_codes"])))
        b1.write_snapshot(s3_rdir / f"{snap.lower()}.tif", snap_arr, transform, crs)

    pilot_path = Path(cfg["c7a_pilot_dir"]) / cfg["c7a_pilot_filename"]
    if len(gpd.read_file(pilot_path)) != int(cfg["expected_c7_fields"]):
        raise RuntimeError("C7 pilot field count changed")
    validity_summary = build_field_validity(pilot_path, s3_rdir, transform, (height, width))
    s3_manifest = {
        "schema_version": "akerpuls-d1s3f-c7b-direct-s3-raster-v1", "status": "PASS",
        "grid": grid, "pilot_fields": int(cfg["expected_c7_fields"]), "snapshot_dates": master["snapshots"],
        "preprocessing_contract": "IDENTICAL_TO_B1_C1_C5B", "pair_rule": "clear_pixel_first_then_lower_CLD; if both non-clear choose lower_CLD but VALID=0",
        "fusion_freeze_sha256": cfg["expected_fusion_freeze_sha256"], "new_reported_pu_total": 0.0,
        "snapshot_validity": validity_summary, "thresholds_tuned": False, "fusion_refit": False,
        "visual_labels_used": False, "product_rule_frozen": False,
        "backend": "DIRECT_CDSE_S3_ALL_PARENT", "process_api_calls": 0, "sentinel_hub_pu_used": 0,
    }
    (s3_rdir / "c7b_manifest.json").write_text(json.dumps(s3_manifest, indent=2) + "\n", encoding="utf-8")

    raster_diag = snapshot_diagnostics(ref_rdir, s3_rdir, pilot_path)
    raster_diag.to_csv(out / "d1s3f_snapshot_diagnostics.csv", index=False)
    for r in raster_diag.itertuples(index=False):
        log(f"D1S3F_SNAPSHOT {r.snapshot} valid_agree={r.valid_agreement_fields:.6f} ndvi_p99={r.ndvi_abs_p99_common_valid:.8g} lswi_p99={r.lswi_abs_p99_common_valid:.8g}")

    log("D1S3F_PROGRESS=RERUN_FROZEN_C7C_PIPELINE_ON_S3_RASTERS")
    c7cfg = read_json(ROOT / cfg["c7c_base_config"])
    c7cfg["raster_dir"] = str(s3_rdir)
    c7cfg["output_dir"] = str(s3_c7c_out)
    if c7cfg["expected_fusion_freeze_sha256"] != cfg["expected_fusion_freeze_sha256"]:
        raise RuntimeError("C7C fusion freeze mismatch")
    fdf = c7c.build_split_validation(c7cfg, s3_c7c_out)
    _cand, s3_summary = c7c.score_fusion(c7cfg, fdf, s3_c7c_out)
    (s3_c7c_out / "c7c_summary.json").write_text(json.dumps(s3_summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    result, detail = compare_pipeline(ref_c7c, s3_c7c_out, cfg)
    detail.to_csv(out / "d1s3f_field_discovery_comparison.csv", index=False)
    status = "PASS_TO_FULL_SKANE_S3_PLAN" if result["pass"] else "REVIEW"
    manifest = {
        "schema_version": "akerpuls-d1s3f-c7-end-to-end-parity-result-v1", "status": status,
        "backend_semantics": sem, "acceptance_contract": cfg["acceptance"], "comparison": result,
        "s3_asset_downloads": int(downloads), "s3_asset_cache_hits": int(cache_hits),
        "s3_downloaded_bytes": int(downloaded_bytes), "process_api_calls": 0, "sentinel_hub_pu_used": 0,
        "thresholds_changed": False, "fusion_refit": False, "visual_labels_used": False,
        "automatic_geometry_replacement": False, "full_skane_s3_executed": False,
        "next_step": "PASS authorizes only a separately guarded full-Skane direct-S3 acquisition plan using the frozen backend. REVIEW means diagnose without tuning on this C7 outcome."
    }
    (out / "d1s3f_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    log("AKERPULS D1-S3F C7 END-TO-END BACKEND PARITY")
    log(f"STATUS={status}")
    log(f"FIELDS={result['fields_compared']} DISCOVERY_AGREE={result['field_discovery_exact_agreement']:.6f} UNCERTAIN_AGREE={result['uncertain_flag_exact_agreement']:.6f}")
    log(f"BASELINE_REF={result['reference_baseline_candidates']} S3={result['s3_baseline_candidates']} JACCARD={result['baseline_candidate_jaccard']:.6f}")
    log(f"LOCKED_REF={result['reference_locked_candidates']} S3={result['s3_locked_candidates']} SYMDIFF={result['locked_candidate_symmetric_difference']}")
    log(f"SEP_ABS_P95={result['separation_ratio_abs_diff_p95']:.8g} MAX={result['separation_ratio_abs_diff_max']:.8g}")
    log(f"TRUE_LOO_MIN_DICE_ABS_P95={result['true_loo_min_dice_abs_diff_p95']:.8g} MAX={result['true_loo_min_dice_abs_diff_max']:.8g}")
    log(f"FUSION_SCORE_ABS_P95={result['fusion_score_abs_diff_p95']:.8g} MAX={result['fusion_score_abs_diff_max']:.8g}")
    log(f"P90_REF={result['reference_p90']} S3={result['s3_p90']} SYMDIFF={result['fusion_p90_symmetric_difference']}")
    log(f"P95_REF={result['reference_p95']} S3={result['s3_p95']} SYMDIFF={result['fusion_p95_symmetric_difference']} REF_P95_BELOW_S3_P90={result['reference_p95_falling_below_s3_p90']}")
    log("ACCEPTANCE_CHECKS=" + ";".join(f"{k}:{str(v).upper()}" for k, v in result["checks"].items()))
    log(f"S3_ASSET_DOWNLOADS={downloads} S3_ASSET_CACHE_HITS={cache_hits} S3_DOWNLOADED_GIB={downloaded_bytes/(1024**3):.3f}")
    log("PROCESS_API_CALLS=0")
    log("SENTINEL_HUB_PU_USED=0")
    log("THRESHOLDS_CHANGED=FALSE")
    log("FULL_SKANE_S3_EXECUTED=FALSE")
    log(f"D1S3F_STATUS={status}")
    log(f"OUTPUT={out}")
    return 0 if result["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
