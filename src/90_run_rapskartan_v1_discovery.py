#!/usr/bin/env python3
"""Run Rapskartan Skåne V1 discovery through STOPPUNKT A only."""
from __future__ import annotations

import argparse
import json
import shutil
import traceback
from pathlib import Path

import pandas as pd

from rapskartan_v1_discovery_core import (
    FEATURE_BRANCH,
    SCHEMA_VERSION,
    UPSTREAM_COMMIT,
    UPSTREAM_TAG,
    artifact_records,
    crop_code_contract,
    cutoff_contract,
    inventory_geometry,
    inventory_ground_truth,
    repository_snapshot,
    sentinel_process_smoke,
    sentinel_stac_smoke,
    storage_estimate,
    utc_now,
    verify_repository_snapshot,
    write_inventory_csv,
    write_json,
    write_markdown,
)


ROOT = Path(__file__).resolve().parents[1]
COMMITTED_CUTOFF = ROOT / "analysis/rapskartan_v1/temporal_cutoff_contract.json"


def repository_report(path: Path, snapshot: dict, errors: list[str]) -> None:
    hits = snapshot.get("satellite_path_hits") or []
    lines = [
        "# Rapskartan Skåne V1 – repository discovery",
        "",
        f"- Status: `{'PASS' if not errors else 'BLOCKED'}`",
        f"- Feature branch: `{snapshot.get('branch')}` (expected `{FEATURE_BRANCH}`)",
        f"- Feature HEAD: `{snapshot.get('head')}`",
        f"- Feature tree: `{snapshot.get('head_tree')}`",
        f"- Upstream tag: `{UPSTREAM_TAG}`",
        f"- Tag object type: `{snapshot.get('upstream_tag_type')}`",
        f"- Tag object: `{snapshot.get('upstream_tag_object')}`",
        f"- Dereferenced commit: `{snapshot.get('upstream_dereferenced_commit')}` (expected `{UPSTREAM_COMMIT}`)",
        f"- Upstream is ancestor of HEAD: `{snapshot.get('upstream_is_ancestor')}`",
        f"- Working tree clean at start: `{snapshot.get('working_tree_clean')}`",
        "",
        "## Existing satellite implementation",
        "",
        f"- Executable Sentinel/Copernicus integration paths found before this project: `{len(hits)}`",
    ]
    lines.extend([f"- `{item}`" for item in hits] or ["- None. Rapskartan starts from a clean satellite implementation boundary."])
    lines += [
        "",
        "## Scope",
        "",
        "Discovery only. No classifier, features, thresholds, calibration, mass download, Sentinel-1, web or deployment ran.",
        "The 2025 crop label was exposed only to the aggregate inventory function; no 2025 field IDs or geometries were exported with labels.",
    ]
    if errors:
        lines += ["", "## BLOCKED", ""] + [f"- `BLOCKED_REPOSITORY`: {item}" for item in errors]
    write_markdown(path, lines)


def geometry_report(path: Path, geometry: dict) -> None:
    current = geometry["current_2025"]
    lines = [
        "# Rapskartan Skåne V1 – field geometry lineage",
        "",
        f"- Current 2025 source: `{current['path']}`",
        f"- Current source SHA256: `{current['sha256']}`",
        f"- Frozen expected SHA256: `{current['expected_sha256']}`",
        f"- Hash status: `{current['hash_status']}`",
        f"- Frozen current field identities: `{current['field_identity_count']:,}`",
        f"- Blind guard: {current['blind_guard']}",
        "",
        "## Historical official field files",
        "",
        "| Year | Files | Expected | Complete | GiB | Inventory SHA256 |",
        "|---:|---:|---:|---|---:|---|",
    ]
    for row in geometry["historical_year_specific"]:
        lines.append(
            f"| {row['year']} | {row['existing_municipality_files']} | {row['expected_municipality_files']} | "
            f"{row['complete']} | {row['total_bytes'] / 2**30:.3f} | `{row['path_size_inventory_sha256']}` |"
        )
        if row["missing_files"]:
            lines.append(f"\n`WARN_GEOMETRY_{row['year']}` missing: {', '.join(row['missing_files'])}\n")
    lines += [
        "", "## Frozen discovery decision", "",
        f"- Complete year-specific geometry years: `{geometry['complete_years']}`",
        f"- Classification basis proposal: {geometry['classification_basis_proposal']}",
        f"- Split/merge: {geometry['split_merge_rule']}",
        f"- ÅkerMinne relation: {geometry['akerminne_harmonization']}",
        "- `AMBIGUOUS_UNTIL_S2_PILOT`: exact Sentinel-2 usability per historical year is not inferred from file presence and must be measured without 2025 labels.",
    ]
    write_markdown(path, lines)


