#!/usr/bin/env python3
"""Open frozen 2025 labels only after prediction lock, then evaluate without tuning."""
from __future__ import annotations

import argparse
import json
import time
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

from rapskartan_blind_evaluation_core import (
    data_quality_breakdown, evaluate_predictions, evaluation_artifacts, final_reliability,
    join_sample_ground_truth, load_ground_truth, municipality_breakdown, open_prediction_lock,
)
from rapskartan_blind_prediction_core import load_blind_contract, sha256_file
from rapskartan_s2_pilot_core import utc_now, write_dataframe, write_json
from rapskartan_v1_discovery_core import FEATURE_BRANCH, repository_snapshot


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = Path(r"C:\AkerSyncRepo\work\rapskartan_skane_v1_blind_2025_stopD")


def json_records(frame: pd.DataFrame) -> list[dict]:
    clean = frame.astype(object).where(pd.notna(frame), None)
    return clean.to_dict("records")


def plot_main_metrics(path: Path, results: pd.DataFrame) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    labels = {"PRIOR_ONLY": "Historik", "SATELLITE_ONLY": "Sentinel-2", "PRIOR_PLUS_SATELLITE": "Sentinel-2 + historik"}
    colors = {"PRIOR_ONLY": "#718096", "SATELLITE_ONLY": "#d69e2e", "PRIOR_PLUS_SATELLITE": "#2f855a"}
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.2), dpi=140, sharex=True, sharey=True)
    for axis, metric, title in zip(axes, ["precision_at_0_5", "recall_at_0_5", "f1_at_0_5"], ["Precision", "Recall", "F1"]):
        for arm, group in results.groupby("model_arm", sort=True):
            axis.plot(pd.to_datetime(group["cutoff_date"]), group[metric], marker="o", label=labels[arm], color=colors[arm])
        axis.set_title(title); axis.set_ylim(0, 1); axis.grid(alpha=0.22); axis.tick_params(axis="x", rotation=45)
    axes[0].set_ylabel("Viktat blindtestmått vid P ≥ 0,5")
    axes[-1].legend(loc="best", fontsize=8)
    fig.suptitle("Rapskartan 2025 – frysta modeller, ingen efterjustering")
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, metadata={"Software": "AkerSync deterministic QA"})
    plt.close(fig)


def plot_frozen_p95(path: Path, results: pd.DataFrame) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    labels = {"PRIOR_ONLY": "Historik", "SATELLITE_ONLY": "Sentinel-2", "PRIOR_PLUS_SATELLITE": "Sentinel-2 + historik"}
    colors = {"PRIOR_ONLY": "#718096", "SATELLITE_ONLY": "#d69e2e", "PRIOR_PLUS_SATELLITE": "#2f855a"}
    fig, axis = plt.subplots(figsize=(8.4, 5.0), dpi=140)
    for arm, group in results.groupby("model_arm", sort=True):
        available = group["frozen_p95_available"].astype(bool) & group["empirical_precision_at_frozen_p95"].notna()
        shown = group[available]
        if not shown.empty:
            axis.plot(pd.to_datetime(shown["cutoff_date"]), shown["recall_at_frozen_p95"], marker="o", color=colors[arm], label=labels[arm])
            failed = shown[shown["empirical_precision_at_frozen_p95"] < 0.95]
            if not failed.empty:
                axis.scatter(pd.to_datetime(failed["cutoff_date"]), failed["recall_at_frozen_p95"], marker="x", s=70, color="#c53030", zorder=5)
    axis.set_ylim(0, 1); axis.grid(alpha=0.22)
    axis.set_xlabel("Informationscutoff"); axis.set_ylabel("Andel verkliga rapsfält identifierade")
    axis.set_title("Recall vid tröskel fryst för ≥95 % utvecklingsprecision\nRött kryss = empirisk blindprecision under 95 %")
    axis.tick_params(axis="x", rotation=45); axis.legend(loc="best")
    fig.tight_layout(); path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, metadata={"Software": "AkerSync deterministic QA"}); plt.close(fig)


def plot_reliability(path: Path, bins: pd.DataFrame, arm: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    frame = bins[(bins["model_arm"] == arm) & bins["mean_probability"].notna()]
    fig, axis = plt.subplots(figsize=(5.4, 5.0), dpi=140)
    axis.plot([0, 1], [0, 1], "--", color="#718096", linewidth=1)
    if not frame.empty:
        sizes = frame["weighted_fields"].to_numpy(dtype=float)
        sizes = 30 + 120 * sizes / max(1, sizes.max())
        axis.scatter(frame["mean_probability"], frame["observed_fraction"], s=sizes, color="#d69e2e", edgecolor="#744210")
    axis.set(xlim=(0, 1), ylim=(0, 1), xlabel="Genomsnittlig fryst P(raps)", ylabel="Observerad rapsandel", title=f"2025 blindkalibrering · {arm} · 10 juni")
    axis.grid(alpha=0.2); fig.tight_layout(); path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, metadata={"Software": "AkerSync deterministic QA"}); plt.close(fig)


