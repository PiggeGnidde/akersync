#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Formal freeze of the persisted blind M4 2026 field prior.

Verifies the exact reviewed run, key artefact hashes, blind-year guards,
population/probability schema and diagnostics. No model fit or prediction occurs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_BRANCH = "feature/akerpuls-prelim-fields-2026-v0a"
EXPECTED_SOURCE_GIT_HEAD = "89c1b5b2ba9c8ff4eed338db4a2fa98ff76a9bb5"
EXPECTED_M4_V1B_FREEZE_SHA256 = "94ea57736b7aa472c1bca959aeb848b0e764240d3d47202c2a2a4dc144ed7b9a"
SOURCE_DIR = Path(r"C:\AkerSyncRepo\work\akerpuls_m4_2026_prior_v1")
DEFAULT_OUT = Path(r"C:\AkerSyncRepo\work\akerpuls_m4_2026_prior_freeze_v1")
STATUS = "FROZEN_AKERPULS_M4_2026_PRIOR_V1"

EXPECTED_MODEL_SHA256 = "5feaa68f2c021b250d9ef6c0fcc0e1abb615329d89d0027bc9fe25af6d04c7a0"
EXPECTED_PARQUET_SHA256 = "c595553436047132bdf280a685add4e123f579722ba353cbd8906ee778c1e3b8"
EXPECTED_CSV_GZ_SHA256 = "d88d316dc71395ed2ecf095b58d8775707b1f6ff6ea310c272984be1b6b77805"
EXPECTED_ROWS = 128636
EXPECTED_CLASSES = 16
EXPECTED_TRAIN_N = 954786
EXPECTED_TOP1_COUNTS = {
    "höstraps": 4378,
    "höstvete": 12485,
    "vårvete": 145,
    "höstkorn": 61,
    "vårkorn": 7849,
    "havre": 475,
    "råg": 1278,
    "rågvete": 573,
    "sockerbetor": 2096,
    "matpotatis": 476,
    "stärkelsepotatis": 1055,
    "vall på åkermark": 56131,
    "majs": 1806,
    "baljväxter": 115,
    "träda/miljöyta": 5575,
    "annan gröda": 34138,
}
EXPECTED_PROB_COLUMNS = [f"p__{x}" for x in EXPECTED_TOP1_COUNTS]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def git_guard() -> str:
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    if branch != EXPECTED_BRANCH:
        raise RuntimeError(f"Expected branch {EXPECTED_BRANCH}, got {branch}")
    dirty = subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True).strip()
    if dirty:
        raise RuntimeError("Working tree must be clean")
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def verify_source(src: Path) -> dict:
    required = {
        "model/M4_2026_FINAL.txt": EXPECTED_MODEL_SHA256,
        "M4_2026_FIELD_PRIOR.parquet": EXPECTED_PARQUET_SHA256,
        "M4_2026_FIELD_PRIOR.csv.gz": EXPECTED_CSV_GZ_SHA256,
    }
    hashes = {}
    for rel, expected in required.items():
        p = src / rel
        if not p.is_file():
            raise FileNotFoundError(p)
        got = sha256_file(p)
        if got != expected:
            raise RuntimeError(f"Artefact SHA mismatch for {rel}: {got}")
        hashes[rel] = got

    metadata_path = src / "M4_2026_PRIOR_METADATA.json"
    diag_path = src / "M4_2026_DIAGNOSTICS.json"
    env_path = src / "ENVIRONMENT.json"
    feature_path = src / "FEATURE_CONTRACT.json"
    source_freeze_path = src / "SOURCE_M4_V1B_FREEZE.json"
    manifest_path = src / "SHA256_MANIFEST.txt"
    for p in (metadata_path, diag_path, env_path, feature_path, source_freeze_path, manifest_path):
        if not p.is_file():
            raise FileNotFoundError(p)

    metadata = load_json(metadata_path)
    diag = load_json(diag_path)
    source_freeze = load_json(source_freeze_path)

    if metadata.get("status") != "PASS_TO_M4_2026_PRIOR_FREEZE_REVIEW":
        raise RuntimeError(f"Unexpected source status: {metadata.get('status')}")
    if metadata.get("git_head") != EXPECTED_SOURCE_GIT_HEAD:
        raise RuntimeError(f"Unexpected source git head: {metadata.get('git_head')}")
    if metadata.get("source_m4_v1b_freeze_sha256") != EXPECTED_M4_V1B_FREEZE_SHA256:
        raise RuntimeError("Source metadata does not pin the accepted M4 V1B freeze")
    if int(metadata.get("training_n_total", -1)) != EXPECTED_TRAIN_N:
        raise RuntimeError("Training N mismatch")
    if int(metadata.get("prediction_rows", -1)) != EXPECTED_ROWS:
        raise RuntimeError("Prediction-row count mismatch")
    if metadata.get("probability_columns") != EXPECTED_PROB_COLUMNS:
        raise RuntimeError("Probability class/order mismatch")

    blind = metadata.get("blind_year_policy", {})
    if blind.get("history_through_year") != 2025 or blind.get("target_year") != 2026:
        raise RuntimeError("Blind-year policy mismatch")
    if blind.get("2026_crop_labels_used") is not False or blind.get("2026_satellite_used") is not False:
        raise RuntimeError("Forbidden 2026 information used")

    guards = diag.get("guards", {})
    for k in ("crop_label_2026_used", "sentinel_2026_used", "merge_m0_used", "fusion_executed", "geometry_mutated", "thresholds_tuned"):
        if guards.get(k) is not False:
            raise RuntimeError(f"Guard failed: {k}={guards.get(k)}")
    if int(diag.get("fields", -1)) != EXPECTED_ROWS or int(diag.get("classes", -1)) != EXPECTED_CLASSES:
        raise RuntimeError("Diagnostics population/class count mismatch")
    if int(diag.get("training_n_total", -1)) != EXPECTED_TRAIN_N:
        raise RuntimeError("Diagnostics training N mismatch")
    if float(diag.get("probability_row_sum_max_abs_error", 1.0)) > 1e-8:
        raise RuntimeError("Probability row-sum error too large")
    if diag.get("top1_counts") != EXPECTED_TOP1_COUNTS:
        raise RuntimeError("Top-1 class census changed")
    if sum(EXPECTED_TOP1_COUNTS.values()) != EXPECTED_ROWS:
        raise RuntimeError("Pinned top-1 census does not sum to field population")

    if source_freeze.get("status") != "FROZEN_AKERPULS_M4_REIMPLEMENTATION_V1B":
        raise RuntimeError("Embedded source M4 V1B freeze status mismatch")

    # Inspect canonical Parquet without loading the full matrix into memory.
    pf = pd.read_parquet(src / "M4_2026_FIELD_PRIOR.parquet", columns=["current_field_id", "top1_class", "top1_prob", "entropy"])
    if len(pf) != EXPECTED_ROWS:
        raise RuntimeError(f"Parquet row count mismatch: {len(pf)}")
    if pf["current_field_id"].nunique() != EXPECTED_ROWS:
        raise RuntimeError("Parquet current_field_id is not unique")
    if pf["top1_class"].value_counts().to_dict() != EXPECTED_TOP1_COUNTS:
        raise RuntimeError("Parquet top1 census differs from diagnostics")

    return {
        "key_hashes": hashes,
        "metadata_sha256": sha256_file(metadata_path),
        "diagnostics_sha256": sha256_file(diag_path),
        "environment_sha256": sha256_file(env_path),
        "feature_contract_sha256": sha256_file(feature_path),
        "source_m4_v1b_freeze_copy_sha256": sha256_file(source_freeze_path),
        "source_manifest_sha256": sha256_file(manifest_path),
        "probability_row_sum_max_abs_error": float(diag["probability_row_sum_max_abs_error"]),
        "top1_counts": EXPECTED_TOP1_COUNTS,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-dir", default=str(SOURCE_DIR))
    ap.add_argument("--output-dir", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    freeze_git_head = git_guard()
    src = Path(args.source_dir)
    out = Path(args.output_dir)
    if out.exists():
        raise RuntimeError(f"Freeze output already exists: {out}")

    verified = verify_source(src)

    payload = {
        "schema_version": "akerpuls-m4-2026-prior-freeze-v1",
        "status": STATUS,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "freeze_git_head": freeze_git_head,
        "source_run_git_head": EXPECTED_SOURCE_GIT_HEAD,
        "source_run_dir": str(src),
        "source_m4_v1b_freeze_sha256": EXPECTED_M4_V1B_FREEZE_SHA256,
        "target_year": 2026,
        "history_through_year": 2025,
        "fields": EXPECTED_ROWS,
        "classes": EXPECTED_CLASSES,
        "training_n_total": EXPECTED_TRAIN_N,
        "key_artefacts": verified["key_hashes"],
        "metadata_sha256": verified["metadata_sha256"],
        "diagnostics_sha256": verified["diagnostics_sha256"],
        "environment_sha256": verified["environment_sha256"],
        "feature_contract_sha256": verified["feature_contract_sha256"],
        "source_m4_v1b_freeze_copy_sha256": verified["source_m4_v1b_freeze_copy_sha256"],
        "source_run_manifest_sha256": verified["source_manifest_sha256"],
        "probability_row_sum_max_abs_error": verified["probability_row_sum_max_abs_error"],
        "top1_counts": verified["top1_counts"],
        "guards": {
            "2026_crop_labels_used": False,
            "2026_satellite_used": False,
            "merge_m0_used": False,
            "fusion_executed": False,
            "geometry_mutated": False,
            "thresholds_tuned": False,
            "model_fit_executed_in_freeze": False,
            "prediction_executed_in_freeze": False,
        },
        "next": "BUILD_M1_PAIR_PRIOR_FEATURES_ON_EXACT_FROZEN_27146_M0_PAIR_UNIVERSE",
    }

    out.mkdir(parents=True, exist_ok=False)
    freeze_json = out / "AKERPULS_M4_2026_PRIOR_FREEZE_V1.json"
    freeze_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    freeze_sha = sha256_file(freeze_json)
    (out / "AKERPULS_M4_2026_PRIOR_FREEZE_V1.sha256").write_text(
        freeze_sha + "  AKERPULS_M4_2026_PRIOR_FREEZE_V1.json\n", encoding="utf-8"
    )
    shutil.copyfile(src / "SHA256_MANIFEST.txt", out / "SOURCE_RUN_SHA256_MANIFEST.txt")

    print("AKERPULS M4 2026 PRIOR FORMAL FREEZE")
    print(f"STATUS={STATUS}")
    print(f"SOURCE_RUN_GIT_HEAD={EXPECTED_SOURCE_GIT_HEAD}")
    print(f"FREEZE_GIT_HEAD={freeze_git_head}")
    print(f"SOURCE_M4_V1B_FREEZE_SHA256={EXPECTED_M4_V1B_FREEZE_SHA256}")
    print(f"M4_2026_PRIOR_FREEZE_SHA256={freeze_sha}")
    print(f"FIELDS={EXPECTED_ROWS} CLASSES={EXPECTED_CLASSES} TRAIN_N={EXPECTED_TRAIN_N}")
    print(f"MODEL_SHA256={EXPECTED_MODEL_SHA256}")
    print(f"PARQUET_SHA256={EXPECTED_PARQUET_SHA256}")
    print(f"CSV_GZ_SHA256={EXPECTED_CSV_GZ_SHA256}")
    print("BLIND_2026_GUARDS=PASS")
    print("MODEL_FIT_EXECUTED_IN_FREEZE=FALSE PREDICTION_EXECUTED_IN_FREEZE=FALSE")
    print("NEXT=BUILD_M1_PAIR_PRIOR_FEATURES_ON_EXACT_FROZEN_27146_M0_PAIR_UNIVERSE")
    print(f"OUTPUT={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
