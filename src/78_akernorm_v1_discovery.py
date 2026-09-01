#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import traceback
from pathlib import Path

import pandas as pd

from akernorm_v1_discovery_core import (
    ANALYSIS_BRANCH,
    ANALYSIS_COMMIT,
    ANALYSIS_DIR,
    CONTEXT_COMMIT,
    CONTEXT_TAG,
    FEATURE_BRANCH,
    SCHEMA_VERSION,
    VALIDATION_COMMIT,
    VALIDATION_TAG,
    actual_reproduction_metrics,
    analysis_inventory,
    artifact_hashes,
    build_crop_code_contract,
    compare_reproduction,
    fetch_official_norms,
    norm_snapshot_value_relation,
    repository_snapshot,
    run_logged,
    sha256_file,
    stable_json,
    utc_now,
    verify_frozen_inputs,
    verify_repository_snapshot,
    write_markdown,
)


ROOT = Path(__file__).resolve().parents[1]
EXPECTED = ROOT / "analysis/akernorm_v1_discovery/expected_reproduction_v1.json"


def repository_report(path: Path, snapshot: dict, failures: list[str]) -> None:
    lines = [
        "# ÅkerNorm V1 – repository discovery",
        "",
        f"- Status: `{'PASS' if not failures else 'BLOCKED'}`",
        f"- Feature branch: `{snapshot['branch']}` (expected `{FEATURE_BRANCH}`)",
        f"- Feature HEAD: `{snapshot['head']}`",
        f"- Context tag/commit: `{CONTEXT_TAG}` → `{snapshot['context_commit_actual']}`",
        f"- Validation tag/commit: `{VALIDATION_TAG}` → `{snapshot['validation_commit_actual']}`",
        f"- Identified analysis branch: `{ANALYSIS_BRANCH}`",
        f"- Identified analysis commit: `{snapshot['analysis_commit_actual']}`",
        f"- Context is ancestor of feature HEAD: `{snapshot['context_is_ancestor_of_head']}`",
        f"- Imported analysis differs from identified commit: `{bool(snapshot['imported_analysis_diff_paths'])}`",
        f"- Working tree clean at discovery start: `{snapshot['working_tree_clean']}`",
        "",
        "## Scope",
        "",
        "Discovery and reproduction only. No model contract, model freeze, field engine, pilot, full Skåne run or web integration is created.",
        "Sentinel-2 files are not read or changed.",
    ]
    if failures:
        lines += ["", "## BLOCKED", ""] + [f"- `BLOCKED_REPOSITORY`: {value}" for value in failures]
    write_markdown(path, lines)


def inventory_report(path: Path, inventory: dict) -> None:
    lines = [
        "# ÅkerNorm analysis inventory",
        "",
        f"- Branch: `{inventory['analysis_branch']}`",
        f"- HEAD: `{inventory['analysis_commit']}`",
        f"- Merge-base with context: `{inventory['merge_base_with_context']}`",
        f"- Analysis commits after validation freeze: `{inventory['commit_count_after_validation']}`",
        f"- Files in analysis directory: `{inventory['file_count']}`",
        f"- Scripts/runners: `{inventory['suffix_counts']}`",
        "",
        "## Reproduced analysis contract",
        "",
        f"- Years: `{inventory['filters']['history_years']}`",
        f"- ÅkerMinne status: `{inventory['filters']['history_status']}`",
        f"- Minimum dominant SKO share: `{inventory['filters']['minimum_dominant_sko_share']}`",
        f"- Weight: `{inventory['filters']['weight']}`",
        f"- Score: `{inventory['filters']['score']}`",
        "- Same field may contribute in several years; this is the frozen field-year population.",
        "- Official target is one 2026 norm value per SKO, not eleven annual target observations.",
        "",
        "## Existing QA packaging",
        "",
        f"- Tests: {inventory['tests']}",
        f"- Manifests: {inventory['manifests']}",
        "- The discovery wrapper adds the missing cross-crop comparison, exact PxWeb query/raw hashes and one STOPPUNKT A verifier.",
        "",
        "## Analysis entry points",
        "",
    ]
    for item in inventory["files"]:
        if item["path"].endswith((".py", ".bat", ".csv")):
            lines.append(f"- `{item['path']}` — `{item['sha256']}`")
    write_markdown(path, lines)


