#!/usr/bin/env python3
"""Train, calibrate and freeze the pre-blind Rapskartan model candidate."""
from __future__ import annotations

import argparse
import json
import time
import traceback
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from rapskartan_model_core import (
    FORBIDDEN_YEAR, artifact_records, load_model_contract, model_contract_sha256,
    sha256_file, temporal_feature_columns, utc_now, write_dataframe, write_json,
)
from rapskartan_model_training import (
    arm_families, arm_feature_columns, crossfit_calibration, fit_calibrator,
    fit_estimator, group_oof_predictions, make_estimator, probability_metrics,
    reliability_bins, selection_key, year_oof_predictions,
)
from rapskartan_v1_discovery_core import FEATURE_BRANCH, UPSTREAM_COMMIT, UPSTREAM_TAG, repository_snapshot


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = Path(r"C:\AkerSyncRepo\work\rapskartan_skane_v1_model_stopC")
MODEL_VERSION = "rapskartan-model-v1-preblind-rc1"


def load_verified_dataset(out: Path) -> tuple[dict[str, Any], dict[str, pd.DataFrame]]:
    manifest_path = out / "development_dataset_manifest.json"
    if not manifest_path.exists():
        raise RuntimeError(f"Development dataset manifest is missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "PASS" or manifest.get("scope", {}).get("target_year_2025_labels_accessed") is not False:
        raise RuntimeError("Development dataset is not a leakage-safe PASS")
    for record in manifest.get("artifacts", []):
        path = out / record["path"]
        if not path.is_file() or path.stat().st_size != int(record["bytes"]) or sha256_file(path) != record["sha256"]:
            raise RuntimeError(f"Development dataset artifact mismatch: {record['path']}")
    frames = {
        "selection": pd.read_csv(out / "development_field_selection.csv", dtype={"development_field_id": str, "municipality_code": str}),
        "labels": pd.read_csv(out / "development_labels.csv", dtype={"development_field_id": str}),
        "prior": pd.read_csv(out / "development_prior_features.csv", dtype={"development_field_id": str, "municipality_code": str}),
        "temporal": pd.read_csv(out / "development_temporal_features.csv", dtype={"development_field_id": str, "municipality_code": str}),
    }
    for name, frame in frames.items():
        if "target_year" in frame and (pd.to_numeric(frame["target_year"], errors="raise") >= FORBIDDEN_YEAR).any():
            raise RuntimeError(f"BLIND_GUARD: {name} contains target year 2025")
    return manifest, frames


def joined_base(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    selection = frames["selection"]
    labels = frames["labels"]
    prior = frames["prior"]
    base = selection.merge(labels, on=["development_field_id", "target_year", "area_ha"], validate="one_to_one")
    base = base.merge(prior, on=["development_field_id", "target_year", "municipality_code"], validate="one_to_one")
    if len(base) != len(selection) or base["is_winter_rapeseed"].isna().any():
        raise RuntimeError("Development labels/prior join is incomplete")
    base["area_population_weight"] = pd.to_numeric(base["population_weight"], errors="raise") * pd.to_numeric(base["area_ha"], errors="raise")
    return base


def frame_for_arm(base: pd.DataFrame, temporal: pd.DataFrame, arm: str, cutoff_month_day: str) -> pd.DataFrame:
    if arm == "PRIOR_ONLY":
        result = base.copy()
        result["cutoff_date"] = result["target_year"].astype(str) + "-" + cutoff_month_day
        result["data_quality_status"] = "PRIOR_AVAILABLE"
        return result.reset_index(drop=True)
    satellite = temporal[temporal["cutoff_date"].astype(str).str[5:] == cutoff_month_day].copy()
    satellite = satellite[satellite["data_quality_status"] == "USABLE"]
    result = base.merge(
        satellite, on=["development_field_id", "target_year", "municipality_code", "geographic_fold"],
        validate="one_to_one", suffixes=("", "_sat"),
    )
    if result.empty:
        raise RuntimeError(f"{arm} {cutoff}: no usable satellite rows")
    return result.reset_index(drop=True)


def flat_metric_record(prefix: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        **prefix,
        **{key: value for key, value in metrics.items() if not isinstance(value, dict)},
        "threshold_95": metrics["threshold_at_95_precision"]["threshold"],
        "threshold_95_available": metrics["threshold_at_95_precision"]["available"],
        "threshold_90": metrics["threshold_at_90_precision"]["threshold"],
        "threshold_90_available": metrics["threshold_at_90_precision"]["available"],
    }


def reliability_plot(path: Path, rows: list[dict[str, Any]], title: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    frame = pd.DataFrame(rows)
    usable = frame.dropna(subset=["mean_probability", "observed_fraction"])
    fig, axis = plt.subplots(figsize=(5.4, 5.0), dpi=130)
    axis.plot([0, 1], [0, 1], linestyle="--", color="#718096", linewidth=1)
    if not usable.empty:
        sizes = np.clip(usable["weighted_fields"].to_numpy(dtype=float), 5, None)
        sizes = 30 + 120 * sizes / sizes.max()
        axis.scatter(usable["mean_probability"], usable["observed_fraction"], s=sizes, color="#d69e2e", edgecolor="#744210")
    axis.set(xlim=(0, 1), ylim=(0, 1), xlabel="Mean calibrated P(raps)", ylabel="Observed raps fraction", title=title)
    axis.grid(alpha=0.2)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, format="png", metadata={"Software": "AkerSync deterministic QA"})
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    started = time.monotonic()
    out = args.output_dir.resolve()
    (out / "logs").mkdir(parents=True, exist_ok=True)
    (out / "models").mkdir(parents=True, exist_ok=True)
    (out / "qa").mkdir(parents=True, exist_ok=True)
    (out / "logs" / "model_traceback.log").unlink(missing_ok=True)

    try:
        print("[MODEL] Verifying leakage-safe development dataset...", flush=True)
        dataset_manifest, frames = load_verified_dataset(out)
        contract = load_model_contract(ROOT)
        snapshot = repository_snapshot(ROOT)
        if snapshot["branch"] != FEATURE_BRANCH or not snapshot["working_tree_clean"]:
            raise RuntimeError("Model training requires the clean Rapskartan feature branch")
        base = joined_base(frames)
        temporal = frames["temporal"]
        prior_columns = list(contract["prior"]["features"])
        satellite_columns = temporal_feature_columns(contract)
        missing_prior = sorted(set(prior_columns) - set(base.columns))
        missing_satellite = sorted(set(satellite_columns) - set(temporal.columns))
        if missing_prior or missing_satellite:
            raise RuntimeError(f"Feature contract mismatch: prior={missing_prior}, satellite={missing_satellite}")

        candidate_rows: list[dict[str, Any]] = []
        year_rows: list[dict[str, Any]] = []
        oof_rows: list[pd.DataFrame] = []
        selected_models: list[dict[str, Any]] = []
        calibration_records: list[dict[str, Any]] = []
        threshold_records: list[dict[str, Any]] = []
        model_paths: list[str] = []
        print("[MODEL] Running whole-year OOF baselines, cross-fitted calibration and deterministic selection...", flush=True)
        for cutoff_month_day in contract["temporal"]["cutoff_month_days"]:
            cutoff_label = cutoff_month_day
            for arm in contract["model"]["arms"]:
                frame = frame_for_arm(base, temporal, arm, cutoff_label)
                features = arm_feature_columns(arm, prior_columns, satellite_columns)
                best: dict[str, Any] | None = None
                for family in arm_families(arm):
                    raw_oof = year_oof_predictions(frame, features, family, contract)
                    for calibration_method in contract["model"]["calibration_candidates"]:
                        calibrated = crossfit_calibration(raw_oof, frame, calibration_method, "target_year", contract)
                        metrics = probability_metrics(
                            frame["is_winter_rapeseed"].to_numpy(dtype=int), calibrated,
                            frame["population_weight"].to_numpy(dtype=float),
                            frame["area_population_weight"].to_numpy(dtype=float),
                            bins=int(contract["model"]["calibration_bins"]),
                        )
                        prefix = {"cutoff_month_day": cutoff_label, "model_arm": arm, "model_family": family, "calibration": calibration_method}
                        candidate_rows.append(flat_metric_record(prefix, metrics))
                        for year in sorted(frame["target_year"].astype(int).unique()):
                            mask = frame["target_year"].astype(int).to_numpy() == year
                            fold_metrics = probability_metrics(
                                frame.loc[mask, "is_winter_rapeseed"].to_numpy(dtype=int), calibrated[mask],
                                frame.loc[mask, "population_weight"].to_numpy(dtype=float),
                                frame.loc[mask, "area_population_weight"].to_numpy(dtype=float),
                                bins=int(contract["model"]["calibration_bins"]),
                            )
                            year_rows.append(flat_metric_record({**prefix, "heldout_year": int(year)}, fold_metrics))
                        choice = {
                            "family": family, "calibration": calibration_method, "raw_oof": raw_oof,
                            "calibrated_oof": calibrated, "metrics": metrics, "frame": frame, "features": features,
                        }
                        if best is None or selection_key(metrics, family, calibration_method) > selection_key(best["metrics"], best["family"], best["calibration"]):
                            best = choice
                if best is None:
                    raise RuntimeError(f"No model candidate for {arm} {cutoff_label}")
                frame = best["frame"]
                estimator = make_estimator(best["family"], contract, seed_offset=900)
                fit_estimator(
                    estimator, best["family"], frame[best["features"]],
                    frame["is_winter_rapeseed"].to_numpy(dtype=int), frame["population_weight"].to_numpy(dtype=float),
                )
                calibrator = fit_calibrator(
                    best["calibration"], best["raw_oof"], frame["is_winter_rapeseed"].to_numpy(dtype=int),
                    frame["population_weight"].to_numpy(dtype=float), int(contract["model"]["random_seed"]) + 901,
                )
                bundle = {
                    "schema_version": "rapskartan-frozen-model-bundle-v1", "model_version": MODEL_VERSION,
                    "model_arm": arm, "cutoff_month_day": cutoff_label,
                    "model_family": best["family"], "calibration_method": best["calibration"],
                    "feature_columns": best["features"], "training_years": list(contract["development_years"]),
                    "estimator": estimator, "calibrator": calibrator,
                }
                relative = f"models/{arm.lower()}_{cutoff_label.replace('-', '')}.joblib"
                joblib.dump(bundle, out / relative, compress=3)
                model_paths.append(relative)
                threshold_records.append({
                    "model_arm": arm, "cutoff_month_day": cutoff_label,
                    "precision_95": best["metrics"]["threshold_at_95_precision"],
                    "precision_90": best["metrics"]["threshold_at_90_precision"],
                    "fixed_probability_thresholds": list(contract["model"]["probability_thresholds"]),
                    "source": "cross-fitted whole-year OOF development predictions",
                })
                calibration_records.append({
                    "model_arm": arm, "cutoff_month_day": cutoff_label,
                    "method": best["calibration"], "base_family": best["family"],
                    "brier": best["metrics"]["brier"], "ece": best["metrics"]["ece"],
                    "fit_source": "all pre-2025 whole-year OOF raw predictions",
                    "selection_source": "cross-fitted calibration by held-out development year",
                })
                selected_models.append({
                    "model_arm": arm, "cutoff_month_day": cutoff_label,
                    "model_family": best["family"], "calibration": best["calibration"],
                    "feature_count": len(best["features"]), "training_rows": len(frame),
                    "usable_years": sorted(frame["target_year"].astype(int).unique().tolist()),
                    "model_path": relative, "metrics": best["metrics"],
                })
                evaluation = frame[["development_field_id", "target_year", "municipality_code", "geographic_fold", "is_winter_rapeseed", "population_weight", "area_population_weight"]].copy()
                evaluation["cutoff_month_day"] = cutoff_label
                evaluation["model_arm"] = arm
                evaluation["model_family"] = best["family"]
                evaluation["calibration"] = best["calibration"]
                evaluation["raw_probability_oof"] = best["raw_oof"]
                evaluation["calibrated_probability_oof"] = best["calibrated_oof"]
                oof_rows.append(evaluation)
                print(f"[MODEL] {cutoff_label} {arm}: {best['family']} + {best['calibration']} · PR-AUC {best['metrics']['pr_auc']:.3f} · R@P95 {best['metrics']['recall_at_95_precision']:.3f}", flush=True)

        cv_by_cutoff = pd.DataFrame(candidate_rows).sort_values(
            ["cutoff_month_day", "model_arm", "model_family", "calibration"], kind="mergesort",
        ).reset_index(drop=True)
        cv_by_year = pd.DataFrame(year_rows).sort_values(
            ["cutoff_month_day", "model_arm", "model_family", "calibration", "heldout_year"], kind="mergesort",
        ).reset_index(drop=True)
        oof = pd.concat(oof_rows, ignore_index=True).sort_values(
            ["cutoff_month_day", "model_arm", "target_year", "development_field_id"], kind="mergesort",
        ).reset_index(drop=True)
        write_dataframe(out / "development_cv_by_cutoff.csv", cv_by_cutoff)
        write_dataframe(out / "development_cv_by_year.csv", cv_by_year)
        write_dataframe(out / "development_oof_predictions.csv", oof)

        print("[MODEL] Running municipality-group robustness at the final cutoff...", flush=True)
        geo_rows = []
        final_label = contract["temporal"]["cutoff_month_days"][-1]
        for selected in [item for item in selected_models if item["cutoff_month_day"] == final_label]:
            arm = selected["model_arm"]
            frame = frame_for_arm(base, temporal, arm, final_label)
            features = arm_feature_columns(arm, prior_columns, satellite_columns)
            raw_geo = group_oof_predictions(frame, features, selected["model_family"], "geographic_fold", contract)
            calibrated_geo = crossfit_calibration(raw_geo, frame, selected["calibration"], "geographic_fold", contract)
            for fold in sorted(frame["geographic_fold"].unique()):
                mask = frame["geographic_fold"].to_numpy() == fold
                metrics = probability_metrics(
                    frame.loc[mask, "is_winter_rapeseed"].to_numpy(dtype=int), calibrated_geo[mask],
                    frame.loc[mask, "population_weight"].to_numpy(dtype=float),
                    frame.loc[mask, "area_population_weight"].to_numpy(dtype=float),
                    bins=int(contract["model"]["calibration_bins"]),
                )
                geo_rows.append(flat_metric_record({
                    "model_arm": arm, "cutoff_month_day": final_label,
                    "model_family": selected["model_family"], "calibration": selected["calibration"],
                    "heldout_geographic_fold": int(fold),
                }, metrics))
        write_dataframe(out / "development_geographic_robustness.csv", pd.DataFrame(geo_rows))

        print("[MODEL] Writing calibration QA and immutable pre-blind contracts...", flush=True)
        reliability_paths = []
        reliability_records = []
        for arm in contract["model"]["arms"]:
            frame = oof[(oof["model_arm"] == arm) & (oof["cutoff_month_day"] == final_label)]
            bins = reliability_bins(
                frame["is_winter_rapeseed"].to_numpy(dtype=int), frame["calibrated_probability_oof"].to_numpy(dtype=float),
                frame["population_weight"].to_numpy(dtype=float), bins=int(contract["model"]["calibration_bins"]),
            )
            for row in bins:
                reliability_records.append({"model_arm": arm, "cutoff_month_day": final_label, **row})
            relative = f"qa/reliability_{arm.lower()}_{final_label.replace('-', '')}.png"
            reliability_plot(out / relative, bins, f"{arm} · cutoff {final_label} · development OOF")
            reliability_paths.append(relative)
        write_dataframe(out / "development_reliability_bins.csv", pd.DataFrame(reliability_records))

        feature_contract = {
            "schema_version": "rapskartan-feature-contract-v1", "model_version": MODEL_VERSION,
            "development_years": list(contract["development_years"]), "forbidden_target_year": FORBIDDEN_YEAR,
            "cutoff_month_days": list(contract["temporal"]["cutoff_month_days"]),
            "causal_rule": contract["temporal"]["causal_rule"],
            "sentinel2": contract["sentinel2"], "cloud_mask": contract["cloud_mask"],
            "prior_features": prior_columns, "satellite_features": satellite_columns,
            "no_data_rule": "Satellite and combined arms emit NO_DATA when fewer than two usable observations exist; no-data is never negative class.",
            "target_label_excluded_from_features": True,
        }
        write_json(out / "feature_contract_v1.json", feature_contract)
        write_json(out / "threshold_contract_v1.json", {
            "schema_version": "rapskartan-threshold-contract-v1", "model_version": MODEL_VERSION,
            "selection_years": list(contract["development_years"]), "blind_year_used": False,
            "records": threshold_records,
        })
        write_json(out / "calibration_contract_v1.json", {
            "schema_version": "rapskartan-calibration-contract-v1", "model_version": MODEL_VERSION,
            "selection_years": list(contract["development_years"]), "blind_year_used": False,
            "cross_fit_group": "target_year", "records": calibration_records,
        })
        write_json(out / "development_cv_results.json", {
            "schema_version": "rapskartan-development-cv-results-v1", "status": "PASS",
            "model_version": MODEL_VERSION, "development_years": list(contract["development_years"]),
            "primary_split": "whole target year held out", "calibration_split": "held-out target year within base-model OOF predictions",
            "geographic_robustness": "five deterministic municipality groups at final cutoff",
            "selected_models": selected_models,
        })

        code_paths = [
            "config/rapskartan_model_development_v1.json", "src/rapskartan_model_core.py",
            "src/rapskartan_model_training.py", "src/94_build_rapskartan_model_dataset.py",
            "src/95_train_rapskartan_models.py",
        ]
        code_hashes = [{"path": path, "sha256": sha256_file(ROOT / path)} for path in code_paths]
        input_hashes = {
            "development_dataset_manifest.json": sha256_file(out / "development_dataset_manifest.json"),
            "model_development_contract.json": sha256_file(out / "model_development_contract.json"),
            "development_field_selection.csv": sha256_file(out / "development_field_selection.csv"),
            "development_labels.csv": sha256_file(out / "development_labels.csv"),
            "development_prior_features.csv": sha256_file(out / "development_prior_features.csv"),
            "development_temporal_features.csv": sha256_file(out / "development_temporal_features.csv"),
        }
        model_contract = {
            "schema_version": "rapskartan-model-contract-v1", "status": "PRE_BLIND_FROZEN_CANDIDATE",
            "model_version": MODEL_VERSION, "created_at_utc": utc_now(),
            "feature_branch": FEATURE_BRANCH, "feature_head": snapshot["head"], "feature_tree": snapshot["head_tree"],
            "upstream_tag": UPSTREAM_TAG, "upstream_commit": UPSTREAM_COMMIT,
            "development_years": list(contract["development_years"]), "blind_year_used": False,
            "selected_models": [{key: value for key, value in item.items() if key != "metrics"} for item in selected_models],
            "code_hashes": code_hashes, "input_hashes": input_hashes,
            "scope": {
                "model_development_pre_2025_only": True, "target_year_2025_labels_accessed": False,
                "blind_2025_predictions_created": False, "sentinel1": False, "full_skane": False,
                "web": False, "deployment": False, "tag": False, "merge": False,
            },
        }
        write_json(out / "rapskartan_model_contract_v1.json", model_contract)

        contract_paths = [
            "rapskartan_model_contract_v1.json", "feature_contract_v1.json", "threshold_contract_v1.json",
            "calibration_contract_v1.json", "development_cv_results.json", "development_cv_by_cutoff.csv",
            "development_cv_by_year.csv", "development_geographic_robustness.csv",
            "development_reliability_bins.csv", "development_oof_predictions.csv", *model_paths, *reliability_paths,
        ]
        write_json(out / "model_artifacts_manifest.json", {
            "schema_version": "rapskartan-model-artifacts-manifest-v1", "status": "PASS",
            "model_version": MODEL_VERSION, "created_at_utc": utc_now(),
            "feature_head": snapshot["head"], "feature_tree": snapshot["head_tree"],
            "development_dataset_manifest_sha256": sha256_file(out / "development_dataset_manifest.json"),
            "model_development_contract_sha256": model_contract_sha256(ROOT),
            "artifacts": artifact_records(out, contract_paths),
            "scope": model_contract["scope"],
        })

        print("=" * 88)
        print("RAPSKARTAN SKANE V1 PRE-BLIND MODEL CANDIDATE: PASS")
        print("=" * 88)
        print(f"Models: {len(model_paths)} · arms: 3 · cutoffs: 9 · years: {contract['development_years']}")
        print(f"Year-held-out candidate rows: {len(cv_by_cutoff)} · geographic robustness rows: {len(geo_rows)}")
        print(f"Elapsed model time: {time.monotonic() - started:.1f} s")
        print("2025 labels/predictions, Sentinel-1, full Skåne, web and deployment: NO")
        print("Run the independent STOPPUNKT C verifier next.")
        return 0
    except Exception as exc:
        traceback.print_exc()
        (out / "logs" / "model_traceback.log").write_text(traceback.format_exc(), encoding="utf-8")
        print(f"RAPSKARTAN PRE-BLIND MODEL CANDIDATE: FAIL — {exc}")
        print("No 2025 blind prediction/evaluation or later phase ran.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
