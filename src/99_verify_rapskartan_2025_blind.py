#!/usr/bin/env python3
"""Independent STOPPUNKT D verifier for the frozen 2025 Rapskartan blind benchmark."""
from __future__ import annotations

import argparse
import json
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

from rapskartan_blind_evaluation_core import (
    LABEL_COLUMNS, evaluate_predictions, join_sample_ground_truth, load_ground_truth,
    open_prediction_lock, verify_locked_artifacts,
)
from rapskartan_blind_prediction_core import (
    frozen_runtime_contract, load_blind_contract, make_predictions, sha256_file, verify_stop_c,
)
from rapskartan_v1_discovery_core import FEATURE_BRANCH, repository_snapshot


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STOP_C = Path(r"C:\AkerSyncRepo\work\rapskartan_skane_v1_model_stopC")
DEFAULT_OUT = Path(r"C:\AkerSyncRepo\work\rapskartan_skane_v1_blind_2025_stopD")
DEFAULT_TRUTH = Path(r"C:\AkerSyncRepo\work\akerscore_validation_csv_upload")


def compare_frames(expected: pd.DataFrame, actual: pd.DataFrame, keys: list[str]) -> None:
    if list(expected.columns) != list(actual.columns) or len(expected) != len(actual):
        raise RuntimeError("Recomputed benchmark schema/row count mismatch")
    expected = expected.sort_values(keys, kind="mergesort").reset_index(drop=True)
    actual = actual.sort_values(keys, kind="mergesort").reset_index(drop=True)
    for column in expected.columns:
        if pd.api.types.is_numeric_dtype(expected[column]) and pd.api.types.is_numeric_dtype(actual[column]):
            if not np.allclose(pd.to_numeric(expected[column], errors="coerce"), pd.to_numeric(actual[column], errors="coerce"), rtol=1e-9, atol=1e-9, equal_nan=True):
                raise RuntimeError(f"Recomputed numeric benchmark mismatch: {column}")
        else:
            left = expected[column].astype(str).replace("nan", "")
            right = actual[column].astype(str).replace("nan", "")
            if not left.equals(right):
                raise RuntimeError(f"Recomputed benchmark mismatch: {column}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--stop-c-dir", type=Path, default=DEFAULT_STOP_C)
    parser.add_argument("--ground-truth-dir", type=Path, default=DEFAULT_TRUTH)
    args = parser.parse_args(); out = args.output_dir.resolve()
    try:
        snapshot = repository_snapshot(ROOT)
        if snapshot["branch"] != FEATURE_BRANCH or not snapshot["working_tree_clean"]:
            raise RuntimeError(f"Verifier requires clean branch {FEATURE_BRANCH}")
        frozen = verify_stop_c(ROOT, args.stop_c_dir.resolve())
        contract = frozen_runtime_contract(args.stop_c_dir.resolve(), load_blind_contract(ROOT))
        lock = open_prediction_lock(out, ROOT)
        manifest_path = out / "blind_evaluation_manifest.json"
        if not manifest_path.is_file():
            raise RuntimeError("Blind evaluation manifest is missing")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("status") != "PASS" or manifest.get("prediction_lock_sha256") != sha256_file(out / "prediction_lock_manifest.json"):
            raise RuntimeError("Blind evaluation is not bound to the verified prediction lock")
        verify_locked_artifacts(out, manifest)
        for record in manifest.get("code_hashes", []):
            path = ROOT / record["path"]
            if not path.is_file() or sha256_file(path) != record["sha256"]:
                raise RuntimeError(f"Blind evaluation code hash mismatch: {record['path']}")

        selection = pd.read_csv(out / "blind_field_selection.csv", dtype={"development_field_id": str, "current_field_id": str, "municipality_code": str})
        prior = pd.read_csv(out / "blind_prior_features.csv", dtype={"development_field_id": str, "current_field_id": str, "municipality_code": str})
        temporal = pd.read_csv(out / "blind_temporal_features.csv", dtype={"development_field_id": str, "municipality_code": str})
        predictions = pd.read_csv(out / "blind_predictions_locked.csv", dtype={"development_field_id": str, "current_field_id": str, "municipality_code": str})
        required_prediction_columns = {
            "field_id", "municipality_code", "target_year", "cutoff_date",
            "latest_used_acquisition", "days_since_last_obs", "valid_obs_count",
            "valid_pixel_fraction", "prior_raps_probability", "satellite_score",
            "p_raps", "confidence_status", "data_quality_status", "model_arm",
            "model_version", "feature_contract_version", "source_manifest_id",
        }
        missing_prediction_columns = sorted(required_prediction_columns - set(predictions.columns))
        if missing_prediction_columns:
            raise RuntimeError(f"Blind prediction contract columns are missing: {missing_prediction_columns}")
        if not predictions["field_id"].astype(str).equals(predictions["current_field_id"].astype(str)):
            raise RuntimeError("Blind prediction field_id alias differs from frozen current_field_id")
        if not np.allclose(predictions["p_raps"], predictions["calibrated_probability"], rtol=0, atol=0, equal_nan=True):
            raise RuntimeError("Blind prediction p_raps alias differs from calibrated probability")
        if LABEL_COLUMNS & set(predictions.columns) or LABEL_COLUMNS & set(prior.columns) or LABEL_COLUMNS & set(temporal.columns):
            raise RuntimeError("A pre-lock artifact contains target labels")
        if len(predictions) != len(selection) * 27 or predictions.groupby(["current_field_id", "cutoff_date", "model_arm"]).size().ne(1).any():
            raise RuntimeError("Blind prediction arm/cutoff coverage is incomplete")
        satellite = predictions[predictions["model_arm"] != "PRIOR_ONLY"]
        if satellite.loc[satellite["data_quality_status"] == "NO_DATA", "calibrated_probability"].notna().any():
            raise RuntimeError("No-data fields silently received satellite probabilities")
        usable_temporal = temporal[temporal["data_quality_status"] == "USABLE"]
        if (pd.to_datetime(usable_temporal["latest_used_acquisition"]) > pd.to_datetime(usable_temporal["cutoff_date"])).any():
            raise RuntimeError("CAUSALITY_FAILURE: blind temporal features use future observations")

        recomputed_predictions = make_predictions(selection, prior, temporal, args.stop_c_dir.resolve(), contract)
        probability_columns = ["raw_probability", "calibrated_probability"]
        if not np.allclose(recomputed_predictions[probability_columns], predictions[probability_columns], rtol=1e-10, atol=1e-12, equal_nan=True):
            raise RuntimeError("Independent frozen-model prediction recomputation differs")
        for column in ["predicted_at_frozen_p95", "predicted_at_frozen_p90", "predicted_at_0_5", "predicted_at_0_8", "predicted_at_0_9", "predicted_at_0_95"]:
            if not recomputed_predictions[column].astype(bool).equals(predictions[column].astype(bool)):
                raise RuntimeError(f"Independent decision recomputation differs: {column}")

        truth_path = args.ground_truth_dir.resolve() / contract["ground_truth"]["relative_path"]
        truth, inventory = load_ground_truth(truth_path, contract)
        sample = join_sample_ground_truth(selection, truth, int(contract["resource_guards"]["minimum_joined_positive_sample_fields"]))
        stored_sample = pd.read_csv(out / "blind_ground_truth_sample.csv", dtype={"development_field_id": str, "current_field_id": str, "municipality_code": str})
        if not sample[["current_field_id", "is_winter_rapeseed"]].sort_values("current_field_id").reset_index(drop=True).equals(stored_sample[["current_field_id", "is_winter_rapeseed"]].sort_values("current_field_id").reset_index(drop=True)):
            raise RuntimeError("Stored blind labels differ from independently reopened ground truth")
        recomputed_results, recomputed_confusion = evaluate_predictions(predictions, sample)
        stored_results = pd.read_csv(out / "blind_benchmark_main.csv")
        stored_confusion = pd.read_csv(out / "blind_confusion_matrices.csv")
        compare_frames(recomputed_results, stored_results, ["cutoff_date", "model_arm"])
        compare_frames(recomputed_confusion, stored_confusion, ["cutoff_date", "model_arm", "threshold"])

        qa = json.loads((out / "blind_benchmark_qa.json").read_text(encoding="utf-8"))
        scope = qa.get("scope", {})
        if qa.get("status") != "PASS" or qa.get("ground_truth_opened_after_lock") is not True or qa.get("model_feature_calibration_threshold_tuning_after_unblind") is not False:
            raise RuntimeError("Blind benchmark process-integrity declaration is invalid")
        if any(scope.get(key) is not False for key in ["model_retuning", "threshold_retuning", "sentinel1", "full_skane_prediction", "web", "deployment", "tag", "merge"]):
            raise RuntimeError("Blind benchmark crossed a later-phase boundary")

        print("=" * 88)
        print("RAPSKARTAN SKANE V1 STOPPUNKT D BLIND VERIFIER: PASS")
        print("=" * 88)
        print(f"Prediction lock: {lock['critical_prediction_sha256']}")
        print(f"Population: {inventory['fields']:,} fields / {inventory['winter_rapeseed_fields']:,} raps")
        print(f"Blind sample: {len(sample):,} fields / {int(sample['is_winter_rapeseed'].sum()):,} raps")
        print("Frozen predictions independently recomputed: PASS")
        print("Ground truth independently reopened/joined: PASS")
        print("All 27 arm/cutoff benchmark rows and confusion matrices: PASS")
        final = stored_results[stored_results["cutoff_date"] == stored_results["cutoff_date"].max()]
        for row in final.itertuples(index=False):
            precision = "–" if pd.isna(row.empirical_precision_at_frozen_p95) else f"{row.empirical_precision_at_frozen_p95:.3f}"
            recall = "–" if pd.isna(row.recall_at_frozen_p95) else f"{row.recall_at_frozen_p95:.3f}"
            print(f"10 June {row.model_arm}: PR-AUC {row.pr_auc_usable:.3f} · frozen-P95 precision/recall {precision}/{recall}")
        print("Model/feature/calibration/threshold tuning after unblind: NO")
        print("Full Skåne prediction, web, Sentinel-1, deployment, tag and merge: NO")
        print("STOPPUNKT D")
        return 0
    except Exception as exc:
        traceback.print_exc()
        print(f"RAPSKARTAN STOPPUNKT D BLIND VERIFIER: FAIL — {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
