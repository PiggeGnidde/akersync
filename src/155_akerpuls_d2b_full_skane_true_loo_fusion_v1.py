#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D2B full-Skåne TRUE-LOO + frozen three-signal QA fusion.

Authorized only after the D2A review stop. Local disk/CPU only: no STAC, S3 or
Sentinel Hub Process API. The stage consumes only D2A baseline split candidates,
recomputes the frozen C6 TRUE leave-one-snapshot-out signal with the exact D0b
local normalization windows, joins the frozen rolling history prior, then applies
the frozen C7A empirical-midrank fusion. No thresholds are tuned/refit and no
geometry is automatically mutated or persisted.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import importlib.util
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config" / "akerpuls_d2b_full_skane_true_loo_fusion_v1.json"
THIS = Path(__file__).resolve()


def log(msg: str) -> None:
    print(msg, flush=True)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


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


def repo_path(v: str) -> Path:
    p = Path(v)
    return p if p.is_absolute() else ROOT / p


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def git_guard(cfg: dict[str, Any]) -> tuple[str, str]:
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    if branch != cfg["feature_branch"]:
        raise RuntimeError(f"Expected branch {cfg['feature_branch']}, got {branch}")
    dirty = subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True).strip()
    if dirty:
        raise RuntimeError("Working tree must be clean")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    return branch, head


def normalize_field_id(v: Any) -> str:
    s = str(v).strip()
    p = s.split("|")
    if len(p) >= 3 and p[0] == "2025":
        return "|".join(p[1:])
    return s


def empirical_midrank(ref_sorted: np.ndarray, values: np.ndarray) -> np.ndarray:
    """Exact C7C empirical midrank transform."""
    ref = np.asarray(ref_sorted, dtype=float)
    x = np.asarray(values, dtype=float)
    left = np.searchsorted(ref, x, side="left")
    right = np.searchsorted(ref, x, side="right")
    return (left + right) / (2.0 * len(ref))


def bool_series(x: pd.Series) -> pd.Series:
    if x.dtype == bool:
        return x
    return x.astype(str).str.strip().str.lower().isin({"true", "1", "yes"})


def validate_config(cfg: dict[str, Any]) -> None:
    if cfg.get("schema_version") != "akerpuls-d2b-full-skane-true-loo-fusion-v1":
        raise RuntimeError("Unexpected D2B config schema")
    auth = cfg["authorization"]
    if auth.get("status") != "AUTHORIZED_AFTER_D2A_REVIEW" or auth.get("user_command") != "GO D2B":
        raise RuntimeError("D2B does not contain the explicit post-D2A authorization")
    if any(bool(v) for v in cfg["guards"].values()):
        raise RuntimeError("D2B forbidden-scope guard unexpectedly enabled")
    ex = cfg["execution"]
    if ex.get("stage") != "D2B_ONLY" or ex.get("candidate_scope") != "D2A_B2_SPLIT_CANDIDATES_ONLY":
        raise RuntimeError("D2B candidate/stage scope changed")
    if int(ex.get("omission_refits", -1)) != 4 or not bool(ex.get("stop_after_d2b_for_review")):
        raise RuntimeError("D2B TRUE-LOO/review boundary changed")
    e = cfg["expected"]
    if int(e["fields"]) != 128636 or int(e["analysis_cells"]) != 46 or int(e["split_candidates"]) != 12676:
        raise RuntimeError("D2B frozen parent population changed")
    if int(e["development_reference_n"]) != 367:
        raise RuntimeError("D2B frozen fusion reference size changed")
    if list(e["weights"]) != [1/3, 1/3, 1/3]:
        raise RuntimeError("D2B frozen fusion weights changed")


def build_normalization_variants(datasets, band_maps, features, norm_geoms, d2a):
    """C6 scaling semantics on one D0b normalization population, I/O efficient."""
    from rasterio.features import rasterize
    from rasterio.windows import transform as window_transform

    bounds = d2a.bounds_for_geometries(norm_geoms)
    win = d2a.aligned_window(datasets[0], bounds)
    tr = window_transform(win, datasets[0].transform)
    h, w = int(win.height), int(win.width)
    field_mask = rasterize([(geom, 1) for geom in norm_geoms], out_shape=(h, w), transform=tr,
                           fill=0, dtype="uint8", all_touched=False) > 0
    if not field_mask.any():
        raise RuntimeError("D2B normalization population rasterized to zero pixels")

    valids = [ds.read(int(bm["VALID"]), window=win).astype(np.float32) > 0.5
              for ds, bm in zip(datasets, band_maps)]
    specs = {
        "FULL4": [0, 1, 2, 3],
        "OMIT_APRIL": [1, 2, 3],
        "OMIT_MAY": [0, 2, 3],
        "OMIT_JUNE": [0, 1, 3],
        "OMIT_JULY": [0, 1, 2],
    }
    variants: dict[str, dict[str, Any]] = {}
    masks: dict[str, np.ndarray] = {}
    for key, snaps in specs.items():
        vm = field_mask.copy()
        for i in snaps:
            vm &= valids[i]
        n = int(vm.sum())
        if n <= 0:
            raise RuntimeError(f"D2B normalization variant {key} has zero valid field pixels")
        masks[key] = vm
        variants[key] = {"snaps": snaps, "pixels": n, "center_parts": [], "scale_parts": []}

    # Read each source feature once. Appending in snapshot->feature order exactly
    # matches C6 extract_features/robust_scale_for_variant.
    for sidx, (ds, bm) in enumerate(zip(datasets, band_maps)):
        relevant = [k for k, v in variants.items() if sidx in v["snaps"]]
        for feat in features:
            arr = ds.read(int(bm[feat]), window=win).astype(np.float32)
            for key in relevant:
                vals = arr[masks[key]].astype(np.float64, copy=False)
                center = float(np.nanmedian(vals))
                mad = float(np.nanmedian(np.abs(vals - center)) * 1.4826)
                std = float(np.nanstd(vals))
                scale = mad if mad > 1e-6 else (std if std > 1e-6 else 1.0)
                if not np.isfinite(center) or not np.isfinite(scale) or scale <= 0:
                    raise RuntimeError(f"D2B non-finite normalization statistic {key}/{feat}")
                variants[key]["center_parts"].append(center)
                variants[key]["scale_parts"].append(scale)
            del arr

    for key, v in variants.items():
        v["center"] = np.asarray(v.pop("center_parts"), dtype=float)
        v["scale"] = np.asarray(v.pop("scale_parts"), dtype=float)
    return variants, [float(x) for x in bounds]