def select_error_cases(predictions: pd.DataFrame, truth: pd.DataFrame, per_category: int = 25) -> pd.DataFrame:
    joined = predictions.merge(truth[["current_field_id", "is_winter_rapeseed"]], on="current_field_id", validate="many_to_one")
    final_date = joined["cutoff_date"].max()
    final = joined[(joined["cutoff_date"] == final_date) & (joined["model_arm"] == "PRIOR_PLUS_SATELLITE")].copy()
    final["probability"] = pd.to_numeric(final["calibrated_probability"], errors="coerce")
    final["decision"] = final["probability"].ge(0.5) & final["probability"].notna()
    pieces = []
    definitions = [
        ("TOP_CONFIDENT_TRUE_POSITIVE", final[(final.is_winter_rapeseed == 1) & final.decision], ["probability", "current_field_id"], [False, True]),
        ("TOP_CONFIDENT_FALSE_POSITIVE", final[(final.is_winter_rapeseed == 0) & final.decision], ["probability", "current_field_id"], [False, True]),
        ("TOP_CONFIDENT_FALSE_NEGATIVE", final[(final.is_winter_rapeseed == 1) & ~final.decision & final.probability.notna()], ["probability", "current_field_id"], [True, True]),
    ]
    for category, frame, columns, ascending in definitions:
        selected = frame.sort_values(columns, ascending=ascending, kind="mergesort").head(per_category).copy()
        selected["qa_category"] = category; pieces.append(selected)
    uncertain = final[final.probability.notna()].copy(); uncertain["distance_to_0_5"] = (uncertain.probability - 0.5).abs()
    uncertain = uncertain.sort_values(["distance_to_0_5", "current_field_id"], kind="mergesort").head(per_category); uncertain["qa_category"] = "UNCERTAIN_NEAR_0_5"; pieces.append(uncertain)
    early = joined[(joined["cutoff_date"] == joined["cutoff_date"].min()) & (joined["model_arm"] == "SATELLITE_ONLY") & joined["calibrated_probability"].isna()].copy()
    early["probability"] = np.nan; early = early.sort_values(["municipality_code", "current_field_id"], kind="mergesort").head(per_category); early["qa_category"] = "NO_DATA_EARLY"; pieces.append(early)
    keep = ["qa_category", "current_field_id", "municipality_code", "cutoff_date", "model_arm", "area_ha", "is_winter_rapeseed", "probability", "data_quality_status"]
    return pd.concat(pieces, ignore_index=True)[keep]


def write_error_geojson(path: Path, cases: pd.DataFrame, geometry_table: pd.DataFrame) -> None:
    import geopandas as gpd
    from shapely import wkb
    from shapely.geometry import mapping

    geometry = geometry_table.copy()
    geometry["geometry"] = geometry["geometry_wkb_hex"].map(lambda value: wkb.loads(bytes.fromhex(value)))
    geometry = gpd.GeoDataFrame(geometry.drop(columns="geometry_wkb_hex"), geometry="geometry", crs=3006).to_crs(4326)
    joined = geometry.merge(cases, on=["current_field_id", "municipality_code"], validate="one_to_many")
    features = []
    for row in joined.sort_values(["qa_category", "current_field_id"], kind="mergesort").itertuples(index=False):
        properties = {key: getattr(row, key) for key in ["qa_category", "current_field_id", "municipality_code", "cutoff_date", "model_arm", "area_ha", "is_winter_rapeseed", "probability", "data_quality_status"]}
        properties = {key: (None if pd.isna(value) else value.item() if hasattr(value, "item") else value) for key, value in properties.items()}
        features.append({"type": "Feature", "geometry": mapping(row.geometry), "properties": properties})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")


