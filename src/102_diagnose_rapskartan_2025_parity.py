#!/usr/bin/env python3
"""Read-only offline replay of the failed parity gate; never generates a map."""
from __future__ import annotations

import argparse
import contextlib
import importlib.metadata
import json
import platform
import shutil
import sys
import time
import traceback
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd
import rasterio
from shapely import wkb

from rapskartan_blind_prediction_core import (
    build_blind_temporal_features, frozen_runtime_contract, load_blind_contract,
    make_predictions, verify_stop_c,
)
from rapskartan_map_product_core import (
    aggregate_local_scene_timeseries, compare_parity_predictions, load_map_contract,
    select_parity_field_ids, sha256_bytes, sha256_file, stable_json, verify_stop_d,
)
from rapskartan_model_core import SPECTRAL_NAMES, temporal_feature_columns
from rapskartan_parity_diagnostic_core import (
    Tee, compare_tables, ensure_separate_output, heartbeat, local_path, offline_audit,
    read_day_checkpoint, read_table, save_day_checkpoint, save_table,
    validate_scenes, verify_day_assets,
)
from rapskartan_s2_pilot_core import artifact_records, write_json
from rapskartan_v1_discovery_core import repository_snapshot


ROOT = Path(__file__).resolve().parents[1]
FEATURE_BRANCH = "feature/rapskartan-skane-v1a"


def runtime_versions() -> dict:
    return {
        "python": platform.python_version(), "platform": platform.platform(),
        "packages": {name: importlib.metadata.version(name) for name in
                     ("numpy", "pandas", "scikit-learn", "rasterio", "shapely", "pyproj", "geopandas", "joblib", "pyarrow")},
        "gdal": rasterio.__gdal_version__, "proj": rasterio.__proj_version__,
    }


def satellite_only(frame):
    return frame[frame.model_arm == "SATELLITE_ONLY"].copy()


