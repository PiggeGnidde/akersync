#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D1-S3h: C5 geographic confirmation of Process-vs-direct-S3 backend equivalence.

The acceptance contract is frozen after the C7 REVIEW diagnosis and before any
C5 direct-S3 end-to-end outcome is observed. C5 is geographically separate from
C7 but belongs to the frozen fusion development/reference population; therefore
this stage validates backend equivalence, not model generalization.

No Sentinel Hub Process API call is permitted. The original C5B Process rasters
are immutable references. A compatibility staging directory lets the already
frozen C7C split/TRUE-LOO/fusion implementation run unchanged on C5.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config" / "akerpuls_d1s3h_c5_independent_e2e_v1.json"
MASTER = ROOT / "config" / "akerpuls_prelim_fields_2026_v0.json"
PARENT = ROOT / "src" / "142_akerpuls_d1s3_parity_v1.py"
DIAG = ROOT / "src" / "143_akerpuls_d1s3b_diagnostic_v1.py"
RESILIENT = ROOT / "src" / "144_akerpuls_d1s3c_independent_holdout_v1.py"
B1 = ROOT / "src" / "112_akerpuls_prelim_fields_2026_b1_rasters.py"
D1F = ROOT / "src" / "147_akerpuls_d1s3f_c7_end_to_end_parity_v1.py"
C7C = ROOT / "src" / "135_akerpuls_c7c_frozen_fusion_validation.py"
SNAPS = ["S2_2026_APRIL", "S2_2026_MAY", "S2_2026_JUNE", "S2_2026_JULY"]
EMPTY_DATE_POLICY = "ZERO_FILLED_FLOAT32_SOURCE_WITH_DATAMASK_0"


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


