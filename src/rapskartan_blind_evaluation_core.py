#!/usr/bin/env python3
"""Post-lock ground-truth and evaluation helpers for Rapskartan STOPPUNKT D."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, f1_score, precision_score, recall_score, roc_auc_score

from rapskartan_model_training import expected_calibration_error, reliability_bins, weighted_brier
from rapskartan_s2_pilot_core import artifact_records, sha256_file


LABEL_COLUMNS = {
    "is_winter_rapeseed", "dominant_crop_name", "dominant_crop_code_raw",
    "dominant_crop_subcategory_raw", "crop_group", "official_crop_name",
    "crop_code_raw", "crop_subcategory_raw", "grdkod_mar", "grdkod_und",
}


def verify_locked_artifacts(root: Path, lock: dict[str, Any]) -> None:
    for record in lock.get("artifacts", []):
        path = root / record["path"]
        if not path.is_file() or path.stat().st_size != int(record["bytes"]) or sha256_file(path) != record["sha256"]:
            raise RuntimeError(f"Prediction-lock artifact mismatch: {record['path']}")


def open_prediction_lock(output_dir: Path, repository_root: Path) -> dict[str, Any]:
    path = output_dir / "prediction_lock_manifest.json"
    if not path.is_file():
        raise RuntimeError("GROUND_TRUTH_GATE: prediction_lock_manifest.json is missing")
    lock = json.loads(path.read_text(encoding="utf-8"))
    if lock.get("status") != "PREDICTIONS_HASH_LOCKED" or lock.get("labels_opened") is not False:
        raise RuntimeError("GROUND_TRUTH_GATE: predictions are not cleanly hash-locked before labels")
    verify_locked_artifacts(output_dir, lock)
    predictions = output_dir / "blind_predictions_locked.csv"
    if sha256_file(predictions) != lock.get("critical_prediction_sha256"):
        raise RuntimeError("GROUND_TRUTH_GATE: critical prediction hash mismatch")
    for record in lock.get("code_hashes", []):
        code = repository_root / record["path"]
        if not code.is_file() or sha256_file(code) != record["sha256"]:
            raise RuntimeError(f"GROUND_TRUTH_GATE: prediction code changed after lock: {record['path']}")
    for filename in ("blind_field_selection.csv", "blind_prior_features.csv", "blind_temporal_features.csv", "blind_predictions_locked.csv"):
        columns = set(pd.read_csv(output_dir / filename, nrows=0).columns)
        leaked = sorted(columns & LABEL_COLUMNS)
        if leaked:
            raise RuntimeError(f"GROUND_TRUTH_GATE: {filename} contains label columns {leaked}")
    return lock


def load_ground_truth(path: Path, contract: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    expected = contract["ground_truth"]
    if not path.is_file() or sha256_file(path) != expected["expected_sha256"]:
        raise RuntimeError("Frozen 2025 ground-truth file/hash mismatch")
    columns = [
        "current_field_id", "history_year", "current_area_m2", "dominant_crop_code_raw",
        "dominant_crop_subcategory_raw", "dominant_crop_name", "status",
    ]
    frame = pd.read_csv(path, usecols=columns, low_memory=False, dtype={"current_field_id": str})
    frame = frame[pd.to_numeric(frame["history_year"], errors="raise").astype(int) == 2025].copy()
    if len(frame) != int(expected["expected_2025_fields"]) or not frame["current_field_id"].is_unique:
        raise RuntimeError("2025 ground truth does not contain the frozen unique field population")
    frame["is_winter_rapeseed"] = frame["dominant_crop_name"].eq(expected["positive_name"]).astype(int)
    positives = frame[frame["is_winter_rapeseed"] == 1]
    if len(positives) != int(expected["expected_2025_winter_rapeseed_fields"]):
        raise RuntimeError("Frozen 2025 winter-rapeseed field count changed")
    area = float(pd.to_numeric(positives["current_area_m2"], errors="raise").sum() / 10_000.0)
    if not np.isclose(area, float(expected["expected_2025_winter_rapeseed_area_ha"]), rtol=0, atol=1e-5):
        raise RuntimeError("Frozen 2025 winter-rapeseed area changed")
    codes = set(pd.to_numeric(positives["dominant_crop_code_raw"], errors="raise").astype(int))
    if codes != {20} or positives["dominant_crop_subcategory_raw"].notna().any():
        raise RuntimeError("Frozen 2025 positive crop-code path changed")
    inventory = {
        "schema_version": "rapskartan-2025-ground-truth-inventory-v1", "status": "PASS",
        "source_path": str(path.resolve()), "source_sha256": sha256_file(path),
        "fields": len(frame), "winter_rapeseed_fields": len(positives),
        "winter_rapeseed_area_ha": area, "positive_code_path": "20/<NULL>",
        "opened_after_prediction_lock": True,
    }
    return frame, inventory


def join_sample_ground_truth(selection: pd.DataFrame, truth: pd.DataFrame, minimum_positives: int) -> pd.DataFrame:
    keep = [
        "current_field_id", "current_area_m2", "dominant_crop_code_raw",
        "dominant_crop_subcategory_raw", "dominant_crop_name", "status", "is_winter_rapeseed",
    ]
    joined = selection.merge(truth[keep], on="current_field_id", how="left", validate="one_to_one")
    if len(joined) != len(selection) or joined["is_winter_rapeseed"].isna().any():
        raise RuntimeError("Blind sample ground-truth join is incomplete")
    joined["is_winter_rapeseed"] = joined["is_winter_rapeseed"].astype(int)
    if int(joined["is_winter_rapeseed"].sum()) < int(minimum_positives):
        raise RuntimeError("Blind sample contains too few positive fields for the frozen benchmark")
    return joined


def _safe_ratio(numerator: float, denominator: float) -> float | None:
    return float(numerator / denominator) if denominator > 0 else None


def _decision_counts(y: np.ndarray, decision: np.ndarray, weights: np.ndarray) -> dict[str, float]:
    return {
        "tp": float(weights[(decision) & (y == 1)].sum()),
        "fp": float(weights[(decision) & (y == 0)].sum()),
        "tn": float(weights[(~decision) & (y == 0)].sum()),
        "fn": float(weights[(~decision) & (y == 1)].sum()),
    }


def evaluate_predictions(predictions: pd.DataFrame, sample_truth: pd.DataFrame, bins: int = 10) -> tuple[pd.DataFrame, pd.DataFrame]:
    labels = sample_truth[["current_field_id", "is_winter_rapeseed"]].copy()
    frame = predictions.merge(labels, on="current_field_id", validate="many_to_one")
    frame["area_population_weight"] = pd.to_numeric(frame["area_ha"], errors="raise") * pd.to_numeric(frame["population_weight"], errors="raise")
    results, confusion = [], []
    for (cutoff, arm), group in frame.groupby(["cutoff_date", "model_arm"], sort=True):
        y = group["is_winter_rapeseed"].to_numpy(dtype=int)
        weight = group["population_weight"].to_numpy(dtype=float)
        area_weight = group["area_population_weight"].to_numpy(dtype=float)
        probability = pd.to_numeric(group["calibrated_probability"], errors="coerce").to_numpy(dtype=float)
        usable = np.isfinite(probability)
        decision = usable & (probability >= 0.5)
        counts = _decision_counts(y, decision, weight)
        area_counts = _decision_counts(y, decision, area_weight)
        usable_y, usable_p, usable_w = y[usable], probability[usable], weight[usable]
        pr_auc = float(average_precision_score(usable_y, usable_p, sample_weight=usable_w)) if usable.any() and len(np.unique(usable_y)) == 2 else None
        roc_auc = float(roc_auc_score(usable_y, usable_p, sample_weight=usable_w)) if usable.any() and len(np.unique(usable_y)) == 2 else None
        p95_available = bool(group["frozen_p95_available"].iloc[0])
        p95_decision = group["predicted_at_frozen_p95"].astype(bool).to_numpy() if p95_available else np.zeros(len(group), dtype=bool)
        p95 = _decision_counts(y, p95_decision, weight)
        p90_available = bool(group["frozen_p90_available"].iloc[0])
        p90_decision = group["predicted_at_frozen_p90"].astype(bool).to_numpy() if p90_available else np.zeros(len(group), dtype=bool)
        p90 = _decision_counts(y, p90_decision, weight)
        record = {
            "cutoff_date": cutoff, "model_arm": arm, "sample_fields": len(group),
            "sample_positive_fields": int(y.sum()), "weighted_fields": float(weight.sum()),
            "weighted_positive_fields": float(weight[y == 1].sum()),
            "usable_fields": int(usable.sum()), "no_data_fields": int((~usable).sum()),
            "weighted_no_data_fields": float(weight[~usable].sum()),
            "positive_no_data_fields": int(((~usable) & (y == 1)).sum()),
            "precision_at_0_5": _safe_ratio(counts["tp"], counts["tp"] + counts["fp"]),
            "recall_at_0_5": _safe_ratio(counts["tp"], counts["tp"] + counts["fn"]),
            "f1_at_0_5": float(f1_score(y, decision, sample_weight=weight, zero_division=0)),
            "pr_auc_usable": pr_auc, "roc_auc_usable": roc_auc,
            "brier_usable": weighted_brier(usable_y, usable_p, usable_w) if usable.any() else None,
            "ece_usable": expected_calibration_error(usable_y, usable_p, usable_w, bins=bins) if usable.any() else None,
            "area_precision_at_0_5": _safe_ratio(area_counts["tp"], area_counts["tp"] + area_counts["fp"]),
            "area_recall_at_0_5": _safe_ratio(area_counts["tp"], area_counts["tp"] + area_counts["fn"]),
            "frozen_p95_available": p95_available,
            "frozen_p95_threshold": float(group["frozen_p95_threshold"].iloc[0]),
            "empirical_precision_at_frozen_p95": _safe_ratio(p95["tp"], p95["tp"] + p95["fp"]),
            "recall_at_frozen_p95": _safe_ratio(p95["tp"], p95["tp"] + p95["fn"]),
            "weighted_predicted_at_frozen_p95": p95["tp"] + p95["fp"],
            "frozen_p90_available": p90_available,
            "frozen_p90_threshold": float(group["frozen_p90_threshold"].iloc[0]),
            "empirical_precision_at_frozen_p90": _safe_ratio(p90["tp"], p90["tp"] + p90["fp"]),
            "recall_at_frozen_p90": _safe_ratio(p90["tp"], p90["tp"] + p90["fn"]),
            "weighted_predicted_at_frozen_p90": p90["tp"] + p90["fp"],
        }
        for value in (0.5, 0.8, 0.9, 0.95):
            key = f"predicted_at_{str(value).replace('.', '_')}"
            fixed = group[key].astype(bool).to_numpy()
            record[f"weighted_fields_p_ge_{str(value).replace('.', '_')}"] = float(weight[fixed].sum())
        results.append(record)
        for threshold_name, vector in (("0.5", decision), ("FROZEN_P95", p95_decision), ("FROZEN_P90", p90_decision)):
            sample_counts = _decision_counts(y, vector, np.ones(len(group)))
            weighted_counts = _decision_counts(y, vector, weight)
            confusion.append({"cutoff_date": cutoff, "model_arm": arm, "threshold": threshold_name, **{f"sample_{k}": int(v) for k, v in sample_counts.items()}, **{f"weighted_{k}": v for k, v in weighted_counts.items()}})
    return pd.DataFrame(results).sort_values(["cutoff_date", "model_arm"], kind="mergesort").reset_index(drop=True), pd.DataFrame(confusion).sort_values(["cutoff_date", "model_arm", "threshold"], kind="mergesort").reset_index(drop=True)


def data_quality_breakdown(predictions: pd.DataFrame, sample_truth: pd.DataFrame) -> pd.DataFrame:
    labels = sample_truth[["current_field_id", "is_winter_rapeseed"]]
    frame = predictions[predictions["model_arm"] == "SATELLITE_ONLY"].merge(labels, on="current_field_id", validate="many_to_one")
    frame["weighted_positive"] = frame["population_weight"] * frame["is_winter_rapeseed"]
    return frame.groupby(["cutoff_date", "data_quality_status"], sort=True).agg(
        sample_fields=("current_field_id", "size"), weighted_fields=("population_weight", "sum"),
        sample_positive_fields=("is_winter_rapeseed", "sum"), weighted_positive_fields=("weighted_positive", "sum"),
        median_days_since_last_obs=("days_since_last_obs", "median"),
        median_valid_obs_count=("valid_obs_count", "median"),
        median_valid_pixel_fraction=("mean_valid_pixel_fraction", "median"),
    ).reset_index()


def municipality_breakdown(predictions: pd.DataFrame, sample_truth: pd.DataFrame) -> pd.DataFrame:
    final = predictions["cutoff_date"].max()
    frame = predictions[predictions["cutoff_date"] == final].merge(sample_truth[["current_field_id", "is_winter_rapeseed"]], on="current_field_id", validate="many_to_one")
    rows = []
    for (code, arm), group in frame.groupby(["municipality_code", "model_arm"], sort=True):
        y = group["is_winter_rapeseed"].to_numpy(dtype=int)
        w = group["population_weight"].to_numpy(dtype=float)
        p = pd.to_numeric(group["calibrated_probability"], errors="coerce").to_numpy(dtype=float)
        usable = np.isfinite(p)
        decision = usable & (p >= 0.5)
        p95 = group["predicted_at_frozen_p95"].astype(bool).to_numpy()
        c05 = _decision_counts(y, decision, w)
        c95 = _decision_counts(y, p95, w)
        rows.append({
            "municipality_code": str(code), "cutoff_date": final, "model_arm": arm,
            "sample_fields": len(group), "sample_positive_fields": int(y.sum()), "no_data_fields": int((~usable).sum()),
            "precision_at_0_5": _safe_ratio(c05["tp"], c05["tp"] + c05["fp"]),
            "recall_at_0_5": _safe_ratio(c05["tp"], c05["tp"] + c05["fn"]),
            "empirical_precision_at_frozen_p95": _safe_ratio(c95["tp"], c95["tp"] + c95["fp"]),
            "recall_at_frozen_p95": _safe_ratio(c95["tp"], c95["tp"] + c95["fn"]),
        })
    return pd.DataFrame(rows)


def final_reliability(predictions: pd.DataFrame, sample_truth: pd.DataFrame, bins: int = 10) -> pd.DataFrame:
    final = predictions["cutoff_date"].max()
    frame = predictions[predictions["cutoff_date"] == final].merge(sample_truth[["current_field_id", "is_winter_rapeseed"]], on="current_field_id", validate="many_to_one")
    rows = []
    for arm, group in frame.groupby("model_arm", sort=True):
        usable = group["calibrated_probability"].notna()
        for row in reliability_bins(group.loc[usable, "is_winter_rapeseed"].to_numpy(dtype=int), group.loc[usable, "calibrated_probability"].to_numpy(dtype=float), group.loc[usable, "population_weight"].to_numpy(dtype=float), bins=bins):
            rows.append({"cutoff_date": final, "model_arm": arm, **row})
    return pd.DataFrame(rows)


def evaluation_artifacts(root: Path, relatives: Iterable[str]) -> list[dict[str, Any]]:
    return artifact_records(root, relatives)
