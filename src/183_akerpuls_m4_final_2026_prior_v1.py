#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Train and persist the final frozen-contract M4 prior for blind year 2026.

Prerequisite: formal M4 V1B reimplementation freeze.
Uses only frozen ÅkerMinne history through 2025 plus frozen static context.
No 2026 crop labels, Sentinel data, M0 merge evidence, fusion, or geometry mutation.

Persists:
- final LightGBM portable text model,
- full 128636 x 16 per-field probability matrix (Parquet + CSV.GZ),
- diagnostics and training provenance,
- exact feature contract/environment,
- SHA-256 manifest.

This is a review package, not yet the formal 2026-prior freeze.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_BRANCH = "feature/akerpuls-prelim-fields-2026-v0a"
BASE_SCRIPT = ROOT / "src" / "179_akerpuls_m4_reimplementation_reproduction_gate_v1.py"
BASE_CONFIG = ROOT / "config" / "akerpuls_m4_reimplementation_v1.json"
PATCH_CONFIG = ROOT / "config" / "akerpuls_m4_target_validity_patch_v1b.json"

FREEZE_DIR = Path(r"C:\AkerSyncRepo\work\akerpuls_m4_reimplementation_v1b_freeze")
FREEZE_JSON = FREEZE_DIR / "AKERPULS_M4_REIMPLEMENTATION_V1B_FREEZE.json"
EXPECTED_FREEZE_SHA256 = "94ea57736b7aa472c1bca959aeb848b0e764240d3d47202c2a2a4dc144ed7b9a"

REPRO_DIR = Path(r"C:\AkerSyncRepo\work\akerpuls_m4_reproduction_gate_v1b")
EXPECTED_FEATURE_CONTRACT_SHA256 = "a264d348728dd417435fa418c4e9b14abf927d727c0f5b2c2f9587e6be986d35"

