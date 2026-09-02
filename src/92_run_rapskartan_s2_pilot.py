#!/usr/bin/env python3
"""Run the bounded, pre-2025 Sentinel-2 datapilot through STOPPUNKT B only."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
import traceback
from pathlib import Path
from typing import Any

import pandas as pd

from rapskartan_s2_pilot_core import (
    PROCESS_URL, STATS_URL, ApiCache, artifact_records, build_process_request,
    build_stat_request, cache_inventory, contract_sha256, dataframe_csv_bytes,
    edge_geometry, geometry_mapping, image_dimensions, load_and_select_fields,
    load_contract, oauth_token, parse_scl_response, parse_stat_response,
    public_stac_inventory, sha256_bytes, sha256_file, utc_now, write_dataframe,
    write_json,
)
from rapskartan_v1_discovery_core import (
    FEATURE_BRANCH, UPSTREAM_COMMIT, UPSTREAM_TAG, repository_snapshot,
    verify_repository_snapshot,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STOP_A = Path(r"C:\AkerSyncRepo\work\rapskartan_skane_v1_discovery_stopA")


def verify_stop_a(stop_a: Path) -> dict[str, Any]:
    path = stop_a / "discovery_manifest.json"
    if not path.exists():
        raise RuntimeError(f"STOPPUNKT A manifest is missing: {path}")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("status") != "PASS":
        raise RuntimeError("Accepted STOPPUNKT A manifest is not PASS")
    if manifest.get("upstream_tag") != UPSTREAM_TAG or manifest.get("upstream_commit") != UPSTREAM_COMMIT:
        raise RuntimeError("STOPPUNKT A upstream freeze mismatch")
    for record in manifest.get("artifacts", []):
        artifact = stop_a / record["path"]
        if (not artifact.is_file() or artifact.stat().st_size != int(record["bytes"])
                or sha256_file(artifact) != record["sha256"]):
            raise RuntimeError(f"STOPPUNKT A artifact mismatch: {record['path']}")
    accepted_head = str(manifest.get("feature_head") or "")
    if not accepted_head:
        raise RuntimeError("STOPPUNKT A manifest lacks feature_head")
    ancestry = subprocess.run(
        ["git", "merge-base", "--is-ancestor", accepted_head, "HEAD"], cwd=ROOT,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
    )
    if ancestry.returncode:
        raise RuntimeError("Accepted STOPPUNKT A commit is not an ancestor of current HEAD")
    return manifest


def field_meta(row: Any) -> dict[str, Any]:
    return {
        "pilot_field_id": str(row.pilot_field_id),
        "target_year": int(row.target_year),
        "municipality_code": str(row.municipality_code),
        "municipality_name": str(row.municipality_name),
        "geography_role": str(row.geography_role),
        "pilot_group": str(row.pilot_group),
        "official_crop_name": str(row.official_crop_name),
        "area_ha": round(float(row.area_ha), 6),
    }


def request_record(kind: str, meta: dict[str, Any], cache_meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "request_kind": kind,
        "pilot_field_id": meta["pilot_field_id"],
        "target_year": meta["target_year"],
        "endpoint": cache_meta["endpoint"],
        "cache_key": cache_meta["cache_key"],
        "request_sha256": cache_meta["request_sha256"],
        "response_sha256": cache_meta["response_sha256"],
        "response_bytes": int(cache_meta["response_bytes"]),
        "cache_hit": bool(cache_meta["cache_hit"]),
        "processing_units_spent": cache_meta.get("processing_units_spent"),
    }


def collect_statistics(selected: Any, contract: dict[str, Any], cache: ApiCache) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    projected = selected.to_crs(32633).sort_values("pilot_field_id", kind="mergesort")
    metric_rows: list[dict[str, Any]] = []
    scl_rows: list[dict[str, Any]] = []
    edge_rows: list[dict[str, Any]] = []
    requests: list[dict[str, Any]] = []
    for row in projected.itertuples(index=False):
        meta = field_meta(row)
        for rule in contract["edge_rules"]:
            rule_id = str(rule["id"])
            geom = edge_geometry(row.geometry, float(rule["negative_buffer_m"]))
            if geom is None:
                edge_rows.append({
                    **meta, "edge_rule": rule_id,
                    "negative_buffer_m": float(rule["negative_buffer_m"]),
                    "geometry_status": "EMPTY_AFTER_BUFFER", "effective_area_ha": 0.0,
                })
                continue
            edge_rows.append({
                **meta, "edge_rule": rule_id,
                "negative_buffer_m": float(rule["negative_buffer_m"]),
                "geometry_status": "USABLE",
                "effective_area_ha": round(float(geom.area) / 10_000.0, 6),
            })
            payload = build_stat_request(geometry_mapping(geom), int(row.target_year), contract)
            result = cache.fetch(STATS_URL, payload, response_suffix=".json", accept="application/json")
            metric_rows.extend(parse_stat_response(result.body, contract, field_meta=meta, edge_rule=rule_id))
            requests.append(request_record(f"FIELD_METRICS_{rule_id}", meta, result.metadata))

        original = edge_geometry(row.geometry, 0)
        if original is None:
            raise RuntimeError(f"Original geometry unexpectedly empty: {row.pilot_field_id}")
        payload = build_stat_request(geometry_mapping(original), int(row.target_year), contract, scl_distribution=True)
        result = cache.fetch(STATS_URL, payload, response_suffix=".json", accept="application/json")
        scl_rows.extend(parse_scl_response(result.body, field_meta=meta))
        requests.append(request_record("SCL_DISTRIBUTION_ORIGINAL", meta, result.metadata))

    metrics = pd.DataFrame(metric_rows)
    scl = pd.DataFrame(scl_rows)
    edges = pd.DataFrame(edge_rows)
    inventory = pd.DataFrame(requests)
    if not metrics.empty:
        metrics = metrics.sort_values(
            ["pilot_field_id", "edge_rule", "acquisition_date", "interval_from"], kind="mergesort",
        ).reset_index(drop=True)
    if not scl.empty:
        scl = scl.sort_values(
            ["pilot_field_id", "acquisition_date", "interval_from"], kind="mergesort",
        ).reset_index(drop=True)
    selected_ids = set(projected["pilot_field_id"].astype(str))
    original_ids = set(metrics.loc[metrics["edge_rule"] == "ORIGINAL", "pilot_field_id"].astype(str)) if not metrics.empty else set()
    scl_ids = set(scl["pilot_field_id"].astype(str)) if not scl.empty else set()
    if original_ids != selected_ids:
        raise RuntimeError(f"Statistics API lacks original-geometry rows for {sorted(selected_ids - original_ids)}")
    if scl_ids != selected_ids:
        raise RuntimeError(f"Statistics API lacks SCL rows for {sorted(selected_ids - scl_ids)}")
    edges = edges.sort_values(["pilot_field_id", "edge_rule"], kind="mergesort").reset_index(drop=True)
    inventory = inventory.sort_values(["pilot_field_id", "request_kind"], kind="mergesort").reset_index(drop=True)
    return metrics, scl, edges, inventory


def make_edge_summary(metrics: pd.DataFrame, edge_states: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for state in edge_states.itertuples(index=False):
        subset = metrics[(metrics["pilot_field_id"] == state.pilot_field_id)
                         & (metrics["edge_rule"] == state.edge_rule)] if not metrics.empty else metrics
        counts = subset["data_quality_status"].value_counts().to_dict() if not subset.empty else {}
        rows.append({
            "pilot_field_id": state.pilot_field_id, "target_year": int(state.target_year),
            "municipality_code": state.municipality_code, "pilot_group": state.pilot_group,
            "edge_rule": state.edge_rule, "negative_buffer_m": state.negative_buffer_m,
            "geometry_status": state.geometry_status, "effective_area_ha": state.effective_area_ha,
            "interval_rows": len(subset), "valid_intervals": int(counts.get("VALID", 0)),
            "low_coverage_intervals": int(counts.get("LOW_COVERAGE", 0)),
            "no_data_intervals": int(counts.get("NO_DATA_TOO_FEW_PIXELS", 0)),
            "median_valid_pixel_fraction": (
                round(float(subset["valid_pixel_fraction"].median()), 8) if not subset.empty else None
            ),
        })
    return pd.DataFrame(rows).sort_values(["pilot_field_id", "edge_rule"], kind="mergesort").reset_index(drop=True)


def enrich_scl(scl: pd.DataFrame, contract: dict[str, Any]) -> pd.DataFrame:
    if scl.empty:
        return scl
    all_cols = [f"scl_{code}_fraction" for code in range(12)]
    for column in all_cols:
        scl[column] = pd.to_numeric(scl[column], errors="coerce")
    valid_cols = [f"scl_{int(code)}_fraction" for code in contract["cloud_mask"]["valid_scl_codes"]]
    excluded_cols = [f"scl_{int(code)}_fraction" for code in contract["cloud_mask"]["excluded_scl_codes"]]
    scl["scl_valid_fraction"] = scl[valid_cols].sum(axis=1, min_count=1)
    scl["scl_excluded_fraction"] = scl[excluded_cols].sum(axis=1, min_count=1)
    scl["scl_fraction_sum"] = scl[all_cols].sum(axis=1, min_count=1)
    return scl


def deterministic_field_ids(selection: pd.DataFrame, wanted: int, *, cloud_images: bool = False) -> list[str]:
    ordered = selection.sort_values(
        ["pilot_group", "target_year", "municipality_code", "area_ha", "pilot_field_id"], kind="mergesort",
    )
    if cloud_images:
        if wanted != 4:
            raise RuntimeError("Current cloud-mask QA contract expects exactly four fields")
        positives = ordered[ordered["pilot_group"] == "WINTER_RAPESEED"]["pilot_field_id"].tolist()
        controls = ordered[ordered["pilot_group"] != "WINTER_RAPESEED"]["pilot_field_id"].tolist()
        return [positives[0], positives[-1], controls[0], controls[-1]]
    positions = ([round(i * (len(ordered) - 1) / (wanted - 1)) for i in range(wanted)]
                 if wanted > 1 else [len(ordered) // 2])
    return ordered.iloc[positions]["pilot_field_id"].tolist()


def plot_timeseries(metrics: pd.DataFrame, selection: pd.DataFrame, out: Path, contract: dict[str, Any]) -> list[str]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    paths: list[str] = []
    for field_id in deterministic_field_ids(selection, int(contract["qa"]["timeseries_plot_fields"])):
        frame = metrics[(metrics["pilot_field_id"] == field_id)
                        & (metrics["edge_rule"] == "ORIGINAL")].copy()
        if frame.empty:
            raise RuntimeError(f"No time-series rows for QA field {field_id}")
        frame["date"] = pd.to_datetime(frame["acquisition_date"], errors="coerce")
        frame["NDVI_p50"] = pd.to_numeric(frame["NDVI_p50"], errors="coerce")
        frame["valid_pixel_fraction"] = pd.to_numeric(frame["valid_pixel_fraction"], errors="coerce")
        frame = frame.sort_values("date")
        metadata = selection[selection["pilot_field_id"] == field_id].iloc[0]
        fig, axis = plt.subplots(figsize=(8.0, 4.5), dpi=120)
        axis.plot(frame["date"], frame["NDVI_p50"], color="#276749", marker="o", markersize=2.5, linewidth=1.2)
        axis.set_ylabel("NDVI P50")
        axis.set_ylim(-0.2, 1.0)
        axis.grid(alpha=0.25)
        coverage = axis.twinx()
        coverage.plot(frame["date"], frame["valid_pixel_fraction"], color="#2b6cb0", alpha=0.35, linewidth=1.0)
        coverage.set_ylabel("Valid pixel fraction")
        coverage.set_ylim(0, 1.05)
        axis.set_title(f"{metadata.official_crop_name} · {metadata.municipality_name} {int(metadata.target_year)}\n{field_id}")
        fig.tight_layout()
        relative = f"qa/timeseries_{field_id}.png"
        path = out / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path, format="png", metadata={"Software": "AkerSync deterministic QA"})
        plt.close(fig)
        paths.append(relative)
    return paths


def cloud_date_pairs(scl: pd.DataFrame, field_id: str) -> list[tuple[str, str, float]]:
    frame = scl[(scl["pilot_field_id"] == field_id) & (scl["source_valid_pixels"] > 0)].copy()
    frame["scl_excluded_fraction"] = pd.to_numeric(frame["scl_excluded_fraction"], errors="coerce")
    frame = frame.dropna(subset=["scl_excluded_fraction", "acquisition_date"])
    frame = frame.sort_values(["scl_excluded_fraction", "acquisition_date"], kind="mergesort")
    if len(frame) < 2:
        raise RuntimeError(f"Fewer than two SCL acquisitions for cloud-mask QA field {field_id}")
    clear, cloudy = frame.iloc[0], frame.iloc[-1]
    if clear.acquisition_date == cloudy.acquisition_date:
        raise RuntimeError(f"Cloud-mask QA dates are not distinct for {field_id}")
    return [("CLEAREST", str(clear.acquisition_date), float(clear.scl_excluded_fraction)),
            ("CLOUDIEST", str(cloudy.acquisition_date), float(cloudy.scl_excluded_fraction))]


def make_cloud_images(selected: Any, selection: pd.DataFrame, scl: pd.DataFrame, out: Path,
                      contract: dict[str, Any], cache: ApiCache) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    from PIL import Image

    projected = selected.to_crs(32633).set_index("pilot_field_id", drop=False)
    records: list[dict[str, Any]] = []
    requests: list[dict[str, Any]] = []
    paths: list[str] = []
    ids = deterministic_field_ids(selection, int(contract["qa"]["cloud_mask_image_fields"]), cloud_images=True)
    for field_id in ids:
        row = projected.loc[field_id]
        meta = field_meta(row)
        geom = edge_geometry(row.geometry, 0)
        width, height = image_dimensions(geom.bounds, int(contract["qa"]["image_max_pixels"]))
        for role, acquisition_date, excluded_fraction in cloud_date_pairs(scl, field_id):
            payload = build_process_request(geometry_mapping(geom), acquisition_date, width, height, contract)
            result = cache.fetch(PROCESS_URL, payload, response_suffix=".png", accept="image/png")
            if not result.body.startswith(b"\x89PNG\r\n\x1a\n"):
                raise RuntimeError(f"Process API did not return PNG for {field_id} {acquisition_date}")
            relative = f"qa/cloudmask_{field_id}_{role.lower()}_{acquisition_date}.png"
            path = out / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(result.body)
            with Image.open(path) as image:
                image.verify()
            records.append({
                **meta, "date_role": role, "acquisition_date": acquisition_date,
                "scl_excluded_fraction": round(excluded_fraction, 8), "width": width,
                "height": height, "artifact_path": relative,
                "artifact_sha256": sha256_bytes(result.body), "cache_key": result.metadata["cache_key"],
            })
            requests.append(request_record(f"QA_PNG_{role}", meta, result.metadata))
            paths.append(relative)
    return pd.DataFrame(records), pd.DataFrame(requests), paths


def offline_verify_images(records: pd.DataFrame, selected: Any, contract: dict[str, Any], cache: ApiCache) -> list[str]:
    projected = selected.to_crs(32633).set_index("pilot_field_id", drop=False)
    hashes: list[str] = []
    for record in records.sort_values(["pilot_field_id", "date_role"], kind="mergesort").itertuples(index=False):
        row = projected.loc[record.pilot_field_id]
        geom = edge_geometry(row.geometry, 0)
        payload = build_process_request(
            geometry_mapping(geom), str(record.acquisition_date), int(record.width), int(record.height), contract,
        )
        result = cache.fetch(PROCESS_URL, payload, response_suffix=".png", accept="image/png")
        hashes.append(result.metadata["response_sha256"])
    return hashes


def qa_report(path: Path, qa: dict[str, Any], warnings: list[str]) -> None:
    lines = [
        "# Rapskartan Skåne V1 – bounded Sentinel-2 datapilot QA", "",
        f"- Overall: `{qa['status']}`",
        f"- Selected development fields: `{qa['selected_fields']}`",
        f"- Development years: `{qa['target_years']}`",
        f"- Field/edge time-series rows: `{qa['metric_rows']}`",
        f"- SCL interval rows: `{qa['scl_rows']}`",
        f"- Authenticated cache misses this run: `{qa['authenticated_requests']}`",
        f"- Cache hits this run: `{qa['cache_hits']}`",
        f"- Cache bytes: `{qa['cache_bytes']}`",
        f"- Offline deterministic rerun: `{qa['deterministic_rerun']}`",
        f"- Time-series plots / cloud-mask images: `{qa['timeseries_plots']}` / `{qa['cloud_mask_images']}`",
        "- 2025 row-level identities or labels accessed: `NO`",
        "- Classifier/model/threshold/calibration/Sentinel-1/full Skåne/web/deployment: `NO`", "",
        "## Frozen datapilot choices", "",
        "- Sentinel-2 L2A field statistics at 10 m; bands B02–B12 listed in the contract.",
        "- SCL 2, 4 and 5 are valid. All other SCL classes are explicitly excluded.",
        "- CLD is diagnostic only and never used as a threshold.",
        "- Polygon tests use original geometry, 10 m inward buffer and 20 m inward buffer.",
        "- Empty inward buffers and low/no valid-pixel intervals are explicit, never silently imputed.",
    ]
    if warnings:
        lines += ["", "## WARN", ""] + [f"- `{warning}`" for warning in warnings]
    lines += ["", "## STOPPUNKT B", "", "No model development may start without Bengt's explicit GO MODELLUTVECKLING."]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--stop-a-dir", type=Path, default=DEFAULT_STOP_A)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    args = parser.parse_args()
    started = time.monotonic()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / "logs").mkdir(parents=True, exist_ok=True)
    (out / "logs" / "fatal_traceback.log").unlink(missing_ok=True)

    try:
        print("[DATAPILOT] Verifying repository, accepted STOPPUNKT A and frozen contract...")
        snapshot = repository_snapshot(ROOT)
        repository_errors = verify_repository_snapshot(snapshot)
        if repository_errors:
            raise RuntimeError(f"Repository verification failed: {repository_errors}")
        stop_a = verify_stop_a(args.stop_a_dir.resolve())
        contract = load_contract(ROOT)
        shutil.copyfile(ROOT / "config/rapskartan_s2_pilot_v1.json", out / "s2_pilot_contract.json")

        print("[DATAPILOT] Selecting 24 deterministic pre-2025 development fields...")
        selected, selection = load_and_select_fields(ROOT, args.raw_root.resolve(), contract)
        if 2025 in set(selection["target_year"].astype(int)):
            raise RuntimeError("BLIND_GUARD: selected pilot contains target year 2025")
        write_dataframe(out / "pilot_selection.csv", selection)

        print("[DATAPILOT] Inventorying public Sentinel-2 L2A scenes for both bounded strata...")
        stac_paths: list[str] = []
        for stratum in contract["pilot_strata"]:
            year, code = int(stratum["target_year"]), str(stratum["municipality_code"])
            subset = selected[(selected["target_year"].astype(int) == year)
                              & (selected["municipality_code"] == code)]
            inventory = public_stac_inventory(subset.to_crs(4326).total_bounds, year, contract)
            relative = f"source/stac_{year}_{code}.json"
            write_json(out / relative, inventory)
            stac_paths.append(relative)

        print("[DATAPILOT] Fetching/caching daily field statistics and explicit SCL distributions...")
        online = ApiCache(
            args.cache_root.resolve(), oauth_token(),
            request_limit=int(contract["resource_guards"]["maximum_authenticated_api_requests"]),
        )
        metrics, scl, edge_states, requests = collect_statistics(selected, contract, online)
        scl = enrich_scl(scl, contract)
        if metrics.empty or scl.empty:
            raise RuntimeError("Sentinel-2 Statistics API returned an empty pilot table")
        edge_summary = make_edge_summary(metrics, edge_states)
        write_dataframe(out / "field_timeseries.csv", metrics)
        write_dataframe(out / "scl_timeseries.csv", scl)
        write_dataframe(out / "edge_rule_summary.csv", edge_summary)

        print("[DATAPILOT] Rendering bounded time-series and cloud-mask QA examples...")
        timeseries_paths = plot_timeseries(metrics, selection, out, contract)
        cloud_examples, image_requests, cloud_paths = make_cloud_images(selected, selection, scl, out, contract, online)
        requests = pd.concat([requests, image_requests], ignore_index=True).sort_values(
            ["pilot_field_id", "request_kind"], kind="mergesort",
        ).reset_index(drop=True)
        write_dataframe(out / "cloud_mask_examples.csv", cloud_examples)
        write_dataframe(out / "api_request_inventory.csv", requests)

        print("[DATAPILOT] Replaying every statistics/image request from cache and comparing hashes...")
        offline = ApiCache(
            args.cache_root.resolve(), None, offline=True,
            request_limit=int(contract["resource_guards"]["maximum_authenticated_api_requests"]),
        )
        metrics2, scl2, edge_states2, _ = collect_statistics(selected, contract, offline)
        scl2 = enrich_scl(scl2, contract)
        edge_summary2 = make_edge_summary(metrics2, edge_states2)
        online_hashes = {
            "field_timeseries.csv": sha256_bytes(dataframe_csv_bytes(metrics)),
            "scl_timeseries.csv": sha256_bytes(dataframe_csv_bytes(scl)),
            "edge_rule_summary.csv": sha256_bytes(dataframe_csv_bytes(edge_summary)),
        }
        offline_hashes = {
            "field_timeseries.csv": sha256_bytes(dataframe_csv_bytes(metrics2)),
            "scl_timeseries.csv": sha256_bytes(dataframe_csv_bytes(scl2)),
            "edge_rule_summary.csv": sha256_bytes(dataframe_csv_bytes(edge_summary2)),
        }
        online_image_hashes = sorted(cloud_examples["artifact_sha256"].tolist())
        offline_image_hashes = sorted(offline_verify_images(cloud_examples, selected, contract, offline))
        if online_hashes != offline_hashes or online_image_hashes != offline_image_hashes:
            raise RuntimeError("Deterministic cache rerun hash mismatch")
        write_json(out / "determinism_rerun.json", {
            "schema_version": "rapskartan-s2-determinism-v1", "status": "PASS",
            "online_artifact_hashes": online_hashes, "offline_artifact_hashes": offline_hashes,
            "online_image_response_hashes": online_image_hashes,
            "offline_image_response_hashes": offline_image_hashes,
            "offline_cache_hits": offline.cache_hits, "offline_cache_misses": offline.cache_misses,
            "offline_authenticated_requests": offline.authenticated_requests,
        })

        cache = cache_inventory(args.cache_root.resolve())
        maximum_cache = int(contract["resource_guards"]["maximum_cache_bytes"])
        if int(cache["bytes"]) > maximum_cache:
            raise RuntimeError(f"RESOURCE_GUARD: cache is {cache['bytes']} bytes, maximum is {maximum_cache}")
        write_json(out / "cache_inventory.json", cache)
        runtime = {
            "schema_version": "rapskartan-s2-runtime-volume-v1",
            "elapsed_seconds": round(time.monotonic() - started, 3), "selected_fields": len(selection),
            "authenticated_requests": online.authenticated_requests, "cache_hits": online.cache_hits,
            "cache_misses": online.cache_misses, "response_bytes": int(requests["response_bytes"].sum()),
            "cache_bytes": int(cache["bytes"]), "resource_guards": contract["resource_guards"],
        }
        write_json(out / "runtime_volume.json", runtime)

        warnings: list[str] = []
        empty_edges = int((edge_summary["geometry_status"] != "USABLE").sum())
        low_rows = int((metrics["data_quality_status"] == "LOW_COVERAGE").sum())
        no_data_rows = int((metrics["data_quality_status"] == "NO_DATA_TOO_FEW_PIXELS").sum())
        if empty_edges:
            warnings.append(f"WARN_EMPTY_INWARD_BUFFERS: {empty_edges} field/edge combinations")
        if low_rows:
            warnings.append(f"WARN_LOW_COVERAGE_INTERVALS: {low_rows} rows")
        if no_data_rows:
            warnings.append(f"WARN_NO_DATA_INTERVALS: {no_data_rows} rows")
        qa = {
            "schema_version": "rapskartan-s2-datapilot-qa-v1", "status": "PASS",
            "selected_fields": len(selection),
            "target_years": sorted(selection["target_year"].astype(int).unique().tolist()),
            "metric_rows": len(metrics), "scl_rows": len(scl), "edge_combinations": len(edge_summary),
            "empty_edge_combinations": empty_edges,
            "valid_intervals": int((metrics["data_quality_status"] == "VALID").sum()),
            "low_coverage_intervals": low_rows, "no_data_intervals": no_data_rows,
            "authenticated_requests": online.authenticated_requests, "cache_hits": online.cache_hits,
            "cache_misses": online.cache_misses, "cache_bytes": int(cache["bytes"]),
            "deterministic_rerun": "PASS", "timeseries_plots": len(timeseries_paths),
            "cloud_mask_images": len(cloud_paths), "warnings": warnings,
            "scope": {
                "sentinel2_datapilot_only": True, "row_level_2025_accessed": False,
                "classifier_created": False, "model_fitted": False, "threshold_selected": False,
                "sentinel1_touched": False, "full_skane_run": False, "web_touched": False,
                "deployment": False,
            },
        }
        write_json(out / "pilot_qa.json", qa)
        qa_report(out / "pilot_qa.md", qa, warnings)

        artifact_paths = [
            "s2_pilot_contract.json", "pilot_selection.csv", "field_timeseries.csv",
            "scl_timeseries.csv", "edge_rule_summary.csv", "cloud_mask_examples.csv",
            "api_request_inventory.csv", "determinism_rerun.json", "cache_inventory.json",
            "runtime_volume.json", "pilot_qa.json", "pilot_qa.md", *stac_paths,
            *timeseries_paths, *cloud_paths,
        ]
        write_json(out / "s2_pilot_manifest.json", {
            "schema_version": "rapskartan-s2-datapilot-manifest-v1", "status": "PASS",
            "created_at_utc": utc_now(), "feature_branch": FEATURE_BRANCH,
            "feature_head": snapshot["head"], "feature_tree": snapshot["head_tree"],
            "upstream_tag": UPSTREAM_TAG, "upstream_commit": UPSTREAM_COMMIT,
            "accepted_stop_a_head": stop_a["feature_head"], "contract_sha256": contract_sha256(ROOT),
            "selection_sha256": sha256_file(out / "pilot_selection.csv"),
            "artifacts": artifact_records(out, artifact_paths), "scope": qa["scope"],
        })

        print("=" * 88)
        print("RAPSKARTAN SKANE V1 SENTINEL-2 DATAPILOT: PASS")
        print("=" * 88)
        print(f"Selected fields: {len(selection)} · years: {qa['target_years']}")
        print(f"Time-series rows: {len(metrics):,} · SCL rows: {len(scl):,}")
        print(f"Authenticated requests/cache hits: {online.authenticated_requests}/{online.cache_hits}")
        print(f"Cache: {cache['bytes'] / 2**20:.2f} MiB · offline hash rerun: PASS")
        print(f"QA: {len(timeseries_paths)} time-series plots · {len(cloud_paths)} cloud-mask images")
        for warning in warnings:
            print(warning)
        print("2025 row labels/classifier/model/Sentinel-1/full Skane/web/deployment: NO")
        print("STOPPUNKT B")
        return 0
    except Exception as exc:
        traceback.print_exc()
        (out / "logs" / "fatal_traceback.log").write_text(traceback.format_exc(), encoding="utf-8")
        print(f"RAPSKARTAN SKANE V1 SENTINEL-2 DATAPILOT: FAIL OR BLOCKED — {exc}")
        print("STOPPUNKT B: no model development or later phase has run.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