def loo_columns() -> list[str]:
    cols = [
        "parent_field_id_2025", "analysis_cell_id", "field_id_normalized",
        "reference_pixels", "existing_separation_ratio", "reference_fit_ok",
        "reference_separation_ratio", "true_loo_refits_ok",
        "true_loo_min_child_dice", "true_loo_mean_child_dice",
        "true_loo_min_child_fraction", "true_loo_stable", "true_loo_failure_reason",
    ]
    for s in ("april", "may", "june", "july"):
        cols += [f"omit_{s}_pixels", f"omit_{s}_fit_ok", f"omit_{s}_labels_swapped",
                 f"omit_{s}_dice0", f"omit_{s}_dice1", f"omit_{s}_min_dice",
                 f"omit_{s}_mean_dice", f"omit_{s}_min_child_fraction"]
    return cols


def process_cell_true_loo(cid: str, candidates: pd.DataFrame, candidate_ids: list[str],
                          cubes, valids, labels, variants, b2, b2cfg, tloo, tlcfg) -> pd.DataFrame:
    from scipy import ndimage as ndi

    if not candidate_ids:
        return pd.DataFrame(columns=loo_columns())
    cindex = candidates.set_index("parent_field_id_2025", drop=False)
    sp = b2cfg["split"]
    contract = tlcfg["true_loo_contract"]
    minpix = int(contract["minimum_reference_comparison_pixels"])
    minfrac_req = float(contract["minimum_child_fraction_each_omission_on_comparison_domain"])
    mindice_req = float(contract["minimum_each_child_dice_each_omission"])
    mean_req = float(contract["minimum_mean_matched_child_dice_across_all_omissions"])
    snap_names = list(tlcfg["snapshot_order"])
    rows: list[dict[str, Any]] = []

    for local_pos, fid in enumerate(candidate_ids, 1):
        rec = cindex.loc[fid]
        fm = labels == local_pos
        interior = ndi.binary_erosion(fm, structure=np.ones((3, 3), dtype=bool),
                                      iterations=int(sp["interior_erosion_pixels"]), border_value=0)
        if int(interior.sum()) < int(sp["minimum_valid_pixels"]):
            interior = fm.copy()

        full_valid = np.logical_and.reduce(valids)
        ref_mask = interior & full_valid
        nref = int(ref_mask.sum())
        base: dict[str, Any] = {
            "parent_field_id_2025": fid,
            "analysis_cell_id": cid,
            "field_id_normalized": normalize_field_id(fid),
            "reference_pixels": nref,
            "existing_separation_ratio": float(pd.to_numeric(rec["separation_ratio"], errors="coerce")),
        }
        if nref < minpix:
            base.update({"reference_fit_ok": False, "reference_separation_ratio": np.nan,
                         "true_loo_refits_ok": 0, "true_loo_min_child_dice": 0.0,
                         "true_loo_mean_child_dice": 0.0, "true_loo_min_child_fraction": 0.0,
                         "true_loo_stable": False, "true_loo_failure_reason": "TOO_FEW_REFERENCE_PIXELS"})
            rows.append(base); continue

        ref = variants["FULL4"]
        fit_ref = tloo.fit_mask(b2, cubes, ref_mask, ref["snaps"], ref["center"], ref["scale"])
        if fit_ref is None:
            base.update({"reference_fit_ok": False, "reference_separation_ratio": np.nan,
                         "true_loo_refits_ok": 0, "true_loo_min_child_dice": 0.0,
                         "true_loo_mean_child_dice": 0.0, "true_loo_min_child_fraction": 0.0,
                         "true_loo_stable": False, "true_loo_failure_reason": "REFERENCE_K2_FAILED"})
            rows.append(base); continue

        ref_lab, _centers, ref_between, ref_within = fit_ref
        ref_sep = float(ref_between / max(ref_within, 0.15))
        if abs(base["existing_separation_ratio"] - ref_sep) > 0.03:
            raise RuntimeError(
                f"D2B {fid}: reconstructed full4 separation {ref_sep:.4f} != D2A {base['existing_separation_ratio']:.4f}"
            )
        base["reference_fit_ok"] = True
        base["reference_separation_ratio"] = ref_sep
        ref_flat = np.flatnonzero(ref_mask.ravel())
        all_child_dice: list[float] = []
        all_minfrac: list[float] = []
        omission_ok = 0
        failures: list[str] = []
        per: dict[str, Any] = {}

        for omit_idx, snap_name in enumerate(snap_names):
            key = f"OMIT_{snap_name}"
            state = variants[key]
            valid3 = np.logical_and.reduce([valids[i] for i in state["snaps"]])
            m3 = interior & valid3
            n3 = int(m3.sum())
            prefix = f"omit_{snap_name.lower()}"
            per[f"{prefix}_pixels"] = n3
            if n3 < minpix:
                per.update({f"{prefix}_fit_ok": False, f"{prefix}_labels_swapped": False,
                            f"{prefix}_dice0": 0.0, f"{prefix}_dice1": 0.0,
                            f"{prefix}_min_dice": 0.0, f"{prefix}_mean_dice": 0.0,
                            f"{prefix}_min_child_fraction": 0.0})
                failures.append(f"{snap_name}:TOO_FEW_PIXELS")
                all_child_dice.extend([0.0, 0.0]); all_minfrac.append(0.0)
                continue
            fit3 = tloo.fit_mask(b2, cubes, m3, state["snaps"], state["center"], state["scale"])
            if fit3 is None:
                per.update({f"{prefix}_fit_ok": False, f"{prefix}_labels_swapped": False,
                            f"{prefix}_dice0": 0.0, f"{prefix}_dice1": 0.0,
                            f"{prefix}_min_dice": 0.0, f"{prefix}_mean_dice": 0.0,
                            f"{prefix}_min_child_fraction": 0.0})
                failures.append(f"{snap_name}:K2_FAILED")
                all_child_dice.extend([0.0, 0.0]); all_minfrac.append(0.0)
                continue

            lab3 = fit3[0]
            m3_flat = np.flatnonzero(m3.ravel())
            loc = np.searchsorted(m3_flat, ref_flat)
            if np.any(loc >= len(m3_flat)) or not np.array_equal(m3_flat[loc], ref_flat):
                raise RuntimeError(f"D2B {fid} {key}: FULL4 reference domain not subset of 3-date domain")
            pred_ref = lab3[loc]
            frac0 = float(np.mean(pred_ref == 0)); frac1 = float(np.mean(pred_ref == 1))
            minfrac = min(frac0, frac1)
            d0, d1, swapped = tloo.optimal_binary_dice(ref_lab, pred_ref)
            md = min(d0, d1); av = 0.5 * (d0 + d1)
            per.update({f"{prefix}_fit_ok": True, f"{prefix}_labels_swapped": bool(swapped),
                        f"{prefix}_dice0": d0, f"{prefix}_dice1": d1,
                        f"{prefix}_min_dice": md, f"{prefix}_mean_dice": av,
                        f"{prefix}_min_child_fraction": minfrac})
            omission_ok += 1
            all_child_dice.extend([d0, d1]); all_minfrac.append(minfrac)
            if minfrac < minfrac_req:
                failures.append(f"{snap_name}:CHILD_FRACTION")
            if md < mindice_req:
                failures.append(f"{snap_name}:DICE")

        mean_dice = float(np.mean(all_child_dice)) if all_child_dice else 0.0
        min_dice = float(np.min(all_child_dice)) if all_child_dice else 0.0
        min_child_fraction = float(np.min(all_minfrac)) if all_minfrac else 0.0
        stable = (omission_ok == 4 and min_child_fraction >= minfrac_req
                  and min_dice >= mindice_req and mean_dice >= mean_req)
        if mean_dice < mean_req:
            failures.append("MEAN_DICE")
        base.update(per)
        base.update({"true_loo_refits_ok": omission_ok,
                     "true_loo_min_child_dice": min_dice,
                     "true_loo_mean_child_dice": mean_dice,
                     "true_loo_min_child_fraction": min_child_fraction,
                     "true_loo_stable": bool(stable),
                     "true_loo_failure_reason": "" if stable else ";".join(failures)})
        rows.append(base)

    df = pd.DataFrame(rows)
    for c in loo_columns():
        if c not in df.columns:
            df[c] = np.nan
    return df[loo_columns()]