def write_report(path: Path, results: pd.DataFrame, inventory: dict, sample: pd.DataFrame, lock_sha: str) -> None:
    lines = [
        "# Rapskartan Skåne V1 – 2025 blind benchmark", "",
        "- Process integrity: `PASS`", "- Model/feature/calibration/threshold tuning after unblind: `NO`",
        f"- Prediction lock SHA256: `{lock_sha}`", f"- Frozen population: `{inventory['fields']:,}` fields; `{inventory['winter_rapeseed_fields']:,}` winter-rapeseed fields.",
        f"- Bounded blind sample: `{len(sample):,}` fields; `{int(sample['is_winter_rapeseed'].sum()):,}` observed winter-rapeseed fields.",
        "- PR-AUC/Brier/ECE use only fields with a probability. Recall treats no-data positives as not found.",
        "- `frozen P95` means a threshold selected before 2025; its empirical 2025 precision is reported separately.", "",
        "## Main results", "",
        "| cutoff | arm | precision@0.5 | recall@0.5 | F1@0.5 | PR-AUC usable | blind precision at frozen P95 | recall at frozen P95 | no-data |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    def fmt(value): return "–" if pd.isna(value) else f"{float(value):.3f}"
    for row in results.itertuples(index=False):
        lines.append(f"| {row.cutoff_date} | {row.model_arm} | {fmt(row.precision_at_0_5)} | {fmt(row.recall_at_0_5)} | {fmt(row.f1_at_0_5)} | {fmt(row.pr_auc_usable)} | {fmt(row.empirical_precision_at_frozen_p95)} | {fmt(row.recall_at_frozen_p95)} | {int(row.no_data_fields)} |")
    lines += ["", "## Scope", "", "No Sentinel-1, full-Skåne prediction export, web build, deployment, tag or merge was run. Any improvement idea belongs to a later version and cannot alter this V1 blind result."]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ground-truth-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    started = time.monotonic(); out = args.output_dir.resolve()
    (out / "logs").mkdir(parents=True, exist_ok=True); (out / "qa").mkdir(parents=True, exist_ok=True)
    (out / "logs" / "evaluation_traceback.log").unlink(missing_ok=True)
    try:
        print("[BLIND-EVAL] Re-verifying immutable prediction lock before opening any 2025 label...", flush=True)
        snapshot = repository_snapshot(ROOT)
        if snapshot["branch"] != FEATURE_BRANCH or not snapshot["working_tree_clean"]:
            raise RuntimeError(f"Blind evaluation requires clean branch {FEATURE_BRANCH}")
        contract = load_blind_contract(ROOT)
        lock = open_prediction_lock(out, ROOT)
        lock_sha = sha256_file(out / "prediction_lock_manifest.json")
        evaluation_started_at = utc_now()

        print("[BLIND-EVAL] PREDICTION LOCK VERIFIED — opening frozen 2025 ground truth now...", flush=True)
        truth_path = args.ground_truth_dir.resolve() / contract["ground_truth"]["relative_path"]
        truth, inventory = load_ground_truth(truth_path, contract)
        selection = pd.read_csv(out / "blind_field_selection.csv", dtype={"current_field_id": str, "development_field_id": str, "municipality_code": str})
        sample = join_sample_ground_truth(selection, truth, int(contract["resource_guards"]["minimum_joined_positive_sample_fields"]))
        write_dataframe(out / "blind_ground_truth_sample.csv", sample)
        write_json(out / "blind_ground_truth_inventory.json", inventory)

        print("[BLIND-EVAL] Computing the frozen benchmark, calibration and spatial/data-quality QA...", flush=True)
        predictions = pd.read_csv(out / "blind_predictions_locked.csv", dtype={"current_field_id": str, "development_field_id": str, "municipality_code": str})
        results, confusion = evaluate_predictions(predictions, sample)
        quality = data_quality_breakdown(predictions, sample)
        spatial = municipality_breakdown(predictions, sample)
        reliability = final_reliability(predictions, sample)
        write_dataframe(out / "blind_benchmark_main.csv", results)
        write_dataframe(out / "blind_confusion_matrices.csv", confusion)
        write_dataframe(out / "blind_data_quality_breakdown.csv", quality)
        write_dataframe(out / "blind_spatial_by_municipality.csv", spatial)
        write_dataframe(out / "blind_reliability_bins.csv", reliability)

        cases = select_error_cases(predictions, sample)
        write_dataframe(out / "blind_error_cases.csv", cases)
        geometry = pd.read_csv(out / "blind_selection_geometry_wkb.csv", dtype={"current_field_id": str, "municipality_code": str})
        write_error_geojson(out / "qa/blind_error_cases.geojson", cases, geometry)
        plot_main_metrics(out / "qa/blind_precision_recall_f1_by_date.png", results)
        plot_frozen_p95(out / "qa/blind_recall_at_frozen_p95_by_date.png", results)
        reliability_paths = []
        for arm in sorted(results["model_arm"].unique()):
            relative = f"qa/blind_reliability_{arm.lower()}_0610.png"
            plot_reliability(out / relative, reliability, arm); reliability_paths.append(relative)

        write_report(out / "blind_benchmark_qa.md", results, inventory, sample, lock_sha)
        warnings = []
        below = results[(results["frozen_p95_available"].astype(bool)) & results["empirical_precision_at_frozen_p95"].notna() & (results["empirical_precision_at_frozen_p95"] < 0.95)]
        if not below.empty:
            warnings.append(f"WARN_FROZEN_P95_BELOW_TARGET: {len(below)} arm/cutoff rows have empirical 2025 precision below 0.95; no threshold was changed.")
        no_prediction = results[(results["frozen_p95_available"].astype(bool)) & results["empirical_precision_at_frozen_p95"].isna()]
        if not no_prediction.empty:
            warnings.append(f"WARN_FROZEN_P95_NO_PREDICTIONS: {len(no_prediction)} arm/cutoff rows emitted no positive prediction at the frozen threshold.")
        qa = {
            "schema_version": "rapskartan-2025-blind-benchmark-qa-v1", "status": "PASS",
            "process_integrity": "PASS", "prediction_lock_sha256": lock_sha,
            "evaluation_started_at_utc": evaluation_started_at, "ground_truth_opened_after_lock": True,
            "population_fields": inventory["fields"], "population_positive_fields": inventory["winter_rapeseed_fields"],
            "sample_fields": len(sample), "sample_positive_fields": int(sample["is_winter_rapeseed"].sum()),
            "result_rows": len(results), "warnings": warnings,
            "model_feature_calibration_threshold_tuning_after_unblind": False,
            "scope": contract["scope"], "elapsed_seconds": round(time.monotonic() - started, 3),
        }
        write_json(out / "blind_benchmark_qa.json", qa)
        write_json(out / "blind_benchmark_results.json", {
            "schema_version": "rapskartan-2025-blind-results-v1", "status": "PASS",
            "model_version": contract["model_version"], "prediction_lock_sha256": lock_sha,
            "ground_truth_sha256": inventory["source_sha256"], "results": json_records(results), "warnings": warnings,
        })
        relatives = [
            "blind_ground_truth_sample.csv", "blind_ground_truth_inventory.json", "blind_benchmark_main.csv",
            "blind_confusion_matrices.csv", "blind_data_quality_breakdown.csv", "blind_spatial_by_municipality.csv",
            "blind_reliability_bins.csv", "blind_error_cases.csv", "blind_benchmark_qa.md",
            "blind_benchmark_qa.json", "blind_benchmark_results.json", "qa/blind_error_cases.geojson",
            "qa/blind_precision_recall_f1_by_date.png", "qa/blind_recall_at_frozen_p95_by_date.png", *reliability_paths,
        ]
        manifest = {
            "schema_version": "rapskartan-2025-blind-evaluation-manifest-v1", "status": "PASS",
            "created_at_utc": utc_now(), "repository_head": snapshot["head"], "repository_tree": snapshot["head_tree"],
            "prediction_lock_sha256": lock_sha, "critical_prediction_sha256": lock["critical_prediction_sha256"],
            "ground_truth_sha256": inventory["source_sha256"],
            "code_hashes": [{"path": path, "sha256": sha256_file(ROOT / path)} for path in ["src/rapskartan_blind_evaluation_core.py", "src/98_evaluate_rapskartan_2025_blind.py"]],
            "artifacts": evaluation_artifacts(out, relatives), "warnings": warnings,
            "scope": contract["scope"],
        }
        write_json(out / "blind_evaluation_manifest.json", manifest)

        print("=" * 88)
        print("RAPSKARTAN SKANE V1 2025 BLIND BENCHMARK: PASS")
        print("=" * 88)
        print(f"Population: {inventory['fields']:,} fields / {inventory['winter_rapeseed_fields']:,} raps")
        print(f"Blind sample: {len(sample):,} fields / {int(sample['is_winter_rapeseed'].sum()):,} observed raps")
        print(f"Results: {len(results)} arm/cutoff rows · warnings: {len(warnings)}")
        for warning in warnings:
            print(warning)
        print("Model/feature/calibration/threshold tuning after unblind: NO")
        print("Full Skåne prediction export, web, Sentinel-1 and deployment: NO")
        print("Run the independent STOPPUNKT D verifier next.")
        return 0
    except Exception as exc:
        traceback.print_exc(); (out / "logs" / "evaluation_traceback.log").write_text(traceback.format_exc(), encoding="utf-8")
        print(f"RAPSKARTAN 2025 BLIND EVALUATION: FAIL — {exc}")
        print("No tuning, full Skåne prediction, web, Sentinel-1 or deployment ran.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
