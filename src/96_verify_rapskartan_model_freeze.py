#!/usr/bin/env python3
"""Independent STOPPUNKT C verifier for the pre-blind Rapskartan model candidate."""
from __future__ import annotations

import argparse
import json
import subprocess
import traceback
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from rapskartan_model_core import (
    FORBIDDEN_YEAR, REQUIRED_DEVELOPMENT_YEARS, load_model_contract,
    model_contract_sha256, sha256_file, temporal_feature_columns,
)
from rapskartan_v1_discovery_core import (
    FEATURE_BRANCH, UPSTREAM_COMMIT, UPSTREAM_TAG, repository_snapshot,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = Path(r"C:\AkerSyncRepo\work\rapskartan_skane_v1_model_stopC")
REQUIRED_CONTRACTS = [
    "rapskartan_model_contract_v1.json", "feature_contract_v1.json",
    "threshold_contract_v1.json", "calibration_contract_v1.json",
    "development_cv_results.json", "development_cv_by_cutoff.csv",
    "model_artifacts_manifest.json",
]


def verify_artifacts(root: Path, manifest: dict[str, Any]) -> None:
    for record in manifest.get("artifacts", []):
        path = root / record["path"]
        if not path.is_file() or path.stat().st_size != int(record["bytes"]) or sha256_file(path) != record["sha256"]:
            raise RuntimeError(f"Model artifact mismatch: {record['path']}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    out = args.output_dir.resolve()
    try:
        snapshot = repository_snapshot(ROOT)
        if snapshot["branch"] != FEATURE_BRANCH or not snapshot["working_tree_clean"]:
            raise RuntimeError("Verifier requires a clean Rapskartan feature branch")
        if snapshot["upstream_tag"] != UPSTREAM_TAG or snapshot["upstream_dereferenced_commit"] != UPSTREAM_COMMIT:
            raise RuntimeError("Upstream freeze mismatch")
        for name in REQUIRED_CONTRACTS:
            if not (out / name).is_file():
                raise RuntimeError(f"Required STOPPUNKT C artifact missing: {name}")

        dataset_manifest = json.loads((out / "development_dataset_manifest.json").read_text(encoding="utf-8"))
        model_manifest = json.loads((out / "model_artifacts_manifest.json").read_text(encoding="utf-8"))
        model_contract = json.loads((out / "rapskartan_model_contract_v1.json").read_text(encoding="utf-8"))
        feature_contract = json.loads((out / "feature_contract_v1.json").read_text(encoding="utf-8"))
        threshold_contract = json.loads((out / "threshold_contract_v1.json").read_text(encoding="utf-8"))
        calibration_contract = json.loads((out / "calibration_contract_v1.json").read_text(encoding="utf-8"))
        cv_results = json.loads((out / "development_cv_results.json").read_text(encoding="utf-8"))
        if dataset_manifest.get("status") != "PASS" or model_manifest.get("status") != "PASS" or cv_results.get("status") != "PASS":
            raise RuntimeError("Dataset/model/CV status is not PASS")
        verify_artifacts(out, dataset_manifest)
        verify_artifacts(out, model_manifest)
        if model_manifest["development_dataset_manifest_sha256"] != sha256_file(out / "development_dataset_manifest.json"):
            raise RuntimeError("Model manifest is not bound to this development dataset")
        if model_manifest["model_development_contract_sha256"] != model_contract_sha256(ROOT):
            raise RuntimeError("Model manifest is not bound to the repository contract")
        if model_manifest["feature_head"] != snapshot["head"] or model_manifest["feature_tree"] != snapshot["head_tree"]:
            raise RuntimeError("Model manifest repository snapshot mismatch")

        selection = pd.read_csv(out / "development_field_selection.csv", dtype={"development_field_id": str, "municipality_code": str})
        labels = pd.read_csv(out / "development_labels.csv", dtype={"development_field_id": str})
        prior = pd.read_csv(out / "development_prior_features.csv", dtype={"development_field_id": str})
        temporal = pd.read_csv(out / "development_temporal_features.csv", dtype={"development_field_id": str})
        oof = pd.read_csv(out / "development_oof_predictions.csv", dtype={"development_field_id": str})
        cv = pd.read_csv(out / "development_cv_by_cutoff.csv")
        cv_year = pd.read_csv(out / "development_cv_by_year.csv")
        geo = pd.read_csv(out / "development_geographic_robustness.csv")
        reliability = pd.read_csv(out / "development_reliability_bins.csv")

        expected_fields = int(load_model_contract(ROOT)["resource_guards"]["expected_selected_field_years"])
        if len(selection) != expected_fields or len(labels) != expected_fields or len(prior) != expected_fields:
            raise RuntimeError("Development field/label/prior row count mismatch")
        if selection["development_field_id"].duplicated().any() or labels["development_field_id"].duplicated().any():
            raise RuntimeError("Development field identities are not unique")
        for name, frame in {"selection": selection, "labels": labels, "prior": prior, "temporal": temporal, "oof": oof}.items():
            years = sorted(pd.to_numeric(frame["target_year"], errors="raise").astype(int).unique().tolist())
            if years != REQUIRED_DEVELOPMENT_YEARS or any(year >= FORBIDDEN_YEAR for year in years):
                raise RuntimeError(f"{name}: development years are not exactly 2018-2024")
        label_like = {"is_winter_rapeseed", "crop_group", "official_crop_name", "crop_code_raw", "crop_subcategory_raw"}
        if label_like & set(temporal.columns) or label_like & set(prior.columns):
            raise RuntimeError("A feature file contains label-like columns")
        if set(labels["is_winter_rapeseed"].astype(int).unique()) != {0, 1} or int(labels["is_winter_rapeseed"].sum()) != 420:
            raise RuntimeError("Expected 420 positive and 1,260 negative development labels")
        expected_temporal = expected_fields * 9
        if len(temporal) != expected_temporal:
            raise RuntimeError(f"Temporal rows {len(temporal)}, expected {expected_temporal}")
        usable = temporal[temporal["data_quality_status"] == "USABLE"].copy()
        latest = pd.to_datetime(usable["latest_used_acquisition"], errors="raise")
        cutoffs = pd.to_datetime(usable["cutoff_date"], errors="raise")
        if (latest > cutoffs).any():
            raise RuntimeError("CAUSALITY_FAILURE: a feature uses a future acquisition")
        spectral_columns = temporal_feature_columns(load_model_contract(ROOT))
        if temporal.loc[temporal["data_quality_status"] == "NO_DATA", spectral_columns].notna().to_numpy().any():
            raise RuntimeError("NO_DATA feature rows retain model inputs")

        arms = {"PRIOR_ONLY", "SATELLITE_ONLY", "PRIOR_PLUS_SATELLITE"}
        cutoffs_expected = set(load_model_contract(ROOT)["temporal"]["cutoff_month_days"])
        if set(cv["model_arm"]) != arms or set(cv["cutoff_month_day"]) != cutoffs_expected:
            raise RuntimeError("CV results do not cover all arms/cutoffs")
        if {"PRIOR_FREQUENCY_BASELINE", "LOGISTIC_REGRESSION", "RANDOM_FOREST"} - set(cv["model_family"]):
            raise RuntimeError("Mandatory model baselines are missing")
        if set(cv_year["heldout_year"].astype(int)) != set(REQUIRED_DEVELOPMENT_YEARS):
            raise RuntimeError("Whole-year held-out CV coverage is incomplete")
        if len(geo) != 15 or set(geo["heldout_geographic_fold"].astype(int)) != set(range(5)):
            raise RuntimeError("Five-fold geographic robustness is incomplete")
        probability_columns = ["raw_probability_oof", "calibrated_probability_oof"]
        if oof[probability_columns].isna().any().any() or ((oof[probability_columns] < 0) | (oof[probability_columns] > 1)).any().any():
            raise RuntimeError("OOF probabilities are missing or outside [0,1]")
        if len(reliability) != 30 or set(reliability["model_arm"]) != arms:
            raise RuntimeError("Reliability QA bins are incomplete")

        selected_models = cv_results.get("selected_models", [])
        if len(selected_models) != 27 or len(threshold_contract.get("records", [])) != 27 or len(calibration_contract.get("records", [])) != 27:
            raise RuntimeError("Expected 27 frozen arm/cutoff model selections")
        if threshold_contract.get("blind_year_used") is not False or calibration_contract.get("blind_year_used") is not False:
            raise RuntimeError("Threshold or calibration contract used the blind year")
        if feature_contract.get("target_label_excluded_from_features") is not True:
            raise RuntimeError("Feature contract does not exclude target labels")
        model_files = sorted((out / "models").glob("*.joblib"))
        if len(model_files) != 27:
            raise RuntimeError(f"Expected 27 model files, found {len(model_files)}")
        expected_features = {
            "PRIOR_ONLY": list(feature_contract["prior_features"]),
            "SATELLITE_ONLY": list(feature_contract["satellite_features"]),
            "PRIOR_PLUS_SATELLITE": list(feature_contract["prior_features"]) + list(feature_contract["satellite_features"]),
        }
        for path in model_files:
            bundle = joblib.load(path)
            if bundle.get("schema_version") != "rapskartan-frozen-model-bundle-v1":
                raise RuntimeError(f"Unexpected model bundle schema: {path.name}")
            if bundle.get("training_years") != REQUIRED_DEVELOPMENT_YEARS or FORBIDDEN_YEAR in bundle.get("training_years", []):
                raise RuntimeError(f"Model bundle contains invalid training years: {path.name}")
            if "is_winter_rapeseed" in bundle or bundle.get("feature_columns") != expected_features[bundle["model_arm"]]:
                raise RuntimeError(f"Model bundle leaks labels or violates feature contract: {path.name}")
        scope = model_contract.get("scope", {})
        required_false = [
            "target_year_2025_labels_accessed", "blind_2025_predictions_created", "sentinel1",
            "full_skane", "web", "deployment", "tag", "merge",
        ]
        if any(scope.get(key) is not False for key in required_false):
            raise RuntimeError("Model contract crossed a forbidden phase boundary")
        if scope.get("model_development_pre_2025_only") is not True or model_contract.get("blind_year_used") is not False:
            raise RuntimeError("Model contract is not explicitly pre-blind")

        print("=" * 88)
        print("RAPSKARTAN SKANE V1 STOPPUNKT C PRE-BLIND VERIFIER: PASS")
        print("=" * 88)
        print(f"Repository HEAD: {snapshot['head']}")
        print(f"Development: {expected_fields:,} field-years · years 2018-2024 · 33 municipalities")
        print(f"Feature rows: {len(temporal):,} · usable: {len(usable):,} · explicit no-data: {len(temporal) - len(usable):,}")
        print("Model arms/cutoffs: 3/9 · frozen model bundles: 27")
        print("Whole-year CV / geographic robustness / calibration / thresholds: PASS")
        print("2025 row labels/predictions, Sentinel-1, full Skåne, web/deployment/tag/merge: NO")
        print("STOPPUNKT C")
        print("READY FOR 2025 BLIND TEST")
        print("2025 LABELS HAVE NOT BEEN USED FOR MODEL/FITTING/THRESHOLD SELECTION")
        return 0
    except Exception as exc:
        traceback.print_exc()
        print(f"RAPSKARTAN STOPPUNKT C PRE-BLIND VERIFIER: FAIL — {exc}")
        print("NOT READY FOR 2025 BLIND TEST")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