def validate_cached_cell(csv_path: Path, meta_path: Path, key: str, candidate_ids: list[str]) -> pd.DataFrame | None:
    if not csv_path.is_file() or not meta_path.is_file():
        return None
    try:
        meta = read_json(meta_path)
    except Exception:
        return None
    if meta.get("output_key_sha256") != key or meta.get("csv_sha256") != sha256_file(csv_path):
        return None
    df = pd.read_csv(csv_path, dtype={"parent_field_id_2025": str, "analysis_cell_id": str})
    if len(df) != len(candidate_ids) or set(df.parent_field_id_2025.astype(str)) != set(candidate_ids):
        return None
    if df.parent_field_id_2025.duplicated().any():
        return None
    return df


def main() -> int:
    import geopandas as gpd
    import rasterio
    from shapely.geometry import box

    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(CFG))
    ap.add_argument("--output-dir")
    args = ap.parse_args()
    cfg = read_json(Path(args.config))
    validate_config(cfg)
    branch, head = git_guard(cfg)
    out = Path(args.output_dir or cfg["output_dir"])
    out.mkdir(parents=True, exist_ok=True)

    log("D2B_PROGRESS=VERIFY_AUTHORIZED_D2A_PARENT_AND_FROZEN_INPUTS")
    p2 = cfg["parent_d2_plan"]
    d2_contract_path = Path(p2["execution_contract"])
    cell_plan_path = Path(p2["cell_plan"])
    if sha256_file(d2_contract_path) != p2["expected_execution_contract_sha256"]:
        raise RuntimeError("D2 execution contract SHA changed")
    if sha256_file(cell_plan_path) != p2["expected_cell_plan_sha256"]:
        raise RuntimeError("D2 cell plan SHA changed")
    d2_contract = read_json(d2_contract_path)
    sb = d2_contract.get("stage_boundaries", {})
    if not bool(sb.get("d2b_requires_separate_authorization")):
        raise RuntimeError("Parent D2 contract no longer requires separate D2B authorization")
    if bool(d2_contract.get("automatic_split")) or bool(d2_contract.get("automatic_merge")) or bool(d2_contract.get("automatic_geometry_replacement")):
        raise RuntimeError("Parent D2 contract unexpectedly enables geometry mutation")

    pa = cfg["parent_d2a"]
    d2a_manifest_path = Path(pa["manifest"])
    d2a_csv_path = Path(pa["field_split_discovery"])
    d2a_cells_path = Path(pa["cell_summary"])
    for p in (d2a_manifest_path, d2a_csv_path, d2a_cells_path):
        if not p.is_file():
            raise FileNotFoundError(p)
    d2a_manifest = read_json(d2a_manifest_path)
    if d2a_manifest.get("status") != pa["required_status"]:
        raise RuntimeError(f"D2A status changed: {d2a_manifest.get('status')}")
    if bool(d2a_manifest.get("true_loo_executed")) or bool(d2a_manifest.get("fusion_executed")):
        raise RuntimeError("D2A provenance unexpectedly contains D2B computation")
    if d2a_manifest.get("parent_d2_execution_contract_sha256") != p2["expected_execution_contract_sha256"]:
        raise RuntimeError("D2A parent D2 contract differs from authorized contract")
    d2a_csv_sha = sha256_file(d2a_csv_path)
    if d2a_manifest.get("output_hashes", {}).get("field_split_discovery_sha256") != d2a_csv_sha:
        raise RuntimeError("D2A field discovery CSV SHA does not match D2A manifest")

    d2a = pd.read_csv(d2a_csv_path, encoding="utf-8-sig", dtype={"parent_field_id_2025": str, "analysis_cell_id": str})
    if len(d2a) != int(pa["expected_fields"]) or d2a.parent_field_id_2025.duplicated().any():
        raise RuntimeError("D2A full field population changed")
    counts = d2a.discovery_type.astype(str).value_counts().to_dict()
    if int(counts.get("SPLIT_CANDIDATE", 0)) != int(pa["expected_split_candidates"]):
        raise RuntimeError(f"D2A split candidate census changed: {counts}")
    if int(counts.get("UNCHANGED", 0)) != int(pa["expected_unchanged"]) or int(counts.get("UNCERTAIN", 0)) != int(pa["expected_uncertain"]):
        raise RuntimeError(f"D2A parent census changed: {counts}")
    candidates = d2a[d2a.discovery_type.astype(str).eq("SPLIT_CANDIDATE")].copy()
    if not np.isfinite(pd.to_numeric(candidates.separation_ratio, errors="coerce").to_numpy(dtype=float)).all():
        raise RuntimeError("D2A candidate separation signal is non-finite")

    inp = cfg["frozen_inputs"]
    partition_path = Path(inp["field_partition"])
    windows_path = Path(inp["resolved_normalization_windows"])
    vrt_idx_path = Path(inp["d1s3j_vrt_output_index"])
    if sha256_file(windows_path) != inp["expected_resolved_normalization_windows_sha256"]:
        raise RuntimeError("D0b resolved normalization windows SHA changed")
    b2cfg_path = repo_path(inp["b2_config"]); b2script_path = repo_path(inp["b2_script"])
    tloocfg_path = repo_path(inp["true_loo_config"]); tlooscript_path = repo_path(inp["true_loo_script"])
    formal_path = repo_path(inp["formal_fusion_config"]); fusion_path = Path(inp["fusion_artifact"])
    prior_path = Path(inp["rolling_prior"])
    for p in (partition_path, windows_path, vrt_idx_path, b2cfg_path, b2script_path,
              tloocfg_path, tlooscript_path, formal_path, fusion_path, prior_path):
        if not p.is_file():
            raise FileNotFoundError(p)

    if sha256_file(fusion_path) != inp["expected_fusion_artifact_sha256"]:
        raise RuntimeError("Frozen fusion artifact SHA changed")
    formal = read_json(formal_path); freeze = read_json(fusion_path)
    expected = cfg["expected"]
    if formal.get("status") != "FROZEN_QA_RANKING_NOT_AUTOMATIC_GEOMETRY":
        raise RuntimeError("Formal fusion freeze status changed")
    if formal["fusion"]["source_freeze_sha256"] != inp["expected_fusion_artifact_sha256"]:
        raise RuntimeError("Formal fusion config no longer binds exact artifact")
    if list(freeze["signals"]) != list(expected["signals"]) or list(freeze["weights"]) != list(expected["weights"]):
        raise RuntimeError("Frozen fusion signals/weights changed")
    if freeze.get("uses_visual_labels") is not False or freeze.get("product_rule") is not False:
        raise RuntimeError("Frozen fusion artifact unexpectedly uses labels/product rule")
    if abs(float(freeze["development_fusion_p90"]) - float(expected["development_p90"])) > 1e-6 or abs(float(freeze["development_fusion_p95"]) - float(expected["development_p95"])) > 1e-6:
        raise RuntimeError("Frozen fusion P90/P95 changed")
    for sig in expected["signals"]:
        ref = np.asarray(freeze["reference_sorted_values"][sig], dtype=float)
        if len(ref) != int(expected["development_reference_n"]) or not np.isfinite(ref).all() or np.any(ref[1:] < ref[:-1]):
            raise RuntimeError(f"Frozen reference array invalid for {sig}")

    b2cfg = read_json(b2cfg_path); tlcfg = read_json(tloocfg_path)
    if int(tlcfg["true_loo_contract"]["minimum_reference_comparison_pixels"]) != int(expected["minimum_reference_comparison_pixels"]):
        raise RuntimeError("TRUE-LOO minimum reference pixels changed")
    if list(tlcfg["snapshot_order"]) != list(expected["true_loo_snapshot_names"]):
        raise RuntimeError("TRUE-LOO snapshot order changed")
    b2 = load_module(b2script_path, "d2b_b2")
    tloo = load_module(tlooscript_path, "d2b_true_loo")
    d2a_mod = load_module(ROOT / "src" / "154_akerpuls_d2a_full_skane_split_discovery_v1.py", "d2b_d2a_helpers")

    part = pd.read_csv(partition_path, encoding="utf-8-sig", dtype={"parent_field_id_2025": str, "analysis_cell_id": str})
    windows = pd.read_csv(windows_path, encoding="utf-8-sig", dtype={"analysis_cell_id": str})
    cell_plan = pd.read_csv(cell_plan_path, encoding="utf-8-sig", dtype={"analysis_cell_id": str})
    vrt_idx = pd.read_csv(vrt_idx_path, encoding="utf-8-sig", dtype={"snapshot": str})
    if len(cell_plan) != int(expected["analysis_cells"]) or len(windows) != int(expected["analysis_cells"]):
        raise RuntimeError("D2B cell population changed")

    log("D2B_PROGRESS=VERIFY_AND_REPROJECT_FROZEN_GEOMETRY")
    local_paths = read_json(repo_path(inp["local_paths"]))
    geom_path = Path(local_paths[inp["geometry_local_paths_key"]])
    if sha256_file(geom_path) != inp["expected_geometry_sha256"]:
        raise RuntimeError("Frozen geometry SHA changed")
    g0 = gpd.read_file(geom_path)
    if len(g0) != int(expected["fields"]) or g0.crs is None:
        raise RuntimeError("Frozen geometry count/CRS changed")
    if bool(cfg["projection_geometry_policy"]["require_source_geometry_valid_before_reprojection"]):
        valid_source = g0.geometry.notna() & ~g0.geometry.is_empty & g0.geometry.is_valid
        if not bool(valid_source.all()):
            raise RuntimeError("Frozen source geometry contains invalid/null/empty rows")
    ids = d2a_mod.infer_ids(g0)
    g_raw = g0.to_crs(int(expected["target_crs_epsg"])).copy().reset_index(drop=True)
    g_raw["parent_field_id_2025"] = ids.to_numpy()
    g = g_raw.copy()
    g, repair_info = d2a_mod.repair_projected_geometry(g, cfg)
    if set(g.parent_field_id_2025.astype(str)) != set(part.parent_field_id_2025.astype(str)):
        raise RuntimeError("D2B geometry field population differs from frozen partition")
    log(f"D2B_GEOMETRY PROJECTED_INVALID_BEFORE_REPAIR={repair_info['projected_invalid_before_repair']} REPAIRED_FOR_RASTER_OPS={repair_info['repaired_for_raster_ops']} MAX_ABS_AREA_DELTA_M2={repair_info['max_abs_area_delta_m2']:.9g} MAX_REL_AREA_DELTA={repair_info['max_rel_area_delta']:.9g}")

    snaps = list(expected["snapshot_order"])
    vrt_lookup = {str(r.snapshot): Path(str(r.path)) for r in vrt_idx.itertuples(index=False)}
    if set(vrt_lookup) != set(snaps):
        raise RuntimeError("D2B VRT snapshot set changed")
    datasets = [rasterio.open(vrt_lookup[s]) for s in snaps]
    try:
        base_ds = datasets[0]
        for ds in datasets[1:]:
            if ds.crs != base_ds.crs or ds.transform != base_ds.transform or ds.width != base_ds.width or ds.height != base_ds.height:
                raise RuntimeError("D2B snapshot VRT grids differ")
        features = list(b2cfg["feature_bands_per_snapshot"])
        band_maps = []
        for ds in datasets:
            bm = {name: i + 1 for i, name in enumerate(ds.descriptions) if name}
            missing = [x for x in features + ["VALID"] if x not in bm]
            if missing:
                raise RuntimeError(f"D2B VRT missing frozen B2 bands: {missing}")
            band_maps.append(bm)

        id_to_pos = {str(fid): i for i, fid in enumerate(g.parent_field_id_2025.astype(str))}
        raw_sidx = g_raw.sindex
        script_sha = sha256_file(THIS)
        b2_sha = sha256_file(b2cfg_path); tloo_sha = sha256_file(tloocfg_path)
        all_cell_loo: list[pd.DataFrame] = []
        cell_cache_hits = cell_built = 0

        log("D2B_PROGRESS=RUN_TRUE_LOO_ON_12676_D2A_CANDIDATES_BY_46_CELLS")
        for ci, cp in enumerate(cell_plan.sort_values("execution_order").itertuples(index=False), 1):
            cid = str(cp.analysis_cell_id)
            cc = candidates[candidates.analysis_cell_id.astype(str).eq(cid)].copy()
            candidate_ids = sorted(cc.parent_field_id_2025.astype(str).tolist())
            wb = (float(cp.normalization_minx), float(cp.normalization_miny), float(cp.normalization_maxx), float(cp.normalization_maxy))
            raw_norm_pos = list(raw_sidx.query(box(*wb), predicate="intersects"))
            if len(raw_norm_pos) != int(cp.resolved_normalization_fields):
                raise RuntimeError(f"D2B normalization population mismatch {cid}: {len(raw_norm_pos)} != {cp.resolved_normalization_fields}")
            norm_geoms = [g.geometry.iloc[int(p)] for p in raw_norm_pos]

            cell_dir = out / "cells" / cid
            cell_dir.mkdir(parents=True, exist_ok=True)
            csv_path = cell_dir / "d2b_true_loo.csv"
            meta_path = cell_dir / "d2b_true_loo.meta.json"
            key_payload = {
                "schema": "akerpuls-d2b-cell-true-loo-v1", "script_sha256": script_sha,
                "d2_contract_sha256": p2["expected_execution_contract_sha256"],
                "cell_plan_sha256": p2["expected_cell_plan_sha256"],
                "d2a_discovery_sha256": d2a_csv_sha, "analysis_cell_id": cid,
                "candidate_ids": candidate_ids, "normalization_window": list(wb),
                "resolved_normalization_fields": int(cp.resolved_normalization_fields),
                "b2_config_sha256": b2_sha, "true_loo_config_sha256": tloo_sha,
                "geometry_sha256": inp["expected_geometry_sha256"], "vrt_index_sha256": sha256_file(vrt_idx_path),
            }
            output_key = sha256_obj(key_payload)
            loo_df = validate_cached_cell(csv_path, meta_path, output_key, candidate_ids)
            if loo_df is not None:
                cell_cache_hits += 1
            else:
                variants, norm_bounds = build_normalization_variants(datasets, band_maps, features, norm_geoms, d2a_mod)
                d2a_meta_path = Path(pa["cell_root"]) / cid / "d2a_split_discovery.meta.json"
                if not d2a_meta_path.is_file():
                    raise FileNotFoundError(d2a_meta_path)
                d2a_meta = read_json(d2a_meta_path)
                if int(d2a_meta["normalization_sample_pixels"]) != int(variants["FULL4"]["pixels"]):
                    raise RuntimeError(f"D2B FULL4 normalization pixel count differs from D2A in {cid}")
                if not np.allclose(np.asarray(d2a_meta["normalization_center"], dtype=float), variants["FULL4"]["center"], rtol=0, atol=1e-10):
                    raise RuntimeError(f"D2B FULL4 normalization center differs from D2A in {cid}")
                if not np.allclose(np.asarray(d2a_meta["normalization_scale"], dtype=float), variants["FULL4"]["scale"], rtol=0, atol=1e-10):
                    raise RuntimeError(f"D2B FULL4 normalization scale differs from D2A in {cid}")

                if candidate_ids:
                    cand_pos = [id_to_pos[x] for x in candidate_ids]
                    cand_geoms = [g.geometry.iloc[p] for p in cand_pos]
                    cubes, valids, labels, _ = d2a_mod.read_owner_cell_arrays(datasets, band_maps, features, cand_geoms)
                    loo_df = process_cell_true_loo(cid, cc, candidate_ids, cubes, valids, labels,
                                                   variants, b2, b2cfg, tloo, tlcfg)
                    del cubes, valids, labels
                else:
                    loo_df = pd.DataFrame(columns=loo_columns())
                tmp = csv_path.with_suffix(".csv.partial")
                loo_df.to_csv(tmp, index=False, encoding="utf-8-sig")
                tmp.replace(csv_path)
                meta = {
                    "schema_version": "akerpuls-d2b-cell-true-loo-result-v1",
                    "output_key_sha256": output_key, "csv_sha256": sha256_file(csv_path),
                    "analysis_cell_id": cid, "candidates": len(candidate_ids),
                    "normalization_fields": len(raw_norm_pos), "normalization_bounds": norm_bounds,
                    "variant_normalization_pixels": {k: int(v["pixels"]) for k, v in variants.items()},
                    "full4_matches_d2a_scaling": True,
                    "true_loo_stable": int(bool_series(loo_df.true_loo_stable).sum()) if len(loo_df) else 0,
                    "fusion_executed_in_cell_stage": False, "merge_executed": False,
                    "automatic_geometry_replacement": False,
                    "completed_utc": datetime.now(timezone.utc).isoformat(),
                }
                mtmp = meta_path.with_suffix(".json.partial")
                mtmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                mtmp.replace(meta_path)
                cell_built += 1
                del variants
                gc.collect()
            all_cell_loo.append(loo_df)
            if ci % 5 == 0 or ci == len(cell_plan):
                stable_n = int(bool_series(loo_df.true_loo_stable).sum()) if len(loo_df) else 0
                log(f"D2B_CELL_PROGRESS={ci}/{len(cell_plan)} BUILT={cell_built} CACHE_HITS={cell_cache_hits} LAST={cid} CAND={len(candidate_ids)} STABLE={stable_n}")

        loo = pd.concat(all_cell_loo, ignore_index=True) if all_cell_loo else pd.DataFrame(columns=loo_columns())
        loo = loo.sort_values("parent_field_id_2025").reset_index(drop=True)
        if len(loo) != int(expected["split_candidates"]) or loo.parent_field_id_2025.duplicated().any():
            raise RuntimeError("D2B TRUE-LOO output is not exactly the 12,676 unique D2A candidates")
        if set(loo.parent_field_id_2025.astype(str)) != set(candidates.parent_field_id_2025.astype(str)):
            raise RuntimeError("D2B TRUE-LOO candidate IDs differ from D2A candidates")
        loo_path = out / "d2b_true_loo_candidates.csv"
        loo.to_csv(loo_path, index=False, encoding="utf-8-sig")

        log("D2B_PROGRESS=JOIN_ROLLING_PRIOR_AND_APPLY_FROZEN_FUSION")
        cand = candidates.copy()
        cand["field_id_normalized"] = cand.parent_field_id_2025.map(normalize_field_id)
        loo_merge = loo[["field_id_normalized", "reference_fit_ok", "reference_separation_ratio",
                         "true_loo_refits_ok", "true_loo_min_child_dice", "true_loo_mean_child_dice",
                         "true_loo_min_child_fraction", "true_loo_stable", "true_loo_failure_reason"]].copy()
        cand = cand.merge(loo_merge, on="field_id_normalized", how="left", validate="one_to_one")

        prior = pd.read_csv(prior_path, dtype={"field_id": str})
        prior["field_id_normalized"] = prior.field_id.map(normalize_field_id)
        if prior.field_id_normalized.duplicated().any():
            raise RuntimeError("Rolling prior normalized IDs are not unique")
        prior_cols = ["field_id_normalized", "prototype_p_splitmerge_2026"]
        if "prototype_p_strict_same_2026" in prior.columns:
            prior_cols.append("prototype_p_strict_same_2026")
        cand = cand.merge(prior[prior_cols], on="field_id_normalized", how="left", validate="many_to_one")

        weights = np.asarray(expected["weights"], dtype=float)
        parts = []
        for sig in expected["signals"]:
            cand[sig] = pd.to_numeric(cand[sig], errors="coerce")
            if not np.isfinite(cand[sig].to_numpy(dtype=float)).all():
                raise RuntimeError(f"D2B fusion signal non-finite: {sig}")
            ref = np.asarray(freeze["reference_sorted_values"][sig], dtype=float)
            cdf = empirical_midrank(ref, cand[sig].to_numpy(dtype=float))
            cand[f"cdf_{sig}"] = cdf
            parts.append(cdf)
        cand["fusion_score"] = np.vstack(parts).T @ weights
        p90 = float(expected["development_p90"]); p95 = float(expected["development_p95"])
        cand["fusion_ge_dev_p90"] = cand.fusion_score >= p90
        cand["fusion_ge_dev_p95"] = cand.fusion_score >= p95
        cand["qa_tier"] = np.where(cand.fusion_ge_dev_p95, "HIGH_PRIORITY_SPLIT_CANDIDATE",
                            np.where(cand.fusion_ge_dev_p90, "SPLIT_CANDIDATE", "EVIDENCE_ONLY"))
        cand = cand.sort_values(["fusion_score", "parent_field_id_2025"], ascending=[False, True]).reset_index(drop=True)
        fusion_path_out = out / "d2b_fusion_candidates.csv"
        cand.to_csv(fusion_path_out, index=False, encoding="utf-8-sig")

        p90_n = int(cand.fusion_ge_dev_p90.sum()); p95_n = int(cand.fusion_ge_dev_p95.sum())
        stable_n = int(bool_series(cand.true_loo_stable).sum())
        cell_rows = []
        for cp in cell_plan.sort_values("execution_order").itertuples(index=False):
            cid = str(cp.analysis_cell_id); x = cand[cand.analysis_cell_id.astype(str).eq(cid)]
            cell_rows.append({"execution_order": int(cp.execution_order), "analysis_cell_id": cid,
                              "d2a_split_candidates": int(len(x)),
                              "true_loo_stable": int(bool_series(x.true_loo_stable).sum()) if len(x) else 0,
                              "fusion_ge_p90": int(x.fusion_ge_dev_p90.sum()) if len(x) else 0,
                              "fusion_ge_p95": int(x.fusion_ge_dev_p95.sum()) if len(x) else 0,
                              "fusion_p90_fraction_of_candidates": float(x.fusion_ge_dev_p90.mean()) if len(x) else 0.0,
                              "fusion_p95_fraction_of_candidates": float(x.fusion_ge_dev_p95.mean()) if len(x) else 0.0})
        cell_df = pd.DataFrame(cell_rows)
        cell_out = out / "d2b_cell_summary.csv"
        cell_df.to_csv(cell_out, index=False, encoding="utf-8-sig")

        signals_finite = all(np.isfinite(cand[s].to_numpy(dtype=float)).all() for s in expected["signals"])
        cdf_finite = all(np.isfinite(cand[f"cdf_{s}"].to_numpy(dtype=float)).all() for s in expected["signals"])
        checks = {
            "explicit_go_d2b_authorization": cfg["authorization"]["user_command"] == "GO D2B",
            "parent_d2a_review_pass": d2a_manifest.get("status") == pa["required_status"],
            "parent_d2_contract_exact": sha256_file(d2_contract_path) == p2["expected_execution_contract_sha256"],
            "parent_cell_plan_exact": sha256_file(cell_plan_path) == p2["expected_cell_plan_sha256"],
            "exact_d2a_candidate_population": len(cand) == int(expected["split_candidates"]),
            "all_candidate_true_loo_rows": len(loo) == int(expected["split_candidates"]),
            "all_46_cells_accounted_for": len(cell_df) == int(expected["analysis_cells"]),
            "fusion_signals_finite": signals_finite,
            "fusion_cdfs_finite": cdf_finite,
            "fusion_score_finite": bool(np.isfinite(cand.fusion_score.to_numpy(dtype=float)).all()),
            "p95_subset_p90": bool((~cand.fusion_ge_dev_p95 | cand.fusion_ge_dev_p90).all()),
            "frozen_fusion_exact": sha256_file(fusion_path) == inp["expected_fusion_artifact_sha256"],
            "thresholds_not_tuned": True, "fusion_not_refit": True,
            "merge_not_executed": True, "automatic_geometry_replacement_false": True,
            "review_stop_preserved": bool(cfg["execution"]["stop_after_d2b_for_review"]),
        }
        status = "PASS_TO_D2B_REVIEW_STOP" if all(checks.values()) else "REVIEW"

        tier_counts = cand.qa_tier.value_counts().to_dict()
        fs = cand.fusion_score
        manifest = {
            "schema_version": "akerpuls-d2b-full-skane-true-loo-fusion-result-v1",
            "status": status, "generated_utc": datetime.now(timezone.utc).isoformat(),
            "git": {"branch": branch, "head": head}, "authorization": cfg["authorization"],
            "parent_d2_execution_contract_sha256": p2["expected_execution_contract_sha256"],
            "parent_d2a_discovery_sha256": d2a_csv_sha,
            "geometry_repair_for_raster_ops_only": repair_info,
            "candidates": int(len(cand)), "true_loo_stable": stable_n,
            "true_loo_stable_fraction": stable_n / len(cand),
            "fusion_ge_p90": p90_n, "fusion_ge_p90_fraction": p90_n / len(cand),
            "fusion_ge_p95": p95_n, "fusion_ge_p95_fraction": p95_n / len(cand),
            "qa_tier_counts": {k: int(v) for k, v in tier_counts.items()},
            "fusion_score": {"p50": float(fs.quantile(.5)), "p90": float(fs.quantile(.9)),
                             "p95": float(fs.quantile(.95)), "max": float(fs.max())},
            "true_loo_min_child_dice": {"p10": float(pd.to_numeric(cand.true_loo_min_child_dice).quantile(.1)),
                                         "p50": float(pd.to_numeric(cand.true_loo_min_child_dice).quantile(.5)),
                                         "p90": float(pd.to_numeric(cand.true_loo_min_child_dice).quantile(.9))},
            "cells": int(len(cell_df)), "cell_cache": {"built": cell_built, "hits": cell_cache_hits},
            "checks": checks,
            "output_hashes": {"true_loo_candidates_sha256": sha256_file(loo_path),
                              "fusion_candidates_sha256": sha256_file(fusion_path_out),
                              "cell_summary_sha256": sha256_file(cell_out)},
            "network_calls": 0, "process_api_calls": 0, "sentinel_hub_pu_used": 0,
            "thresholds_tuned": False, "fusion_refit": False, "merge_executed": False,
            "automatic_geometry_replacement": False,
            "next_step": "Review D2B full-Skane ranking; no geometry mutation is authorized.",
            "interpretation": cfg["interpretation"],
        }
        (out / "d2b_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        log("AKERPULS D2B FULL-SKANE TRUE-LOO + FROZEN FUSION")
        log(f"STATUS={status}")
        log(f"CANDIDATES={len(cand)} TRUE_LOO_STABLE={stable_n} FRACTION={stable_n/len(cand):.6f}")
        log(f"FUSION_GE_P90={p90_n} FRACTION={p90_n/len(cand):.6f} THRESHOLD={p90:.6f}")
        log(f"FUSION_GE_P95={p95_n} FRACTION={p95_n/len(cand):.6f} THRESHOLD={p95:.6f}")
        log("QA_TIERS=" + ";".join(f"{k}:{int(tier_counts.get(k,0))}" for k in ("HIGH_PRIORITY_SPLIT_CANDIDATE","SPLIT_CANDIDATE","EVIDENCE_ONLY")))
        log(f"FUSION_SCORE=P50:{fs.quantile(.5):.6f};P90:{fs.quantile(.9):.6f};P95:{fs.quantile(.95):.6f};MAX:{fs.max():.6f}")
        td = pd.to_numeric(cand.true_loo_min_child_dice)
        log(f"TRUE_LOO_MIN_CHILD_DICE=P10:{td.quantile(.1):.6f};P50:{td.quantile(.5):.6f};P90:{td.quantile(.9):.6f}")
        maxp90 = cell_df.loc[cell_df.fusion_ge_p90.idxmax()] if len(cell_df) else None
        maxp95 = cell_df.loc[cell_df.fusion_ge_p95.idxmax()] if len(cell_df) else None
        log(f"CELL_P90_MAX={int(maxp90.fusion_ge_p90) if maxp90 is not None else 0}@{maxp90.analysis_cell_id if maxp90 is not None else 'NONE'} CELL_P95_MAX={int(maxp95.fusion_ge_p95) if maxp95 is not None else 0}@{maxp95.analysis_cell_id if maxp95 is not None else 'NONE'}")
        log(f"CELL_CACHE=BUILT:{cell_built};HITS:{cell_cache_hits}")
        log("CHECKS=" + ";".join(f"{k}:{str(v).upper()}" for k, v in checks.items()))
        log("NETWORK_CALLS=0")
        log("PROCESS_API_CALLS=0")
        log("SENTINEL_HUB_PU_USED=0")
        log("THRESHOLDS_TUNED=FALSE")
        log("FUSION_REFIT=FALSE")
        log("MERGE_EXECUTED=FALSE")
        log("AUTOMATIC_GEOMETRY_REPLACEMENT=FALSE")
        log("GEOMETRY_MUTATION_AUTHORIZED=FALSE")
        log(f"D2B_STATUS={status}")
        log(f"OUTPUT={out}")
        return 0 if status == "PASS_TO_D2B_REVIEW_STOP" else 2
    finally:
        for ds in datasets:
            ds.close()


if __name__ == "__main__":
    raise SystemExit(main())