def source_report(path: Path, source: dict, snapshot_comparison: list[dict]) -> None:
    lines = [
        "# Official norm-yield source discovery",
        "",
        "- Source: Jordbruksverket PxWeb",
        f"- Table: `{source['table']}` — {source['title']}",
        f"- API: `{source['api_url']}`",
        f"- Retrieved UTC: `{source['retrieved_at_utc']}`",
        f"- Raw unit: `{source['raw_unit']}`",
        f"- Normalized unit: `{source['normalized_unit']}`",
        f"- Conversion: `{source['conversion']}`",
        f"- Metadata raw SHA256: `{source['metadata_raw_sha256']}`",
        f"- Normalized table SHA256: `{source['normalized_sha256']}`",
        "- Missing or suppressed values remain explicit; no missing value is converted to zero.",
        "",
        "## Queries and raw responses",
        "",
        "| Crop | PXWeb label | published SKO | query SHA256 | raw response SHA256 | normalized SHA256 |",
        "|---|---|---:|---|---|---|",
    ]
    for item in source["crop_sources"]:
        lines.append(
            f"| {item['crop_key']} | {item['resolved_crop_text']} | {item['published_sko']} | "
            f"`{item['query_sha256']}` | `{item['raw_response_sha256']}` | `{item['normalized_legacy_sha256']}` |"
        )
    lines += ["", "## Cross-check against analysis snapshots", ""]
    for item in snapshot_comparison:
        lines.append(
            f"- `{item['crop']}`: `{item['outcome']}` — compared `{item['compared_sko_rows']}` SKO rows; "
            f"exact `{item['exact_count']}`, rounding-equivalent `{item['rounding_equivalent_count']}`, "
            f"rounding increment `{item['rounding_increment_kg_ha']}` kg/ha, max absolute difference "
            f"`{item['max_absolute_difference_kg_ha']}` kg/ha"
        )
        for equivalent in item["rounding_equivalences"]:
            lines.append(f"  - `ROUNDING_EQUIVALENT`: {equivalent}")
        for mismatch in item["mismatches"]:
            lines.append(f"  - `MISMATCH`: {mismatch}")
    write_markdown(path, lines)


def compare_analysis_snapshots(source: dict) -> list[dict]:
    results = []
    for crop, committed_name, rounding_increment in (
        ("hostvete", "normskord_hostvete_2026.csv", 1),
        ("varkorn", "normskord_varkorn_2026.csv", 10),
    ):
        current = pd.read_csv(source["legacy_paths"][crop], dtype={"sko_id": str})
        committed = pd.read_csv(ROOT / ANALYSIS_DIR / committed_name, dtype={"sko_id": str})
        for frame in (current, committed):
            frame["sko_id"] = frame["sko_id"].astype(str).str.zfill(4)
            frame["norm_kg_ha"] = pd.to_numeric(frame["norm_kg_ha"], errors="coerce")
        merged = committed[["sko_id", "norm_kg_ha"]].merge(
            current[["sko_id", "norm_kg_ha"]], on="sko_id", how="outer", suffixes=("_analysis", "_pxweb")
        )
        exact_count = 0
        rounding_equivalences = []
        mismatches = []
        absolute_differences = []
        for row in merged.itertuples(index=False):
            left, right = row.norm_kg_ha_analysis, row.norm_kg_ha_pxweb
            relation = norm_snapshot_value_relation(left, right, rounding_increment)
            if pd.notna(left) and pd.notna(right):
                absolute_differences.append(abs(float(left) - float(right)))
            if relation == "EXACT":
                exact_count += 1
            elif relation == "ROUNDING_EQUIVALENT":
                rounding_equivalences.append(
                    f"SKO {row.sko_id}: analysis={left:g}, exact PxWeb={right:g}"
                )
            else:
                mismatches.append(f"SKO {row.sko_id}: analysis={left}, current PxWeb={right}")
        if mismatches:
            outcome = "MISMATCH"
        elif rounding_equivalences:
            outcome = "PASS_ROUNDING_EQUIVALENT"
        else:
            outcome = "PASS_EXACT"
        results.append({
            "crop": crop,
            "status": "PASS" if not mismatches else "MISMATCH",
            "outcome": outcome,
            "compared_sko_rows": int(len(merged)),
            "exact_count": exact_count,
            "rounding_equivalent_count": len(rounding_equivalences),
            "rounding_increment_kg_ha": rounding_increment,
            "max_absolute_difference_kg_ha": max(absolute_differences, default=0.0),
            "rounding_equivalences": rounding_equivalences,
            "mismatches": mismatches,
        })
    return results