DEFAULT_OUT = Path(r"C:\AkerSyncRepo\work\akerpuls_m4_2026_prior_v1")
STATUS = "PASS_TO_M4_2026_PRIOR_FREEZE_REVIEW"
TARGET_YEAR = 2026
EXPECTED_FIELDS = 128636
EXPECTED_TRAIN_N_BY_YEAR = {
    2018: 113062,
    2019: 114486,
    2020: 118916,
    2021: 118190,
    2022: 119101,
    2023: 120330,
    2024: 122065,
    2025: 128636,
}
EXPECTED_TOTAL_TRAIN_N = 954786


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def package_version(name: str):
    try:
        import importlib.metadata
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def git_guard() -> str:
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    if branch != EXPECTED_BRANCH:
        raise RuntimeError(f"Expected branch {EXPECTED_BRANCH}, got {branch}")
    dirty = subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True).strip()
    if dirty:
        raise RuntimeError("Working tree must be clean")
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def load_base_module():
    spec = importlib.util.spec_from_file_location("m4_final_base", BASE_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def verify_freeze() -> dict:
    if not FREEZE_JSON.is_file():
        raise FileNotFoundError(FREEZE_JSON)
    got = sha256_file(FREEZE_JSON)
    if got != EXPECTED_FREEZE_SHA256:
        raise RuntimeError(f"M4 V1B freeze SHA changed: {got}")
    freeze = load_json(FREEZE_JSON)
    if freeze.get("status") != "FROZEN_AKERPULS_M4_REIMPLEMENTATION_V1B":
        raise RuntimeError(f"Unexpected M4 freeze status: {freeze.get('status')}")
    guards = freeze.get("guards", {})
    if guards.get("prediction_2026_executed") is not False:
        raise RuntimeError("Freeze indicates 2026 was already predicted")
    return freeze


def prepare_base_v1b(mod, cfg: dict):
    base = list(mod.prepare_base(cfg))
    ids, cls_wide, known_wide, cov_wide, share_wide, static_i, soil_i = base

    patch = load_json(PATCH_CONFIG)
    rule = patch["rule"]
    excluded = set(rule["exclude_statuses"])
    if excluded != {"NO_PUBLIC_MATCH"}:
        raise RuntimeError(f"Unexpected V1B excluded statuses: {sorted(excluded)}")
    if not rule.get("apply_to_target_validity") or not rule.get("apply_to_history_feature_validity"):
        raise RuntimeError("V1B validity rule must apply to both target and history")

    hist_meta = cfg["inputs"]["history"]
    hist_path = Path(cfg["inputs"]["directory"]) / hist_meta["file"]
    status = pd.read_csv(
        hist_path,
        usecols=["current_field_id", "history_year", "status"],
        compression="gzip",
        low_memory=False,
    )
    status["current_field_id"] = status["current_field_id"].astype("string")
    status["history_year"] = pd.to_numeric(status["history_year"], errors="raise").astype(int)
    status_wide = status.pivot(index="current_field_id", columns="history_year", values="status").reindex(ids)

    bad = status_wide.isin(sorted(excluded))
    cls_wide = cls_wide.mask(bad, mod.UNKNOWN)
    known_wide = known_wide & (~bad.fillna(False))
    return ids, cls_wide, known_wide, cov_wide, share_wide, static_i, soil_i


def write_manifest(out: Path) -> Path:
    rows = []
    for p in sorted(out.rglob("*")):
        if p.is_file() and p.name != "SHA256_MANIFEST.txt":
            rows.append(f"{sha256_file(p)}  {p.relative_to(out).as_posix()}")
    path = out / "SHA256_MANIFEST.txt"
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def quantiles(x: np.ndarray) -> dict:
    qs = [0.0, 0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99, 1.0]
    vals = np.quantile(x, qs)
    return {str(q): float(v) for q, v in zip(qs, vals)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output-dir", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    git_head = git_guard()
    freeze = verify_freeze()
    out = Path(args.output_dir)
    if out.exists():
        raise RuntimeError(f"Output directory already exists: {out}")

    cfg = load_json(BASE_CONFIG)
    expected_lgb = cfg["lightgbm"]["package_version"]
    if package_version("lightgbm") != expected_lgb:
        raise RuntimeError(f"lightgbm=={expected_lgb} required; installed={package_version('lightgbm')}")
    if package_version("pyarrow") is None:
        raise RuntimeError("pyarrow is required to persist the canonical 2026 prior Parquet")

    import lightgbm as lgb
    import pyarrow  # noqa: F401

    feature_contract_path = REPRO_DIR / "FEATURE_CONTRACT.json"
    if not feature_contract_path.is_file():
        raise FileNotFoundError(feature_contract_path)
    if sha256_file(feature_contract_path) != EXPECTED_FEATURE_CONTRACT_SHA256:
        raise RuntimeError("Frozen reproduction feature contract SHA changed")
    frozen_feature_contract = load_json(feature_contract_path)

    print("AKERPULS M4 FINAL 2026 PRIOR V1")
    print(f"GIT_HEAD={git_head}")
    print(f"M4_V1B_FREEZE_SHA256={EXPECTED_FREEZE_SHA256}")
    print(f"LIGHTGBM_VERSION={package_version('lightgbm')} PYARROW_VERSION={package_version('pyarrow')}")
    print("SATELLITE_2026_USED=FALSE MERGE_M0_USED=FALSE CROP_LABEL_2026_USED=FALSE")
    print("PROGRESS=LOAD_FROZEN_INPUTS_AND_BUILD_V1B_HISTORY")

    mod = load_base_module()
    base = prepare_base_v1b(mod, cfg)
    ids = base[0]
    if len(ids) != EXPECTED_FIELDS:
        raise RuntimeError(f"Field census changed: {len(ids)}")

    domains = mod.categorical_domains(cfg, base)
    feature_order, cat_cols, num_cols = mod.build_feature_schema(cfg)
    if feature_order != frozen_feature_contract["feature_order"]:
        raise RuntimeError("Computed feature order differs from frozen reproduction contract")
    if cat_cols != frozen_feature_contract["categorical_features"]:
        raise RuntimeError("Computed categorical feature list differs from frozen contract")
    if domains != frozen_feature_contract["categorical_domains"]:
        raise RuntimeError("Computed categorical domains differ from frozen contract")

    class_to_int = {c: i for i, c in enumerate(cfg["target_classes"])}
    train_frames = []
    train_targets = []
    census = []

    print("PROGRESS=BUILD_TRAINING_TARGET_YEARS_2018_2025")
    for year in range(2018, 2026):
        X, target, valid = mod.build_year_features(year, cfg, base, domains)
        X = X[feature_order]
        y_int = target.map(class_to_int)
        good = valid & y_int.notna().to_numpy()
        n = int(good.sum())
        expected = EXPECTED_TRAIN_N_BY_YEAR[year]
        print(f"TRAIN_TARGET_YEAR={year} N={n} EXPECTED={expected} MATCH={str(n == expected).upper()}")
        if n != expected:
            raise RuntimeError(f"Final training census mismatch year={year}: {n} != {expected}")
        train_frames.append(X.loc[good])
        train_targets.append(y_int.loc[good].astype(int))
        census.append({"year": year, "n": n})

    X_train = pd.concat(train_frames, axis=0, ignore_index=True)
    y_train_s = pd.concat(train_targets, axis=0, ignore_index=True)
    y_train = y_train_s.to_numpy(dtype=np.int32)
    if len(y_train) != EXPECTED_TOTAL_TRAIN_N:
        raise RuntimeError(f"Final train N mismatch: {len(y_train)} != {EXPECTED_TOTAL_TRAIN_N}")
    present = sorted(np.unique(y_train).tolist())
    if present != list(range(len(cfg["target_classes"]))):
        raise RuntimeError(f"Not all 16 target classes are present in final training data: {present}")

    class_counts = {
        cfg["target_classes"][i]: int((y_train == i).sum())
        for i in range(len(cfg["target_classes"]))
    }

    params = dict(cfg["lightgbm"])
    params.pop("package_version", None)
    objective = params.pop("objective")
    params["objective"] = objective
    params["num_class"] = len(cfg["target_classes"])

    print(f"PROGRESS=FIT_FINAL_M4 TRAIN_N={len(y_train)} FEATURES={len(feature_order)} CLASSES={len(cfg['target_classes'])}")
    model = lgb.LGBMClassifier(**params)
    model.fit(X_train, y_train, categorical_feature=cat_cols)

    print("PROGRESS=BUILD_BLIND_2026_FEATURES")
    X26, target26, valid26 = mod.build_year_features(TARGET_YEAR, cfg, base, domains)
    X26 = X26[feature_order]
    if len(X26) != EXPECTED_FIELDS:
        raise RuntimeError("2026 feature row count mismatch")
    if bool(valid26.any()):
        raise RuntimeError("2026 target-valid vector unexpectedly contains observed labels")
    if not bool((target26 == mod.UNKNOWN).all()):
        raise RuntimeError("2026 target placeholder unexpectedly contains crop labels")

    print("PROGRESS=PREDICT_BLIND_2026_PRIOR")
    proba = np.asarray(model.predict_proba(X26), dtype=np.float64)
    nclass = len(cfg["target_classes"])
    if proba.shape != (EXPECTED_FIELDS, nclass):
        raise RuntimeError(f"Unexpected 2026 probability shape: {proba.shape}")
    if not np.isfinite(proba).all():
        raise RuntimeError("2026 probabilities contain NaN/Inf")
    if float(proba.min()) < -1e-12 or float(proba.max()) > 1.0 + 1e-12:
        raise RuntimeError("2026 probabilities outside [0,1]")
    row_sums = proba.sum(axis=1)
    max_sum_err = float(np.max(np.abs(row_sums - 1.0)))
    if max_sum_err > 1e-8:
        raise RuntimeError(f"2026 probability row sums invalid: max error {max_sum_err}")

    out.mkdir(parents=True, exist_ok=False)
    model_dir = out / "model"
    model_dir.mkdir()
    model_path = model_dir / "M4_2026_FINAL.txt"
    model.booster_.save_model(str(model_path))

    shutil.copyfile(feature_contract_path, out / "FEATURE_CONTRACT.json")
    shutil.copyfile(FREEZE_JSON, out / "SOURCE_M4_V1B_FREEZE.json")
    shutil.copyfile(PATCH_CONFIG, out / "V1B_TARGET_VALIDITY_PATCH.json")

    top_idx = np.argsort(-proba, axis=1)[:, :3]
    top_prob = np.take_along_axis(proba, top_idx, axis=1)
    classes = np.asarray(cfg["target_classes"], dtype=object)
    eps = 1e-15
    entropy = -np.sum(np.clip(proba, eps, 1.0) * np.log(np.clip(proba, eps, 1.0)), axis=1)

    pred = pd.DataFrame({"current_field_id": ids.astype("string")})
    for j, cls in enumerate(cfg["target_classes"]):
        pred[f"p__{cls}"] = proba[:, j].astype(np.float32)
    pred["top1_class"] = classes[top_idx[:, 0]]
    pred["top1_prob"] = top_prob[:, 0].astype(np.float32)
    pred["top2_class"] = classes[top_idx[:, 1]]
    pred["top2_prob"] = top_prob[:, 1].astype(np.float32)
    pred["top3_class"] = classes[top_idx[:, 2]]
    pred["top3_prob"] = top_prob[:, 2].astype(np.float32)
    pred["entropy"] = entropy.astype(np.float32)
    pred["valid_history_years"] = X26["valid_history_years"].to_numpy(dtype=np.float32)
    pred["lag_1"] = X26["lag_1"].astype("string").fillna(mod.UNKNOWN).to_numpy()
    pred["lag_2"] = X26["lag_2"].astype("string").fillna(mod.UNKNOWN).to_numpy()
    pred["lag_3"] = X26["lag_3"].astype("string").fillna(mod.UNKNOWN).to_numpy()

    parquet_path = out / "M4_2026_FIELD_PRIOR.parquet"
    csv_path = out / "M4_2026_FIELD_PRIOR.csv.gz"
    pred.to_parquet(parquet_path, index=False, engine="pyarrow", compression="zstd")
    pred.to_csv(csv_path, index=False, compression="gzip")

    top1_counts = pred["top1_class"].value_counts().reindex(cfg["target_classes"], fill_value=0)
    mean_probs = proba.mean(axis=0)
    diagnostics = {
        "schema_version": "akerpuls-m4-2026-prior-diagnostics-v1",
        "status": STATUS,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": git_head,
        "target_year": TARGET_YEAR,
        "fields": EXPECTED_FIELDS,
        "classes": nclass,
        "training_target_years": [2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025],
        "training_n_by_year": census,
        "training_n_total": int(len(y_train)),
        "training_class_counts": class_counts,
        "probability_row_sum_max_abs_error": max_sum_err,
        "probability_min": float(proba.min()),
        "probability_max": float(proba.max()),
        "top1_probability_quantiles": quantiles(top_prob[:, 0]),
        "entropy_quantiles": quantiles(entropy),
        "valid_history_years_quantiles": quantiles(X26["valid_history_years"].to_numpy(dtype=np.float64)),
        "top1_counts": {str(k): int(v) for k, v in top1_counts.items()},
        "mean_prior_probability_by_class": {
            cls: float(mean_probs[i]) for i, cls in enumerate(cfg["target_classes"])
        },
        "guards": {
            "crop_label_2026_used": False,
            "sentinel_2026_used": False,
            "merge_m0_used": False,
            "fusion_executed": False,
            "geometry_mutated": False,
            "thresholds_tuned": False,
        },
    }
    (out / "M4_2026_DIAGNOSTICS.json").write_text(
        json.dumps(diagnostics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    environment = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": git_head,
        "python": sys.version,
        "platform": platform.platform(),
        "packages": {
            "numpy": package_version("numpy"),
            "pandas": package_version("pandas"),
            "scikit-learn": package_version("scikit-learn"),
            "lightgbm": package_version("lightgbm"),
            "pyarrow": package_version("pyarrow"),
        },
        "lightgbm_params": cfg["lightgbm"],
    }
    (out / "ENVIRONMENT.json").write_text(
        json.dumps(environment, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    metadata = {
        "schema_version": "akerpuls-m4-final-2026-prior-v1",
        "status": STATUS,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": git_head,
        "target_year": TARGET_YEAR,
        "source_m4_v1b_freeze_sha256": EXPECTED_FREEZE_SHA256,
        "base_config_sha256": sha256_file(BASE_CONFIG),
        "validity_patch_sha256": sha256_file(PATCH_CONFIG),
        "feature_contract_sha256": EXPECTED_FEATURE_CONTRACT_SHA256,
        "training_n_total": int(len(y_train)),
        "prediction_rows": int(len(pred)),
        "probability_columns": [f"p__{c}" for c in cfg["target_classes"]],
        "model_file": str(model_path.relative_to(out)),
        "parquet_file": str(parquet_path.relative_to(out)),
        "csv_gz_file": str(csv_path.relative_to(out)),
        "blind_year_policy": {
            "history_through_year": 2025,
            "target_year": 2026,
            "2026_crop_labels_used": False,
            "2026_satellite_used": False,
        },
        "next": "FREEZE_M4_2026_PRIOR_THEN_BUILD_M1_PAIR_FEATURES_ON_FROZEN_27146_PAIR_UNIVERSE",
    }
    (out / "M4_2026_PRIOR_METADATA.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    manifest = write_manifest(out)

    print(f"STATUS={STATUS}")
    print(f"TRAIN_N_TOTAL={len(y_train)} EXPECTED={EXPECTED_TOTAL_TRAIN_N}")
    print(f"PREDICTION_ROWS={len(pred)} CLASSES={nclass}")
    print(f"PROB_ROW_SUM_MAX_ABS_ERROR={max_sum_err:.3e}")
    print(f"TOP1_PROB_P50={np.median(top_prob[:,0]):.6f} P90={np.quantile(top_prob[:,0],0.90):.6f}")
    print(f"ENTROPY_P50={np.median(entropy):.6f} P90={np.quantile(entropy,0.90):.6f}")
    print("TOP1_COUNTS=" + " | ".join(f"{k}:{int(v)}" for k, v in top1_counts.items()))
    print(f"MODEL_SHA256={sha256_file(model_path)}")
    print(f"PARQUET_SHA256={sha256_file(parquet_path)}")
    print(f"CSV_GZ_SHA256={sha256_file(csv_path)}")
    print("CROP_LABEL_2026_USED=FALSE SATELLITE_2026_USED=FALSE MERGE_M0_USED=FALSE")
    print("FUSION_EXECUTED=FALSE GEOMETRY_MUTATED=FALSE THRESHOLDS_TUNED=FALSE")
    print(f"SHA256_MANIFEST={manifest}")
    print("NEXT=FREEZE_M4_2026_PRIOR_THEN_BUILD_M1_PAIR_FEATURES_ON_FROZEN_27146_PAIR_UNIVERSE")
    print(f"OUTPUT={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