def as_bool(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series.fillna(False)
    return series.astype(str).str.strip().str.lower().isin(["true", "1", "yes"])


def finite_q(values: Any, q: float) -> float:
    x = pd.to_numeric(pd.Series(values), errors="coerce").to_numpy(dtype=float)
    x = x[np.isfinite(x)]
    return float(np.quantile(x, q)) if len(x) else math.nan


def finite_max(values: Any, empty: float = math.nan) -> float:
    x = pd.to_numeric(pd.Series(values), errors="coerce").to_numpy(dtype=float)
    x = x[np.isfinite(x)]
    return float(np.max(x)) if len(x) else float(empty)


def jaccard(a: set[str], b: set[str]) -> float:
    u = a | b
    return 1.0 if not u else len(a & b) / len(u)


def link_or_copy(src: Path, dst: Path) -> None:
    if not src.is_file():
        raise FileNotFoundError(src)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        if dst.stat().st_size != src.stat().st_size:
            raise RuntimeError(f"Existing staged file size mismatch: {dst}")
        return
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def c7_style_cfg(cfg: dict[str, Any], raster_dir: Path, output_dir: Path) -> dict[str, Any]:
    fp = cfg["frozen_fusion_pipeline"]
    return {
        "schema_version": "akerpuls-d1s3h-c5-c7c-adapter-v1",
        "pilot_dir": cfg["c5a_pilot_dir"],
        "raster_dir": str(raster_dir),
        "output_dir": str(output_dir),
        "pilot_filename": cfg["c5a_pilot_filename"],
        "expected_pilot_fields": int(cfg["expected_c5_fields"]),
        "candidate_discovery_contract": fp["candidate_discovery_contract"],
        "locked_split_rule": fp["locked_split_rule"],
        "fusion_freeze": cfg["fusion_freeze"],
        "expected_fusion_freeze_sha256": cfg["expected_fusion_freeze_sha256"],
        "rolling_prior": cfg["rolling_prior"],
        "true_loo_config": cfg["true_loo_config"],
        "fusion_tiers": {
            "development_p90": float(fp["development_p90"]),
            "development_p95": float(fp["development_p95"]),
        },
        "june_validity_strata": {
            "high": float(fp["june_validity_high"]),
            "medium": float(fp["june_validity_medium"]),
        },
        "guards": {
            "threshold_tuning": False, "fusion_refit": False,
            "visual_labels": False, "product_rule_freeze": False,
            "automatic_geometry_change": False,
            "sentinel_process_api_calls": False,
            "crop_classification": False, "full_skane": False,
        },
    }


def write_compat_manifest(path: Path, grid: dict[str, Any], cfg: dict[str, Any],
                          master: dict[str, Any], validity: list[dict[str, Any]] | None,
                          backend: str, empty_dates: list[str] | None = None) -> None:
    m = {
        "schema_version": "akerpuls-d1s3h-c5-c7b-compat-v1",
        "status": "PASS",
        "grid": grid,
        "pilot_fields": int(cfg["expected_c5_fields"]),
        "snapshot_dates": master["snapshots"],
        "preprocessing_contract": "IDENTICAL_TO_B1_C1_C5B",
        "pair_rule": "clear_pixel_first_then_lower_CLD; if both non-clear choose lower_CLD but VALID=0",
        "fusion_freeze_sha256": cfg["expected_fusion_freeze_sha256"],
        "thresholds_tuned": False,
        "fusion_refit": False,
        "visual_labels_used": False,
        "product_rule_frozen": False,
        "backend": backend,
        "snapshot_validity": validity or [],
        "process_api_calls": 0,
        "sentinel_hub_pu_used": 0,
    }
    if empty_dates is not None:
        m["empty_frozen_date_policy"] = EMPTY_DATE_POLICY
        m["empty_frozen_dates"] = list(empty_dates)
    path.write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def stage_process_reference(cfg: dict[str, Any], master: dict[str, Any], out: Path) -> tuple[Path, dict[str, Any]]:
    src = Path(cfg["c5b_process_reference_dir"])
    manifest = read_json(src / "c5b_manifest.json")
    if manifest.get("status") != "PASS" or manifest.get("preprocessing_contract") != "IDENTICAL_TO_B1":
        raise RuntimeError("C5B Process reference is not the accepted clean PASS")
    if manifest.get("thresholds_tuned") is not False:
        raise RuntimeError("C5B Process reference reports threshold tuning")
    if int(manifest.get("pilot_fields", 0)) != int(cfg["expected_c5_fields"]):
        raise RuntimeError("C5B Process reference field count changed")

    stage = out / "process_c5b_compat"
    stage.mkdir(parents=True, exist_ok=True)
    for snap in SNAPS:
        name = f"{snap.lower()}.tif"
        link_or_copy(src / name, stage / name)
    link_or_copy(src / "field_snapshot_validity.csv", stage / "field_snapshot_validity.csv")
    write_compat_manifest(stage / "c7b_manifest.json", manifest["grid"], cfg, master,
                          manifest.get("snapshot_validity", []), "PROCESS_C5B_REFERENCE")
    return stage, manifest["grid"]


def verify_reference_adapter(cfg: dict[str, Any], new_fdf: pd.DataFrame) -> dict[str, Any]:
    legacy_path = Path(cfg["c5c_legacy_validation_dir"]) / "c5c_field_validation.csv"
    legacy = pd.read_csv(legacy_path, dtype={"parent_field_id_2025": str})
    new = new_fdf.copy()
    legacy_ids = set(legacy["parent_field_id_2025"].astype(str))
    new_ids = set(new["parent_field_id_2025"].astype(str))
    if legacy_ids != new_ids or len(new) != int(cfg["expected_c5_fields"]):
        raise RuntimeError("C5 compatibility adapter field population differs from legacy C5C")
    m = legacy[["parent_field_id_2025", "discovery_type", "split_candidate_pass"]].merge(
        new[["parent_field_id_2025", "discovery_type", "locked_split_pass"]],
        on="parent_field_id_2025", suffixes=("_legacy", "_adapter"), validate="one_to_one")
    discovery_exact = bool((m.discovery_type_legacy.astype(str) == m.discovery_type_adapter.astype(str)).all())
    locked_exact = bool((as_bool(m.split_candidate_pass) == as_bool(m.locked_split_pass)).all())
    exp = cfg["expected_legacy_c5"]
    baseline = int((new.discovery_type.astype(str) == "SPLIT_CANDIDATE").sum())
    locked = int(as_bool(new.locked_split_pass).sum())
    uncertain = int((new.discovery_type.astype(str) == "UNCERTAIN").sum())
    if not discovery_exact or not locked_exact:
        raise RuntimeError("C5 C7C compatibility adapter does not reproduce legacy C5C discovery/locked rule")
    if baseline != int(exp["baseline_split_candidates"]) or locked != int(exp["locked_split_candidates"]) or uncertain != int(exp["uncertain"]):
        raise RuntimeError(f"C5 legacy count guard failed: baseline={baseline} locked={locked} uncertain={uncertain}")
    return {"discovery_exact": discovery_exact, "locked_exact": locked_exact,
            "baseline": baseline, "locked": locked, "uncertain": uncertain}


def query_frozen_date_scenes(resilient: Any, parent: Any, row: Any,
                             parent_cfg: dict[str, Any], out: Path,
                             cfg: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        return resilient.query_stac_resilient(parent, row, parent_cfg, out, cfg)
    except RuntimeError as exc:
        if str(exc).strip() != f"No STAC scenes for {row.date} / {row.tile_id}":
            raise
        log(f"D1S3H_STAC_EMPTY date={row.date} tile={row.tile_id} policy={EMPTY_DATE_POLICY}")
        return []


def compare_pipeline(ref_dir: Path, s3_dir: Path, cfg: dict[str, Any]) -> tuple[dict[str, Any], pd.DataFrame]:
    rf = pd.read_csv(ref_dir / "c7c_field_validation.csv", dtype={"parent_field_id_2025": str})
    sf = pd.read_csv(s3_dir / "c7c_field_validation.csv", dtype={"parent_field_id_2025": str})
    m = rf.merge(sf, on="parent_field_id_2025", suffixes=("_ref", "_s3"), validate="one_to_one")
    if len(m) != int(cfg["expected_c5_fields"]):
        raise RuntimeError("C5 pipeline comparison field count mismatch")

    discovery_agree = float((m.discovery_type_ref.astype(str) == m.discovery_type_s3.astype(str)).mean())
    uncertain_ref = m.discovery_type_ref.astype(str).eq("UNCERTAIN")
    uncertain_s3 = m.discovery_type_s3.astype(str).eq("UNCERTAIN")
    uncertain_agree = float((uncertain_ref == uncertain_s3).mean())
    ref_cand = set(rf.loc[rf.discovery_type.astype(str).eq("SPLIT_CANDIDATE"), "parent_field_id_2025"].astype(str))
    s3_cand = set(sf.loc[sf.discovery_type.astype(str).eq("SPLIT_CANDIDATE"), "parent_field_id_2025"].astype(str))
    common_cand = ref_cand & s3_cand
    candidate_j = jaccard(ref_cand, s3_cand)
    ref_locked = set(rf.loc[as_bool(rf.locked_split_pass), "parent_field_id_2025"].astype(str))
    s3_locked = set(sf.loc[as_bool(sf.locked_split_pass), "parent_field_id_2025"].astype(str))

    cm = m[m.parent_field_id_2025.astype(str).isin(common_cand)].copy()
    sep_diff = np.abs(pd.to_numeric(cm.separation_ratio_ref, errors="coerce") - pd.to_numeric(cm.separation_ratio_s3, errors="coerce"))

    rt = pd.read_csv(ref_dir / "c7c_true_loo_candidates.csv", dtype={"field_id_normalized": str})
    st = pd.read_csv(s3_dir / "c7c_true_loo_candidates.csv", dtype={"field_id_normalized": str})
    tm = rt[["field_id_normalized", "true_loo_min_child_dice"]].merge(
        st[["field_id_normalized", "true_loo_min_child_dice"]], on="field_id_normalized",
        suffixes=("_ref", "_s3"), how="inner", validate="one_to_one")
    loo_diff = np.abs(pd.to_numeric(tm.true_loo_min_child_dice_ref, errors="coerce") -
                      pd.to_numeric(tm.true_loo_min_child_dice_s3, errors="coerce"))

    rc = pd.read_csv(ref_dir / "c7c_fusion_candidates.csv", dtype={"parent_field_id_2025": str})
    sc = pd.read_csv(s3_dir / "c7c_fusion_candidates.csv", dtype={"parent_field_id_2025": str})
    fm = rc[["parent_field_id_2025", "fusion_score", "fusion_ge_dev_p90", "fusion_ge_dev_p95"]].merge(
        sc[["parent_field_id_2025", "fusion_score", "fusion_ge_dev_p90", "fusion_ge_dev_p95"]],
        on="parent_field_id_2025", suffixes=("_ref", "_s3"), how="inner", validate="one_to_one")
    fm["fusion_abs_diff"] = np.abs(pd.to_numeric(fm.fusion_score_ref, errors="coerce") -
                                    pd.to_numeric(fm.fusion_score_s3, errors="coerce"))

    rp90 = set(rc.loc[as_bool(rc.fusion_ge_dev_p90), "parent_field_id_2025"].astype(str))
    sp90 = set(sc.loc[as_bool(sc.fusion_ge_dev_p90), "parent_field_id_2025"].astype(str))
    rp95 = set(rc.loc[as_bool(rc.fusion_ge_dev_p95), "parent_field_id_2025"].astype(str))
    sp95 = set(sc.loc[as_bool(sc.fusion_ge_dev_p95), "parent_field_id_2025"].astype(str))
    priority_union = rp90 | sp90
    common_fusion = set(fm.parent_field_id_2025.astype(str))
    priority_noncommon = priority_union - common_fusion
    priority_diff = fm.loc[fm.parent_field_id_2025.astype(str).isin(priority_union), "fusion_abs_diff"]

    result = {
        "fields_compared": int(len(m)),
        "field_discovery_exact_agreement": discovery_agree,
        "uncertain_flag_exact_agreement": uncertain_agree,
        "reference_baseline_candidates": len(ref_cand), "s3_baseline_candidates": len(s3_cand),
        "baseline_candidate_jaccard": candidate_j,
        "reference_locked_candidates": len(ref_locked), "s3_locked_candidates": len(s3_locked),
        "locked_candidate_symmetric_difference": len(ref_locked ^ s3_locked),
        "common_baseline_candidates": len(common_cand),
        "separation_ratio_abs_diff_p95": finite_q(sep_diff, .95),
        "separation_ratio_abs_diff_max": finite_max(sep_diff),
        "common_true_loo_candidates": int(len(tm)),
        "true_loo_min_dice_abs_diff_p95": finite_q(loo_diff, .95),
        "true_loo_min_dice_abs_diff_max": finite_max(loo_diff),
        "common_fusion_candidates": int(len(fm)),
        "fusion_score_abs_diff_p95": finite_q(fm.fusion_abs_diff, .95),
        "fusion_score_abs_diff_global_max_diagnostic": finite_max(fm.fusion_abs_diff),
        "priority_union_candidates": len(priority_union),
        "priority_union_noncommon_candidates": len(priority_noncommon),
        "priority_union_noncommon_ids": sorted(priority_noncommon),
        "fusion_priority_union_abs_diff_max": finite_max(priority_diff, empty=0.0),
        "reference_p90": len(rp90), "s3_p90": len(sp90),
        "fusion_p90_symmetric_difference": len(rp90 ^ sp90),
        "reference_p95": len(rp95), "s3_p95": len(sp95),
        "fusion_p95_symmetric_difference": len(rp95 ^ sp95),
        "reference_p95_falling_below_s3_p90": len(rp95 - sp90),
    }
    a = cfg["acceptance"]
    checks = {
        "field_discovery": discovery_agree >= float(a["field_discovery_exact_agreement_min"]),
        "uncertain_flag": uncertain_agree >= float(a["uncertain_flag_exact_agreement_min"]),
        "baseline_candidate_jaccard": candidate_j >= float(a["baseline_candidate_jaccard_min"]),
        "locked_candidate_symdiff": result["locked_candidate_symmetric_difference"] <= int(a["locked_candidate_symmetric_difference_max"]),
        "separation_p95": result["separation_ratio_abs_diff_p95"] <= float(a["separation_ratio_abs_diff_p95_max"]),
        "separation_max": result["separation_ratio_abs_diff_max"] <= float(a["separation_ratio_abs_diff_max"]),
        "true_loo_p95": result["true_loo_min_dice_abs_diff_p95"] <= float(a["true_loo_min_dice_abs_diff_p95_max"]),
        "true_loo_max": result["true_loo_min_dice_abs_diff_max"] <= float(a["true_loo_min_dice_abs_diff_max"]),
        "fusion_score_p95": result["fusion_score_abs_diff_p95"] <= float(a["fusion_score_abs_diff_p95_max"]),
        "priority_union_score_max": result["fusion_priority_union_abs_diff_max"] <= float(a["fusion_priority_union_abs_diff_max"]),
        "priority_union_all_comparable": result["priority_union_noncommon_candidates"] <= int(a["fusion_priority_union_noncommon_candidates_max"]),
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
    if cfg.get("schema_version") != "akerpuls-d1s3h-c5-backend-confirmation-v1":
        raise RuntimeError("Unexpected D1-S3h config schema")
    if any(bool(v) for v in cfg["guards"].values()):
        raise RuntimeError("D1-S3h forbidden-scope guard unexpectedly enabled")
    a = cfg["acceptance"]
    if not bool(a["frozen_before_c5_s3_outcomes"]) or not bool(a["global_low_tier_fusion_max_is_not_an_acceptance_metric"]):
        raise RuntimeError("D1-S3h post-C7 acceptance contract is not frozen as declared")
    if cfg["empty_frozen_date_policy"] != EMPTY_DATE_POLICY:
        raise RuntimeError("D1-S3h empty-date policy changed")
    sem = cfg["candidate_backend_semantics"]
    expected_sem = ("ALL_ACQUISITIONS_RETURNED_BY_FROZEN_STAC_QUERY", "PARENT", "SCL_NONZERO", "SCALE_OFFSET", "NEAREST")
    got_sem = (sem["scene_scope"], sem["scene_order"], sem["coverage"], sem["reflectance"], sem["resampling"])
    if got_sem != expected_sem or not bool(sem["frozen_from_d1s3e"]):
        raise RuntimeError("D1-S3h backend semantics changed")

    d1f_manifest = read_json(Path(cfg["d1s3f_output_dir"]) / "d1s3f_manifest.json")
    d1g_manifest = read_json(Path(cfg["d1s3g_output_dir"]) / "d1s3g_manifest.json")
    if d1f_manifest.get("status") != "REVIEW" or d1g_manifest.get("d1s3f_status") != "REVIEW":
        raise RuntimeError("D1-S3h requires preserved D1-S3f REVIEW provenance")
    if d1g_manifest.get("failed_frozen_checks") != ["fusion_score_max"]:
        raise RuntimeError("D1-S3g provenance differs from the diagnosed single-check REVIEW")

    out = Path(args.output_dir or cfg["output_dir"]); out.mkdir(parents=True, exist_ok=True)
    master = read_json(MASTER)
    c7c = load_module(C7C, "d1s3h_c7c")
    b1 = load_module(B1, "d1s3h_b1")
    parent = load_module(PARENT, "d1s3h_parent")
    diag = load_module(DIAG, "d1s3h_diag")
    resilient = load_module(RESILIENT, "d1s3h_resilient")
    d1f = load_module(D1F, "d1s3h_d1f")
    parent_cfg = read_json(ROOT / cfg["parent_parity_config"])
    if parent_cfg["expected_final_execution_contract_sha256"] != cfg["expected_final_execution_contract_sha256"]:
        raise RuntimeError("D1-S3h execution-contract binding changed")

    pilot_path = Path(cfg["c5a_pilot_dir"]) / cfg["c5a_pilot_filename"]
    if len(gpd.read_file(pilot_path)) != int(cfg["expected_c5_fields"]):
        raise RuntimeError("C5 pilot field count changed")

    log("D1S3H_PROGRESS=STAGE_IMMUTABLE_C5_PROCESS_REFERENCE_AND_RUN_FROZEN_FUSION")
    ref_rdir, grid = stage_process_reference(cfg, master, out)
    ref_fusion = out / "process_c5_frozen_fusion"; ref_fusion.mkdir(parents=True, exist_ok=True)
    ref_cfg = c7_style_cfg(cfg, ref_rdir, ref_fusion)
    ref_fdf = c7c.build_split_validation(ref_cfg, ref_fusion)
    _ref_cand, ref_summary = c7c.score_fusion(ref_cfg, ref_fdf, ref_fusion)
    adapter = verify_reference_adapter(cfg, ref_fdf)
    log(f"D1S3H_REFERENCE_ADAPTER baseline={adapter['baseline']} locked={adapter['locked']} uncertain={adapter['uncertain']} legacy_exact=TRUE")

    bbox = list(map(float, grid["bbox_32633"])); width = int(grid["width"]); height = int(grid["height"])
    with rasterio.open(ref_rdir / "s2_2026_april.tif") as rr:
        transform, crs = rr.transform, rr.crs
        if rr.width != width or rr.height != height:
            raise RuntimeError("C5 reference raster grid/manifest mismatch")

    log("D1S3H_PROGRESS=QUERY_FROZEN_DATES_FOR_EXACT_C5_GRID")
    scene_sets: dict[str, list[dict[str, Any]]] = {}; all_sets = []; empty_dates: list[str] = []
    for _snap, days in master["snapshots"].items():
        for day in days:
            row = SimpleNamespace(date=day, tile_id="C5_FULL", minx=bbox[0], miny=bbox[1], maxx=bbox[2], maxy=bbox[3])
            scenes = query_frozen_date_scenes(resilient, parent, row, parent_cfg, out, cfg)
            if not scenes: empty_dates.append(day)
            scene_sets[day] = scenes; all_sets.append(scenes)
            log(f"D1S3H_STAC date={day} scenes={len(scenes)}")

    unique, projected_bytes = parent.estimate_unique_assets(all_sets)
    projected_gib = projected_bytes / (1024 ** 3)
    cache_root = Path(cfg["s3_cache_root"]); cache_root.mkdir(parents=True, exist_ok=True)
    free_gib = shutil.disk_usage(cache_root).free / (1024 ** 3)
    rg = cfg["resource_guards"]
    if len(unique) > int(rg["maximum_unique_scene_assets"]): raise RuntimeError("D1-S3h asset guard exceeded")
    if projected_gib > float(rg["maximum_projected_download_gib"]): raise RuntimeError("D1-S3h download guard exceeded")
    if free_gib - projected_gib < float(rg["minimum_free_gib_after_projected_download"]): raise RuntimeError("D1-S3h disk guard failed")
    log(f"D1S3H_UNIQUE_SCENE_ASSETS={len(unique)} PROJECTED_GIB={projected_gib:.3f} FREE_GIB={free_gib:.3f}")
    dlcfg = {**parent_cfg, "resource_guards": {**parent_cfg["resource_guards"],
             "maximum_unique_scene_assets": int(rg["maximum_unique_scene_assets"]),
             "maximum_download_gib": float(rg["maximum_projected_download_gib"]),
             "minimum_free_gib_after_projected_download": float(rg["minimum_free_gib_after_projected_download"])}}
    downloads, cache_hits, downloaded_bytes = parent.download_assets(all_sets, cache_root, dlcfg)

    log("D1S3H_PROGRESS=BUILD_DIRECT_S3_C5_SNAPSHOTS")
    s3_rdir = out / "s3_c5b_compat"; s3_rdir.mkdir(parents=True, exist_ok=True)
    daily_arrays: dict[str, np.ndarray] = {}
    for day in sorted(scene_sets):
        scenes = scene_sets[day]
        if scenes:
            scene_data = [diag.reproject_scene(sc, cache_root, (height, width), transform, crs, parent) for sc in scenes]
            arr, _owner = diag.mosaic(scene_data, "PARENT", "SCL_NONZERO", "SCALE_OFFSET")
        else:
            scene_data = []; arr = np.zeros((8, height, width), dtype=np.float32)
        daily_arrays[day] = arr
        d1f.write_source(s3_rdir / "source_daily" / f"s2_{day}.tif", arr, transform, crs)
        log(f"D1S3H_DAILY date={day} scenes={len(scene_data)} data_fraction={float((arr[7] > .5).mean()):.6f}")
    for snap, days in master["snapshots"].items():
        snap_arr = b1.choose_pair([daily_arrays[d] for d in days], set(map(int, sem["clear_scl_codes"])))
        b1.write_snapshot(s3_rdir / f"{snap.lower()}.tif", snap_arr, transform, crs)
    validity = d1f.build_field_validity(pilot_path, s3_rdir, transform, (height, width))
    write_compat_manifest(s3_rdir / "c7b_manifest.json", grid, cfg, master, validity,
                          "DIRECT_CDSE_S3_ALL_PARENT_C5", empty_dates)

    raster_diag = d1f.snapshot_diagnostics(ref_rdir, s3_rdir, pilot_path)
    raster_diag.to_csv(out / "d1s3h_snapshot_diagnostics.csv", index=False)
    for r in raster_diag.itertuples(index=False):
        log(f"D1S3H_SNAPSHOT {r.snapshot} valid_agree={r.valid_agreement_fields:.6f} ndvi_p99={r.ndvi_abs_p99_common_valid:.8g} lswi_p99={r.lswi_abs_p99_common_valid:.8g}")

    log("D1S3H_PROGRESS=RUN_SAME_FROZEN_FUSION_ON_C5_S3")
    s3_fusion = out / "s3_c5_frozen_fusion"; s3_fusion.mkdir(parents=True, exist_ok=True)
    s3_cfg = c7_style_cfg(cfg, s3_rdir, s3_fusion)
    s3_fdf = c7c.build_split_validation(s3_cfg, s3_fusion)
    _s3_cand, s3_summary = c7c.score_fusion(s3_cfg, s3_fdf, s3_fusion)

    result, detail = compare_pipeline(ref_fusion, s3_fusion, cfg)
    detail.to_csv(out / "d1s3h_field_discovery_comparison.csv", index=False)
    status = "PASS_TO_FULL_SKANE_S3_PLAN" if result["pass"] else "REVIEW"
    manifest = {
        "schema_version": "akerpuls-d1s3h-c5-backend-confirmation-result-v1",
        "status": status,
        "c7_frozen_status_preserved": "REVIEW",
        "reference_adapter": adapter,
        "reference_fusion_summary": ref_summary,
        "s3_fusion_summary": s3_summary,
        "backend_semantics": sem,
        "empty_frozen_date_policy": EMPTY_DATE_POLICY,
        "empty_frozen_dates": empty_dates,
        "acceptance_contract": a,
        "comparison": result,
        "s3_asset_downloads": int(downloads), "s3_asset_cache_hits": int(cache_hits),
        "s3_downloaded_bytes": int(downloaded_bytes),
        "process_api_calls": 0, "sentinel_hub_pu_used": 0,
        "thresholds_changed": False, "fusion_refit": False, "visual_labels_used": False,
        "automatic_geometry_replacement": False, "full_skane_s3_executed": False,
        "interpretation": cfg["interpretation"],
    }
    (out / "d1s3h_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    log("AKERPULS D1-S3H C5 GEOGRAPHIC BACKEND CONFIRMATION")
    log(f"STATUS={status}")
    log("C7_FROZEN_STATUS_REMAINS=REVIEW")
    log(f"EMPTY_FROZEN_DATES={','.join(empty_dates) if empty_dates else 'NONE'}")
    log(f"FIELDS={result['fields_compared']} DISCOVERY_AGREE={result['field_discovery_exact_agreement']:.6f} UNCERTAIN_AGREE={result['uncertain_flag_exact_agreement']:.6f}")
    log(f"BASELINE_REF={result['reference_baseline_candidates']} S3={result['s3_baseline_candidates']} JACCARD={result['baseline_candidate_jaccard']:.6f}")
    log(f"LOCKED_REF={result['reference_locked_candidates']} S3={result['s3_locked_candidates']} SYMDIFF={result['locked_candidate_symmetric_difference']}")
    log(f"SEP_ABS_P95={result['separation_ratio_abs_diff_p95']:.8g} MAX={result['separation_ratio_abs_diff_max']:.8g}")
    log(f"TRUE_LOO_MIN_DICE_ABS_P95={result['true_loo_min_dice_abs_diff_p95']:.8g} MAX={result['true_loo_min_dice_abs_diff_max']:.8g}")
    log(f"FUSION_SCORE_ABS_P95={result['fusion_score_abs_diff_p95']:.8g} GLOBAL_MAX_DIAGNOSTIC={result['fusion_score_abs_diff_global_max_diagnostic']:.8g}")
    log(f"PRIORITY_UNION={result['priority_union_candidates']} NONCOMMON={result['priority_union_noncommon_candidates']} SCORE_ABS_MAX={result['fusion_priority_union_abs_diff_max']:.8g}")
    log(f"P90_REF={result['reference_p90']} S3={result['s3_p90']} SYMDIFF={result['fusion_p90_symmetric_difference']}")
    log(f"P95_REF={result['reference_p95']} S3={result['s3_p95']} SYMDIFF={result['fusion_p95_symmetric_difference']} REF_P95_BELOW_S3_P90={result['reference_p95_falling_below_s3_p90']}")
    log("ACCEPTANCE_CHECKS=" + ";".join(f"{k}:{str(v).upper()}" for k, v in result["checks"].items()))
    log(f"S3_ASSET_DOWNLOADS={downloads} S3_ASSET_CACHE_HITS={cache_hits} S3_DOWNLOADED_GIB={downloaded_bytes/(1024**3):.3f}")
    log("PROCESS_API_CALLS=0")
    log("SENTINEL_HUB_PU_USED=0")
    log("THRESHOLDS_CHANGED=FALSE")
    log("FULL_SKANE_S3_EXECUTED=FALSE")
    log(f"D1S3H_STATUS={status}")
    log(f"OUTPUT={out}")
    return 0 if result["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