def run(args, base: Path) -> Path:
    print("[DIAG] OFFLINE ONLY: no credentials, catalog queries or downloads.", flush=True)
    engine_profile = getattr(args, "engine_profile", "original")
    if engine_profile not in {"original", "reference_pixels_v2"}:
        raise RuntimeError("Unknown diagnostic engine profile")
    print(f"[DIAG] Engine profile: {engine_profile}; production runner remains unchanged.", flush=True)
    snapshot = repository_snapshot(ROOT)
    if snapshot["branch"] != FEATURE_BRANCH or not snapshot["working_tree_clean"]:
        raise RuntimeError(f"Diagnostic requires clean branch {FEATURE_BRANCH}")
    contract = load_map_contract(ROOT)
    print("[DIAG] Verifying the frozen model and accepted prediction/evaluation manifests...", flush=True)
    with heartbeat("verifying frozen inputs"):
        verify_stop_c(ROOT, args.stop_c_dir)
        verify_stop_d(ROOT, args.stop_d_dir, contract)
    frozen = frozen_runtime_contract(args.stop_c_dir, load_blind_contract(ROOT))
    for key in ("model_version", "frozen_feature_contract_version", "frozen_model_contract_id", "frozen_feature_contract"):
        contract[key] = frozen[key]
    selection = read_table(args.stop_d_dir / "blind_field_selection.csv")
    locked_all = read_table(args.stop_d_dir / "blind_predictions_locked.csv")
    ids = select_parity_field_ids(selection, locked_all, contract)
    selection = selection[selection.development_field_id.isin(ids)].copy()
    locked = satellite_only(locked_all[locked_all.development_field_id.isin(ids)])
    prior = read_table(args.stop_d_dir / "blind_prior_features.csv")
    prior = prior[prior.development_field_id.isin(ids)].copy()
    reference_ts = read_table(args.stop_d_dir / "blind_s2_timeseries.csv")
    reference_ts = reference_ts[reference_ts.development_field_id.isin(ids)].copy()
    reference_features = read_table(args.stop_d_dir / "blind_temporal_features.csv")
    reference_features = reference_features[reference_features.development_field_id.isin(ids)].copy()
    geometries = read_table(args.stop_d_dir / "blind_selection_geometry_wkb.csv")
    geometry = selection.merge(geometries[["development_field_id", "geometry_wkb_hex"]],
                               on="development_field_id", validate="one_to_one")
    fields = gpd.GeoDataFrame(
        geometry.drop(columns="geometry_wkb_hex"),
        geometry=[wkb.loads(value, hex=True) for value in geometry.geometry_wkb_hex],
        crs=f"EPSG:{load_blind_contract(ROOT)['geometry']['crs_epsg']}",
    )
    if len(fields) != len(ids) or fields.geometry.is_empty.any() or not fields.geometry.is_valid.all():
        raise RuntimeError("Locked parity geometry is incomplete or invalid")
    scene_file = args.product_dir / "source" / "scene_inventory.json"
    document = json.loads(scene_file.read_text(encoding="utf-8"))
    scenes = validate_scenes(document, contract)
    versions = runtime_versions()
    identity_inputs = {
        "diagnostic_version": "offline-parity-v1", "repository_tree": snapshot["head_tree"],
        "scene_inventory_sha256": sha256_file(scene_file), "field_ids": ids,
        "prediction_lock_sha256": sha256_file(args.stop_d_dir / "prediction_lock_manifest.json"),
        "model_manifest_sha256": sha256_file(args.stop_c_dir / "model_artifacts_manifest.json"),
        "runtime": versions,
    }
    if engine_profile != "original":
        identity_inputs["engine_profile"] = engine_profile
        identity_inputs["candidate_code_sha256"] = sha256_file(ROOT / "src/rapskartan_local_candidate.py")
    identity = sha256_bytes(stable_json(identity_inputs).encode("utf-8"))
    out = base / f"run_{identity[:16]}"
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "diagnostic_inputs.json", identity_inputs)
    save_table(out / "selected_fields.csv", selection)
    save_table(out / "reference_timeseries.csv", reference_ts)
    save_table(out / "reference_features.csv", reference_features)
    print(f"[DIAG] {len(ids)} locked fields; output: {out}", flush=True)

    print("[DIAG] Replaying reference features through the unchanged models...", flush=True)
    with heartbeat("reference replay"):
        replay = satellite_only(make_predictions(selection, prior, reference_features, args.stop_c_dir, contract))
        rebuilt_features = build_blind_temporal_features(reference_ts, selection, contract)
        rebuilt = satellite_only(make_predictions(selection, prior, rebuilt_features, args.stop_c_dir, contract))
    save_table(out / "reference_feature_replay_predictions.csv", replay)
    save_table(out / "reference_timeseries_replay_predictions.csv", rebuilt)
    _, replay_gate = compare_parity_predictions(replay, locked, contract)
    _, rebuilt_gate = compare_parity_predictions(rebuilt, locked, contract)
    print(f"[DIAG] Reference feature replay: {replay_gate['status']}; decision agreement {replay_gate['decision_agreement']:.6f}", flush=True)

    dates = sorted({item["acquisition_date"] for item in scenes})
    parts, verified, modes = [], [], []
    started = time.monotonic()
    for index, day in enumerate(dates, start=1):
        day_scenes = [scene for scene in scenes if scene["acquisition_date"] == day]
        print(f"[DIAG] {day}: checking {len(day_scenes)*11} existing assets...", flush=True)
        with heartbeat(f"{day} asset checksum verification"):
            verified.extend(verify_day_assets(day_scenes, args.scene_archive))
        cached = read_day_checkpoint(out / "checkpoints", day, identity)
        if cached is None:
            with heartbeat(f"{day} local pixel processing"):
                profile_args = {} if engine_profile == "original" else {"engine_profile": engine_profile}
                cached = aggregate_local_scene_timeseries(fields, day_scenes, args.scene_archive, contract, progress_prefix=f"DIAG-{day}", **profile_args)
            save_day_checkpoint(out / "checkpoints", day, identity, cached)
            mode = "computed"
        else:
            mode = "checkpoint"
        parts.append(cached)
        modes.append({"date": day, "mode": mode, "rows": len(cached)})
        print(f"[DIAG] dates {index}/{len(dates)}; rows {sum(len(part) for part in parts):,}; {mode}; {time.monotonic()-started:.0f}s", flush=True)
    local_ts = pd.concat(parts, ignore_index=True).sort_values(["development_field_id", "acquisition_date"])
    save_table(out / "local_timeseries.csv", local_ts)
    save_table(out / "verified_scene_assets.csv", pd.DataFrame(verified))
    save_table(out / "date_progress.csv", pd.DataFrame(modes))
    local_features = build_blind_temporal_features(local_ts, selection, contract)
    save_table(out / "local_features.csv", local_features)
    with heartbeat("local feature prediction"):
        local_predictions = satellite_only(make_predictions(selection, prior, local_features, args.stop_c_dir, contract))
    save_table(out / "local_predictions.csv", local_predictions)

    observation_columns = ["sample_pixels", "valid_pixels", "valid_pixel_fraction"] + [
        f"{band}_p{percentile}" for band in SPECTRAL_NAMES for percentile in (10, 50, 90)]
    observation_comparison, observation_summary = compare_tables(
        local_ts, reference_ts, ["development_field_id", "acquisition_date"], observation_columns)
    save_table(out / "observation_comparison.csv", observation_comparison)
    save_table(out / "observation_variable_summary.csv", observation_summary)
    quality = local_ts[["development_field_id", "acquisition_date", "data_quality_status"]].merge(
        reference_ts[["development_field_id", "acquisition_date", "data_quality_status"]],
        on=["development_field_id", "acquisition_date"], how="outer", validate="one_to_one",
        suffixes=("_local", "_reference"), indicator=True)
    quality["quality_agrees"] = quality._merge.eq("both") & quality.data_quality_status_local.eq(quality.data_quality_status_reference)
    save_table(out / "observation_quality.csv", quality)
    feature_columns = temporal_feature_columns(contract["frozen_feature_contract"])
    comparison, summary = compare_tables(local_features, reference_features, ["development_field_id", "cutoff_date"], feature_columns)
    save_table(out / "feature_comparison.csv", comparison)
    save_table(out / "feature_variable_summary.csv", summary)
    _, rebuild_summary = compare_tables(rebuilt_features, reference_features, ["development_field_id", "cutoff_date"], feature_columns)
    save_table(out / "reference_rebuild_variable_summary.csv", rebuild_summary)
    score_rows, score_summary = compare_tables(local_predictions, locked, ["development_field_id", "cutoff_date"], ["raw_probability", "calibrated_probability"])
    save_table(out / "score_comparison.csv", score_rows)
    save_table(out / "score_variable_summary.csv", score_summary)
    parity_rows, local_gate = compare_parity_predictions(local_predictions, locked, contract)
    save_table(out / "parity_rows.csv", parity_rows)
    save_table(out / "decision_mismatches.csv", parity_rows[~parity_rows.decision_agrees])
    by_date = []
    for day, frame in parity_rows.groupby("cutoff_date", sort=True):
        by_date.append({"cutoff_date": day, "rows": len(frame),
                        "decision_mismatches": int((~frame.decision_agrees).sum()),
                        "median_abs_probability_delta": float(frame.probability_abs_delta.median()),
                        "p95_abs_probability_delta": float(frame.probability_abs_delta.quantile(.95))})
    save_table(out / "parity_by_date.csv", pd.DataFrame(by_date))
    previous_path = args.product_dir / "qa" / "local_engine_parity_rows.csv"
    previous_gate = None
    if previous_path.is_file():
        previous = read_table(previous_path)
        baseline = previous.rename(columns={
            "data_quality_status_local": "data_quality_status", "calibrated_probability_local": "calibrated_probability",
            "predicted_at_frozen_p95_local": "predicted_at_frozen_p95"})
        _, previous_gate = compare_parity_predictions(local_predictions, baseline, contract)
    summary = {
        "status": "DIAGNOSTICS_COMPLETE", "diagnostic_id": identity,
        "repository_head": snapshot["head"], "fields": len(ids), "acquisition_dates": len(dates),
        "observations_local": len(local_ts), "observations_reference": len(reference_ts),
        "reference_feature_replay_vs_locked": replay_gate,
        "reference_timeseries_replay_vs_locked": rebuilt_gate,
        "local_engine_vs_locked": local_gate,
        "local_engine_vs_previous_local_run": previous_gate,
        "scope": {"offline_only": True, "model_retuning": False, "threshold_retuning": False,
                  "ground_truth_used_for_analysis": False, "full_map_generated": False,
                  "source_archive_modified": False},
        "interpretation": "Completion is not parity approval. All production thresholds remain unchanged.",
        "engine_profile": engine_profile,
    }
    write_json(out / "diagnostic_summary.json", summary)
    end_snapshot = repository_snapshot(ROOT)
    if end_snapshot["head"] != snapshot["head"] or not end_snapshot["working_tree_clean"]:
        raise RuntimeError("Repository changed during diagnostic run")
    print(f"[DIAG] DIAGNOSTICS COMPLETE. Local parity status: {local_gate['status']}. No map product was generated.", flush=True)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stop-c-dir", type=Path, default=Path(r"C:\AkerSyncRepo\work\rapskartan_skane_v1_model_stopC"))
    parser.add_argument("--stop-d-dir", type=Path, default=Path(r"C:\AkerSyncRepo\work\rapskartan_skane_v1_blind_2025_stopD"))
    parser.add_argument("--product-dir", type=Path, default=ROOT / "data/derived/rapskartan_v1/2025")
    parser.add_argument("--scene-archive", type=Path, default=Path(r"C:\AkerSyncRaw\rapskartan_v1\sentinel2_l2a\map_product_2025_scene_archive_v1"))
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/derived/rapskartan_v1/2025_parity_diagnostic_v1")
    parser.add_argument("--engine-profile", choices=["original", "reference_pixels_v2"], default="original")
    args = parser.parse_args()
    sys.addaudithook(offline_audit)
    for name,value in vars(args).items():
        if isinstance(value, Path):
            setattr(args, name, local_path(value))
    base = args.output_dir
    ensure_separate_output(base, [args.stop_c_dir, args.stop_d_dir, args.product_dir, args.scene_archive])
    base.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(base).free < 2 * 2**30:
        raise RuntimeError("Diagnostic needs 2 GiB output headroom (no 250 GiB download guard).")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    log = base / f"diagnostic_console_{stamp}.log"
    print(f"Diagnostic log: {log}", flush=True)
    with log.open("w", encoding="utf-8") as handle:
        with contextlib.redirect_stdout(Tee(sys.stdout, handle)), contextlib.redirect_stderr(Tee(sys.stderr, handle)):
            try:
                out = run(args, base)
            except Exception:
                traceback.print_exc()
                print("DIAGNOSTIC BLOCKED. Existing scene files and date checkpoints are unchanged/reusable.")
                print(f"Return this log: {log}")
                return 1
    shutil.copyfile(log, out / "diagnostic_console.log")
    files = sorted(path.name for path in out.iterdir() if path.is_file() and path.name != "diagnostic_manifest.json")
    write_json(out / "diagnostic_manifest.json", {"status": "DIAGNOSTICS_COMPLETE", "artifacts": artifact_records(out, files)})
    archive = base / f"rapskartan_parity_diagnostic_{stamp}.zip"
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as output:
        for name in [*files, "diagnostic_manifest.json"]:
            output.write(out / name, name)
    with zipfile.ZipFile(archive) as output:
        if output.testzip() is not None:
            raise RuntimeError("Diagnostic ZIP integrity failure")
    print(f"RETURN THIS ZIP: {archive}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
