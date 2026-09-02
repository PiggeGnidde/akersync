#!/usr/bin/env python3
"""Independent verifier for Rapskartan Sentinel-2 datapilot STOPPUNKT B."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from rapskartan_s2_pilot_core import contract_sha256, load_contract, sha256_file
from rapskartan_v1_discovery_core import (
    FEATURE_BRANCH, UPSTREAM_COMMIT, UPSTREAM_TAG, repository_snapshot,
    verify_repository_snapshot,
)


ROOT = Path(__file__).resolve().parents[1]


def verify_artifacts(out: Path, manifest: dict) -> None:
    records = manifest.get("artifacts") or []
    if not records:
        raise RuntimeError("Datapilot manifest has no artifacts")
    for record in records:
        path = out / record["path"]
        if (not path.is_file() or path.stat().st_size != int(record["bytes"])
                or sha256_file(path) != record["sha256"]):
            raise RuntimeError(f"Manifest artifact mismatch: {record['path']}")


def verify_scope(scope: dict) -> None:
    if not scope.get("sentinel2_datapilot_only"):
        raise RuntimeError("Manifest is not marked Sentinel-2 datapilot-only")
    forbidden = [
        "row_level_2025_accessed", "classifier_created", "model_fitted", "threshold_selected",
        "sentinel1_touched", "full_skane_run", "web_touched", "deployment",
    ]
    if any(scope.get(key) for key in forbidden):
        raise RuntimeError("A forbidden post-STOPPUNKT-B scope flag is true")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    out = args.output_dir.resolve()
    manifest = json.loads((out / "s2_pilot_manifest.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "PASS":
        raise RuntimeError(f"Datapilot manifest is not PASS: {manifest.get('status')}")
    if manifest.get("upstream_tag") != UPSTREAM_TAG or manifest.get("upstream_commit") != UPSTREAM_COMMIT:
        raise RuntimeError("Datapilot upstream freeze mismatch")
    verify_artifacts(out, manifest)
    verify_scope(manifest.get("scope") or {})

    snapshot = repository_snapshot(ROOT)
    repository_errors = verify_repository_snapshot(snapshot)
    if repository_errors:
        raise RuntimeError(f"Repository verification failed: {repository_errors}")
    if manifest.get("feature_branch") != FEATURE_BRANCH or manifest.get("feature_head") != snapshot.get("head"):
        raise RuntimeError("Datapilot feature branch/HEAD differs from current repository")

    contract = load_contract(ROOT)
    if manifest.get("contract_sha256") != contract_sha256(ROOT):
        raise RuntimeError("Datapilot contract hash mismatch")
    selection = pd.read_csv(out / "pilot_selection.csv", dtype={"municipality_code": str})
    expected = int(contract["expected_selected_fields"])
    if len(selection) != expected or selection["pilot_field_id"].nunique() != expected:
        raise RuntimeError(f"Pilot selection is not exactly {expected} unique fields")
    if set(selection["target_year"].astype(int)) != set(contract["blind_guard"]["allowed_target_years"]):
        raise RuntimeError("Pilot selection development years mismatch")
    if (selection["target_year"].astype(int) >= int(contract["blind_guard"]["forbidden_target_year"])).any():
        raise RuntimeError("BLIND_GUARD: selection contains 2025 or later")
    group_counts = selection.groupby(["target_year", "pilot_group"]).size().to_dict()
    for stratum in contract["pilot_strata"]:
        year = int(stratum["target_year"])
        expected_groups = {
            "WINTER_RAPESEED": int(stratum["winter_rapeseed_fields"]),
            "WINTER_CROP_CONTROL": int(stratum["winter_crop_control_fields"]),
            "SPRING_CROP_CONTROL": int(stratum["spring_crop_control_fields"]),
        }
        for group, count in expected_groups.items():
            if int(group_counts.get((year, group), 0)) != count:
                raise RuntimeError(f"Selection group mismatch: {year}/{group}")
    if sha256_file(out / "pilot_selection.csv") != manifest.get("selection_sha256"):
        raise RuntimeError("Selection hash differs from manifest")

    metrics = pd.read_csv(out / "field_timeseries.csv", dtype={"municipality_code": str})
    if metrics.empty or not set(metrics["pilot_field_id"]).issubset(set(selection["pilot_field_id"])):
        raise RuntimeError("Field time-series identities are empty or outside the frozen selection")
    if set(metrics["edge_rule"]) - {str(item["id"]) for item in contract["edge_rules"]}:
        raise RuntimeError("Unexpected polygon edge rule in time-series")
    allowed_status = {"VALID", "LOW_COVERAGE", "NO_DATA_TOO_FEW_PIXELS"}
    if set(metrics["data_quality_status"]) - allowed_status:
        raise RuntimeError("Unexpected field time-series data-quality status")
    dates = pd.to_datetime(metrics["acquisition_date"], errors="raise")
    if (dates.dt.year >= int(contract["blind_guard"]["forbidden_target_year"])).any():
        raise RuntimeError("BLIND_GUARD: time-series contains 2025 or later")
    if not (dates.dt.strftime("%m-%d") <= "06-10").all() or not (dates.dt.strftime("%m-%d") >= "03-01").all():
        raise RuntimeError("Time-series date is outside the frozen spring interval")
    for column in ["sample_pixels", "valid_pixels", "valid_pixel_fraction", "NDVI_p50", "NDRE_p50"]:
        if column not in metrics.columns:
            raise RuntimeError(f"Missing required time-series column: {column}")
    fractions = pd.to_numeric(metrics["valid_pixel_fraction"], errors="raise")
    if ((fractions < 0) | (fractions > 1)).any():
        raise RuntimeError("Valid-pixel fraction is outside [0,1]")

    edges = pd.read_csv(out / "edge_rule_summary.csv")
    if len(edges) != expected * len(contract["edge_rules"]):
        raise RuntimeError("Edge-rule summary row count mismatch")
    if set(edges["geometry_status"]) - {"USABLE", "EMPTY_AFTER_BUFFER"}:
        raise RuntimeError("Unexpected edge geometry status")
    original = edges[edges["edge_rule"] == "ORIGINAL"]
    if len(original) != expected or (original["geometry_status"] != "USABLE").any():
        raise RuntimeError("Every original field geometry must be usable")

    scl = pd.read_csv(out / "scl_timeseries.csv", dtype={"municipality_code": str})
    required_scl = {f"scl_{code}_fraction" for code in range(12)} | {
        "scl_valid_fraction", "scl_excluded_fraction", "scl_fraction_sum",
    }
    if scl.empty or not required_scl.issubset(scl.columns):
        raise RuntimeError("SCL time-series is empty or incomplete")
    observed_sums = pd.to_numeric(scl["scl_fraction_sum"], errors="coerce").dropna()
    if not observed_sums.empty and ((observed_sums < -0.001) | (observed_sums > 1.001)).any():
        raise RuntimeError("SCL class fractions do not form a bounded distribution")

    examples = pd.read_csv(out / "cloud_mask_examples.csv")
    expected_images = int(contract["qa"]["cloud_mask_image_fields"]) * int(contract["qa"]["cloud_mask_dates_per_field"])
    if len(examples) != expected_images or examples["artifact_path"].nunique() != expected_images:
        raise RuntimeError("Cloud-mask QA image count mismatch")
    if set(examples["date_role"]) != {"CLEAREST", "CLOUDIEST"}:
        raise RuntimeError("Cloud-mask QA does not contain clearest and cloudiest examples")
    plot_records = [x for x in manifest["artifacts"] if str(x["path"]).startswith("qa/timeseries_")]
    cloud_records = [x for x in manifest["artifacts"] if str(x["path"]).startswith("qa/cloudmask_")]
    if len(plot_records) != int(contract["qa"]["timeseries_plot_fields"]) or len(cloud_records) != expected_images:
        raise RuntimeError("Manifest QA plot/image count mismatch")

    request_inventory = pd.read_csv(out / "api_request_inventory.csv")
    if len(request_inventory) > int(contract["resource_guards"]["maximum_authenticated_api_requests"]):
        raise RuntimeError("API request inventory exceeds the frozen resource guard")
    if request_inventory[["request_sha256", "response_sha256", "cache_key"]].isna().any().any():
        raise RuntimeError("API request inventory lacks reproducibility hashes")
    runtime = json.loads((out / "runtime_volume.json").read_text(encoding="utf-8"))
    if int(runtime["authenticated_requests"]) > int(contract["resource_guards"]["maximum_authenticated_api_requests"]):
        raise RuntimeError("Authenticated requests exceed the frozen resource guard")
    cache = json.loads((out / "cache_inventory.json").read_text(encoding="utf-8"))
    if int(cache["bytes"]) > int(contract["resource_guards"]["maximum_cache_bytes"]):
        raise RuntimeError("Cache volume exceeds the frozen resource guard")
    determinism = json.loads((out / "determinism_rerun.json").read_text(encoding="utf-8"))
    if (determinism.get("status") != "PASS"
            or determinism.get("online_artifact_hashes") != determinism.get("offline_artifact_hashes")
            or determinism.get("online_image_response_hashes") != determinism.get("offline_image_response_hashes")
            or int(determinism.get("offline_authenticated_requests", -1)) != 0
            or int(determinism.get("offline_cache_misses", -1)) != 0):
        raise RuntimeError("Offline deterministic rerun is not an exact PASS")

    qa = json.loads((out / "pilot_qa.json").read_text(encoding="utf-8"))
    if qa.get("status") != "PASS" or qa.get("deterministic_rerun") != "PASS":
        raise RuntimeError("Datapilot QA is not PASS")
    forbidden_suffixes = {".pkl", ".pickle", ".joblib", ".onnx", ".model"}
    forbidden_files = [path for path in out.rglob("*") if path.is_file() and path.suffix.lower() in forbidden_suffixes]
    if forbidden_files:
        raise RuntimeError(f"Model-like artifacts exist at STOPPUNKT B: {forbidden_files}")

    print("=" * 88)
    print("RAPSKARTAN SKANE V1 STOPPUNKT B VERIFIER: PASS")
    print("=" * 88)
    print(f"Upstream: {UPSTREAM_TAG} -> {UPSTREAM_COMMIT}")
    print(f"Feature HEAD: {snapshot['head']}")
    print(f"Development fields/years: {len(selection)} / {sorted(selection.target_year.astype(int).unique())}")
    print(f"Field/edge rows: {len(metrics):,} · SCL rows: {len(scl):,}")
    print(f"QA plots/images: {len(plot_records)}/{len(cloud_records)}")
    print(f"Cache: {int(cache['bytes']) / 2**20:.2f} MiB · deterministic offline rerun: PASS")
    print("2025 row labels/classifier/model/Sentinel-1/full Skane/web/deployment: NO")
    print("STOPPUNKT B")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
