#!/usr/bin/env python3
"""Build the leakage-safe pre-2025 Rapskartan model-development dataset."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
import traceback
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from rapskartan_model_core import (
    FORBIDDEN_YEAR, annual_geometry_path, build_temporal_features, classify_crop,
    collect_development_statistics, dataset_artifact_manifest, load_model_contract,
    model_contract_sha256, prior_from_overlap_records, select_development_year,
    sha256_bytes, sha256_file, stable_rank, write_dataframe, write_json,
)
from rapskartan_s2_pilot_core import ApiCache, cache_inventory, oauth_token, utc_now
from rapskartan_v1_discovery_core import (
    FEATURE_BRANCH, UPSTREAM_COMMIT, UPSTREAM_TAG, load_official_tables,
    official_lookup, raw_text, repository_snapshot, verify_repository_snapshot,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STOP_B = Path(r"C:\AkerSyncRepo\work\rapskartan_skane_v1_s2_pilot_stopB")
DEFAULT_OUT = Path(r"C:\AkerSyncRepo\work\rapskartan_skane_v1_model_stopC")
ACCEPTED_REL = Path("analysis/rapskartan_v1/accepted_stopB_manifest.json")


def verify_stop_b(stop_b: Path) -> dict[str, Any]:
    accepted = json.loads((ROOT / ACCEPTED_REL).read_text(encoding="utf-8"))
    if accepted.get("status") != "PASS" or not accepted["authorization"].get("go_model_development_received"):
        raise RuntimeError("Repository does not contain an accepted STOPPUNKT B + GO MODELLUTVECKLING")
    manifest_path = stop_b / "s2_pilot_manifest.json"
    if not manifest_path.exists():
        raise RuntimeError(f"Accepted STOPPUNKT B manifest is missing: {manifest_path}")
    if sha256_file(manifest_path) != accepted["source_archive"]["execution_manifest_sha256"]:
        raise RuntimeError("STOPPUNKT B execution manifest differs from the accepted return")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "PASS" or manifest.get("feature_tree") != accepted["source_archive"]["feature_tree"]:
        raise RuntimeError("STOPPUNKT B status/tree mismatch")
    for record in manifest.get("artifacts", []):
        path = stop_b / record["path"]
        if not path.is_file() or path.stat().st_size != int(record["bytes"]) or sha256_file(path) != record["sha256"]:
            raise RuntimeError(f"STOPPUNKT B artifact mismatch: {record['path']}")
    tree_history = subprocess.run(
        ["git", "log", "--format=%T"], cwd=ROOT, text=True, encoding="utf-8",
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if tree_history.returncode or accepted["source_archive"]["feature_tree"] not in tree_history.stdout.splitlines():
        raise RuntimeError("Accepted STOPPUNKT B tree is not present in branch history")
    return manifest


def municipalities() -> list[dict[str, str]]:
    document = json.loads((ROOT / "config/akerminne_skane_municipalities.json").read_text(encoding="utf-8"))
    rows = [{"code": str(item["code"]), "name": str(item["name"])} for item in document["municipalities"]]
    if len(rows) != 33:
        raise RuntimeError("Expected exactly 33 Skåne municipalities")
    return rows


def load_year_candidates(raw_root: Path, year: int, contract: dict[str, Any], official: dict) -> tuple[Any, list[dict[str, Any]]]:
    import geopandas as gpd

    pieces = []
    sources: list[dict[str, Any]] = []
    for municipality in municipalities():
        path = annual_geometry_path(raw_root, year, municipality["name"])
        if not path.exists():
            raise FileNotFoundError(path)
        sources.append({
            "source_role": "TARGET_GEOMETRY_AND_DEVELOPMENT_LABEL",
            "target_year": int(year), "history_year": None,
            "municipality_code": municipality["code"], "municipality_name": municipality["name"],
            "path": str(path.resolve()), "bytes": path.stat().st_size, "sha256": sha256_file(path),
        })
        gdf = gpd.read_file(path)
        required = {"arslager", "blockid", "skiftesbeteckning", "grdkod_mar", "grdkod_und", "geometry"}
        missing = sorted(required - set(gdf.columns))
        if missing:
            raise RuntimeError(f"{path.name}: missing development columns {missing}")
        if gdf.crs is None:
            raise RuntimeError(f"{path.name}: CRS is missing")
        if set(pd.to_numeric(gdf["arslager"], errors="raise").astype(int)) != {int(year)}:
            raise RuntimeError(f"{path.name}: contains another target year")
        gdf = gdf.to_crs(3006).copy()
        gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty & gdf.geometry.is_valid].copy()
        gdf["area_ha"] = gdf.geometry.area / 10_000.0
        gdf = gdf[gdf["area_ha"].between(
            float(contract["selection"]["minimum_area_ha"]),
            float(contract["selection"]["maximum_area_ha"]), inclusive="both",
        )].copy()
        names = []
        for row in gdf.itertuples(index=False):
            found = official_lookup(official, year, row.grdkod_mar, row.grdkod_und)
            names.append(found[0] if found else None)
        gdf["official_crop_name"] = names
        gdf["crop_group"] = [classify_crop(name, contract) for name in names]
        gdf = gdf[gdf["crop_group"].notna()].copy()
        gdf["target_year"] = int(year)
        gdf["municipality_code"] = municipality["code"]
        gdf["municipality_name"] = municipality["name"]
        gdf["development_field_id"] = [
            f"{year}-{municipality['code']}-{raw_text(block)}-{raw_text(field)}"
            for block, field in zip(gdf["blockid"], gdf["skiftesbeteckning"])
        ]
        gdf["stable_rank"] = [
            stable_rank(year, municipality["code"], block, field)
            for block, field in zip(gdf["blockid"], gdf["skiftesbeteckning"])
        ]
        gdf["geographic_fold"] = int(stable_rank("geo", municipality["code"])[:8], 16) % int(contract["model"]["geographic_folds"])
        gdf["source_path"] = str(path.resolve())
        pieces.append(gdf)
    candidates = gpd.GeoDataFrame(pd.concat(pieces, ignore_index=True), crs=3006)
    if candidates["development_field_id"].duplicated().any():
        raise RuntimeError(f"{year}: duplicate development field identities")
    return candidates, sources


def select_all_years(raw_root: Path, contract: dict[str, Any]) -> tuple[Any, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    import geopandas as gpd

    official, _ = load_official_tables(ROOT)
    selected_frames = []
    audit_rows = []
    source_rows: list[dict[str, Any]] = []
    for year in contract["development_years"]:
        print(f"[DATASET] Reading and sampling {year} official fields across 33 municipalities...", flush=True)
        candidates, sources = load_year_candidates(raw_root, int(year), contract, official)
        chosen = select_development_year(candidates, int(year), contract)
        for group, frame in chosen.groupby("crop_group", sort=True):
            audit_rows.append({
                "target_year": int(year), "crop_group": str(group),
                "eligible_fields": int(frame["eligible_population"].iloc[0]),
                "selected_fields": len(frame), "population_weight": float(frame["population_weight"].iloc[0]),
                "selected_municipalities": int(frame["municipality_code"].nunique()),
                "selected_area_min_ha": float(frame["area_ha"].min()),
                "selected_area_median_ha": float(frame["area_ha"].median()),
                "selected_area_max_ha": float(frame["area_ha"].max()),
            })
        selected_frames.append(gpd.GeoDataFrame(chosen, geometry="geometry", crs=3006))
        source_rows.extend(sources)
    selected = gpd.GeoDataFrame(pd.concat(selected_frames, ignore_index=True), geometry="geometry", crs=3006)
    selected = selected.sort_values(["target_year", "crop_group", "development_field_id"], kind="mergesort").reset_index(drop=True)
    expected = int(contract["resource_guards"]["expected_selected_field_years"])
    if len(selected) != expected or selected["development_field_id"].duplicated().any():
        raise RuntimeError(f"Selected {len(selected)} development field-years, expected {expected}")
    labels = selected[[
        "development_field_id", "target_year", "crop_group", "population_weight", "area_ha",
    ]].copy()
    labels["is_winter_rapeseed"] = (labels["crop_group"] == "WINTER_RAPESEED").astype(int)
    labels = labels.drop(columns=["crop_group"]).sort_values(["target_year", "development_field_id"], kind="mergesort")
    selection = selected[[
        "development_field_id", "target_year", "municipality_code", "municipality_name", "area_ha",
        "geographic_fold", "source_path",
    ]].copy().sort_values(["target_year", "development_field_id"], kind="mergesort")
    return selected, selection, labels, pd.DataFrame(audit_rows), pd.DataFrame(source_rows)


def load_prior_layer(raw_root: Path, year: int, municipality: dict[str, str], official: dict, source_rows: list[dict[str, Any]], seen: set[str]) -> Any | None:
    import geopandas as gpd

    if year < 2015:
        return None
    path = annual_geometry_path(raw_root, year, municipality["name"])
    if not path.exists():
        raise FileNotFoundError(path)
    key = str(path.resolve())
    if key not in seen:
        source_rows.append({
            "source_role": "PRIOR_HISTORY_GEOMETRY_AND_CROP",
            "target_year": None, "history_year": int(year),
            "municipality_code": municipality["code"], "municipality_name": municipality["name"],
            "path": key, "bytes": path.stat().st_size, "sha256": sha256_file(path),
        })
        seen.add(key)
    gdf = gpd.read_file(path)
    required = {"grdkod_mar", "grdkod_und", "geometry"}
    missing = sorted(required - set(gdf.columns))
    if missing or gdf.crs is None:
        raise RuntimeError(f"{path.name}: invalid prior layer; missing={missing}, crs={gdf.crs}")
    gdf = gdf.to_crs(3006)
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty & gdf.geometry.is_valid].copy()
    names = []
    for row in gdf.itertuples(index=False):
        found = official_lookup(official, year, row.grdkod_mar, row.grdkod_und)
        names.append(found[0] if found else None)
    gdf["official_crop_name"] = names
    return gdf[["official_crop_name", "geometry"]]


def build_priors(selected: Any, raw_root: Path, contract: dict[str, Any], source_rows: list[dict[str, Any]]) -> pd.DataFrame:
    official, _ = load_official_tables(ROOT)
    municipality_by_code = {item["code"]: item for item in municipalities()}
    minimum_overlap = float(contract["prior"]["minimum_overlap_fraction"])
    lags = int(contract["history_lags"])
    rows: list[dict[str, Any]] = []
    seen = {row["path"] for row in source_rows}
    for code, municipality_targets in selected.groupby("municipality_code", sort=True):
        code = str(code)
        needed_years = sorted({
            int(target_year) - lag
            for target_year in municipality_targets["target_year"].astype(int).unique()
            for lag in range(1, lags + 1)
            if int(target_year) - lag >= 2015
        })
        layer_cache = {
            history_year: load_prior_layer(
                raw_root, history_year, municipality_by_code[code], official, source_rows, seen,
            )
            for history_year in needed_years
        }
        for year, targets in municipality_targets.groupby("target_year", sort=True):
            year = int(year)
            histories = {year - lag: layer_cache.get(year - lag) for lag in range(1, lags + 1)}
            for target in targets.itertuples(index=False):
                target_geometry = target.geometry
                overlap_records: list[dict[str, Any]] = []
                for history_year, history in histories.items():
                    if history is None or history.empty:
                        continue
                    indexes = list(history.sindex.query(target_geometry, predicate="intersects"))
                    if not indexes:
                        continue
                    candidates = history.iloc[indexes].copy()
                    candidates["_overlap"] = candidates.geometry.intersection(target_geometry).area
                    best = candidates.sort_values(["_overlap", "official_crop_name"], ascending=[False, True], kind="mergesort").iloc[0]
                    fraction = float(best["_overlap"]) / float(target_geometry.area)
                    overlap_records.append({
                        "history_year": int(history_year),
                        "official_crop_name": best["official_crop_name"] if fraction >= minimum_overlap else None,
                        "overlap_fraction": fraction,
                    })
                features = prior_from_overlap_records(year, overlap_records, history_lags=lags)
                rows.append({
                    "development_field_id": str(target.development_field_id), "target_year": year,
                    "municipality_code": code, **features,
                })
    result = pd.DataFrame(rows).sort_values(["target_year", "development_field_id"], kind="mergesort").reset_index(drop=True)
    if len(result) != len(selected) or result["development_field_id"].duplicated().any():
        raise RuntimeError("Prior features do not cover the selected development fields exactly once")
    if (result["target_year"].astype(int) >= FORBIDDEN_YEAR).any():
        raise RuntimeError("BLIND_GUARD: prior feature output contains 2025")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--stop-b-dir", type=Path, default=DEFAULT_STOP_B)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--cache-root", type=Path, required=True)
    args = parser.parse_args()
    started = time.monotonic()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / "logs").mkdir(parents=True, exist_ok=True)
    (out / "logs" / "dataset_traceback.log").unlink(missing_ok=True)

    try:
        print("[DATASET] Verifying repository, accepted STOPPUNKT B and frozen model-development contract...", flush=True)
        snapshot = repository_snapshot(ROOT)
        errors = verify_repository_snapshot(snapshot)
        if errors:
            raise RuntimeError(f"Repository verification failed: {errors}")
        if snapshot["branch"] != FEATURE_BRANCH:
            raise RuntimeError(f"Expected branch {FEATURE_BRANCH}")
        stop_b = verify_stop_b(args.stop_b_dir.resolve())
        contract = load_model_contract(ROOT)
        shutil.copyfile(ROOT / "config/rapskartan_model_development_v1.json", out / "model_development_contract.json")

        print("[DATASET] Deterministically selecting 1,680 pre-2025 field-years...", flush=True)
        selected, selection, labels, sampling_audit, source_inventory = select_all_years(args.raw_root.resolve(), contract)
        write_dataframe(out / "development_field_selection.csv", selection)
        write_dataframe(out / "development_labels.csv", labels)
        write_dataframe(out / "development_sampling_audit.csv", sampling_audit)

        print("[DATASET] Building field-history priors from only earlier annual crop layers...", flush=True)
        source_rows = source_inventory.to_dict("records")
        priors = build_priors(selected, args.raw_root.resolve(), contract, source_rows)
        source_inventory = pd.DataFrame(source_rows).drop_duplicates("path").sort_values(
            ["history_year", "target_year", "municipality_code", "path"], na_position="first", kind="mergesort",
        )
        write_dataframe(out / "development_prior_features.csv", priors)
        write_dataframe(out / "development_source_inventory.csv", source_inventory)

        print("[DATASET] Fetching or replaying leakage-safe Sentinel-2 field statistics...", flush=True)
        cache_root = args.cache_root.resolve()
        token = oauth_token()
        cache = ApiCache(
            cache_root, token, request_limit=int(contract["resource_guards"]["maximum_authenticated_api_requests"]),
        )
        timeseries, requests = collect_development_statistics(selected, contract, cache)
        write_dataframe(out / "development_s2_timeseries.csv", timeseries)
        write_dataframe(out / "development_api_request_inventory.csv", requests)

        print("[DATASET] Building causal cutoff features with no future acquisitions...", flush=True)
        temporal = build_temporal_features(timeseries, selection, contract)
        write_dataframe(out / "development_temporal_features.csv", temporal)

        print("[DATASET] Replaying all Sentinel-2 requests offline and checking exact hashes...", flush=True)
        offline = ApiCache(
            cache_root, None, offline=True,
            request_limit=int(contract["resource_guards"]["maximum_authenticated_api_requests"]),
        )
        timeseries_2, requests_2 = collect_development_statistics(selected, contract, offline)
        temporal_2 = build_temporal_features(timeseries_2, selection, contract)
        online_hashes = {
            "development_s2_timeseries.csv": write_dataframe(out / "development_s2_timeseries.csv", timeseries),
            "development_temporal_features.csv": write_dataframe(out / "development_temporal_features.csv", temporal),
        }
        offline_hashes = {
            "development_s2_timeseries.csv": sha256_bytes(timeseries_2.to_csv(index=False, lineterminator="\n", float_format="%.10g", na_rep="").encode("utf-8")),
            "development_temporal_features.csv": sha256_bytes(temporal_2.to_csv(index=False, lineterminator="\n", float_format="%.10g", na_rep="").encode("utf-8")),
        }
        if online_hashes != offline_hashes or offline.cache_misses or offline.authenticated_requests:
            raise RuntimeError("Offline dataset rerun is not byte-identical")
        write_json(out / "development_determinism.json", {
            "schema_version": "rapskartan-model-dataset-determinism-v1", "status": "PASS",
            "online_hashes": online_hashes, "offline_hashes": offline_hashes,
            "offline_cache_hits": offline.cache_hits, "offline_cache_misses": offline.cache_misses,
            "offline_authenticated_requests": offline.authenticated_requests,
        })

        cache_summary = cache_inventory(cache_root)
        if int(cache_summary["bytes"]) > int(contract["resource_guards"]["maximum_cache_bytes"]):
            raise RuntimeError("RESOURCE_GUARD: development cache exceeds contract")
        write_json(out / "development_cache_inventory.json", cache_summary)
        usable = temporal[temporal["data_quality_status"] == "USABLE"]
        qa = {
            "schema_version": "rapskartan-model-dataset-qa-v1", "status": "PASS",
            "selected_field_years": len(selection), "development_years": sorted(selection["target_year"].astype(int).unique().tolist()),
            "municipalities": int(selection["municipality_code"].nunique()),
            "positive_labels": int(labels["is_winter_rapeseed"].sum()), "negative_labels": int((labels["is_winter_rapeseed"] == 0).sum()),
            "timeseries_rows": len(timeseries), "temporal_feature_rows": len(temporal), "usable_feature_rows": len(usable),
            "no_data_feature_rows": int((temporal["data_quality_status"] == "NO_DATA").sum()),
            "authenticated_requests": cache.authenticated_requests, "cache_hits": cache.cache_hits,
            "cache_misses": cache.cache_misses, "cache_bytes": int(cache_summary["bytes"]),
            "deterministic_rerun": "PASS", "elapsed_seconds": round(time.monotonic() - started, 3),
            "blind_guard": {
                "target_year_2025_rows": 0, "target_year_2025_labels_accessed": False,
                "future_acquisition_features": 0, "sentinel1": False, "blind_prediction": False,
                "blind_evaluation": False, "full_skane": False, "web": False, "deployment": False,
            },
        }
        write_json(out / "development_dataset_qa.json", qa)
        artifact_paths = [
            "model_development_contract.json", "development_field_selection.csv", "development_labels.csv",
            "development_sampling_audit.csv", "development_prior_features.csv", "development_source_inventory.csv",
            "development_s2_timeseries.csv", "development_api_request_inventory.csv",
            "development_temporal_features.csv", "development_determinism.json",
            "development_cache_inventory.json", "development_dataset_qa.json",
        ]
        write_json(out / "development_dataset_manifest.json", {
            "schema_version": "rapskartan-model-dataset-manifest-v1", "status": "PASS",
            "created_at_utc": utc_now(), "feature_branch": FEATURE_BRANCH,
            "feature_head": snapshot["head"], "feature_tree": snapshot["head_tree"],
            "upstream_tag": UPSTREAM_TAG, "upstream_commit": UPSTREAM_COMMIT,
            "accepted_stop_b_feature_head": stop_b["feature_head"],
            "accepted_stop_b_feature_tree": stop_b["feature_tree"],
            "contract_sha256": model_contract_sha256(ROOT),
            "artifacts": dataset_artifact_manifest(out, artifact_paths), "scope": qa["blind_guard"],
        })
        print("=" * 88)
        print("RAPSKARTAN SKANE V1 LEAKAGE-SAFE DEVELOPMENT DATASET: PASS")
        print("=" * 88)
        print(f"Field-years: {len(selection):,} · years: {qa['development_years']} · municipalities: {qa['municipalities']}")
        print(f"Labels: {qa['positive_labels']} raps / {qa['negative_labels']} controls")
        print(f"Cutoff rows: {len(temporal):,} · usable: {len(usable):,} · no-data: {qa['no_data_feature_rows']:,}")
        print(f"Network/cache: {cache.authenticated_requests}/{cache.cache_hits} · offline rerun: PASS")
        print("2025 labels/predictions, Sentinel-1, full Skåne, web and deployment: NO")
        return 0
    except Exception as exc:
        traceback.print_exc()
        (out / "logs" / "dataset_traceback.log").write_text(traceback.format_exc(), encoding="utf-8")
        print(f"RAPSKARTAN MODEL DATASET: FAIL OR BLOCKED — {exc}")
        print("No 2025 blind prediction/evaluation or later phase ran.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