def satellite_report(path: Path, stac: dict, process: dict, storage: dict) -> None:
    lines = [
        "# Rapskartan Skåne V1 – Sentinel-2 L2A access discovery",
        "",
        f"- Retrieved UTC: `{utc_now()}`",
        f"- Public STAC smoke: `{stac['status']}`",
        f"- Authenticated Process API pixel smoke: `{process['status']}`",
        "- Collection: `sentinel-2-l2a`",
        "- Smoke AOI: fixed 0.01° box near Lund; not selected from crop labels.",
        f"- Smoke period: `{process['datetime']}` (before blind year)",
        f"- Pixel request: `{process['width']}×{process['height']}`; `{', '.join(process['bands'])}`",
        f"- Request SHA256: `{process['request_sha256']}`",
        "- OAuth secrets logged or persisted: `NO`",
        "- Pixel payload persisted: `NO`",
    ]
    if stac.get("first_item_id"):
        lines += [
            f"- STAC item: `{stac['first_item_id']}` at `{stac.get('first_item_datetime')}`",
            f"- STAC response SHA256: `{stac.get('search_raw_sha256')}`",
        ]
    if stac.get("error"):
        lines.append(f"- `BLOCKED_STAC`: {stac['error']}")
    if process.get("response_sha256"):
        lines += [
            f"- Process response: `{process['response_bytes']}` bytes; SHA256 `{process['response_sha256']}`",
            f"- Processing units reported: `{process.get('processing_units_spent')}`",
        ]
    if process.get("error"):
        lines.append(f"- `BLOCKED_PROCESS`: {process['error']}")
    lines += [
        "", "## API and credentials", "",
        f"- STAC collection: `{stac['collection_url']}`",
        f"- STAC search: `{stac['search_url']}`",
        f"- OAuth token endpoint: `{process['token_url']}`",
        f"- Process API: `{process['process_url']}`",
        "- Local environment names: `CDSE_CLIENT_ID`, `CDSE_CLIENT_SECRET`.",
        "- Reuse OAuth tokens until expiry; do not request one token per API call.",
        "",
        "## Bands and quality inventory",
        "",
        "Required next-pilot inventory: B02, B03, B04, B05, B06, B07, B08, B8A, B11, B12, SCL, dataMask and CLD if reproducible.",
        "No cloud mask is frozen here. The S2 pilot must verify exact SCL codes and explicitly exclude no-data, saturated/defective, shadow, medium/high cloud, cirrus, snow/ice and relevant water pixels.",
        "",
        "## Cache and storage estimate", "",
        f"- Uncompressed seven-year upper planning equivalent: `{storage['uncompressed_seven_year_upper_planning_gib']}` GiB.",
        f"- Recommended bounded source-cache envelope: `{storage['recommended_source_cache_envelope_gib'][0]}–{storage['recommended_source_cache_envelope_gib'][1]}` GiB.",
        f"- Recommended derived field-aggregate envelope: `{storage['recommended_field_aggregate_envelope_gib'][0]}–{storage['recommended_field_aggregate_envelope_gib'][1]}` GiB.",
        f"- First S2 pilot cache bound: `{storage['pilot_budget']['source_cache_gib'][0]}–{storage['pilot_budget']['source_cache_gib'][1]}` GiB.",
        f"- Cache root: `{storage['cache_contract']['root']}`.",
        "- Estimate only; no allocation or mass download has been performed.",
        "",
        "Official documentation: https://documentation.dataspace.copernicus.eu/APIs/STAC.html",
        "OAuth: https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Overview/Authentication.html",
        "Process API: https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Process.html",
        "Quotas: https://documentation.dataspace.copernicus.eu/Quotas.html",
    ]
    write_markdown(path, lines)