def run_reproduction(args, source: dict, reproduction: Path, logs: Path) -> None:
    py = sys.executable
    analysis = ROOT / ANALYSIS_DIR
    input_dir = str(args.input_dir)

    def step(name: str, script: str, *script_args: str) -> None:
        run_logged([py, str(analysis / script), *map(str, script_args)], ROOT, logs / f"{name}.log")

    step("01_hostvete_score", "run_validation.py", "--input-dir", input_dir, "--output-dir", reproduction / "hostvete/base", "--norm-csv", source["legacy_paths"]["hostvete"])
    step("02_hostvete_climate", "prepare_pthbv_climate_twofiles.py", "--temp-netcdf", args.temp_netcdf, "--precip-netcdf", args.precip_netcdf, "--input-dir", input_dir, "--local-paths", args.local_paths, "--output-dir", reproduction / "hostvete/climate")
    step("03_hostvete_climate_all", "run_climate_validation.py", "--sko-fit-table", reproduction / "hostvete/base/sko_fit_table.csv", "--climate-csv", reproduction / "hostvete/climate/sko_climate_2011_2025_apr_jul.csv", "--output-dir", reproduction / "hostvete/climate_all")
    step("04_hostvete_climate_sensitivity", "run_climate_validation.py", "--sko-fit-table", reproduction / "hostvete/base/sko_fit_table.csv", "--climate-csv", reproduction / "hostvete/climate/sko_climate_2011_2025_apr_jul.csv", "--output-dir", reproduction / "hostvete/climate_excl_sparse", "--exclude-sko", "1321", "1124", "1221")

    crops = [
        ("varkorn", "run_varkorn_validation.py", "prepare_pthbv_climate_varkorn.py", None),
        ("havre", "run_havre_validation.py", "prepare_pthbv_climate_havre.py", None),
        ("hostraps", "run_hostraps_validation.py", "prepare_pthbv_climate_hostraps.py", None),
    ]
    index = 5
    for crop, score_script, climate_script, _ in crops:
        step(f"{index:02d}_{crop}_score", score_script, "--input-dir", input_dir, "--output-dir", reproduction / f"{crop}/base", "--norm-csv", source["legacy_paths"][crop]); index += 1
        step(f"{index:02d}_{crop}_climate", climate_script, "--temp-netcdf", args.temp_netcdf, "--precip-netcdf", args.precip_netcdf, "--input-dir", input_dir, "--local-paths", args.local_paths, "--output-dir", reproduction / f"{crop}/climate"); index += 1
        step(f"{index:02d}_{crop}_climate_all", "run_climate_validation.py", "--sko-fit-table", reproduction / f"{crop}/base/sko_fit_table.csv", "--climate-csv", reproduction / f"{crop}/climate/sko_climate_2011_2025_apr_jul.csv", "--output-dir", reproduction / f"{crop}/climate_all"); index += 1
        if crop in {"varkorn", "hostraps"}:
            step(f"{index:02d}_{crop}_climate_core", "run_climate_validation.py", "--sko-fit-table", reproduction / f"{crop}/base/sko_fit_table.csv", "--climate-csv", reproduction / f"{crop}/climate/sko_climate_2011_2025_apr_jul.csv", "--output-dir", reproduction / f"{crop}/climate_geographic_core", "--exclude-sko", "0731", "1124", "1131", "1321"); index += 1

    for crop, code, label in (("matpotatis", "45", "Matpotatis"), ("starkelsepotatis", "46", "Stärkelsepotatis")):
        step(f"{index:02d}_{crop}_score", "run_specialcrop_validation.py", "--input-dir", input_dir, "--output-dir", reproduction / f"{crop}/base", "--norm-csv", source["legacy_paths"][crop], "--crop-code", code, "--crop-label", label, "--label-pattern", "potatis", "--min-sko", "4"); index += 1
        step(f"{index:02d}_{crop}_climate", "prepare_pthbv_climate_specialcrop.py", "--temp-netcdf", args.temp_netcdf, "--precip-netcdf", args.precip_netcdf, "--input-dir", input_dir, "--local-paths", args.local_paths, "--output-dir", reproduction / f"{crop}/climate", "--crop-code", code, "--crop-label", label, "--label-pattern", "potatis"); index += 1
        step(f"{index:02d}_{crop}_climate_optional", "run_climate_validation_optional.py", "--sko-fit-table", reproduction / f"{crop}/base/sko_fit_table.csv", "--climate-csv", reproduction / f"{crop}/climate/sko_climate_2011_2025_apr_jul.csv", "--output-dir", reproduction / f"{crop}/climate_all", "--label", label); index += 1
        step(f"{index:02d}_{crop}_climate_core_optional", "run_climate_validation_optional.py", "--sko-fit-table", reproduction / f"{crop}/base/sko_fit_table.csv", "--climate-csv", reproduction / f"{crop}/climate/sko_climate_2011_2025_apr_jul.csv", "--output-dir", reproduction / f"{crop}/climate_geographic_core", "--exclude-sko", "0731", "1124", "1131", "1321", "--label", f"{label} core"); index += 1


