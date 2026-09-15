#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D2 full-Skane model plan only.

Zero network and zero model execution. This stage binds the completed D1-S3k
field-validity QA, D0b local-normalization windows, frozen B2/TRUE-LOO/fusion
contracts and rolling 2026 history prior into one deterministic execution plan.

The plan deliberately splits future computation into D2A baseline discovery and
D2B TRUE-LOO+fusion, with a mandatory stopping point after D2A.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config" / "akerpuls_d2_full_skane_model_plan_v1.json"


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


def repo_path(v: str) -> Path:
    p = Path(v)
    return p if p.is_absolute() else ROOT / p


def validate_config(cfg: dict[str, Any]) -> None:
    if cfg.get("schema_version") != "akerpuls-d2-full-skane-model-plan-v1":
        raise RuntimeError("Unexpected D2 plan schema")
    if any(bool(v) for v in cfg["guards"].values()):
        raise RuntimeError("D2 plan unexpectedly enables execution/forbidden scope")
    if not bool(cfg["plan_acceptance"]["frozen_before_full_skane_model_outputs"]):
        raise RuntimeError("D2 plan was not frozen before full-Skane model outputs")
    exp = cfg["expected"]
    if int(exp["fields"]) != 128636 or int(exp["analysis_cells"]) != 46:
        raise RuntimeError("Frozen D2 field/cell domain changed")
    if int(exp["minimum_normalization_fields"]) != 200 or int(exp["minimum_b2_valid_pixels"]) != 24:
        raise RuntimeError("Frozen D2 normalization/B2 minimum changed")
    ep = cfg["execution_plan"]
    if not bool(ep["stop_after_d2a_before_true_loo_fusion"]):
        raise RuntimeError("D2 must retain a stopping point after baseline discovery")
    gp = cfg["geometry_policy"]
    if bool(gp["automatic_split"]) or bool(gp["automatic_merge"]) or bool(gp["automatic_geometry_replacement"]):
        raise RuntimeError("D2 plan unexpectedly enables geometry mutation")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(CFG))
    ap.add_argument("--output-dir")
    args = ap.parse_args()

    cfg = read_json(Path(args.config))
    validate_config(cfg)
    branch, head = git_guard(cfg)
    out = Path(args.output_dir or cfg["output"]["plan_dir"])
    out.mkdir(parents=True, exist_ok=True)
    exp = cfg["expected"]

    log("D2PLAN_PROGRESS=VERIFY_D1S3K_PARENT")
    qcfg = cfg["parent_d1s3k"]
    qman_path = Path(qcfg["manifest"])
    qfield_path = Path(qcfg["field_validity"])
    qcell_path = Path(qcfg["analysis_cell_validity"])
    for p in (qman_path, qfield_path, qcell_path):
        if not p.is_file():
            raise FileNotFoundError(p)
    qman = read_json(qman_path)
    if qman.get("status") != qcfg["required_status"]:
        raise RuntimeError(f"D1-S3k status changed: {qman.get('status')}")
    if bool(qman.get("model_executed")) or bool(qman.get("fusion_executed")) or bool(qman.get("automatic_geometry_replacement")):
        raise RuntimeError("D1-S3k provenance unexpectedly contains model/fusion/geometry execution")
    if int(qman.get("network_calls", -1)) != 0 or int(qman.get("process_api_calls", -1)) != 0:
        raise RuntimeError("D1-S3k provenance unexpectedly contains network/Process calls")

    field = pd.read_csv(qfield_path, encoding="utf-8-sig", dtype={"parent_field_id_2025": str, "analysis_cell_id": str, "home_raster_tile_id": str})
    cellqa = pd.read_csv(qcell_path, encoding="utf-8-sig", dtype={"analysis_cell_id": str})
    if len(field) != int(exp["fields"]):
        raise RuntimeError(f"D1-S3k field-validity rows changed: {len(field)}")
    if field.parent_field_id_2025.duplicated().any():
        raise RuntimeError("D1-S3k field-validity IDs are not unique")
    if len(cellqa) != int(exp["analysis_cells"]) or cellqa.analysis_cell_id.duplicated().any():
        raise RuntimeError("D1-S3k analysis-cell QA population changed")

    log("D2PLAN_PROGRESS=VERIFY_D0B_NORMALIZATION_AND_PARTITION")
    d0 = cfg["parent_d0b"]
    contract_path = Path(d0["execution_contract"])
    windows_path = Path(d0["resolved_normalization_windows"])
    partition_path = Path(d0["field_partition"])
    for p in (contract_path, windows_path, partition_path):
        if not p.is_file():
            raise FileNotFoundError(p)
    contract_sha = sha256_file(contract_path)
    if contract_sha != d0["expected_execution_contract_sha256"]:
        raise RuntimeError(f"D0b execution-contract SHA changed: {contract_sha}")
    windows_sha = sha256_file(windows_path)
    if windows_sha != d0["expected_resolved_normalization_windows_sha256"]:
        raise RuntimeError(f"D0b resolved-window SHA changed: {windows_sha}")
    contract = read_json(contract_path)
    if int(contract.get("resolved_normalization_windows", {}).get("unresolved_cells", -1)) != 0:
        raise RuntimeError("D0b contains unresolved normalization windows")
    if contract.get("resolved_normalization_windows", {}).get("sha256") != windows_sha:
        raise RuntimeError("D0b contract/resolved-window SHA mismatch")
    partition_sha = sha256_file(partition_path)
    if contract.get("field_partition", {}).get("sha256") != partition_sha:
        raise RuntimeError("D0b contract/field-partition SHA mismatch")

    windows = pd.read_csv(windows_path, encoding="utf-8-sig", dtype={"analysis_cell_id": str})
    part = pd.read_csv(partition_path, encoding="utf-8-sig", dtype={"parent_field_id_2025": str, "analysis_cell_id": str, "home_raster_tile_id": str})
    if len(windows) != int(exp["analysis_cells"]) or windows.analysis_cell_id.duplicated().any():
        raise RuntimeError("D0b normalization-window population changed")
    if len(part) != int(exp["fields"]) or part.parent_field_id_2025.duplicated().any():
        raise RuntimeError("D0 field-partition population changed")
    if set(part.parent_field_id_2025) != set(field.parent_field_id_2025):
        raise RuntimeError("D1-S3k field population differs from D0 partition")
    expanded = int((pd.to_numeric(windows.normalization_expansion_m, errors="coerce") > 0).sum())
    if expanded != int(exp["sparse_expanded_cells"]):
        raise RuntimeError(f"D0b expanded-cell count changed: {expanded}")
    min_norm = int(pd.to_numeric(windows.resolved_normalization_fields, errors="coerce").min())

    log("D2PLAN_PROGRESS=VERIFY_FROZEN_MODEL_AND_HISTORY_PRIOR")
    fm = cfg["frozen_model"]
    fusion_cfg_path = repo_path(fm["formal_fusion_config"])
    fusion_artifact_path = Path(fm["fusion_artifact"])
    b2_path = repo_path(fm["b2_config"])
    tloo_path = repo_path(fm["true_loo_config"])
    prior_path = Path(fm["rolling_prior"])
    for p in (fusion_cfg_path, fusion_artifact_path, b2_path, tloo_path, prior_path):
        if not p.is_file():
            raise FileNotFoundError(p)

    repo_hashes = contract.get("repo_hashes", {})
    repo_hash_checks = {
        "formal_split_fusion_config": sha256_file(fusion_cfg_path) == repo_hashes.get("formal_split_fusion_config_sha256"),
        "b2_config": sha256_file(b2_path) == repo_hashes.get("b2_config_sha256"),
        "true_loo_config": sha256_file(tloo_path) == repo_hashes.get("true_loo_config_sha256"),
    }
    formal = read_json(fusion_cfg_path)
    if formal.get("status") != "FROZEN_QA_RANKING_NOT_AUTOMATIC_GEOMETRY":
        raise RuntimeError("Formal fusion status changed")
    if any(bool(formal["policy"].get(k)) for k in ("automatic_split", "automatic_merge", "automatic_geometry_replacement")):
        raise RuntimeError("Formal fusion policy unexpectedly enables geometry mutation")
    artifact_sha = sha256_file(fusion_artifact_path)
    if artifact_sha != fm["expected_fusion_artifact_sha256"]:
        raise RuntimeError(f"Fusion artifact SHA changed: {artifact_sha}")
    if formal["fusion"]["source_freeze_sha256"] != artifact_sha:
        raise RuntimeError("Formal fusion config/artifact SHA mismatch")
    if abs(float(formal["fusion"]["development_p90"]) - float(fm["development_p90"])) > 1e-12:
        raise RuntimeError("Frozen P90 changed")
    if abs(float(formal["fusion"]["development_p95"]) - float(fm["development_p95"])) > 1e-12:
        raise RuntimeError("Frozen P95 changed")
    if int(formal["fusion"]["development_n"]) != int(fm["development_reference_n"]):
        raise RuntimeError("Frozen fusion reference population changed")

    prior = pd.read_csv(prior_path, dtype={"field_id": str})
    if "field_id" not in prior.columns or fm["history_signal"] not in prior.columns:
        raise RuntimeError("Rolling prior lacks required field_id/history signal")
    prior = prior.copy()
    prior["field_id_normalized"] = prior.field_id.map(normalize_field_id)
    if prior.field_id_normalized.duplicated().any():
        raise RuntimeError("Rolling prior normalized field IDs are not unique")
    prior_signal = pd.to_numeric(prior[fm["history_signal"]], errors="coerce")
    prior_ids = set(prior.field_id_normalized.astype(str))
    field_norm = field.parent_field_id_2025.map(normalize_field_id)
    missing_prior_ids = sorted(set(field_norm.astype(str)) - prior_ids)
    prior_nonfinite = int((~np.isfinite(prior_signal.to_numpy(dtype=float))).sum())

    log("D2PLAN_PROGRESS=BUILD_DETERMINISTIC_46_CELL_EXECUTION_PLAN")
    # Rebind field ownership to the frozen partition rather than trusting a duplicated QA column.
    qa_cols = ["parent_field_id_2025", "field_pixels", "all4_valid_pixels", "all4_valid_fraction", "pre_b2_ge24_all4_valid_pixels"]
    missing_qa_cols = [c for c in qa_cols if c not in field.columns]
    if missing_qa_cols:
        raise RuntimeError(f"D1-S3k field-validity columns missing: {missing_qa_cols}")
    fq = part[["parent_field_id_2025", "analysis_cell_id", "home_raster_tile_id", "area_ha_2025"]].merge(
        field[qa_cols], on="parent_field_id_2025", how="left", validate="one_to_one"
    )
    if fq.field_pixels.isna().any():
        raise RuntimeError("Field QA/partition merge lost rows")

    plan_rows = []
    for r in windows.sort_values("analysis_cell_id").itertuples(index=False):
        cid = str(r.analysis_cell_id)
        x = fq[fq.analysis_cell_id.astype(str).eq(cid)]
        if len(x) != int(r.owner_fields):
            raise RuntimeError(f"Owner-field mismatch for {cid}: partition={len(x)} windows={r.owner_fields}")
        plan_rows.append({
            "execution_order": len(plan_rows) + 1,
            "analysis_cell_id": cid,
            "owner_fields": int(len(x)),
            "owner_fields_with_raster_pixels": int((pd.to_numeric(x.field_pixels, errors="coerce") > 0).sum()),
            "owner_fields_pre_b2_ge24_all4": int(x.pre_b2_ge24_all4_valid_pixels.astype(bool).sum()),
            "owner_pre_b2_ge24_fraction": float(x.pre_b2_ge24_all4_valid_pixels.astype(bool).mean()) if len(x) else 0.0,
            "owner_all4_field_pixel_valid_fraction": float(pd.to_numeric(x.all4_valid_pixels, errors="coerce").sum() / pd.to_numeric(x.field_pixels, errors="coerce").sum()) if pd.to_numeric(x.field_pixels, errors="coerce").sum() else 0.0,
            "normalization_expansion_m": int(r.normalization_expansion_m),
            "normalization_window_side_m": int(r.normalization_window_side_m),
            "resolved_normalization_fields": int(r.resolved_normalization_fields),
            "normalization_minx": float(r.minx),
            "normalization_miny": float(r.miny),
            "normalization_maxx": float(r.maxx),
            "normalization_maxy": float(r.maxy),
            "d2a_result_relative": f"cells/{cid}/d2a_split_discovery.csv",
            "d2a_sidecar_relative": f"cells/{cid}/d2a_split_discovery.meta.json",
            "d2b_result_relative": f"cells/{cid}/d2b_true_loo_fusion.csv",
            "d2b_sidecar_relative": f"cells/{cid}/d2b_true_loo_fusion.meta.json",
        })
    cell_plan = pd.DataFrame(plan_rows)
    cell_plan_path = out / "d2_cell_execution_plan.csv"
    cell_plan.to_csv(cell_plan_path, index=False, encoding="utf-8-sig")

    raster_snapshot_index = Path(cfg["raster_inputs"]["d1s3j_snapshot_output_index"])
    raster_vrt_index = Path(cfg["raster_inputs"]["d1s3j_vrt_output_index"])
    for p in (raster_snapshot_index, raster_vrt_index):
        if not p.is_file():
            raise FileNotFoundError(p)

    checks = {
        "d1s3k_pass": qman.get("status") == qcfg["required_status"],
        "exact_field_population": len(fq) == int(exp["fields"]) and set(fq.parent_field_id_2025) == set(part.parent_field_id_2025),
        "exact_analysis_cell_population": len(cell_plan) == int(exp["analysis_cells"]) and set(cell_plan.analysis_cell_id) == set(windows.analysis_cell_id),
        "d0b_windows_hash": windows_sha == d0["expected_resolved_normalization_windows_sha256"],
        "all_normalization_windows_resolved": int(contract["resolved_normalization_windows"]["unresolved_cells"]) == 0,
        "minimum_normalization_fields_all_cells": min_norm >= int(exp["minimum_normalization_fields"]),
        "rolling_prior_full_field_coverage": len(missing_prior_ids) == 0,
        "rolling_prior_signal_finite": prior_nonfinite == 0,
        "fusion_freeze_exact": artifact_sha == fm["expected_fusion_artifact_sha256"],
        "repo_model_hashes_match_d0b_contract": all(repo_hash_checks.values()),
        "no_model_execution": True,
        "automatic_geometry_replacement_false": True,
    }
    status = "PASS_TO_D2A_SPLIT_DISCOVERY_EXECUTION" if all(checks.values()) else "REVIEW"

    hashes = {
        "d1s3k_manifest_sha256": sha256_file(qman_path),
        "d1s3k_field_validity_sha256": sha256_file(qfield_path),
        "d1s3k_analysis_cell_validity_sha256": sha256_file(qcell_path),
        "d0b_execution_contract_sha256": contract_sha,
        "d0b_resolved_windows_sha256": windows_sha,
        "field_partition_sha256": partition_sha,
        "d1s3j_snapshot_output_index_sha256": sha256_file(raster_snapshot_index),
        "d1s3j_vrt_output_index_sha256": sha256_file(raster_vrt_index),
        "formal_fusion_config_sha256": sha256_file(fusion_cfg_path),
        "fusion_artifact_sha256": artifact_sha,
        "b2_config_sha256": sha256_file(b2_path),
        "true_loo_config_sha256": sha256_file(tloo_path),
        "rolling_prior_sha256": sha256_file(prior_path),
        "cell_execution_plan_sha256": sha256_file(cell_plan_path),
    }

    execution_contract = {
        "schema_version": "akerpuls-d2-full-skane-execution-contract-v1",
        "source_plan_schema": cfg["schema_version"],
        "plan_status_required": "PASS_TO_D2A_SPLIT_DISCOVERY_EXECUTION",
        "frozen_inputs": hashes,
        "domain": {
            "fields": int(exp["fields"]),
            "analysis_cells": int(exp["analysis_cells"]),
            "expanded_normalization_cells": expanded,
            "minimum_normalization_fields": int(exp["minimum_normalization_fields"]),
            "pre_b2_ge24_all4_fields_from_d1s3k": int(fq.pre_b2_ge24_all4_valid_pixels.astype(bool).sum()),
            "zero_raster_pixel_fields_from_d1s3k": int((pd.to_numeric(fq.field_pixels, errors="coerce") <= 0).sum()),
        },
        "execution_plan": cfg["execution_plan"],
        "geometry_policy": cfg["geometry_policy"],
        "frozen_model": {
            "b2_config_sha256": hashes["b2_config_sha256"],
            "true_loo_config_sha256": hashes["true_loo_config_sha256"],
            "fusion_artifact_sha256": artifact_sha,
            "rolling_prior_sha256": hashes["rolling_prior_sha256"],
            "signals": [fm["history_signal"], fm["separation_signal"], fm["true_loo_signal"]],
            "weights": fm["weights"],
            "development_reference_n": int(fm["development_reference_n"]),
            "development_p90": float(fm["development_p90"]),
            "development_p95": float(fm["development_p95"]),
        },
        "stage_boundaries": {
            "d2a": "B2_BASELINE_SPLIT_DISCOVERY_AND_UNCERTAIN_ONLY",
            "mandatory_stop_after_d2a": True,
            "d2b_requires_separate_authorization": True,
            "d2b": "TRUE_LOO_PLUS_HISTORY_PRIOR_PLUS_FROZEN_FUSION_ON_D2A_CANDIDATES_ONLY",
        },
        "automatic_split": False,
        "automatic_merge": False,
        "automatic_geometry_replacement": False,
        "network_calls": False,
        "sentinel_hub_pu": False,
    }
    contract_out = out / "D2_EXECUTION_CONTRACT.json"
    contract_out.write_bytes(stable_json_bytes(execution_contract))
    execution_sha = sha256_file(contract_out)

    prior_coverage = 1.0 - len(missing_prior_ids) / int(exp["fields"])
    manifest = {
        "schema_version": "akerpuls-d2-full-skane-model-plan-result-v1",
        "status": status,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "git": {"branch": branch, "head": head},
        "checks": checks,
        "repo_hash_checks": repo_hash_checks,
        "fields": int(len(fq)),
        "analysis_cells": int(len(cell_plan)),
        "expanded_normalization_cells": expanded,
        "minimum_resolved_normalization_fields": min_norm,
        "d1s3k_pre_b2_ge24_all4_fields": int(fq.pre_b2_ge24_all4_valid_pixels.astype(bool).sum()),
        "d1s3k_zero_raster_pixel_fields": int((pd.to_numeric(fq.field_pixels, errors="coerce") <= 0).sum()),
        "rolling_prior_rows": int(len(prior)),
        "rolling_prior_missing_field_ids": int(len(missing_prior_ids)),
        "rolling_prior_coverage_fraction": prior_coverage,
        "rolling_prior_nonfinite_signal_rows": prior_nonfinite,
        "full_skane_model_executed": False,
        "candidate_discovery_executed": False,
        "true_loo_executed": False,
        "fusion_executed": False,
        "automatic_geometry_replacement": False,
        "d2_execution_contract_sha256": execution_sha,
        "interpretation": cfg["interpretation"],
    }
    (out / "d2_plan_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    log("AKERPULS D2 FULL-SKANE MODEL PLAN ONLY - ZERO NETWORK / ZERO MODEL")
    log(f"STATUS={status}")
    log(f"FIELDS={len(fq)} ANALYSIS_CELLS={len(cell_plan)} EXPANDED_NORMALIZATION_CELLS={expanded} MIN_RESOLVED_NORM_FIELDS={min_norm}")
    log(f"D1S3K_PRE_B2_GE24_ALL4_FIELDS={int(fq.pre_b2_ge24_all4_valid_pixels.astype(bool).sum())}/{len(fq)}")
    log(f"D1S3K_ZERO_RASTER_PIXEL_FIELDS={int((pd.to_numeric(fq.field_pixels, errors='coerce') <= 0).sum())}")
    log(f"ROLLING_PRIOR_ROWS={len(prior)} MISSING_FIELD_IDS={len(missing_prior_ids)} COVERAGE={prior_coverage:.6f} NONFINITE_SIGNAL_ROWS={prior_nonfinite}")
    log(f"FUSION_FREEZE_SHA256={artifact_sha}")
    log(f"CELL_PLAN_SHA256={hashes['cell_execution_plan_sha256']}")
    log(f"D2_EXECUTION_CONTRACT_SHA256={execution_sha}")
    log("STAGE_D2A=B2_BASELINE_SPLIT_DISCOVERY_ONLY")
    log("MANDATORY_STOP_AFTER_D2A=TRUE")
    log("STAGE_D2B=TRUE_LOO_HISTORY_PRIOR_FROZEN_FUSION_REQUIRES_SEPARATE_AUTHORIZATION")
    log("CHECKS=" + ";".join(f"{k}:{str(v).upper()}" for k, v in checks.items()))
    log("NETWORK_CALLS=0")
    log("PROCESS_API_CALLS=0")
    log("SENTINEL_HUB_PU_USED=0")
    log("FULL_SKANE_MODEL_EXECUTED=FALSE")
    log("AUTOMATIC_GEOMETRY_REPLACEMENT=FALSE")
    log(f"D2PLAN_STATUS={status}")
    log(f"OUTPUT={out}")
    return 0 if status == "PASS_TO_D2A_SPLIT_DISCOVERY_EXECUTION" else 2


if __name__ == "__main__":
    raise SystemExit(main())