def qa_report(path: Path, status: str, errors: list[str], warnings: list[str], snapshot: dict | None, crop: dict | None, inventory: pd.DataFrame | None, geometry: dict | None, stac: dict | None, process: dict | None) -> None:
    lines = [
        "# Rapskartan Skåne V1 – discovery QA",
        "",
        f"- Overall: `{status}`",
        f"- Repository: `{'PASS' if snapshot and not verify_repository_snapshot(snapshot) else 'BLOCKED'}`",
        f"- Crop code contract: `{crop.get('status') if crop else 'BLOCKED'}`",
        f"- Aggregate ground truth inventory: `{'PASS' if inventory is not None else 'BLOCKED'}`",
        f"- Current geometry hash: `{geometry['current_2025']['hash_status'] if geometry else 'BLOCKED'}`",
        f"- STAC: `{stac.get('status') if stac else 'BLOCKED'}`",
        f"- Process API: `{process.get('status') if process else 'BLOCKED'}`",
        "- 2025 row-level labels exported: `NO`",
        "- Classifier/features/threshold/calibration created: `NO`",
        "- Mass download/Sentinel-1/web/deployment run: `NO`",
    ]
    if warnings:
        lines += ["", "## WARN / AMBIGUOUS", ""] + [f"- `{item}`" for item in warnings]
    if errors:
        lines += ["", "## ERROR / BLOCKED", ""] + [f"- `{item}`" for item in errors]
    lines += ["", "## STOPPUNKT A", "", "Do not continue to the Sentinel-2 data pilot without Bengt's explicit GO."]
    write_markdown(path, lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--local-paths", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    out = args.output_dir.resolve()
    source_dir = out / "source"
    logs = out / "logs"
    out.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)
    stale = logs / "fatal_traceback.log"
    stale.unlink(missing_ok=True)

    snapshot = crop = geometry = stac = process = None
    inventory: pd.DataFrame | None = None
    errors: list[str] = []
    warnings: list[str] = []
    try:
        print("[DISCOVERY] Verifying repository and immutable upstream tag...")
        snapshot = repository_snapshot(ROOT)
        repo_errors = verify_repository_snapshot(snapshot)
        errors.extend([f"BLOCKED_REPOSITORY: {item}" for item in repo_errors])
        repository_report(out / "discovery_repository_report.md", snapshot, repo_errors)

        print("[DISCOVERY] Verifying annual crop-code dictionaries...")
        crop = crop_code_contract(ROOT)
        write_json(out / "crop_code_contract.json", crop)
        errors.extend([f"BLOCKED_CROP_CODE: {item}" for item in crop.get("errors", [])])

        print("[DISCOVERY] Aggregating frozen 2015-2025 ground truth (no row-level 2025 export)...")
        try:
            inventory, input_meta = inventory_ground_truth(ROOT, args.input_dir.resolve())
            write_inventory_csv(out / "crop_ground_truth_inventory.csv", inventory)
            write_json(out / "ground_truth_source.json", input_meta)
        except Exception as exc:
            errors.append(f"BLOCKED_GROUND_TRUTH: {type(exc).__name__}: {exc}")

        print("[DISCOVERY] Inventorying year-specific and 2025 reference geometry...")
        try:
            geometry = inventory_geometry(ROOT, args.raw_root.resolve(), args.local_paths.resolve())
            write_json(out / "geometry_lineage.json", geometry)
            geometry_report(out / "geometry_lineage.md", geometry)
            if geometry["current_2025"]["hash_status"] != "PASS":
                errors.append("BLOCKED_GEOMETRY: 2025 source geometry SHA256 differs from frozen ÅkerNorm lineage")
            if len(geometry["complete_years"]) < 3:
                errors.append("BLOCKED_GEOMETRY: fewer than three complete pre-2025 year-specific geometry sets")
            incomplete = [str(row["year"]) for row in geometry["historical_year_specific"] if not row["complete"]]
            if incomplete:
                warnings.append(f"WARN_GEOMETRY_INCOMPLETE_YEARS: {', '.join(incomplete)}")
        except Exception as exc:
            errors.append(f"BLOCKED_GEOMETRY: {type(exc).__name__}: {exc}")

        print("[DISCOVERY] Running minimal public STAC and authenticated 32x32 L2A access smokes...")
        stac = sentinel_stac_smoke(source_dir)
        process = sentinel_process_smoke()
        write_json(out / "satellite_access.json", {"stac": stac, "process": process})
        storage = storage_estimate()
        write_json(out / "cache_storage_estimate.json", storage)
        satellite_report(out / "satellite_access_report.md", stac, process, storage)
        if stac["status"] != "PASS":
            errors.append(f"BLOCKED_STAC: {stac.get('error', stac['status'])}")
        if process["status"] != "PASS":
            errors.append(f"BLOCKED_PROCESS: {process.get('error', process['status'])}")

        committed_cutoff = json.loads(COMMITTED_CUTOFF.read_text(encoding="utf-8"))
        generated_cutoff = cutoff_contract()
        if committed_cutoff != generated_cutoff:
            errors.append("BLOCKED_CUTOFF: committed temporal contract differs from implementation")
        shutil.copyfile(COMMITTED_CUTOFF, out / "temporal_cutoff_contract.json")
        warnings.append("AMBIGUOUS_S2_YEAR_USABILITY: exact optical coverage by development year is deferred to bounded S2 pilot")
        warnings.append("AMBIGUOUS_CLOUD_MASK: exact SCL/CLD mask is deliberately not frozen at discovery")

        status = "PASS" if not errors else "BLOCKED"
        qa_report(out / "discovery_qa.md", status, errors, warnings, snapshot, crop, inventory, geometry, stac, process)
        artifact_names = [
            "discovery_repository_report.md", "crop_ground_truth_inventory.csv", "crop_code_contract.json",
            "ground_truth_source.json", "geometry_lineage.json", "geometry_lineage.md",
            "satellite_access.json", "satellite_access_report.md", "cache_storage_estimate.json",
            "temporal_cutoff_contract.json", "discovery_qa.md", "source/sentinel2_stac_search_smoke.json",
        ]
        existing_names = [name for name in artifact_names if (out / name).exists()]
        manifest = {
            "schema_version": SCHEMA_VERSION, "generated_at_utc": utc_now(), "status": status,
            "upstream_tag": UPSTREAM_TAG, "upstream_commit": UPSTREAM_COMMIT,
            "feature_head": snapshot.get("head") if snapshot else None,
            "scope": {
                "discovery_only": True, "row_level_2025_ground_truth_exported": False,
                "classifier_created": False, "features_created": False, "threshold_selected": False,
                "mass_download_run": False, "sentinel1_touched": False, "web_touched": False, "deployment": False,
            },
            "warnings": warnings, "errors": errors, "artifacts": artifact_records(out, existing_names),
        }
        write_json(out / "discovery_manifest.json", manifest)

        print("=" * 88)
        print(f"RAPSKARTAN SKANE V1 DISCOVERY: {status}")
        print("=" * 88)
        if inventory is not None:
            current = inventory[inventory.target_year == 2025].iloc[0]
            print(f"2025 winter rapeseed: {int(current.winter_rapeseed_fields):,} fields / {float(current.winter_rapeseed_area_ha):,.2f} ha")
            print(f"2025 positive raw code paths: {current.positive_raw_code_pairs}")
        if geometry is not None:
            print(f"Complete year-specific geometry years: {geometry['complete_years']}")
        print(f"Sentinel-2 STAC / Process: {stac.get('status') if stac else 'BLOCKED'} / {process.get('status') if process else 'BLOCKED'}")
        for item in warnings:
            print(item)
        for item in errors:
            print(item)
        print(f"Output: {out}")
        print("STOPPUNKT A: no classifier, mass download, Sentinel-1 or web work has run.")
        return 0 if status == "PASS" else 2
    except Exception:
        stale.write_text(traceback.format_exc(), encoding="utf-8")
        print(traceback.format_exc())
        print("RAPSKARTAN SKANE V1 DISCOVERY: FAIL")
        print(f"Fatal traceback: {stale}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

