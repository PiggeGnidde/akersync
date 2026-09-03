#!/usr/bin/env python3
"""Generate and hash-lock bounded 2025 predictions before opening crop labels."""
from __future__ import annotations

import argparse
import shutil
import time
import traceback
from pathlib import Path

from rapskartan_blind_prediction_core import (
    BLIND_CONTRACT_REL, build_blind_priors, build_blind_temporal_features,
    collect_blind_statistics, frozen_runtime_contract, geometry_wkb_table,
    load_blind_contract, lock_artifacts, make_predictions, read_safe_2025_geometry,
    selection_table, select_blind_fields, sha256_bytes, sha256_file, verify_stop_c,
)
from rapskartan_s2_pilot_core import ApiCache, cache_inventory, oauth_token, utc_now, write_dataframe, write_json
from rapskartan_v1_discovery_core import FEATURE_BRANCH, repository_snapshot


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STOP_C = Path(r"C:\AkerSyncRepo\work\rapskartan_skane_v1_model_stopC")
DEFAULT_OUT = Path(r"C:\AkerSyncRepo\work\rapskartan_skane_v1_blind_2025_stopD")


def csv_bytes(frame) -> bytes:
    return frame.to_csv(index=False, lineterminator="\n", float_format="%.10g", na_rep="").encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--stop-c-dir", type=Path, default=DEFAULT_STOP_C)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--cache-root", type=Path, required=True)
    args = parser.parse_args()
    started = time.monotonic()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / "logs").mkdir(parents=True, exist_ok=True)
    (out / "logs" / "prediction_traceback.log").unlink(missing_ok=True)
    try:
        print("[BLIND-PREDICT] Verifying clean repository and accepted immutable STOPPUNKT C...", flush=True)
        snapshot = repository_snapshot(ROOT)
        if snapshot["branch"] != FEATURE_BRANCH or not snapshot["working_tree_clean"]:
            raise RuntimeError(f"Blind prediction requires clean branch {FEATURE_BRANCH}")
        stop_c = args.stop_c_dir.resolve()
        frozen = verify_stop_c(ROOT, stop_c)
        contract = frozen_runtime_contract(stop_c, load_blind_contract(ROOT))
        shutil.copyfile(ROOT / BLIND_CONTRACT_REL, out / "blind_benchmark_contract.json")

        print("[BLIND-PREDICT] Projecting only identity/municipality/geometry from frozen 2025 source...", flush=True)
        geometry_source = args.raw_root.resolve() / contract["geometry"]["relative_path"]
        candidates = read_safe_2025_geometry(geometry_source, contract)
        selected = select_blind_fields(candidates, contract)
        selection = selection_table(selected, geometry_source)
        write_dataframe(out / "blind_field_selection.csv", selection)
        write_dataframe(out / "blind_selection_geometry_wkb.csv", geometry_wkb_table(selected))

        print("[BLIND-PREDICT] Building 2025 priors from 2021-2024 crop layers only...", flush=True)
        priors, sources = build_blind_priors(selected, args.raw_root.resolve(), contract)
        source_rows = [{
            "source_role": "TARGET_2025_GEOMETRY_SAFE_PROJECTION_ONLY", "history_year": None,
            "municipality_code": None, "path": str(geometry_source), "bytes": geometry_source.stat().st_size,
            "sha256": sha256_file(geometry_source),
        }, *sources.to_dict("records")]
        write_dataframe(out / "blind_prior_features.csv", priors)
        write_dataframe(out / "blind_prediction_source_inventory.csv", __import__("pandas").DataFrame(source_rows))

        print("[BLIND-PREDICT] Fetching or replaying label-free 2025 Sentinel-2 statistics...", flush=True)
        token = oauth_token()
        cache = ApiCache(
            args.cache_root.resolve(), token,
            request_limit=int(contract["resource_guards"]["maximum_authenticated_api_requests"]),
        )
        timeseries, requests = collect_blind_statistics(selected, contract, cache)
        temporal = build_blind_temporal_features(timeseries, selection, contract)
        predictions = make_predictions(selection, priors, temporal, stop_c, contract)
        write_dataframe(out / "blind_s2_timeseries.csv", timeseries)
        write_dataframe(out / "blind_api_request_inventory.csv", requests)
        write_dataframe(out / "blind_temporal_features.csv", temporal)
        write_dataframe(out / "blind_predictions_locked.csv", predictions)

        print("[BLIND-PREDICT] Replaying every request offline and verifying exact feature/prediction hashes...", flush=True)
        offline = ApiCache(
            args.cache_root.resolve(), None, offline=True,
            request_limit=int(contract["resource_guards"]["maximum_authenticated_api_requests"]),
        )
        timeseries_2, _ = collect_blind_statistics(selected, contract, offline)
        temporal_2 = build_blind_temporal_features(timeseries_2, selection, contract)
        predictions_2 = make_predictions(selection, priors, temporal_2, stop_c, contract)
        online_hashes = {
            "blind_s2_timeseries.csv": sha256_file(out / "blind_s2_timeseries.csv"),
            "blind_temporal_features.csv": sha256_file(out / "blind_temporal_features.csv"),
            "blind_predictions_locked.csv": sha256_file(out / "blind_predictions_locked.csv"),
        }
        offline_hashes = {
            "blind_s2_timeseries.csv": sha256_bytes(csv_bytes(timeseries_2)),
            "blind_temporal_features.csv": sha256_bytes(csv_bytes(temporal_2)),
            "blind_predictions_locked.csv": sha256_bytes(csv_bytes(predictions_2)),
        }
        if online_hashes != offline_hashes or offline.cache_misses or offline.authenticated_requests:
            raise RuntimeError("Blind offline rerun is not byte-identical")
        write_json(out / "blind_prediction_determinism.json", {
            "schema_version": "rapskartan-2025-blind-prediction-determinism-v1", "status": "PASS",
            "online_hashes": online_hashes, "offline_hashes": offline_hashes,
            "offline_cache_hits": offline.cache_hits, "offline_cache_misses": offline.cache_misses,
            "offline_authenticated_requests": offline.authenticated_requests,
        })
        cache_summary = cache_inventory(args.cache_root.resolve())
        if int(cache_summary["bytes"]) > int(contract["resource_guards"]["maximum_cache_bytes"]):
            raise RuntimeError("RESOURCE_GUARD: blind cache exceeds contract")
        write_json(out / "blind_cache_inventory.json", cache_summary)

        quality = temporal.groupby([temporal["cutoff_date"].astype(str).str[5:], "data_quality_status"]).size().rename("rows").reset_index().rename(columns={"cutoff_date": "cutoff_month_day"})
        write_dataframe(out / "blind_prediction_data_quality.csv", quality)
        qa = {
            "schema_version": "rapskartan-2025-blind-prediction-qa-v1", "status": "PASS",
            "selected_fields": len(selection), "eligible_geometry_fields": len(candidates),
            "municipalities": int(selection["municipality_code"].nunique()),
            "prediction_rows": len(predictions), "cutoffs": 9, "model_arms": 3,
            "authenticated_requests": cache.authenticated_requests, "cache_hits": cache.cache_hits,
            "cache_bytes": int(cache_summary["bytes"]), "offline_hash_rerun": "PASS",
            "label_columns_projected_from_2025_geometry": [], "ground_truth_opened": False,
            "scope": contract["scope"], "elapsed_seconds": round(time.monotonic() - started, 3),
        }
        write_json(out / "blind_prediction_qa.json", qa)
        relatives = [
            "blind_benchmark_contract.json", "blind_field_selection.csv", "blind_selection_geometry_wkb.csv",
            "blind_prior_features.csv", "blind_prediction_source_inventory.csv", "blind_s2_timeseries.csv",
            "blind_api_request_inventory.csv", "blind_temporal_features.csv", "blind_predictions_locked.csv",
            "blind_prediction_determinism.json", "blind_cache_inventory.json", "blind_prediction_data_quality.csv",
            "blind_prediction_qa.json",
        ]
        code_paths = [
            "config/rapskartan_2025_blind_v1.json", "src/rapskartan_blind_prediction_core.py",
            "src/97_generate_rapskartan_2025_blind_predictions.py",
        ]
        lock = {
            "schema_version": "rapskartan-2025-prediction-lock-v1", "status": "PREDICTIONS_HASH_LOCKED",
            "locked_at_utc": utc_now(), "target_year": 2025,
            "repository_head": snapshot["head"], "repository_tree": snapshot["head_tree"],
            "accepted_stopc_head": frozen["accepted"]["source_archive"]["feature_head"],
            "accepted_stopc_tree": frozen["accepted"]["source_archive"]["feature_tree"],
            "model_artifacts_manifest_sha256": sha256_file(stop_c / "model_artifacts_manifest.json"),
            "model_contract_sha256": sha256_file(stop_c / "rapskartan_model_contract_v1.json"),
            "code_hashes": [{"path": path, "sha256": sha256_file(ROOT / path)} for path in code_paths],
            "artifacts": lock_artifacts(out, relatives),
            "critical_prediction_sha256": sha256_file(out / "blind_predictions_locked.csv"),
            "labels_opened": False, "ground_truth_path_received": False,
            "scope": contract["scope"],
        }
        write_json(out / "prediction_lock_manifest.json", lock)

        print("=" * 88)
        print("RAPSKARTAN 2025 BLIND PREDICTIONS: HASH-LOCKED PASS")
        print("=" * 88)
        print(f"Selected fields: {len(selection):,} · municipalities: 33 · prediction rows: {len(predictions):,}")
        print(f"Network/cache: {cache.authenticated_requests}/{cache.cache_hits} · offline rerun: PASS")
        print(f"Prediction SHA256: {lock['critical_prediction_sha256']}")
        print("2025 crop labels opened: NO")
        print("PREDICTION LOCK COMPLETE — evaluation may now open the separate ground-truth source.")
        return 0
    except Exception as exc:
        traceback.print_exc()
        (out / "logs" / "prediction_traceback.log").write_text(traceback.format_exc(), encoding="utf-8")
        print(f"RAPSKARTAN 2025 BLIND PREDICTION: FAIL OR BLOCKED — {exc}")
        print("Ground-truth source was not opened by this process.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