def write_qa(path: Path, status: str, repository_failures: list[str], input_report: dict, crop_contract: dict, snapshot_comparison: list[dict], comparison: pd.DataFrame | None, warnings: list[str], errors: list[str]) -> None:
    lines = [
        "# ÅkerNorm V1 discovery/reproduction QA",
        "",
        f"- Overall status: `{status}`",
        f"- Repository: `{'PASS' if not repository_failures else 'BLOCKED'}`",
        f"- Frozen inputs: `{input_report['status']}`",
        f"- Crop-code contract: `{crop_contract['status']}`",
        f"- Current PxWeb vs committed wheat/barley snapshots: `{'PASS' if all(x['status'] == 'PASS' for x in snapshot_comparison) else 'MISMATCH'}`",
        f"- Reproduction metrics: `{'NOT_RUN' if comparison is None else ('PASS' if (comparison['status'] == 'PASS').all() else 'MISMATCH')}`",
        "- Product coefficients frozen: `NO`",
        "- Production code created: `NO`",
        "- Pilot/full Skåne/web executed: `NO`",
        "- Sentinel-2 touched: `NO`",
    ]
    if warnings:
        lines += ["", "## WARN", ""] + [f"- `WARN`: {value}" for value in warnings]
    blockers = repository_failures + input_report.get("failures", []) + crop_contract.get("errors", [])
    if blockers:
        lines += ["", "## BLOCKED", ""] + [f"- `BLOCKED`: {value}" for value in blockers]
    if errors:
        lines += ["", "## ERROR / MISMATCH", ""] + [f"- `ERROR`: {value}" for value in errors]
    if comparison is not None:
        mismatches = comparison[comparison["status"] != "PASS"]
        for row in mismatches.itertuples(index=False):
            lines.append(f"- `MISMATCH`: {row.analysis}/{row.population}/{row.metric}: reported={row.reported}, reproduced={row.reproduced}")
    lines += [
        "",
        "## STOPPUNKT A",
        "",
        "No model freeze or later phase is authorized by this report. Bengt must inspect the returned artifacts and explicitly give GO MODELLFREEZE before any phase B work.",
    ]
    write_markdown(path, lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--local-paths", required=True, type=Path)
    parser.add_argument("--temp-netcdf", required=True, type=Path)
    parser.add_argument("--precip-netcdf", required=True, type=Path)
    args = parser.parse_args()

    output = args.output_dir.resolve()
    source_dir = output / "source"
    reproduction = output / "reproduction"
    logs = output / "logs/steps"
    output.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    errors: list[str] = []
    comparison = None
    source: dict = {}
    snapshot_comparison: list[dict] = []

    snapshot = repository_snapshot(ROOT)
    repository_failures = verify_repository_snapshot(snapshot)
    stable_json(output / "repository_snapshot.json", snapshot)
    repository_report(output / "discovery_repository_report.md", snapshot, repository_failures)

    inventory = analysis_inventory(ROOT)
    stable_json(output / "akernorm_analysis_inventory.json", inventory)
    inventory_report(output / "akernorm_analysis_inventory.md", inventory)

    crop_contract = build_crop_code_contract(ROOT)
    stable_json(output / "crop_code_contract.json", crop_contract)
    input_report = verify_frozen_inputs(args.input_dir)
    stable_json(output / "frozen_input_verification.json", input_report)

    prerequisites = []
    for path, label in ((args.local_paths, "local paths config"), (args.temp_netcdf, "PTHBV temperature NetCDF"), (args.precip_netcdf, "PTHBV precipitation NetCDF")):
        if not path.exists():
            prerequisites.append(f"missing {label}: {path}")
    for module in ("numpy", "pandas", "scipy", "geopandas", "shapely", "pyproj", "xarray", "netCDF4"):
        if importlib.util.find_spec(module) is None:
            prerequisites.append(f"missing Python module: {module}")

    blockers = repository_failures + input_report.get("failures", []) + crop_contract.get("errors", []) + prerequisites
    final_status = "BLOCKED" if blockers else "RUNNING"
    if blockers:
        errors.extend(prerequisites)
    else:
        try:
            print("[DISCOVERY] Fetching exact official PxWeb 2026 source snapshot...", flush=True)
            source = fetch_official_norms(source_dir)
            stable_json(output / "official_norm_source_manifest.json", source)
            snapshot_comparison = compare_analysis_snapshots(source)
            source_report(output / "official_norm_source_report.md", source, snapshot_comparison)
            for item in snapshot_comparison:
                if item["rounding_equivalent_count"]:
                    warnings.append(
                        f"{item['crop']}: committed analysis snapshot has "
                        f"{item['rounding_equivalent_count']} values represented at "
                        f"{item['rounding_increment_kg_ha']} kg/ha precision; all are exact "
                        "ROUND_HALF_UP equivalents of the preserved current PxWeb values"
                    )
            mismatches = [item for item in snapshot_comparison if item["status"] != "PASS"]
            if mismatches:
                raise RuntimeError("Current PxWeb values differ from committed analysis snapshots; see official_norm_source_report.md")

            print("[REPRODUCTION] Running frozen score-only and climate analyses...", flush=True)
            run_reproduction(args, source, reproduction, logs)
            comparison, decisions = compare_reproduction(EXPECTED, reproduction)
            comparison.to_csv(output / "reproduction_comparison.csv", index=False, encoding="utf-8", lineterminator="\n")
            stable_json(output / "reproduction_model_decisions.json", decisions)
            stable_json(output / "reproduced_metrics.json", {
                f"{key[0]}::{key[1]}": value for key, value in actual_reproduction_metrics(reproduction).items()
            })
            final_status = "PASS" if (comparison["status"] == "PASS").all() and decisions["status"] == "PASS" else "MISMATCH"
        except Exception as exc:
            final_status = "BLOCKED" if not source else "FAIL"
            errors.append(str(exc))
            (output / "logs").mkdir(parents=True, exist_ok=True)
            (output / "logs/fatal_traceback.log").write_text(traceback.format_exc(), encoding="utf-8")
            print(traceback.format_exc(), file=sys.stderr)

    if not source:
        write_markdown(output / "official_norm_source_report.md", [
            "# Official norm-yield source discovery", "", "- Status: `BLOCKED`", "",
            "The source fetch was not run because repository/input/prerequisite validation failed.",
        ])
    write_qa(output / "discovery_qa.md", final_status, repository_failures, input_report, crop_contract, snapshot_comparison, comparison, warnings, errors)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": final_status,
        "generated_at_utc": utc_now(),
        "repository": snapshot,
        "analysis": {"branch": ANALYSIS_BRANCH, "commit": ANALYSIS_COMMIT},
        "frozen_inputs": input_report,
        "source": source,
        "warnings": warnings,
        "errors": errors,
        "scope": {
            "model_frozen": False,
            "production_code_created": False,
            "pilot_run": False,
            "full_skane_run": False,
            "web_changed": False,
            "sentinel2_changed": False,
        },
    }
    stable_json(output / "discovery_manifest.json", manifest)
    manifest["artifact_hashes"] = artifact_hashes(output)
    stable_json(output / "discovery_manifest.json", manifest)

    print("=" * 88)
    print(f"AKERNORM V1 DISCOVERY/REPRODUCTION: {final_status}")
    print("=" * 88)
    print(f"Output: {output}")
    print("STOPPUNKT A: no model freeze or later phase has been run.")
    if final_status != "PASS":
        for value in blockers:
            print("BLOCKED:", value)
        for value in errors:
            print("ERROR:", value)
    return 0 if final_status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
